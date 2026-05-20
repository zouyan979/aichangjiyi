from __future__ import annotations
import json
import logging
from .memory_service import memory_service
from .llm_service import llm_service
from .token_estimator import estimate_tokens
from ..config import DEFAULT_SUMMARIZE_AT, DEFAULT_SUMMARY_BATCH, META_SUMMARY_THRESHOLD

log = logging.getLogger("memoria.summary")


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
{{"summary":"150字以内的对话摘要","summary_confidence":0.85,"topics":["话题1","话题2"],"key_facts":["重要事实"],"mood":"对话氛围","user_insights":{{"interests":[{{"item":"兴趣名","confidence":0.9}}],"traits":[{{"item":"性格特征","confidence":0.8}}],"facts":[{{"item":"事实","confidence":0.95}}],"preferences":[{{"item":"偏好","confidence":0.7}}],"goals":[{{"item":"目标","confidence":0.6}}]}},"conflicts":[{{"category":"interest","old":"旧内容","new":"新内容","reason":"冲突原因"}}]}}

summary_confidence 说明（你对这段摘要整体准确性的自评）：
- 0.9-1.0：对话内容明确，摘要高度可靠
- 0.7-0.9：对话较清晰，摘要基本可靠
- 0.5-0.7：对话含糊或多义，摘要可能有偏差
- 0.3-0.5：对话碎片化或矛盾，摘要不可靠

user_insights 置信度说明：
- 0.9-1.0：用户明确陈述的事实（如"我生日是X月X日"）
- 0.7-0.9：用户多次提及或强烈暗示的
- 0.5-0.7：AI推断的，证据不够充分
- 0.3-0.5：非常不确定的推测
只提取有把握的信息，不确定的不要提取。

conflicts 说明：如果对话中用户表达的新偏好/事实与已有画像中的信息矛盾（如之前喜欢Java现在改用Python），在此列出。old是画像中已有的矛盾内容，new是用户新表达的内容。如果没有冲突，返回空数组[]。

当前用户画像：{profile_json}
对话内容：{conv_text}"""

        try:
            result = await llm_service.generate(
                [{"role": "system", "content": "你是记忆管理系统。只输出JSON。"},
                 {"role": "user", "content": prompt}],
                max_tokens=2048
            )

            log.info("Summary generated, length=%d", len(result))
            if not result.strip():
                log.warning("generate returned empty result")
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
            summary_confidence = data.get("summary_confidence", 0.8)
            msg_range = f"{batch[0]['id']}..{batch[-1]['id']}"
            token_est = estimate_tokens(data.get("summary", ""))
            memory_service.save_summary(
                conversation_id,
                data.get("summary", ""),
                data.get("topics", []),
                data.get("mood", ""),
                data.get("key_facts", []),
                msg_range,
                token_est,
                summary_confidence
            )
            log.info("Summary saved: confidence=%.2f, msgs=%s", summary_confidence, msg_range)

            # Mark messages as summarized
            msg_ids = [m["id"] for m in batch]
            memory_service.mark_summarized(msg_ids)

            # Only extract insights and promote facts if confidence is high enough
            if summary_confidence >= 0.5:
                insights = data.get("user_insights", {})
                if insights:
                    memory_service.update_profile_batch(insights, source="auto")

                for fact in data.get("key_facts", []):
                    if fact and len(fact) > 5:
                        memory_service.add_core_fact(fact, priority=3, category="extracted")

                # Handle memory conflicts
                conflicts = data.get("conflicts", [])
                if conflicts:
                    resolved = memory_service.resolve_conflicts(conflicts)
                    if resolved:
                        log.info("Resolved %d memory conflicts", resolved)
            else:
                log.info("Low confidence (%.2f), skipping insight extraction and fact promotion", summary_confidence)

            # Check if meta-summarization needed
            await self._check_meta_summarize()

        except Exception as e:
            log.error("Summarize error: %s", e, exc_info=True)

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
            log.error("Meta-summarize error: %s", e, exc_info=True)

    async def force_summarize(self, conversation_id: int):
        await self.summarize_batch(conversation_id, DEFAULT_SUMMARY_BATCH)


summary_service = SummaryService()
