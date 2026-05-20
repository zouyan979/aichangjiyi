from __future__ import annotations
from fastapi import APIRouter
from ..models import ProactiveConfigUpdate
from ..services.proactive_engine import proactive_engine

router = APIRouter(prefix="/api/proactive", tags=["proactive"])


@router.get("/config")
def get_config():
    return proactive_engine._get_config()


@router.put("/config")
def update_config(data: ProactiveConfigUpdate):
    proactive_engine.update_config(data.model_dump(exclude_none=True))
    return {"ok": True}


@router.get("/pending")
def get_pending():
    msg = proactive_engine.get_pending()
    return msg or {}


@router.get("/log")
def get_log(limit: int = 20):
    return proactive_engine.get_log(limit)


@router.post("/trigger")
async def manual_trigger():
    await proactive_engine._send_proactive("manual", "手动触发")
    return {"ok": True}
