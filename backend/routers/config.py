from __future__ import annotations
from fastapi import APIRouter, HTTPException
from ..database import get_db
from ..models import ApiConfigCreate, ApiConfigUpdate, ApiConfigOut
from ..services.llm_service import llm_service

router = APIRouter(prefix="/api/config", tags=["config"])


def _load_active_config():
    db = get_db()
    row = db.execute("SELECT * FROM api_configs WHERE is_active=1 LIMIT 1").fetchone()
    if row:
        llm_service.set_config({
            "base_url": row["base_url"],
            "api_key": row["api_key"],
            "model": row["model"],
            "temperature": row["temperature"],
            "max_tokens": row["max_tokens"]
        })


@router.get("/api")
def list_configs():
    db = get_db()
    rows = db.execute("SELECT * FROM api_configs ORDER BY id").fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["is_active"] = bool(d["is_active"])
        result.append(d)
    return result


@router.post("/api")
def create_config(config: ApiConfigCreate):
    db = get_db()
    cursor = db.execute(
        "INSERT INTO api_configs (name, base_url, api_key, model, temperature, max_tokens, is_active) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (config.name, config.base_url, config.api_key, config.model,
         config.temperature, config.max_tokens, 1)
    )
    # Deactivate others
    db.execute("UPDATE api_configs SET is_active=0 WHERE id != ?", (cursor.lastrowid,))
    db.commit()
    _load_active_config()
    return {"ok": True, "id": cursor.lastrowid}


@router.put("/api/{config_id}")
def update_config(config_id: int, config: ApiConfigUpdate):
    db = get_db()
    sets = []
    vals = []
    for k, v in config.model_dump(exclude_none=True).items():
        sets.append(f"{k}=?")
        vals.append(v)
    if not sets:
        return {"ok": True}
    vals.append(config_id)
    db.execute(f"UPDATE api_configs SET {', '.join(sets)}, updated_at=datetime('now','localtime') WHERE id=?", vals)
    db.commit()
    _load_active_config()
    return {"ok": True}


@router.delete("/api/{config_id}")
def delete_config(config_id: int):
    db = get_db()
    db.execute("DELETE FROM api_configs WHERE id=?", (config_id,))
    db.commit()
    # Activate another if exists
    row = db.execute("SELECT id FROM api_configs LIMIT 1").fetchone()
    if row:
        db.execute("UPDATE api_configs SET is_active=1 WHERE id=?", (row["id"],))
        db.commit()
    _load_active_config()
    return {"ok": True}


@router.post("/api/{config_id}/activate")
def activate_config(config_id: int):
    db = get_db()
    db.execute("UPDATE api_configs SET is_active=0")
    db.execute("UPDATE api_configs SET is_active=1 WHERE id=?", (config_id,))
    db.commit()
    _load_active_config()
    return {"ok": True}


@router.post("/api/test")
async def test_connection(config: ApiConfigCreate):
    try:
        await llm_service.test_connection({
            "base_url": config.base_url,
            "api_key": config.api_key,
            "model": config.model
        })
        return {"ok": True, "message": "连接成功"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
