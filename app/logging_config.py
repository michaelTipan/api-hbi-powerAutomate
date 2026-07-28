"""Configuración de logging para que los mensajes de `app.*` salgan en consola."""

from __future__ import annotations

import logging
import os
import sys
import time
from datetime import datetime

from app.application.services.colombia_time import COLOMBIA_TZ


def _asctime_colombia(secs: float | None = None) -> time.struct_time:
    """Convierte epoch a struct_time en America/Bogota (para %(asctime)s)."""
    stamp = time.time() if secs is None else secs
    return datetime.fromtimestamp(stamp, tz=COLOMBIA_TZ).timetuple()


def configure_logging() -> None:
    """Configura logging con reloj America/Bogota (no UTC del App Service)."""
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    root = logging.getLogger()
    if not root.handlers:
        handler = logging.StreamHandler(sys.stderr)
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        formatter.converter = _asctime_colombia  # type: ignore[method-assign]
        handler.setFormatter(formatter)
        root.addHandler(handler)

    root.setLevel(level)
    logging.getLogger("app").setLevel(level)
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)
