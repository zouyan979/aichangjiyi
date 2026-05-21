from __future__ import annotations
import asyncio
import json
import logging
import re
from datetime import datetime, timedelta
from ..database import get_db
from ..config import (PROACTIVE_CHECK_INTERVAL, PROACTIVE_COOLDOWN,
                      NEGATIVE_KEYWORDS, EVENT_KEYWORDS, TIME_KEYWORDS)
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
                await self._check_triggers()
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error("Proactive loop error: %s", e, exc_info=True)
                await asyncio.sleep(60)

    def _is_user_responsive(self) -> bool:
        """Check if user has been responding to recent proactive messages.
        Returns False if last 2+ proactive messages had no user response."""
        db = get_db()
        rows = db.execute(
            "SELECT id, created_at FROM proactive_log WHERE was_sent=1 "
            "ORDER BY created_at DESC LIMIT 3"
        ).fetchall()
        if len(rows) < 2:
            return True  # Not enough data, assume responsive

        unanswered = 0
        for row in rows:
            proactive_time = row["created_at"]
            # Check if there's a user message after this proactive message
            user_msg = db.execute(
                "SELECT id FROM messages WHERE role='user' AND created_at > ? LIMIT 1",
                (proactive_time,)
            ).fetchone()
            if not user_msg:
                unanswered += 1

        return unanswered < 2  # Silent if 2+ consecutive unanswered

    async def _check_triggers(self):
        config = self._get_config()
        if not config.get("enabled"):
            return

        # Silent strategy: don't spam if user isn't responding
        if not self._is_user_responsive():
            return

        now = datetime.now()
        last_msg_time = self._get_last_user_message_time()

        # Check cooldown
        if now.timestamp() - self._last_sent < PROACTIVE_COOLDOWN:
            return

        # Daily message limit
        max_daily = config.get("max_daily_messages", 5)
        if self._today_sent_count() >= max_daily:
            return

        # Time-based triggers (rule pre-filter)
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
            # LLM decides whether to actually send
            should_send, reason, message = await self._llm_decide(trigger, trigger_detail)
            if should_send and message:
                await self._send_proactive(trigger, trigger_detail, message)
                log.info("Proactive sent (%s): %s | reason: %s", trigger, message[:50], reason)
            else:
                log.info("Proactive skipped (%s): %s", trigger, reason)

    async def _send_proactive(self, trigger_type: str, trigger_detail: str, message: str):
        if llm_service._active_config is None:
            return

        try:
            # Save to proactive_log
            db = get_db()
            db.execute(
                "INSERT INTO proactive_log (trigger_type, trigger_detail, content, was_sent) VALUES (?, ?, ?, 1)",
                (trigger_type, trigger_detail, message)
            )
            db.commit()

            # Save as message
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

    async def _llm_decide(self, trigger_type: str, trigger_detail: str) -> tuple[bool, str, str]:
        """Ask LLM whether to send a proactive message. Returns (should_send, reason, message)."""
        if llm_service._active_config is None:
            return False, "no API config", ""

        try:
            persona_text = persona_service.format_persona_prompt()
            profile = memory_service.get_profile_flat()
            profile_text = json.dumps(profile, ensure_ascii=False, indent=1)

            summaries = memory_service.get_summaries(limit=3)
            summaries_text = "\n".join(f"- {s['summary']}" for s in summaries) if summaries else "暂无"

            patterns = self._analyze_user_patterns()
            now = datetime.now().strftime("%Y-%m-%d %H:%M %A")
            today_count = self._today_sent_count()

            last_msg_time = self._get_last_user_message_time()
            last_msg_ago = ""
            if last_msg_time:
                hours_ago = (datetime.now() - last_msg_time).total_seconds() / 3600
                last_msg_ago = f"{hours_ago:.1f}小时前"

            weather = weather_service.get_weather_summary()
            weather_line = f"当前天气：{weather}" if weather else "天气信息：不可用"

            prompt = f"""你是 Memoria 的主动消息决策模块。根据以下信息判断是否该给用户发一条消息。

## AI 人设
{persona_text}

## 关于用户
{profile_text}

## 最近对话摘要
{summaries_text}

## 用户习惯分析
典型活跃时段：{patterns.get('active_hours', '未知')}
平均每日消息数：{patterns.get('avg_daily_msgs', '未知')}

## 当前状态
当前时间：{now}
{weather_line}
最后对话：{last_msg_ago}
今日已发送：{today_count}/5 条主动消息
触发原因：{trigger_detail}

## 决策规则
1. 如果用户在睡觉时间（23:00-07:00），不要打扰
2. 如果今天已发送过多消息，不要打扰
3. 如果用户近期没回应过主动消息，谨慎发送
4. 如果触发原因是情绪相关的，优先发送关心
5. 如果天气有特殊情况（下雨、大风、骤然降温等），可以主动提醒用户注意
5. 事件跟进（如面试后）应该发送

请以 JSON 格式回答（只输出JSON）：
{{"should_send": true/false, "reason": "判断理由", "message": "如果发送，写2-4句温暖自然的话，直接说内容不要加引号"}}"""

            response = await llm_service.generate(
                [{"role": "system", "content": "你是消息决策系统。只输出JSON。"},
                 {"role": "user", "content": prompt}],
                max_tokens=300
            )

            if not response:
                return False, "LLM no response", ""

            clean = response.strip()
            for prefix in ["```json", "```"]:
                if clean.startswith(prefix):
                    clean = clean[len(prefix):]
            if clean.endswith("```"):
                clean = clean[:-3]

            data = json.loads(clean.strip())
            should_send = data.get("should_send", False)
            reason = data.get("reason", "")
            message = data.get("message", "")

            return should_send, reason, message

        except json.JSONDecodeError:
            log.warning("LLM decision parse failed: %s", response[:200] if response else "empty")
            return False, "parse error", ""
        except Exception as e:
            log.error("LLM decision error: %s", e)
            return False, str(e), ""

    def _analyze_user_patterns(self) -> dict:
        """Analyze user's typical active hours and message frequency."""
        db = get_db()
        # Get message counts per hour (last 30 days)
        rows = db.execute(
            "SELECT strftime('%H', created_at) as hour, COUNT(*) as cnt "
            "FROM messages WHERE role='user' AND created_at > datetime('now','-30 days','localtime') "
            "GROUP BY hour ORDER BY cnt DESC LIMIT 3"
        ).fetchall()

        active_hours = "未知"
        if rows:
            hours = [f"{int(r['hour']):02d}:00" for r in rows]
            active_hours = "、".join(hours)

        # Average daily messages
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
        """Count proactive messages sent today."""
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
