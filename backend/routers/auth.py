"""Authentication router - simple password protection for remote access."""
from __future__ import annotations
import hashlib
import hmac
import os
import time
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from ..database import get_db

router = APIRouter(prefix="/api/auth", tags=["auth"])

# In-memory token store (valid for 24h)
_valid_tokens: dict[str, float] = {}
TOKEN_TTL = 86400  # 24 hours


def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def _get_stored_hash() -> str | None:
    db = get_db()
    row = db.execute("SELECT value FROM app_settings WHERE key='auth_password'").fetchone()
    return row["value"] if row else None


def _generate_token(password_hash: str) -> str:
    token = hashlib.sha256(f"{password_hash}{time.time()}{os.urandom(8).hex()}".encode()).hexdigest()
    _valid_tokens[token] = time.time() + TOKEN_TTL
    return token


def _cleanup_tokens():
    now = time.time()
    expired = [t for t, exp in _valid_tokens.items() if exp < now]
    for t in expired:
        del _valid_tokens[t]


def is_localhost(request: Request) -> bool:
    # Check X-Forwarded-For first (behind reverse proxy like Nginx)
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        # First IP in the chain is the real client
        real_ip = forwarded.split(",")[0].strip()
        return real_ip in ("127.0.0.1", "::1", "localhost")
    host = request.client.host if request.client else ""
    return host in ("127.0.0.1", "::1", "localhost")


def is_auth_configured() -> bool:
    return _get_stored_hash() is not None


def verify_token(token: str | None) -> bool:
    if not token:
        return False
    _cleanup_tokens()
    exp = _valid_tokens.get(token)
    if exp and exp > time.time():
        return True
    return False


class PasswordSetRequest(BaseModel):
    password: str


class LoginRequest(BaseModel):
    password: str


@router.get("/status")
def auth_status():
    return {
        "configured": is_auth_configured(),
        "required": is_auth_configured()
    }


@router.post("/set-password")
def set_password(req: PasswordSetRequest):
    if len(req.password) < 4:
        raise HTTPException(400, "密码至少4位")
    db = get_db()
    pw_hash = _hash_password(req.password)
    db.execute(
        "INSERT OR REPLACE INTO app_settings (key, value) VALUES ('auth_password', ?)",
        (pw_hash,)
    )
    db.commit()
    token = _generate_token(pw_hash)
    return {"ok": True, "token": token}


@router.post("/login")
def login(req: LoginRequest):
    stored_hash = _get_stored_hash()
    if not stored_hash:
        raise HTTPException(400, "未设置密码")
    input_hash = _hash_password(req.password)
    if not hmac.compare_digest(input_hash, stored_hash):
        raise HTTPException(401, "密码错误")
    token = _generate_token(stored_hash)
    return {"ok": True, "token": token}


@router.post("/remove-password")
def remove_password(request: Request):
    # Only allow from localhost
    if not is_localhost(request):
        raise HTTPException(403, "仅允许本地操作")
    db = get_db()
    db.execute("DELETE FROM app_settings WHERE key='auth_password'")
    db.commit()
    _valid_tokens.clear()
    return {"ok": True}
