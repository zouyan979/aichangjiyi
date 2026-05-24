"""Image upload endpoint."""
from __future__ import annotations
import os
import uuid
import base64
import logging
from typing import List
from fastapi import APIRouter, UploadFile, File, HTTPException

log = logging.getLogger("memoria.upload")

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "uploads")
ALLOWED_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp", "image/bmp"}
MAX_SIZE = 10 * 1024 * 1024  # 10MB
MAX_FILES = 4

MIME_EXT = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
}

router = APIRouter(prefix="/api/upload", tags=["upload"])


@router.post("")
async def upload_images(files: List[UploadFile] = File(...)):
    if len(files) > MAX_FILES:
        raise HTTPException(400, f"最多上传 {MAX_FILES} 张图片")

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    results = []

    for f in files:
        content_type = f.content_type or ""
        if content_type not in ALLOWED_TYPES:
            raise HTTPException(400, f"不支持的图片格式: {content_type}")

        data = await f.read()
        if len(data) > MAX_SIZE:
            raise HTTPException(400, f"图片 {f.filename} 超过 10MB 限制")

        ext = MIME_EXT.get(content_type, ".jpg")
        filename = f"{uuid.uuid4().hex}{ext}"
        filepath = os.path.join(UPLOAD_DIR, filename)

        with open(filepath, "wb") as out:
            out.write(data)

        b64 = base64.b64encode(data).decode()
        data_url = f"data:{content_type};base64,{b64}"

        results.append({
            "path": f"uploads/{filename}",
            "data_url": data_url
        })
        log.info("Uploaded: %s (%d bytes)", filename, len(data))

    return {"files": results}
