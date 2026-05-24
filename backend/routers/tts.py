from __future__ import annotations
import base64
from fastapi import APIRouter, HTTPException
from ..models import TTSRequest, TTSConfigUpdate
from ..services.tts_service import tts_service

router = APIRouter(prefix="/api/tts", tags=["tts"])


@router.get("/config")
def get_config():
    cfg = tts_service._get_config()
    return {
        "enabled": cfg.get("enabled", False),
        "voice": cfg.get("voice", "冰糖"),
        "available": tts_service.is_available(),
        "voices": [
            {"id": "冰糖", "name": "冰糖", "gender": "女", "lang": "中文"},
            {"id": "茉莉", "name": "茉莉", "gender": "女", "lang": "中文"},
            {"id": "苏打", "name": "苏打", "gender": "男", "lang": "中文"},
            {"id": "白桦", "name": "白桦", "gender": "男", "lang": "中文"},
            {"id": "Mia", "name": "Mia", "gender": "女", "lang": "英文"},
            {"id": "Chloe", "name": "Chloe", "gender": "女", "lang": "英文"},
            {"id": "Milo", "name": "Milo", "gender": "男", "lang": "英文"},
            {"id": "Dean", "name": "Dean", "gender": "男", "lang": "英文"},
        ]
    }


@router.put("/config")
def update_config(data: TTSConfigUpdate):
    tts_service.update_config(data.model_dump(exclude_none=True))
    return {"ok": True}


@router.post("/synthesize")
async def synthesize(data: TTSRequest):
    if not tts_service.is_available():
        raise HTTPException(400, "语音合成不可用，请检查 API 配置")
    cfg = tts_service._get_config()
    voice = cfg.get("voice", "冰糖")
    try:
        audio_bytes = await tts_service.synthesize(data.text, voice)
        return {"audio": base64.b64encode(audio_bytes).decode("ascii")}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/test")
async def test_voice():
    if not tts_service.is_available():
        raise HTTPException(400, "语音合成不可用，请检查 API 配置")
    cfg = tts_service._get_config()
    voice = cfg.get("voice", "冰糖")
    try:
        audio_bytes = await tts_service.synthesize("你好，这是语音测试。", voice)
        return {"audio": base64.b64encode(audio_bytes).decode("ascii")}
    except ValueError as e:
        raise HTTPException(400, str(e))
