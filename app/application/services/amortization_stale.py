"""Amortización que quedó en APLICANDO_AMORTIZACION sin un Apply vivo.

Pasa cuando el servidor se reinicia (o falla la última escritura del Control) a mitad
del Apply: el Control nunca llega a un estado final y la UI quedaría «aplicando» para
siempre. Se considera interrumpida si este servidor no tiene una amortización en curso
y además hay evidencia de que el Apply terminó: su job quedó fallido (el arranque marca
como fallidos los jobs huérfanos) o el Control no se actualiza hace más de
``STALE_APPLYING_AFTER``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

APPLYING_ESTADO = "APLICANDO_AMORTIZACION"
STALE_APPLYING_AFTER = timedelta(minutes=10)
_AMORTIZATION_JOB_TYPES = ("amortization_process", "amortization_apply")
_COLOMBIA = timezone(timedelta(hours=-5))


def _parse_timestamp(raw: str) -> datetime | None:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=_COLOMBIA)


def applying_is_stale(
    snap: Any,
    *,
    job_manager: Any = None,
    now: datetime | None = None,
) -> bool:
    estado = (getattr(snap, "estado_proceso", "") or "").strip().upper()
    if estado != APPLYING_ESTADO:
        return False
    if job_manager is None:
        from app.application.job_manager import get_job_manager

        job_manager = get_job_manager()
    if job_manager.is_amortization_active():
        return False
    process_key = (getattr(snap, "process_key", "") or "").strip()
    if process_key:
        latest = job_manager.find_latest_job_by_process_and_types(
            process_key, _AMORTIZATION_JOB_TYPES
        )
        status = str((latest or {}).get("status") or "").strip().lower()
        if status in {"queued", "running"}:
            return False
        if status == "failed":
            return True
    updated = _parse_timestamp(getattr(snap, "last_updated_at_proceso", "") or "")
    if updated is None:
        return True
    current = now or datetime.now(timezone.utc)
    return current - updated >= STALE_APPLYING_AFTER


__all__ = ["APPLYING_ESTADO", "STALE_APPLYING_AFTER", "applying_is_stale"]
