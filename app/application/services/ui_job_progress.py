"""Progreso numérico de jobs UI (merge / amort / generate-compatible)."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def set_ui_job_progress(
    job_id: str | None,
    *,
    phase: str,
    current: int,
    total: int,
    extra: dict[str, Any] | None = None,
) -> None:
    """Actualiza ``job.progress`` sin fallar el trabajo principal."""
    if not job_id:
        return
    try:
        from app.application.job_manager import JobManager
        from app.application.services.colombia_time import now_colombia_iso

        payload: dict[str, Any] = {
            "updated_at": now_colombia_iso(),
            "progress": {
                "phase": phase,
                "current": int(current),
                "total": int(total),
            },
        }
        if extra:
            payload["progress"].update(extra)
        await JobManager().set_job(job_id, payload)
    except Exception:
        logger.exception("job %s: no se pudo registrar progress (%s)", job_id, phase)
