from __future__ import annotations
from fastapi import APIRouter, HTTPException
from ..models import (ProfileItemCreate, CoreFactCreate, CoreFactUpdate,
                      SummaryOut, MemoryStatsOut, ContextPreviewOut)
from ..services.memory_service import memory_service
from ..services.context_builder import context_builder

router = APIRouter(prefix="/api/memory", tags=["memory"])


# ---- Profile ----
@router.get("/profile")
def get_profile():
    return memory_service.get_profile()


@router.post("/profile")
def add_profile_item(item: ProfileItemCreate):
    if item.category not in ("name", "interest", "trait", "fact", "preference", "goal"):
        raise HTTPException(400, "无效的分类")
    memory_service.add_profile_item(item.category, item.content, item.source)
    return {"ok": True}


@router.delete("/profile/{category}/{item_id}")
def delete_profile_item(category: str, item_id: int):
    memory_service.delete_profile_item(item_id)
    return {"ok": True}


# ---- Core Facts ----
@router.get("/core-facts")
def get_core_facts():
    return memory_service.get_core_facts()


@router.post("/core-facts")
def add_core_fact(fact: CoreFactCreate):
    memory_service.add_core_fact(fact.content, fact.priority, fact.category, fact.is_pinned)
    return {"ok": True}


@router.put("/core-facts/{fact_id}")
def update_core_fact(fact_id: int, updates: CoreFactUpdate):
    memory_service.update_core_fact(fact_id, updates.model_dump(exclude_none=True))
    return {"ok": True}


@router.delete("/core-facts/{fact_id}")
def delete_core_fact(fact_id: int):
    memory_service.delete_core_fact(fact_id)
    return {"ok": True}


# ---- Summaries ----
@router.get("/summaries")
def get_summaries(conversation_id: int = None, limit: int = 50):
    return memory_service.get_summaries(conversation_id, limit)


# ---- Stats ----
@router.get("/stats")
def get_stats():
    return memory_service.get_stats()


# ---- Context Preview ----
@router.get("/context-preview")
def context_preview(q: str = "你好", conversation_id: int = 1, budget: int = 3000):
    return context_builder.get_preview(q, conversation_id, budget)


# ---- Export/Import ----
@router.get("/export")
def export_memory():
    return memory_service.export_all()


@router.post("/import")
def import_memory(data: dict):
    try:
        memory_service.import_data(data)
        return {"ok": True}
    except Exception as e:
        raise HTTPException(400, str(e))


@router.post("/clear")
def clear_memory():
    memory_service.clear_all()
    return {"ok": True}
