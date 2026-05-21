from __future__ import annotations
import asyncio
import json
import logging
from datetime import datetime, timedelta
from ..database import get_db
from ..config import (PROACTIVE_CHECK_INTERVAL, PROACTIVE_COOLDOWN,
                      NEGATIVE_KEYWORDS, EVENT_KEYWORDS)
from .memory_service import memory_service
from .persona_service import persona_service
from .llm_service import llm_service
from .weather_service import weather_service

log = logging.getLogger("memoria.proactive")


class ProactiveEngine:
    def __init__(self):
        self._task = None
        self._last_sent = 0
        self._pending_message = None

    async def start(self):
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._loop())

    async def stop(self):
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self):
        while True:
            try:
                await asyncio.sleep(PROACTIVE_CHECK_INTERVAL)
                await self._check_and_decide()
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error("Proactive loop error: %s", e, exc_info=True)
                await asyncio.sleep(60)

    def _is_user_responsive(self) -> bool:
        """Check if user has been responding to recent proactive messages."""
        db = get_db()
        rows = db.execute(
            "SELECT id, created_at FROM proactive_log WHERE was_sent=1 "
            "ORDER BY created_at DESC LIMIT 3"
        ).fetchall()
        if len(rows) < 2:
            return True

        unanswered = 0
        for row in rows:
            proactive_time = row["created_at"]
            user_msg = db.execute(
                "SELECT id FROM messages WHERE role='user' AND created_at > ? LIMIT 1",
                (proactive_time,)
            ).fetchone()
            if not user_msg:
                unanswered += 1

        return unanswered < 2

    async def _check_and_decide(self):
        """Let the AI decide naturally whether to reach out — no rigid rules."""
        config = self._get_config()
        if not config.get("enabled"):
            return

        if llm_service._active_config is None:
            return

        # Basic safety: cooldown + daily limit
        now = datetime.now()
        if now.timestamp() - self._last_sent < PROACTIVE_COOLDOWN:
            return

        max_daily = config.get("max_daily_messages", 5)
        if self._today_sent_count() >= max_daily:
            return

        # Don't spam if user isn't responding
        if not self._is_user_responsive():
            return

        # Also check pending scheduled events
        pending_event = self._check_pending_events()

        # Gather rich context for the AI
        context = self._build_context(pending_event)

        # Let the AI decide — like asking a friend "should I text them?"
        should_send, reason, message = await self._llm_decide(context)

        if should_send and message:
            trigger_type = "event" if pending_event else "ai_decided"
            trigger_detail = reason
            await self._send_proactive(trigger_type, trigger_detail, message)
            log.info("Proactive sent: %s | reason: %s", message[:50], reason)
        else:
            log.info("Proactive skipped: %s", reason)

    def _build_context(self, pending_event: dict | None) -> dict:
        """Gather all context the AI needs to make a human-like decision."""
        db = get_db()
        now = datetime.now()

        # Persona
        persona_text = persona_service.format_persona_prompt()

        # User profile
        profile = memory_service.get_profile_flat()
        profile_text = json.dumps(profile, ensure_ascii=False, indent=1)

        # Recent conversation summaries
        summaries = memory_service.get_summaries(limit=5)
        summaries_text = "\n".join(f"- {s['summary']}" for s in summaries) if summaries else "暂无对话记录"

        # Last few messages (to understand recent mood/topic)
        recent_msgs = db.execute(
            "SELECT role, content, created_at FROM messages "
            "ORDER BY created_at DESC LIMIT 6"
        ).fetchall()
        recent_text = ""
        if recent_msgs:
            lines = []
            for m in reversed(recent_msgs):
                role_label = "用户" if m["role"] == "user" else "AI"
                lines.append(f"[{role_label}] {m['content'][:100]}")
            recent_text = "\n".join(lines)

        # User activity patterns
        patterns = self._analyze_user_patterns()

        # Last interaction
        last_msg_time = self._get_last_user_message_time()
        last_msg_ago = "未知"
        if last_msg_time:
            delta = now - last_msg_time
            hours = delta.total_seconds() / 3600
            if hours < 1:
                last_msg_ago = f"{int(delta.total_seconds() / 60)}分钟前"
            elif hours < 24:
                last_msg_ago = f"{hours:.1f}小时前"
            else:
                last_msg_ago = f"{hours / 24:.1f}天前"

        # Recent proactive history
        recent_proactive = db.execute(
            "SELECT trigger_type, trigger_detail, content, created_at FROM proactive_log "
            "WHERE was_sent=1 ORDER BY created_at DESC LIMIT 3"
        ).fetchall()
        proactive_history = ""
        if recent_proactive:
            lines = []
            for p in recent_proactive:
                lines.append(f"- [{p['created_at']}] {p['content'][:60]}")
            proactive_history = "\n".join(lines)

        # Weather
        weather = weather_service.get_weather_summary()

        # Pending events
        event_text = pending_event.get("detail", "") if pending_event else ""

        # Today's count
        today_count = self._today_sent_count()

        # Relationship stage
        stage = persona_service.get_relationship_stage()
        from .persona_service import RELATIONSHIP_STAGES
        stage_info = RELATIONSHIP_STAGES.get(stage, {})
        stage_label = stage_info.get("label", "初识")

        return {
            "persona": persona_text,
            "profile": profile_text,
            "summaries": summaries_text,
            "recent_messages": recent_text,
            "patterns": patterns,
            "last_msg_ago": last_msg_ago,
            "proactive_history": proactive_history,
            "weather": weather,
            "event": event_text,
            "today_count": today_count,
            "max_daily": max_daily,
            "stage_label": stage_label,
            "now": now.strftime("%Y-%m-%d %H:%M %A"),
            "hour": now.hour
        }

    async def _llm_decide(self, ctx: dict) -> tuple[bool, str, str]:
        """Ask the AI: should I reach out to this person right now?"""
        weather_line = f"当前天气：{ctx['weather']}" if ctx['weather'] else ""
        event_line = f"待跟进事件：{ctx['event']}" if ctx['event'] else ""
        proactive_line = f"最近发出的主动消息：\n{ctx['proactive_history']}" if ctx['proactive_history'] else "最近没有发过主动消息"

        prompt = f"""你是 {ctx['persona'].split(chr(10))[0][:30]}

你和用户的关系是「{ctx['stage_label']}」。

## 你对用户的了解
{ctx['profile']}

## 最近的对话记忆
{ctx['summaries']}

## 最近几条消息
{ctx['recent_messages']}

## 当前情况
时间：{ctx['now']}
{weather_line}
距离上次对话：{ctx['last_msg_ago']}
{event_line}
{proactive_line}
今天已发：{ctx['today_count']}/{ctx['max_daily']} 条

## 你需要思考的问题
你现在想不想找用户聊聊天？

像一个真正的朋友一样思考：
- 现在时间合适吗？太晚了就别打扰
- 你们的关系到了什么程度？刚认识就别太热情
- 最近有没有什么值得关心的事？（天气变化、用户提过的重要事件、情绪波动）
- 你最近是不是发太多消息了？别让人觉得烦
- 如果你真的想说点什么，会说什么？要自然，像发微信一样

不要机械地按照规则判断。用你的"感觉"决定。如果你觉得现在不该发，就不发。

以 JSON 格式回答（只输出JSON）：
{{"should_send": true或false, "reason": "你的真实想法，一两句话", "message": "如果要发，写你真正想说的话，2-4句，自然口语化"}}"""

        try:
            response = await llm_service.generate(
                [{"role": "system", "content": "你是用户的AI伙伴，正在考虑要不要主动找用户聊天。用JSON回答。"},
                 {"role": "user", "content": prompt}],
                max_tokens=300
            )

            if not response:
                return False, "AI没有响应", ""

            clean = response.strip()
            for prefix in ["```json", "```"]:
                if clean.startswith(prefix):
                    clean = clean[len(prefix):]
            if clean.endswith("```"):
                clean = clean[:-3]

            data = json.loads(clean.strip())
            return data.get("should_send", False), data.get("reason", ""), data.get("message", "")

        except json.JSONDecodeError:
            log.warning("AI decision parse failed: %s", response[:200] if response else "empty")
            # If JSON fails, treat the whole response as a message if it looks natural
            return False, "parse error", ""
        except Exception as e:
            log.error("AI decision error: %s", e)
            return False, str(e), ""

    def _send_proactive(self, trigger_type: str, trigger_detail: str, message: str):
        """Actually send the proactive message."""
        if llm_service._active_config is None:
            return

        try:
            db = get_db()
            db.execute(
                "INSERT INTO proactive_log (trigger_type, trigger_detail, content, was_sent) VALUES (?, ?, ?, 1)",
                (trigger_type, trigger_detail, message)
            )
            db.commit()

            conversation_id = self._get_active_conversation()
            memory_service.save_message(
                conversation_id, "assistant", message,
                is_proactive=True
            )

            self._last_sent = datetime.now().timestamp()
            self._pending_message = {
                "content": message,
                "trigger_type": trigger_type,
                "trigger_detail": trigger_detail,
                "created_at": datetime.now().isoformat()
            }

        except Exception as e:
            log.error("Proactive send error: %s", e, exc_info=True)

    def _analyze_user_patterns(self) -> dict:
        """Analyze user's typical active hours and message frequency."""
        db = get_db()
        rows = db.execute(
            "SELECT strftime('%H', created_at) as hour, COUNT(*) as cnt "
            "FROM messages WHERE role='user' AND created_at > datetime('now','-30 days','localtime') "
            "GROUP BY hour ORDER BY cnt DESC LIMIT 3"
        ).fetchall()

        active_hours = "未知"
        if rows:
            hours = [f"{int(r['hour']):02d}:00" for r in rows]
            active_hours = "、".join(hours)

        total = db.execute(
            "SELECT COUNT(*) FROM messages WHERE role='user' "
            "AND created_at > datetime('now','-30 days','localtime')"
        ).fetchone()[0]
        avg_daily = max(1, total // 30)

        return {
            "active_hours": active_hours,
            "avg_daily_msgs": avg_daily
        }

    def _today_sent_count(self) -> int:
        db = get_db()
        today = datetime.now().strftime("%Y-%m-%d")
        row = db.execute(
            "SELECT COUNT(*) FROM proactive_log WHERE was_sent=1 AND created_at LIKE ?",
            (f"{today}%",)
        ).fetchone()
        return row[0] if row else 0

    def get_pending(self) -> dict | None:
        msg = self._pending_message
        self._pending_message = None
        return msg

    def _get_config(self) -> dict:
        db = get_db()
        row = db.execute("SELECT value FROM app_settings WHERE key='proactive'").fetchone()
        if row:
            return json.loads(row["value"])
        return {"enabled": False, "max_daily_messages": 5, "absence_hours": 4}

    def update_config(self, config: dict):
        db = get_db()
        current = self._get_config()
        current.update(config)
        db.execute(
            "INSERT OR REPLACE INTO app_settings (key, value) VALUES ('proactive', ?)",
            (json.dumps(current, ensure_ascii=False),)
        )
        db.commit()

    def _get_last_user_message_time(self) -> datetime | None:
        db = get_db()
        row = db.execute(
            "SELECT created_at FROM messages WHERE role='user' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        if row:
            return datetime.strptime(row["created_at"], "%Y-%m-%d %H:%M:%S")
        return None

    def _get_active_conversation(self) -> int:
        db = get_db()
        row = db.execute("SELECT id FROM conversations ORDER BY updated_at DESC LIMIT 1").fetchone()
        return row["id"] if row else 1

    def _check_pending_events(self) -> dict | None:
        """Check for scheduled event-based triggers (e.g., follow up after interview)."""
        db = get_db()
        now = datetime.now()
        row = db.execute(
            "SELECT id, trigger_detail FROM proactive_log "
            "WHERE trigger_type='event' AND was_sent=0 AND fire_at <= ? "
            "ORDER BY fire_at LIMIT 1",
            (now.strftime("%Y-%m-%d %H:%M:%S"),)
        ).fetchone()
        if row:
            db.execute("UPDATE proactive_log SET was_sent=1 WHERE id=?", (row["id"],))
            db.commit()
            return {"detail": row["trigger_detail"]}
        return None

    def extract_events(self, messages: list[dict]):
        """Scan messages for events to schedule (e.g., interview tomorrow)."""
        for msg in messages:
            if msg.get("role") != "user":
                continue
            text = msg.get("content", "")
            for keyword, hours in EVENT_KEYWORDS.items():
                if keyword in text:
                    fire_at = datetime.now() + timedelta(hours=hours)
                    db = get_db()
                    db.execute(
                        "INSERT INTO proactive_log (trigger_type, trigger_detail, was_sent, fire_at) "
                        "VALUES ('event', ?, 0, ?)",
                        (f"跟进：{keyword}", fire_at.strftime("%Y-%m-%d %H:%M:%S"))
                    )
                    db.commit()

    def get_log(self, limit: int = 20) -> list:
        db = get_db()
        rows = db.execute(
            "SELECT * FROM proactive_log ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


proactive_engine = ProactiveEngine()
