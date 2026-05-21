from __future__ import annotations
import json
import asyncio
import logging
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from ..models import ChatRequest
from ..services.llm_service import llm_service
from ..services.context_builder import context_builder
from ..services.memory_service import memory_service
from ..services.summary_service import summary_service
from ..services.persona_service import persona_service
from ..services.token_estimator import estimate_tokens
from ..services.proactive_engine import proactive_engine
from ..services.search_service import search_service
from ..services.weather_service import weather_service

log = logging.getLogger("memoria.chat")

router = APIRouter(prefix="/api/chat", tags=["chat"])

_abort_flags: dict[int, bool] = {}


@router.post("")
async def chat(req: ChatRequest):
    if not llm_service.is_ready():
        raise HTTPException(400, "请先配置API")

    # Save user message
    user_tokens = estimate_tokens(req.content)
    msg_id = memory_service.save_message(req.conversation_id, "user", req.content, user_tokens)

    # Web search (if enabled and query warrants it)
    search_results = None
    if search_service.should_search(req.content):
        search_results = await search_service.search(req.content)

    # Build context
    messages = context_builder.build(req.content, req.conversation_id,
                                     search_results=search_results)

    # Collect full response - shared between generator and background task
    state = {"content": "", "error": None, "done": False}

    async def generate():
        try:
            async for chunk in llm_service.stream(messages):
                if _abort_flags.get(req.conversation_id):
                    _abort_flags[req.conversation_id] = False
                    yield f"data: {json.dumps({'type': 'chunk', 'content': '(已取消)'})}\n\n"
                    break
                state["content"] += chunk
                yield f"data: {json.dumps({'type': 'chunk', 'content': chunk})}\n\n"
        except Exception as e:
            state["error"] = str(e)
            yield f"data: {json.dumps({'type': 'error', 'message': state['error']})}\n\n"
        state["done"] = True
        yield f"data: {json.dumps({'type': 'done', 'message_id': None})}\n\n"

    response = StreamingResponse(generate(), media_type="text/event-stream")

    async def save_response():
        """Save assistant message after streaming completes."""
        for _ in range(300):  # max 150s
            if state["done"]:
                break
            await asyncio.sleep(0.5)
        if state["content"] and not state["error"]:
            ai_tokens = estimate_tokens(state["content"])
            memory_service.save_message(
                req.conversation_id, "assistant", state["content"], ai_tokens
            )
            asyncio.create_task(
                _post_chat_tasks(req.conversation_id, req.content, state["content"])
            )

    response.background = save_response
    return response


@router.post("/stop")
def stop_generation(conversation_id: int = 1):
    _abort_flags[conversation_id] = True
    return {"ok": True}


async def _post_chat_tasks(conversation_id: int, user_msg: str, ai_msg: str):
    try:
        # Auto-summarize check
        unsum_count = memory_service.count_unsummarized(conversation_id)
        log.info("Unsummarized messages: %d", unsum_count)
        await summary_service.check_and_summarize(conversation_id)

        # Check persona growth (every 2 summaries)
        summaries = memory_service.get_summaries(conversation_id, limit=10)
        log.info("Total summaries: %d", len(summaries))
        if len(summaries) > 0 and len(summaries) % 2 == 0:
            await _check_persona_growth(summaries)

        # Check relationship stage upgrade
        new_stage = persona_service.update_relationship_stage()
        if new_stage:
            stage_info = persona_service.RELATIONSHIP_STAGES.get(new_stage, {})
            persona_service.add_growth_event(
                f"关系升级为「{stage_info.get('label', new_stage)}」"
            )

        # Extract events for proactive messages
        proactive_engine.extract_events([{"role": "user", "content": user_msg}])

        # Detect user's city from conversation
        _detect_city(user_msg)

    except Exception as e:
        log.error("PostChatTasks error: %s", e, exc_info=True)


async def _check_persona_growth(summaries: list):
    try:
        persona = persona_service.get_persona()
        profile = memory_service.get_profile_flat()

        recent_summaries = summaries[-3:]
        summaries_text = "\n".join(f"- {s['summary']}" for s in recent_summaries)

        prompt = f"""根据最近的对话，分析AI角色应该如何成长。

当前人设：
名称：{persona['name']}
性格：{persona['base_persona']}
说话风格：{persona['speaking_style']}
当前关系：{persona['relationship']}

用户画像：{json.dumps(profile, ensure_ascii=False)}

最近对话摘要：
{summaries_text}

返回JSON格式（只输出JSON）：
{{"relationship_update":"关系状态描述","emotion_state":"情绪状态","growth_event":"成长事件描述或null","style_adjustments":"风格微调或null"}}"""

        result = await llm_service.generate(
            [{"role": "system", "content": "你是角色成长分析系统。只输出JSON。"},
             {"role": "user", "content": prompt}],
            max_tokens=2048
        )

        clean = result.strip()
        for prefix in ["```json", "```"]:
            if clean.startswith(prefix):
                clean = clean[len(prefix):]
        if clean.endswith("```"):
            clean = clean[:-3]

        try:
            data = json.loads(clean.strip())
        except json.JSONDecodeError:
            return

        updates = {}
        if data.get("relationship_update"):
            updates["relationship"] = data["relationship_update"]
        if data.get("emotion_state"):
            updates["emotion_state"] = data["emotion_state"]
        if data.get("style_adjustments"):
            updates["speaking_style"] = data["style_adjustments"]

        if updates:
            persona_service.update_persona(updates)

        if data.get("growth_event"):
            persona_service.add_growth_event(data["growth_event"])

    except Exception as e:
        log.error("PersonaGrowth error: %s", e, exc_info=True)


# City detection: Chinese city name -> English name for wttr.in
_CITY_MAP = {
    "北京": "Beijing", "上海": "Shanghai", "广州": "Guangzhou", "深圳": "Shenzhen",
    "杭州": "Hangzhou", "成都": "Chengdu", "武汉": "Wuhan", "南京": "Nanjing",
    "重庆": "Chongqing", "西安": "Xian", "天津": "Tianjin", "苏州": "Suzhou",
    "长沙": "Changsha", "郑州": "Zhengzhou", "东莞": "Dongguan", "青岛": "Qingdao",
    "沈阳": "Shenyang", "宁波": "Ningbo", "昆明": "Kunming", "大连": "Dalian",
    "厦门": "Xiamen", "合肥": "Hefei", "福州": "Fuzhou", "济南": "Jinan",
    "温州": "Wenzhou", "石家庄": "Shijiazhuang", "南宁": "Nanning", "哈尔滨": "Harbin",
    "太原": "Taiyuan", "南昌": "Nanchang", "贵阳": "Guiyang", "兰州": "Lanzhou",
    "海口": "Haikou", "银川": "Yinchuan", "西宁": "Xining", "拉萨": "Lhasa",
    "呼和浩特": "Hohhet", "乌鲁木齐": "Urumqi", "珠海": "Zhuhai", "佛山": "Foshan",
    "无锡": "Wuxi", "烟台": "Yantai", "泉州": "Quanzhou", "惠州": "Huizhou",
    "常州": "Changzhou", "中山": "Zhongshan", "嘉兴": "Jiaxing", "南通": "Nantong",
    "金华": "Jinhua", "徐州": "Xuzhou", "台州": "Taizhou", "三亚": "Sanya",
    "香港": "Hong Kong", "澳门": "Macau", "台北": "Taipei",
    # 安徽
    "宿州": "Suzhou+Anhui", "芜湖": "Wuhu", "蚌埠": "Bengbu", "安庆": "Anqing",
    "阜阳": "Fuyang", "六安": "Liu+an", "淮南": "Huainan", "淮北": "Huaibei",
    "铜陵": "Tongling", "黄山": "Huangshan", "滁州": "Chuzhou", "亳州": "Bozhou",
    "池州": "Chizhou", "宣城": "Xuancheng",
    # 山西
    "大同": "Datong", "长治": "Changzhi", "临汾": "Linfen", "运城": "Yuncheng",
    # 河北
    "唐山": "Tangshan", "保定": "Baoding", "邯郸": "Handan", "廊坊": "Langfang",
    # 江西
    "九江": "Jiujiang", "赣州": "Ganzhou", "景德镇": "Jingdezhen",
    # 广西
    "桂林": "Guilin", "柳州": "Liuzhou", "北海": "Beihai",
    # 其他
    "丽江": "Lijiang", "大理": "Dali", "三亚": "Sanya", "敦煌": "Dunhuang",
}

_CITY_PATTERNS = ["我在", "我住在", "我来到", "我在的", "我在这边", "我现在在",
                  "我这边是", "坐标", "所在地", "我在的城市"]


def _detect_city(user_msg: str):
    """Auto-detect user's city from conversation and update weather service."""
    for city_cn, city_en in _CITY_MAP.items():
        if city_cn in user_msg:
            # Check if it's near a location keyword
            for pattern in _CITY_PATTERNS:
                if pattern in user_msg:
                    idx = user_msg.index(pattern)
                    if city_cn in user_msg[idx:idx + len(pattern) + 6]:
                        weather_service.set_city(city_en)
                        log.info("Auto-detected city: %s -> %s", city_cn, city_en)
                        return
            # Also match "XX人" or "家在XX"
            if f"{city_cn}人" in user_msg or f"家在{city_cn}" in user_msg:
                weather_service.set_city(city_en)
                log.info("Auto-detected city from origin: %s -> %s", city_cn, city_en)
                return
