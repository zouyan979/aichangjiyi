from __future__ import annotations
import asyncio
import json
import re
from datetime import datetime, timedelta
from ..database import get_db
from ..config import (PROACTIVE_CHECK_INTERVAL, PROACTIVE_COOLDOWN,
                      NEGATIVE_KEYWORDS, EVENT_KEYWORDS, TIME_KEYWORDS)
from .memory_service import memory_service
from .persona_service import persona_service
from .llm_service import llm_service


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
                await self._check_triggers()
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[ProactiveEngine] Error: {e}")
                await asyncio.sleep(60)

    async def _check_triggers(self):
        config = self._get_config()
        if not config.get("enabled"):
            return

        now = datetime.now()
        last_msg_time = self._get_last_user_message_time()
        interval = config.get("interval_minutes", 30)

        # Check cooldown
        if now.timestamp() - self._last_sent < PROACTIVE_COOLDOWN:
            return

        # Time-based triggers
        trigger = None
        trigger_detail = ""

        if last_msg_time:
            absence = (now - last_msg_time).total_seconds() / 3600
            absence_hours = config.get("absence_hours", 4)
            if absence >= absence_hours:
                trigger = "absence"
                trigger_detail = f"用户已{absence:.0f}小时未说话"

        # Morning/evening greetings
        if not trigger:
            hour = now.hour
            morning = config.get("morning_range", "07:00-09:00")
            evening = config.get("evening_range", "21:00-23:00")

            m_start, m_end = self._parse_range(morning)
            e_start, e_end = self._parse_range(evening)

            if m_start <= hour < m_end:
                if not self._already_sent_today("morning"):
                    trigger = "morning"
                    trigger_detail = "早安问候"
            elif e_start <= hour < e_end:
                if not self._already_sent_today("evening"):
                    trigger = "evening"
                    trigger_detail = "晚安问候"

        # Event-based triggers
        if not trigger:
            event = self._check_pending_events()
            if event:
                trigger = "event"
                trigger_detail = event.get("detail", "")

        # Emotion-based triggers
        if not trigger:
            emotion = self._check_negative_emotion()
            if emotion:
                trigger = "emotion"
                trigger_detail = "检测到负面情绪"

        if trigger:
            await self._send_proactive(trigger, trigger_detail)

    async def _send_proactive(self, trigger_type: str, trigger_detail: str):
        if llm_service._active_config is None:
            return

        try:
            persona_text = persona_service.format_persona_prompt()
            profile = memory_service.get_profile_flat()
            profile_text = json.dumps(profile, ensure_ascii=False, indent=1)

            summaries = memory_service.get_summaries(limit=3)
            recent_text = "\n".join(f"- {s['summary']}" for s in summaries) if summaries else "暂无"

            now = datetime.now().strftime("%Y-%m-%d %H:%M %A")

            prompt = f"""{persona_text}

关于用户：{profile_text}
最近对话摘要：
{recent_text}
当前时间：{now}
触发原因：{trigger_detail}

要求：像老朋友一样自然地发一条消息。2-4句话，简短温暖。根据触发原因和时间调整内容。直接说内容，不要加引号。"""

            response = await llm_service.generate(
                [{"role": "system", "content": "你是用户的AI伙伴，主动给用户发一条自然的关心消息。"},
                 {"role": "user", "content": prompt}],
                max_tokens=200
            )

            if response and response.strip():
                # Save to proactive_log
                db = get_db()
                db.execute(
                    "INSERT INTO proactive_log (trigger_type, trigger_detail, content, was_sent) VALUES (?, ?, ?, 1)",
                    (trigger_type, trigger_detail, response.strip())
                )
                db.commit()

                # Save as message
                conversation_id = self._get_active_conversation()
                memory_service.save_message(
                    conversation_id, "assistant", response.strip(),
                    is_proactive=True
                )

                self._last_sent = datetime.now().timestamp()
                self._pending_message = {
                    "content": response.strip(),
                    "trigger_type": trigger_type,
                    "trigger_detail": trigger_detail,
                    "created_at": datetime.now().isoformat()
                }

        except Exception as e:
            print(f"[ProactiveEngine] Send error: {e}")

    def get_pending(self) -> dict | None:
        msg = self._pending_message
        self._pending_message = None
        return msg

    def _get_config(self) -> dict:
        db = get_db()
        row = db.execute("SELECT value FROM app_settings WHERE key='proactive'").fetchone()
        if row:
            return json.loads(row["value"])
        return {"enabled": False, "interval_minutes": 30,
                "morning_range": "07:00-09:00", "evening_range": "21:00-23:00",
                "absence_hours": 4}

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

    def _already_sent_today(self, trigger_type: str) -> bool:
        db = get_db()
        today = datetime.now().strftime("%Y-%m-%d")
        row = db.execute(
            "SELECT id FROM proactive_log WHERE trigger_type=? AND created_at LIKE ? LIMIT 1",
            (trigger_type, f"{today}%")
        ).fetchone()
        return row is not None

    def _parse_range(self, range_str: str) -> tuple[int, int]:
        try:
            parts = range_str.split("-")
            return int(parts[0].split(":")[0]), int(parts[1].split(":")[0])
        except Exception:
            return 0, 0

    def _check_pending_events(self) -> dict | None:
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

    def _check_negative_emotion(self) -> bool:
        db = get_db()
        recent = db.execute(
            "SELECT content FROM messages WHERE role='user' ORDER BY created_at DESC LIMIT 3"
        ).fetchall()
        if not recent:
            return False
        for row in recent:
            text = row["content"]
            for kw in NEGATIVE_KEYWORDS:
                if kw in text:
                    return True
        return False

    def extract_events(self, messages: list[dict]):
        """Scan messages for events to schedule."""
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
