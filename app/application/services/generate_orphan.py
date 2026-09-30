"""GENERANDO huérfano: el Control anuncia Generate pero ningún job lo sostiene."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.application.services.colombia_time import parse_graph_datetime

ORPHAN_GENERATE_STALE_AFTER = timedelta(minutes=10)

_TERMINAL_JOB_STATUSES = frozenset({"failed", "cancelled", "canceled"})
_LIVE_JOB_STATUSES = frozenset({"queued", "running"})


def _job_last_seen(job: dict[str, Any]) -> datetime | None:
    for key in ("heartbeat_at", "updated_at"):
        dt = parse_graph_datetime(str(job.get(key) or ""))
        if dt is not None:
            return dt
    return None


def is_orphan_generating(
    estado: str | None,
    generate_job_id: str | None,
    *,
    job_manager: Any = None,
    now: datetime | None = None,
    check_generate_lock: bool = True,
    current_job_id: str | None = None,
) -> bool:
    """True si el Control está en GENERANDO sin un Generate vivo que lo respalde.

    ``check_generate_lock=False`` lo usan Generate y Cancelar, que ya corren con
    el mutex de Generate tomado (el lock propio no prueba que haya otro job).
    """
    if (estado or "").strip().upper() != "GENERANDO":
        return False
    if job_manager is None:
        from app.application.job_manager import get_job_manager

        job_manager = get_job_manager()
    if check_generate_lock and job_manager.is_generate_or_finalize_active():
        return False
    job_id = (generate_job_id or "").strip()
    if current_job_id and job_id == current_job_id.strip():
        return False
    job = job_manager.get_job(job_id) if job_id else None
    if not isinstance(job, dict):
        return True
    status = str(job.get("status") or "").strip().lower()
    if status in _TERMINAL_JOB_STATUSES:
        return True
    if status in _LIVE_JOB_STATUSES:
        last_seen = _job_last_seen(job)
        if last_seen is None:
            return False
        ref = now or datetime.now(timezone.utc)
        return ref - last_seen > ORPHAN_GENERATE_STALE_AFTER
    return False
