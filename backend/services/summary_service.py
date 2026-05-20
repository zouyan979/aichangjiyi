from __future__ import annotations
import json
from .memory_service import memory_service
from .llm_service import llm_service
from .token_estimator import estimate_tokens
from ..config import DEFAULT_SUMMARIZE_AT, DEFAULT_SUMMARY_BATCH, META_SUMMARY_THRESHOLD


class SummaryService:
    def __init__(self):
        self._last_summarize_time = {}  # conversation_id -> timestamp

    async def check_and_summarize(self, conversation_id: int):
        import time
        # Cooldown: don't summarize more than once per 5 minutes
        now = time.time()
        last = self._last_summarize_time.get(conversation_id, 0)
        if now - last < 300:
            return
        count = memory_service.count_unsummarized(conversation_id)
        if count < DEFAULT_SUMMARIZE_AT:
            return
        self._last_summarize_time[conversation_id] = now
        await self.summarize_batch(conversation_id, DEFAULT_SUMMARY_BATCH)

    async def summarize_batch(self, conversation_id: int, batch_size: int):
        messages = memory_service.get_unsummarized_messages(conversation_id)
        if len(messages) < batch_size:
            batch = messages
        else:
            batch = messages[:batch_size]

        if len(batch) < 4:
            return

        # Format conversation
        conv_text = "\n".join(
            f"{'用户' if m['role'] == 'user' else 'AI'}: {m['content']}"
            for m in batch
        )

        # Get current profile for context
        profile = memory_service.get_profile_flat()
        profile_json = json.dumps(profile, ensure_ascii=False, indent=1)

        prompt = f"""你是一个记忆管理系统。分析以下对话片段，提取关键信息。

要求返回JSON格式（只输出JSON，不要其他内容）：
{{"summary":"150字以内的对话摘要","topics":["话题1","话题2"],"key_facts":["重要事实"],"mood":"对话氛围","user_insights":{{"interests":[{{"item":"兴趣名","confidence":0.9}}],"traits":[{{"item":"性格特征","confidence":0.8}}],"facts":[{{"item":"事实","confidence":0.95}}],"preferences":[{{"item":"偏好","confidence":0.7}}],"goals":[{{"item":"目标","confidence":0.6}}]}}}}

置信度说明：
- 0.9-1.0：用户明确陈述的事实（如"我生日是X月X日"）
- 0.7-0.9：用户多次提及或强烈暗示的（如反复提到喜欢某事物）
- 0.5-0.7：AI推断的，但证据不够充分（如仅提过一次的兴趣）
- 0.3-0.5：非常不确定的推测
只提取有把握的信息，不确定的不要提取。

当前用户画像：{profile_json}
对话内容：{conv_text}"""

        try:
            result = await llm_service.generate(
                [{"role": "system", "content": "你是记忆管理系统。只输出JSON。"},
                 {"role": "user", "content": prompt}],
                max_tokens=2048
            )

            print(f"[SummaryService] generate result length: {len(result)}")
            if not result.strip():
                print("[SummaryService] WARNING: generate returned empty result")
                return

            # Parse response
            clean = result.strip()
            for prefix in ["```json", "```"]:
                if clean.startswith(prefix):
                    clean = clean[len(prefix):]
            if clean.endswith("```"):
                clean = clean[:-3]
            clean = clean.strip()

            try:
                data = json.loads(clean)
            except json.JSONDecodeError:
                data = {
                    "summary": result[:200],
                    "topics": [],
                    "key_facts": [],
                    "mood": "",
                    "user_insights": {}
                }

            # Save summary
            msg_range = f"{batch[0]['id']}..{batch[-1]['id']}"
            token_est = estimate_tokens(data.get("summary", ""))
            memory_service.save_summary(
                conversation_id,
                data.get("summary", ""),
                data.get("topics", []),
                data.get("mood", ""),
                data.get("key_facts", []),
                msg_range,
                token_est
            )

            # Mark messages as summarized
            msg_ids = [m["id"] for m in batch]
            memory_service.mark_summarized(msg_ids)

            # Extract user insights
            insights = data.get("user_insights", {})
            if insights:
                memory_service.update_profile_batch(insights, source="auto")

            # Promote key facts to core facts
            for fact in data.get("key_facts", []):
                if fact and len(fact) > 5:
                    memory_service.add_core_fact(fact, priority=3, category="extracted")

            # Check if meta-summarization needed
            await self._check_meta_summarize()

        except Exception as e:
            print(f"[SummaryService] Error: {e}")

    async def _check_meta_summarize(self):
        all_summaries = memory_service.get_all_summaries()
        if len(all_summaries) <= META_SUMMARY_THRESHOLD:
            return

        # Merge oldest 10 summaries into one meta-summary
        oldest = all_summaries[:10]
        summaries_text = "\n\n".join(
            f"[{s.get('created_at', '')}] {s.get('summary', '')}"
            for s in oldest
        )

        prompt = f"""将以下多段对话摘要合并为一段简洁的元摘要（150字以内）：
{summaries_text}"""

        try:
            result = await llm_service.generate(
                [{"role": "user", "content": prompt}],
                max_tokens=256
            )

            # Collect all topics and key facts
            all_topics = []
            all_facts = []
            for s in oldest:
                all_topics.extend(s.get("topics", []))
                all_facts.extend(s.get("key_facts", []))

            # Remove old summaries
            db = memory_service.get_db()
            ids = [s["id"] for s in oldest]
            placeholders = ",".join("?" * len(ids))
            db.execute(f"DELETE FROM conversation_summaries WHERE id IN ({placeholders})", ids)
            db.commit()

            # Save meta-summary
            memory_service.save_summary(
                oldest[0].get("conversation_id"),
                f"[元摘要] {result}",
                list(set(all_topics))[:5],
                "",
                list(set(all_facts))[:5],
                f"meta-{oldest[0]['id']}..{oldest[-1]['id']}",
                estimate_tokens(result)
            )
        except Exception as e:
            print(f"[SummaryService] Meta-summarize error: {e}")

    async def force_summarize(self, conversation_id: int):
        await self.summarize_batch(conversation_id, DEFAULT_SUMMARY_BATCH)


summary_service = SummaryService()
