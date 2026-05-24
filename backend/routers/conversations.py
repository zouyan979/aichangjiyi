from __future__ import annotations
from fastapi import APIRouter, HTTPException
from ..database import get_db
from ..models import ConversationCreate, ConversationUpdate, ConversationOut

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


@router.get("")
def list_conversations():
    db = get_db()
    rows = db.execute("SELECT * FROM conversations ORDER BY updated_at DESC").fetchall()
    return [dict(r) for r in rows]


@router.post("")
def create_conversation(data: ConversationCreate):
    db = get_db()
    cursor = db.execute("INSERT INTO conversations (title) VALUES (?)", (data.title,))
    db.commit()
    return {"ok": True, "id": cursor.lastrowid}


@router.put("/{conv_id}")
def update_conversation(conv_id: int, data: ConversationUpdate):
    db = get_db()
    if data.title:
        db.execute("UPDATE conversations SET title=?, updated_at=datetime('now','localtime') WHERE id=?",
                   (data.title, conv_id))
        db.commit()
    return {"ok": True}


@router.delete("/{conv_id}")
def delete_conversation(conv_id: int):
    db = get_db()
    # Check if it's the last conversation
    count = db.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
    if count <= 1:
        raise HTTPException(status_code=400, detail="不能删除最后一个对话")
    db.execute("DELETE FROM conversations WHERE id=?", (conv_id,))
    db.commit()
    return {"ok": True}


@router.get("/{conv_id}/messages")
def get_messages(conv_id: int, limit: int = 100, offset: int = 0):
    db = get_db()
    rows = db.execute(
        "SELECT id, conversation_id, role, content, token_count, is_proactive, metadata, created_at "
        "FROM messages WHERE conversation_id=? ORDER BY created_at LIMIT ? OFFSET ?",
        (conv_id, limit, offset)
    ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["is_proactive"] = bool(d["is_proactive"])
        result.append(d)
    return result
