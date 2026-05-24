from __future__ import annotations
import json
from fastapi import APIRouter
from ..models import ProactiveConfigUpdate
from ..services.proactive_engine import proactive_engine

router = APIRouter(prefix="/api/proactive", tags=["proactive"])


@router.get("/config")
def get_config():
    return proactive_engine._get_config()


@router.put("/config")
def update_config(data: ProactiveConfigUpdate):
    proactive_engine.update_config(data.model_dump(exclude_none=True))
    return {"ok": True}


@router.get("/pending")
def get_pending():
    msg = proactive_engine.get_pending()
    return msg or {}


@router.get("/log")
def get_log(limit: int = 20):
    return proactive_engine.get_log(limit)


@router.post("/trigger")
async def manual_trigger():
    """Manually trigger a proactive message for testing."""
    from ..services.persona_service import persona_service
    from ..services.memory_service import memory_service
    from ..services.weather_service import weather_service
    from datetime import datetime

    persona = persona_service.get_persona()
    name = persona.get("name", "小助手")
    weather = weather_service.get_weather_summary()
    weather_line = f"天气：{weather}" if weather else ""

    ctx = {
        "persona": persona_service.format_persona_prompt(),
        "profile": json.dumps(memory_service.get_profile_flat(), ensure_ascii=False),
        "summaries": "暂无",
        "recent_messages": "",
        "patterns": {"active_hours": "未知", "avg_daily_msgs": 1},
        "last_msg_ago": "未知",
        "proactive_history": "最近没有发过主动消息",
        "weather": weather,
        "event": "",
        "today_count": proactive_engine._today_sent_count(),
        "max_daily": 5,
        "stage_label": persona_service.get_relationship_stage() or "初识",
        "now": datetime.now().strftime("%Y-%m-%d %H:%M %A"),
        "hour": datetime.now().hour
    }
    should_send, reason, message = await proactive_engine._llm_decide(ctx)
    if should_send and message:
        proactive_engine._send_proactive("manual", "手动触发", message)
        return {"ok": True, "message": message, "reason": reason}
    return {"ok": False, "reason": reason}
