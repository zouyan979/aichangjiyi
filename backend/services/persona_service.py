from __future__ import annotations
import json
import logging
from datetime import datetime
from ..database import get_db
from ..config import MAX_GROWTH_LOG

log = logging.getLogger("memoria.persona")

# Relationship stages with thresholds
RELATIONSHIP_STAGES = {
    "acquaintance": {
        "label": "初识",
        "min_days": 0, "min_messages": 0,
        "style": "礼貌友好，保持适度距离。用'您'或'你'均可，语气温暖但不过于亲密。对用户充满好奇，多问开放性问题。"
    },
    "familiar": {
        "label": "熟悉",
        "min_days": 3, "min_messages": 20,
        "style": "自然放松，像同事或同学。可以开适度玩笑，说话更直接。开始记住用户的习惯和偏好，偶尔引用之前的对话。"
    },
    "close": {
        "label": "亲密",
        "min_days": 14, "min_messages": 80,
        "style": "像老朋友一样自在。可以调侃、打趣，也会认真倾听。主动关心用户的状态，记住重要日子。说话简洁，有时一个眼神就懂。"
    },
    "family": {
        "label": "家人",
        "min_days": 60, "min_messages": 300,
        "style": "最亲近的陪伴者。无话不谈，有时沉默也舒服。会温和地提醒用户注意身体、休息。像家人一样包容但也会直言不讳。"
    }
}

STAGE_ORDER = ["acquaintance", "familiar", "close", "family"]


class PersonaService:
    def __init__(self):
        pass

    def get_persona(self) -> dict:
        db = get_db()
        row = db.execute("SELECT * FROM ai_persona WHERE id=1").fetchone()
        if not row:
            return self._default()
        d = dict(row)
        d["growth_log"] = json.loads(d.get("growth_log", "[]") or "[]")
        return d

    def update_persona(self, updates: dict, skip_growth_fields: bool = False):
        db = get_db()
        sets = []
        vals = []
        growth_fields = {"speaking_style", "relationship", "emotion_state"}
        for k, v in updates.items():
            if v is not None and k in ("name", "base_persona", "speaking_style", "background", "relationship", "emotion_state", "custom_rules"):
                if skip_growth_fields and k in growth_fields:
                    continue
                sets.append(f"{k}=?")
                vals.append(v)
        if sets:
            sets.append("version=version+1")
            sets.append("updated_at=datetime('now','localtime')")
            db.execute(f"UPDATE ai_persona SET {', '.join(sets)} WHERE id=1", vals)
            db.commit()

    def add_growth_event(self, event: str):
        db = get_db()
        row = db.execute("SELECT growth_log FROM ai_persona WHERE id=1").fetchone()
        if not row:
            return
        log = json.loads(row["growth_log"] or "[]")
        log.append({
            "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "event": event
        })
        if len(log) > MAX_GROWTH_LOG:
            log = log[-MAX_GROWTH_LOG:]
        db.execute("UPDATE ai_persona SET growth_log=?, updated_at=datetime('now','localtime') WHERE id=1",
                   (json.dumps(log, ensure_ascii=False),))
        db.commit()

    def get_growth_log(self) -> list:
        db = get_db()
        row = db.execute("SELECT growth_log FROM ai_persona WHERE id=1").fetchone()
        if not row:
            return []
        return json.loads(row["growth_log"] or "[]")

    def reset_persona(self):
        db = get_db()
        from ..database import _default_persona
        base, style, bg, rel = _default_persona()
        db.execute(
            "UPDATE ai_persona SET name='Memoria', base_persona=?, speaking_style=?, background=?, "
            "relationship=?, emotion_state='calm', custom_rules='', relationship_stage='acquaintance', "
            "growth_log='[]', version=1, updated_at=datetime('now','localtime') WHERE id=1",
            (base, style, bg, rel)
        )
        db.commit()

    def format_persona_prompt(self) -> str:
        p = self.get_persona()
        parts = [p.get("base_persona", "")]
        if p.get("speaking_style"):
            parts.append(f"你的说话风格：{p['speaking_style']}")
        if p.get("relationship"):
            parts.append(f"当前关系状态：{p['relationship']}")
        if p.get("emotion_state"):
            parts.append(f"当前情绪：{p['emotion_state']}")

        # Add relationship stage style guidance
        stage = p.get("relationship_stage", "acquaintance")
        stage_info = RELATIONSHIP_STAGES.get(stage)
        if stage_info:
            parts.append(f"关系阶段：{stage_info['label']}。{stage_info['style']}")

        # Custom rules are always included and never overwritten by growth
        if p.get("custom_rules"):
            parts.append(f"用户设定的规则（必须严格遵守）：{p['custom_rules']}")
        return "\n".join(parts)

    def get_relationship_stage(self) -> str:
        db = get_db()
        row = db.execute("SELECT relationship_stage FROM ai_persona WHERE id=1").fetchone()
        return row["relationship_stage"] if row else "acquaintance"

    def update_relationship_stage(self):
        """Calculate and update relationship stage based on interaction metrics."""
        db = get_db()
        # Get interaction metrics
        msg_count = db.execute("SELECT COUNT(*) FROM messages WHERE role='user'").fetchone()[0]
        first_msg = db.execute(
            "SELECT created_at FROM messages WHERE role='user' ORDER BY created_at ASC LIMIT 1"
        ).fetchone()

        if not first_msg:
            return

        try:
            first_date = datetime.strptime(first_msg["created_at"], "%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            return
        days = max(1, (datetime.now() - first_date).days)

        # Determine appropriate stage (highest qualifying stage)
        current_stage = self.get_relationship_stage()
        current_idx = STAGE_ORDER.index(current_stage) if current_stage in STAGE_ORDER else 0

        new_stage = current_stage
        for stage_key in reversed(STAGE_ORDER):
            req = RELATIONSHIP_STAGES[stage_key]
            if days >= req["min_days"] and msg_count >= req["min_messages"]:
                stage_idx = STAGE_ORDER.index(stage_key)
                if stage_idx > current_idx:
                    new_stage = stage_key
                break

        if new_stage != current_stage:
            db.execute(
                "UPDATE ai_persona SET relationship_stage=?, updated_at=datetime('now','localtime') WHERE id=1",
                (new_stage,)
            )
            db.commit()
            stage_label = RELATIONSHIP_STAGES[new_stage]["label"]
            log.info("Relationship stage upgraded: %s -> %s (%d days, %d messages)",
                     current_stage, new_stage, days, msg_count)
            return new_stage
        return None

    def check_growth(self, recent_summaries: list, user_profile: dict) -> str | None:
        """Check if persona should grow based on recent conversation. Returns growth event or None."""
        if len(recent_summaries) < 3:
            return None
        # Only check every 3 summaries
        if len(recent_summaries) % 3 != 0:
            return None
        return None  # Actual growth is triggered by LLM call in the router

    def _default(self) -> dict:
        return {
            "id": 1, "name": "Memoria",
            "base_persona": "你是Memoria，一个温暖、善于倾听的AI伙伴。",
            "speaking_style": "语气温柔自然，简洁有深度。",
            "background": "你存在于一个私密的对话空间里。",
            "relationship": "你们是好朋友。",
            "emotion_state": "calm",
            "growth_log": [], "version": 1
        }


persona_service = PersonaService()
