from __future__ import annotations
import json
from ..database import get_db
from ..config import MAX_PROFILE_ITEMS_PER_CAT, MAX_CORE_FACTS


class MemoryService:
    def __init__(self):
        pass

    # ---- User Profile ----
    def get_profile(self) -> dict:
        db = get_db()
        rows = db.execute("SELECT id, category, content, source, confidence FROM user_profiles ORDER BY category, id").fetchall()
        profile = {}
        for r in rows:
            cat = r["category"]
            if cat not in profile:
                profile[cat] = []
            profile[cat].append({"id": r["id"], "content": r["content"], "source": r["source"], "confidence": r["confidence"]})
        return profile

    def get_profile_flat(self) -> dict:
        db = get_db()
        rows = db.execute("SELECT category, content FROM user_profiles").fetchall()
        flat = {}
        for r in rows:
            cat = r["category"]
            if cat not in flat:
                flat[cat] = []
            flat[cat].append(r["content"])
        return flat

    def add_profile_item(self, category: str, content: str, source: str = "manual", confidence: float = 0.8):
        db = get_db()
        try:
            db.execute(
                "INSERT INTO user_profiles (category, content, source, confidence) VALUES (?, ?, ?, ?)",
                (category, content, source, confidence)
            )
            db.commit()
        except Exception:
            # UNIQUE constraint means duplicate — update confidence and timestamp
            db.execute(
                "UPDATE user_profiles SET confidence=MAX(confidence, ?), "
                "updated_at=datetime('now','localtime'), source=? "
                "WHERE category=? AND content=?",
                (confidence, source, category, content)
            )
            db.commit()
        # Trim excess items
        count = db.execute("SELECT COUNT(*) FROM user_profiles WHERE category=?", (category,)).fetchone()[0]
        if count > MAX_PROFILE_ITEMS_PER_CAT:
            db.execute(
                "DELETE FROM user_profiles WHERE category=? AND id NOT IN "
                "(SELECT id FROM user_profiles WHERE category=? ORDER BY updated_at DESC LIMIT ?)",
                (category, category, MAX_PROFILE_ITEMS_PER_CAT)
            )
            db.commit()

    def delete_profile_item(self, item_id: int):
        db = get_db()
        db.execute("DELETE FROM user_profiles WHERE id=?", (item_id,))
        db.commit()

    def update_profile_batch(self, updates: dict, source: str = "auto"):
        if not updates:
            return
        for category, items in updates.items():
            if not isinstance(items, list):
                continue
            for item in items:
                if isinstance(item, dict):
                    # New format: {"item": "...", "confidence": 0.9}
                    text = item.get("item", "").strip()
                    confidence = item.get("confidence", 0.7)
                    if text:
                        self.add_profile_item(category, text, source, confidence)
                elif item and isinstance(item, str) and len(item.strip()) > 0:
                    # Legacy format: plain string
                    self.add_profile_item(category, item.strip(), source)

    def resolve_conflicts(self, conflicts: list) -> int:
        """Handle detected memory conflicts by lowering confidence on old items.
        conflicts: [{"category": "interest", "old": "Java", "new": "Python", "reason": "..."}]
        Returns number of conflicts resolved."""
        if not conflicts:
            return 0
        db = get_db()
        resolved = 0
        for c in conflicts:
            cat = c.get("category", "")
            old = c.get("old", "")
            reason = c.get("reason", "")
            if not cat or not old:
                continue
            # Find the old item and lower its confidence
            row = db.execute(
                "SELECT id, confidence FROM user_profiles WHERE category=? AND content=?",
                (cat, old)
            ).fetchone()
            if row:
                new_conf = max(0.2, (row["confidence"] or 0.8) * 0.4)
                db.execute(
                    "UPDATE user_profiles SET confidence=?, updated_at=datetime('now','localtime') WHERE id=?",
                    (new_conf, row["id"])
                )
                log.info("Conflict resolved: [%s] '%s' confidence %.2f -> %.2f (%s)",
                         cat, old, row["confidence"], new_conf, reason)
                resolved += 1
            else:
                # Try fuzzy match (content contains old or old contains content)
                rows = db.execute(
                    "SELECT id, content, confidence FROM user_profiles WHERE category=?",
                    (cat,)
                ).fetchall()
                for r in rows:
                    if old in r["content"] or r["content"] in old:
                        new_conf = max(0.2, (r["confidence"] or 0.8) * 0.4)
                        db.execute(
                            "UPDATE user_profiles SET confidence=?, updated_at=datetime('now','localtime') WHERE id=?",
                            (new_conf, r["id"])
                        )
                        log.info("Conflict resolved (fuzzy): [%s] '%s' confidence %.2f -> %.2f (%s)",
                                 cat, r["content"], r["confidence"], new_conf, reason)
                        resolved += 1
                        break
        if resolved:
            db.commit()
        return resolved

    # ---- Core Facts ----
    def get_core_facts(self) -> list:
        db = get_db()
        rows = db.execute("SELECT id, content, priority, category, is_pinned FROM core_facts ORDER BY priority DESC, id").fetchall()
        return [{"id": r["id"], "content": r["content"], "priority": r["priority"],
                 "category": r["category"], "is_pinned": bool(r["is_pinned"])} for r in rows]

    def add_core_fact(self, content: str, priority: int = 5, category: str = "general", is_pinned: bool = False):
        db = get_db()
        db.execute(
            "INSERT INTO core_facts (content, priority, category, is_pinned) VALUES (?, ?, ?, ?)",
            (content, priority, category, int(is_pinned))
        )
        db.commit()
        count = db.execute("SELECT COUNT(*) FROM core_facts").fetchone()[0]
        if count > MAX_CORE_FACTS:
            db.execute(
                "DELETE FROM core_facts WHERE is_pinned=0 AND id NOT IN "
                "(SELECT id FROM core_facts ORDER BY is_pinned DESC, priority DESC LIMIT ?)",
                (MAX_CORE_FACTS,)
            )
            db.commit()

    def update_core_fact(self, fact_id: int, updates: dict):
        db = get_db()
        sets = []
        vals = []
        for k, v in updates.items():
            if v is not None:
                sets.append(f"{k}=?")
                vals.append(int(v) if isinstance(v, bool) else v)
        if sets:
            sets.append("updated_at=datetime('now','localtime')")
            vals.append(fact_id)
            db.execute(f"UPDATE core_facts SET {', '.join(sets)} WHERE id=?", vals)
            db.commit()

    def delete_core_fact(self, fact_id: int):
        db = get_db()
        db.execute("DELETE FROM core_facts WHERE id=?", (fact_id,))
        db.commit()

    # ---- Messages ----
    def get_recent_messages(self, conversation_id: int, limit: int = 20) -> list:
        db = get_db()
        rows = db.execute(
            "SELECT id, role, content, token_count, is_proactive, metadata, created_at "
            "FROM messages WHERE conversation_id=? AND is_summarized=0 "
            "ORDER BY created_at DESC LIMIT ?",
            (conversation_id, limit)
        ).fetchall()
        return [dict(r) for r in reversed(rows)]

    def get_unsummarized_messages(self, conversation_id: int) -> list:
        db = get_db()
        rows = db.execute(
            "SELECT id, role, content, created_at FROM messages "
            "WHERE conversation_id=? AND is_summarized=0 AND is_proactive=0 AND role IN ('user','assistant') "
            "ORDER BY created_at",
            (conversation_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def count_unsummarized(self, conversation_id: int) -> int:
        db = get_db()
        row = db.execute(
            "SELECT COUNT(*) FROM messages WHERE conversation_id=? AND is_summarized=0 AND is_proactive=0 AND role IN ('user','assistant')",
            (conversation_id,)
        ).fetchone()
        return row[0]

    def mark_summarized(self, message_ids: list[int]):
        if not message_ids:
            return
        db = get_db()
        placeholders = ",".join("?" * len(message_ids))
        db.execute(f"UPDATE messages SET is_summarized=1 WHERE id IN ({placeholders})", message_ids)
        db.commit()

    def save_message(self, conversation_id: int, role: str, content: str,
                     token_count: int = 0, is_proactive: bool = False) -> int:
        db = get_db()
        cursor = db.execute(
            "INSERT INTO messages (conversation_id, role, content, token_count, is_proactive) VALUES (?, ?, ?, ?, ?)",
            (conversation_id, role, content, token_count, int(is_proactive))
        )
        db.execute(
            "UPDATE conversations SET message_count=message_count+1, updated_at=datetime('now','localtime') WHERE id=?",
            (conversation_id,)
        )
        db.commit()
        return cursor.lastrowid

    # ---- Summaries ----
    def get_summaries(self, conversation_id: int = None, limit: int = 50) -> list:
        db = get_db()
        if conversation_id:
            rows = db.execute(
                "SELECT * FROM conversation_summaries WHERE conversation_id=? ORDER BY created_at DESC LIMIT ?",
                (conversation_id, limit)
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM conversation_summaries ORDER BY created_at DESC LIMIT ?",
                (limit,)
            ).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["topics"] = json.loads(d.get("topics", "[]") or "[]")
            d["key_facts"] = json.loads(d.get("key_facts", "[]") or "[]")
            results.append(d)
        return results

    def get_all_summaries(self) -> list:
        db = get_db()
        rows = db.execute("SELECT * FROM conversation_summaries ORDER BY created_at").fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["topics"] = json.loads(d.get("topics", "[]") or "[]")
            d["key_facts"] = json.loads(d.get("key_facts", "[]") or "[]")
            results.append(d)
        return results

    def save_summary(self, conversation_id: int, summary: str, topics: list,
                     mood: str, key_facts: list, message_range: str,
                     token_estimate: int, confidence: float = 0.8):
        db = get_db()
        db.execute(
            "INSERT INTO conversation_summaries "
            "(conversation_id, summary, topics, mood, key_facts, message_range, token_estimate, confidence) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (conversation_id, summary, json.dumps(topics, ensure_ascii=False),
             mood, json.dumps(key_facts, ensure_ascii=False), message_range, token_estimate, confidence)
        )
        db.commit()

    # ---- Stats ----
    def get_stats(self) -> dict:
        db = get_db()
        msgs = db.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        sums = db.execute("SELECT COUNT(*) FROM conversation_summaries").fetchone()[0]
        prof = db.execute("SELECT COUNT(*) FROM user_profiles").fetchone()[0]
        facts = db.execute("SELECT COUNT(*) FROM core_facts").fetchone()[0]
        saved_tokens = sums * 800  # rough estimate
        return {
            "total_messages": msgs,
            "total_summaries": sums,
            "profile_items": prof,
            "core_facts": facts,
            "estimated_saved_tokens": saved_tokens
        }

    # ---- Export/Import ----
    def export_all(self) -> dict:
        db = get_db()
        profile = self.get_profile()
        summaries = self.get_all_summaries()
        facts = self.get_core_facts()
        messages = db.execute(
            "SELECT conversation_id, role, content, is_proactive, created_at FROM messages ORDER BY created_at"
        ).fetchall()
        return {
            "profile": profile,
            "summaries": summaries,
            "core_facts": facts,
            "messages": [dict(m) for m in messages]
        }

    def import_data(self, data: dict):
        db = get_db()
        if "profile" in data:
            for cat, items in data["profile"].items():
                if isinstance(items, list):
                    for item in items:
                        content = item if isinstance(item, str) else item.get("content", "")
                        if content:
                            self.add_profile_item(cat, content, "import")
        if "core_facts" in data:
            for f in data["core_facts"]:
                self.add_core_fact(
                    f.get("content", ""),
                    f.get("priority", 5),
                    f.get("category", "general"),
                    f.get("is_pinned", False)
                )
        if "summaries" in data:
            for s in data["summaries"]:
                topics = s.get("topics", [])
                if isinstance(topics, str):
                    try:
                        topics = json.loads(topics)
                    except (json.JSONDecodeError, TypeError):
                        topics = [topics]
                key_facts = s.get("key_facts", [])
                if isinstance(key_facts, str):
                    try:
                        key_facts = json.loads(key_facts)
                    except (json.JSONDecodeError, TypeError):
                        key_facts = [key_facts]
                self.save_summary(
                    s.get("conversation_id", 1),
                    s.get("summary", ""),
                    topics,
                    s.get("mood", ""),
                    key_facts,
                    s.get("message_range", ""),
                    s.get("token_estimate", 0),
                    s.get("confidence", 0.8)
                )
        if "messages" in data:
            for m in data["messages"]:
                self.save_message(
                    m.get("conversation_id", 1),
                    m.get("role", "user"),
                    m.get("content", ""),
                    m.get("token_count", 0),
                    bool(m.get("is_proactive", False))
                )
        db.commit()

    def clear_all(self):
        db = get_db()
        db.execute("DELETE FROM messages")
        db.execute("DELETE FROM conversation_summaries")
        db.execute("DELETE FROM user_profiles")
        db.execute("DELETE FROM core_facts")
        db.execute("DELETE FROM proactive_log")
        db.execute("UPDATE conversations SET message_count=0")
        db.commit()


memory_service = MemoryService()
