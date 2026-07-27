"""Configuración de gunicorn: un solo worker porque los jobs viven en memoria."""

import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"
workers = 1
worker_class = "uvicorn.workers.UvicornWorker"
timeout = 600
