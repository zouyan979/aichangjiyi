from __future__ import annotations
import json
from datetime import datetime
from ..database import get_db
from ..config import MAX_GROWTH_LOG


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
            "relationship=?, emotion_state='calm', growth_log='[]', version=1, updated_at=datetime('now','localtime') WHERE id=1",
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
        # Custom rules are always included and never overwritten by growth
        if p.get("custom_rules"):
            parts.append(f"用户设定的规则（必须严格遵守）：{p['custom_rules']}")
        return "\n".join(parts)

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
