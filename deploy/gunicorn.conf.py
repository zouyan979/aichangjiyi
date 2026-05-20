"""Gunicorn 配置 - Memoria 生产部署"""
import os

# 绑定地址（只监听本地，由 Nginx 反代）
bind = "127.0.0.1:8765"

# Worker 数量：SQLite 是单连接，必须用 1 个 worker
workers = 1
worker_class = "uvicorn.workers.UvicornWorker"

# 超时
timeout = 120
graceful_timeout = 30
keepalive = 5

# 日志
accesslog = "-"
errorlog = "-"
loglevel = "info"

# 进程
daemon = False
pidfile = None
umask = 0
user = None
group = None
tmp_upload_dir = None
