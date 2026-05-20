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
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .database import get_db, close_db
from .routers import config as config_router
from .routers import chat as chat_router
from .routers import conversations as conv_router
from .routers import memory as memory_router
from .routers import persona as persona_router
from .routers import proactive as proactive_router
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

# Include routers
app.include_router(config_router.router)
app.include_router(chat_router.router)
app.include_router(conv_router.router)
app.include_router(memory_router.router)
app.include_router(persona_router.router)
app.include_router(proactive_router.router)

# Serve frontend static files
frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
if os.path.exists(frontend_dir):
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
