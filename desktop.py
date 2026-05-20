"""Memoria Desktop - Windows桌面应用入口"""
import sys
import os
import threading
import time
import socket

# Ensure backend package is importable
if getattr(sys, 'frozen', False):
    os.chdir(os.path.dirname(sys.executable))

PORT = 8765
HOST = "127.0.0.1"


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def start_server():
    import uvicorn
    uvicorn.run(
        "backend.main:app",
        host=HOST,
        port=PORT,
        log_level="warning",
        access_log=False,
    )


def main():
    # Start FastAPI in background thread
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()

    # Wait for server to be ready
    for _ in range(50):
        if _port_open(PORT):
            break
        time.sleep(0.1)
    else:
        print("Server failed to start within 5 seconds")
        sys.exit(1)

    # Open webview window
    import webview
    window = webview.create_window(
        "Memoria · 长记忆 AI",
        f"http://{HOST}:{PORT}",
        width=1100,
        height=750,
        min_size=(800, 600),
        text_select=True,
    )
    webview.start(debug=False)


if __name__ == "__main__":
    main()
