from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime


# ---- API Config ----
class ApiConfigCreate(BaseModel):
    name: str = "default"
    base_url: str
    api_key: Optional[str] = None
    model: str
    temperature: float = 0.8
    max_tokens: int = 2048


class ApiConfigUpdate(BaseModel):
    name: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None


class ApiConfigOut(BaseModel):
    id: int
    name: str
    base_url: str
    api_key: str
    model: str
    temperature: float
    max_tokens: int
    is_active: bool


# ---- Conversation ----
class ConversationCreate(BaseModel):
    title: str = "新对话"


class ConversationUpdate(BaseModel):
    title: Optional[str] = None


class ConversationOut(BaseModel):
    id: int
    title: str
    created_at: str
    updated_at: str
    message_count: int


# ---- Chat ----
class ChatRequest(BaseModel):
    conversation_id: int = 1
    content: str


# ---- Messages ----
class MessageOut(BaseModel):
    id: int
    conversation_id: int
    role: str
    content: str
    token_count: int
    is_proactive: bool
    created_at: str


# ---- User Profile ----
class ProfileItemCreate(BaseModel):
    category: str
    content: str
    source: str = "manual"


class ProfileItemOut(BaseModel):
    id: int
    category: str
    content: str
    source: str
    confidence: float


# ---- Core Fact ----
class CoreFactCreate(BaseModel):
    content: str
    priority: int = 5
    category: str = "general"
    is_pinned: bool = False


class CoreFactUpdate(BaseModel):
    content: Optional[str] = None
    priority: Optional[int] = None
    category: Optional[str] = None
    is_pinned: Optional[bool] = None


class CoreFactOut(BaseModel):
    id: int
    content: str
    priority: int
    category: str
    is_pinned: bool


# ---- Summary ----
class SummaryOut(BaseModel):
    id: int
    conversation_id: Optional[int]
    summary: str
    topics: List[str]
    mood: str
    key_facts: List[str]
    token_estimate: int
    created_at: str


# ---- AI Persona ----
class PersonaUpdate(BaseModel):
    name: Optional[str] = None
    base_persona: Optional[str] = None
    speaking_style: Optional[str] = None
    background: Optional[str] = None
    relationship: Optional[str] = None
    emotion_state: Optional[str] = None


class PersonaOut(BaseModel):
    id: int
    name: str
    base_persona: str
    speaking_style: str
    background: str
    relationship: str
    emotion_state: str
    growth_log: List[Dict[str, Any]]
    version: int


# ---- Proactive ----
class ProactiveConfigUpdate(BaseModel):
    enabled: Optional[bool] = None
    interval_minutes: Optional[int] = None
    morning_range: Optional[str] = None
    evening_range: Optional[str] = None
    absence_hours: Optional[int] = None


class ProactiveLogOut(BaseModel):
    id: int
    trigger_type: str
    trigger_detail: str
    content: Optional[str]
    was_sent: bool
    created_at: str


# ---- Memory Stats ----
class MemoryStatsOut(BaseModel):
    total_messages: int
    total_summaries: int
    profile_items: int
    core_facts: int
    estimated_saved_tokens: int


# ---- Context Preview ----
class ContextPreviewOut(BaseModel):
    system_prompt: str
    selected_summaries: List[str]
    recent_messages: List[Dict[str, Any]]
    estimated_tokens: int
