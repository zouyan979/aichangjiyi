"""Memoria 生产环境入口"""
import os
import sys

# Ensure we're in the project root
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from backend.main import app  # noqa: E402

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.main:app",
        host="127.0.0.1",
        port=8765,
        workers=1,  # SQLite needs single worker
        log_level="info",
    )
