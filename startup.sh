#!/bin/bash
set -e
# Si Infra configura Startup Command = startup.sh (ASGI nativo)
python -m gunicorn application:app \
  --workers 1 \
  --worker-class uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:${PORT:-8000} \
  --timeout 600 \
  --access-logfile - \
  --error-logfile -
