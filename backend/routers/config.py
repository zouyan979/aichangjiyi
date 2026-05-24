from __future__ import annotations
import os
import glob
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from ..database import get_db
from ..config import DB_PATH
from ..models import ApiConfigCreate, ApiConfigUpdate, ApiConfigOut, SearchConfigUpdate
from ..services.llm_service import llm_service
from ..services.search_service import search_service
from ..services.weather_service import weather_service

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


def _mask_key(key: str) -> str:
    """Mask API key, showing only last 4 characters."""
    if not key or len(key) <= 8:
        return "****"
    return "*" * (len(key) - 4) + key[-4:]


@router.get("/api")
def list_configs():
    db = get_db()
    rows = db.execute("SELECT * FROM api_configs ORDER BY id").fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["is_active"] = bool(d["is_active"])
        d["api_key"] = _mask_key(d["api_key"])
        result.append(d)
    return result


@router.post("/api")
def create_config(config: ApiConfigCreate):
    db = get_db()
    # If api_key not provided, keep the existing active config's key
    api_key = config.api_key
    if not api_key:
        row = db.execute("SELECT api_key FROM api_configs WHERE is_active=1 LIMIT 1").fetchone()
        api_key = row["api_key"] if row else ""
    cursor = db.execute(
        "INSERT INTO api_configs (name, base_url, api_key, model, temperature, max_tokens, is_active) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (config.name, config.base_url, api_key, config.model,
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


@router.get("/search")
def get_search_config():
    cfg = search_service.get_config()
    # Mask API key
    key = cfg.get("tavily_api_key", "")
    cfg["tavily_api_key"] = _mask_key(key) if key else ""
    return cfg


@router.put("/search")
def update_search_config(config: SearchConfigUpdate):
    updates = config.model_dump(exclude_none=True)
    # If key is masked (unchanged), don't overwrite
    if "tavily_api_key" in updates:
        key = updates["tavily_api_key"]
        if key and "*" in key:
            del updates["tavily_api_key"]
    search_service.update_config(updates)
    return {"ok": True}


@router.get("/weather")
def get_weather_config():
    return {"city": weather_service.get_city()}


@router.put("/weather")
def update_weather_config(city: str = ""):
    weather_service.set_city(city)
    return {"ok": True}


@router.get("/backup/download")
def download_backup():
    """Download current database as backup file."""
    if not os.path.exists(DB_PATH):
        raise HTTPException(status_code=404, detail="数据库不存在")
    return FileResponse(DB_PATH, filename="memoria_backup.db", media_type="application/octet-stream")


@router.get("/backup/list")
def list_backups():
    """List available auto-backups."""
    backup_dir = os.path.join(os.path.dirname(DB_PATH), "backups")
    if not os.path.exists(backup_dir):
        return []
    backups = []
    for f in sorted(glob.glob(os.path.join(backup_dir, "memoria_*.db")), reverse=True):
        stat = os.stat(f)
        backups.append({
            "name": os.path.basename(f),
            "size": stat.st_size,
            "created": stat.st_mtime
        })
    return backups


@router.post("/backup/restore/{name}")
def restore_backup(name: str):
    """Restore from a backup file."""
    import shutil
    backup_dir = os.path.join(os.path.dirname(DB_PATH), "backups")
    backup_path = os.path.join(backup_dir, name)
    if not os.path.exists(backup_path) or ".." in name:
        raise HTTPException(status_code=404, detail="备份不存在")
    # Close existing connection
    from ..database import close_db
    close_db()
    shutil.copy2(backup_path, DB_PATH)
    # Remove WAL files
    for ext in ["-wal", "-shm"]:
        wal = DB_PATH + ext
        if os.path.exists(wal):
            os.remove(wal)
    return {"ok": True, "message": "已恢复，请刷新页面"}
