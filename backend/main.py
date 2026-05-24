import os
import sys
import logging
from .logger import setup_logging

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

setup_logging(level=logging.INFO)
log = logging.getLogger("memoria")

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.responses import Response

from .database import get_db, close_db
from .routers import config as config_router
from .routers import chat as chat_router
from .routers import conversations as conv_router
from .routers import memory as memory_router
from .routers import persona as persona_router
from .routers import proactive as proactive_router
from .routers import tts as tts_router
from .routers import auth as auth_router
from .routers import upload as upload_router
from .services.proactive_engine import proactive_engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    get_db()  # Initialize DB
    config_router._load_active_config()  # Load active API config
    await proactive_engine.start()
    yield
    # Shutdown
    await proactive_engine.stop()
    close_db()


app = FastAPI(title="Memoria - Long Memory AI", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    # Skip auth for: auth endpoints, static files, localhost
    skip = (
        path.startswith("/api/auth")
        or path.startswith("/css")
        or path.startswith("/js")
        or path.startswith("/uploads")
        or path == "/"
        or path == "/index.html"
        or not path.startswith("/api")
    )
    if not skip:
        try:
            from .routers.auth import is_localhost, is_auth_configured, verify_token
            # Localhost always allowed (desktop app)
            if not is_localhost(request) and is_auth_configured():
                token = request.headers.get("Authorization", "").removeprefix("Bearer ")
                if not verify_token(token):
                    return Response('{"detail":"需要登录"}', status_code=401,
                                    media_type="application/json")
        except Exception:
            pass  # DB error during auth check — allow request through
    return await call_next(request)


# Include routers
app.include_router(auth_router.router)
app.include_router(config_router.router)
app.include_router(chat_router.router)
app.include_router(conv_router.router)
app.include_router(memory_router.router)
app.include_router(persona_router.router)
app.include_router(proactive_router.router)
app.include_router(tts_router.router)
app.include_router(upload_router.router)

# Serve uploaded images
_uploads_dir = os.path.join(os.path.dirname(__file__), "data", "uploads")
os.makedirs(_uploads_dir, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=_uploads_dir), name="uploads")

# Serve frontend static files
if getattr(sys, 'frozen', False):
    # PyInstaller: frontend is bundled in _MEIPASS
    _base = sys._MEIPASS
else:
    _base = os.path.dirname(os.path.dirname(__file__))
frontend_dir = os.path.join(_base, "frontend")
if os.path.exists(frontend_dir):
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
