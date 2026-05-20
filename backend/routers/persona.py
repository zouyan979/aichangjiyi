from __future__ import annotations
from fastapi import APIRouter
from ..models import PersonaUpdate
from ..services.persona_service import persona_service, RELATIONSHIP_STAGES, STAGE_ORDER

router = APIRouter(prefix="/api/persona", tags=["persona"])


@router.get("")
def get_persona():
    persona = persona_service.get_persona()
    stage_key = persona.get("relationship_stage", "acquaintance")
    stage_info = RELATIONSHIP_STAGES.get(stage_key, {})
    persona["relationship_stage_label"] = stage_info.get("label", "初识")
    persona["relationship_stage_style"] = stage_info.get("style", "")
    persona["all_stages"] = [
        {"key": k, "label": RELATIONSHIP_STAGES[k]["label"],
         "min_days": RELATIONSHIP_STAGES[k]["min_days"],
         "min_messages": RELATIONSHIP_STAGES[k]["min_messages"]}
        for k in STAGE_ORDER
    ]
    return persona


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
