"""Control de proceso en disco del App Service (espejo de fila 2).

Particionado por ``ACTIVE_ENVIRONMENT`` para que sandbox y producción
puedan compartir el mismo App Service sin cruzar estado.

Escritura atómica ``.tmp`` → ``replace``, igual que ``JobManager``.
El I/O síncrono se ejecuta fuera del event loop vía ``asyncio.to_thread``.
"""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SAFE_BANK = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_STORE_MODES = frozenset({"dual", "local", "excel"})

SCHEMA_VERSION = 1


def process_control_store_mode() -> str:
    raw = (os.getenv("PROCESS_CONTROL_STORE") or "dual").strip().lower()
    if raw not in _STORE_MODES:
        return "dual"
    return raw


def resolve_active_environment_name() -> str:
    raw = (os.getenv("ACTIVE_ENVIRONMENT") or "").strip().lower()
    if raw in ("sandbox", "production"):
        return raw
    return "unknown"


def control_store_dir() -> Path:
    raw = (os.getenv("PAYMENT_VALIDATION_CONTROL_STORE_DIR") or "").strip()
    if raw:
        return Path(raw)
    if (os.getenv("WEBSITE_INSTANCE_ID") or "").strip():
        return Path("/home/site/wwwroot/.payment_validation_control")
    home = (os.getenv("HOME") or "").strip()
    wwwroot = Path(home) / "site" / "wwwroot" if home else None
    if wwwroot is not None and wwwroot.is_dir():
        return wwwroot / ".payment_validation_control"
    return Path(tempfile.gettempdir()) / "hbi_payment_validation_control"


def control_store_path(*, environment: str | None = None, bank_code: str) -> Path | None:
    bank = (bank_code or "").strip()
    if not _SAFE_BANK.match(bank):
        return None
    env = (environment or resolve_active_environment_name()).strip().lower() or "unknown"
    if not _SAFE_BANK.match(env):
        env = "unknown"
    return control_store_dir() / env / f"{bank}.json"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def jsonable_cell(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    iso = getattr(value, "isoformat", None)
    if callable(iso):
        try:
            return iso()
        except Exception:
            return str(value)
    return str(value)


def jsonable_cells(cells: dict[str, Any]) -> dict[str, Any]:
    return {str(k): jsonable_cell(v) for k, v in cells.items()}


def build_store_payload(
    *,
    environment: str,
    bank_code: str,
    control_file_path: str,
    cells: dict[str, Any],
    updated_at: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "environment": environment,
        "bank_code": bank_code,
        "control_file_path": control_file_path,
        "updated_at": updated_at or _utc_now_iso(),
        "cells": jsonable_cells(cells),
    }


def load_control_payload(*, environment: str | None = None, bank_code: str) -> dict[str, Any] | None:
    path = control_store_path(environment=environment, bank_code=bank_code)
    if path is None or not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("process_control_store_load_failed path=%s", path, exc_info=True)
        return None
    if not isinstance(raw, dict):
        return None
    cells = raw.get("cells")
    if not isinstance(cells, dict):
        return None
    return raw


def persist_control_payload(payload: dict[str, Any]) -> bool:
    """Write atómico. False si el disco falla (no debe tumbar el job)."""
    bank = str(payload.get("bank_code") or "").strip()
    env = str(payload.get("environment") or "").strip()
    path = control_store_path(environment=env, bank_code=bank)
    if path is None:
        return False
    tmp = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        tmp.replace(path)
        return True
    except OSError:
        logger.warning("process_control_store_write_failed path=%s", path, exc_info=True)
        try:
            if tmp.is_file():
                tmp.unlink()
        except OSError:
            pass
        return False
