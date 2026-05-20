from __future__ import annotations
from fastapi import APIRouter
from ..models import PersonaUpdate
from ..services.persona_service import persona_service

router = APIRouter(prefix="/api/persona", tags=["persona"])


@router.get("")
def get_persona():
    return persona_service.get_persona()


@router.put("")
def update_persona(data: PersonaUpdate):
    persona_service.update_persona(data.model_dump(exclude_none=True))
    return {"ok": True}


@router.post("/reset")
def reset_persona():
    persona_service.reset_persona()
    return {"ok": True}


@router.get("/growth-log")
def get_growth_log():
    return persona_service.get_growth_log()
