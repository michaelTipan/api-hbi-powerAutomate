#!/bin/bash
set -e
cd /home/site/wwwroot
export LD_LIBRARY_PATH=/tmp/oryx/platforms/python/3.14.4/lib
ORYX_PY="/tmp/oryx/platforms/python/3.14.4/bin/python3"
if [ ! -x "$ORYX_PY" ]; then ORYX_PY=python3; fi
export PYTHONPATH=/home/site/wwwroot:/home/site/wwwroot/.python_packages/lib/site-packages
exec "$ORYX_PY" -m gunicorn application:app \
  --bind=0.0.0.0:${PORT:-8000} \
  --workers=1 \
  --worker-class=uvicorn.workers.UvicornWorker \
  --timeout=600
