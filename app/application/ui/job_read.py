"""Lectura opcional de jobs para la UI (sin migrar stores).

- Generate / Finalize / Dry-run / Apply → JobManager (disco).
- Notify / Merge → dict in-memory de sharepoint (solo si el proceso sigue vivo).

La proyección de negocio NO debe depender de estos stores como verdad.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Literal

from app.application.job_manager import JobManager

logger = logging.getLogger(__name__)

JobStoreName = Literal["job_manager", "sharepoint_memory", "none"]

MemoryJobLookup = Callable[[str], dict[str, Any] | None]


@dataclass(frozen=True)
class JobReadResult:
    job_id: str
    payload: dict[str, Any]
    store: JobStoreName


def _graph_poll_path(job_type: str, job_id: str) -> str | None:
    t = (job_type or "").strip().lower()
    if t in {"generate", "finalize", "amortization_dry_run", "amortization_apply"}:
        return f"/graph/sharepoint/payment-validation/jobs/{job_id}"
    if t in {"notify_validar_extractos", "notify"}:
        return f"/graph/sharepoint/notify-validar-extractos-email/jobs/{job_id}"
    if t in {"merge_composite_validado_pdfs", "merge"}:
        return f"/graph/sharepoint/merge-composite-validado-pdfs/jobs/{job_id}"
    return None


def read_job_manager(job_id: str) -> JobReadResult | None:
    job = JobManager().get_job(job_id)
    if not job:
        return None
    return JobReadResult(job_id=job_id, payload=dict(job), store="job_manager")


def _legacy_memory_lookup() -> MemoryJobLookup | None:
    """Store legado de Notify/Merge en el router de SharePoint.

    Ese diccionario se movió a ``JobManager`` (ya cubierto por
    ``read_job_manager``), así que hoy puede no existir. Si falta, no hay
    segundo store y la lectura debe devolver ``None``: un ``AttributeError``
    aquí rompía la proyección completa del proceso (lista vacía y 500 en el
    detalle para cualquier proceso con NotifyJobId o MergeJobId en Control).
    """
    try:
        from app.adapters.primary.http.routers import sharepoint as sp
    except Exception:
        return None
    store = getattr(sp, "_validation_jobs", None)
    if not isinstance(store, dict):
        return None
    return lambda jid: store.get(jid)


def read_sharepoint_memory_job(
    job_id: str,
    *,
    lookup: MemoryJobLookup | None = None,
) -> JobReadResult | None:
    """Busca un job Notify/Merge vivo. ``lookup`` inyectable en tests."""
    resolved = lookup if lookup is not None else _legacy_memory_lookup()
    if resolved is None:
        return None
    try:
        hit = resolved(job_id)
    except Exception as exc:
        logger.warning(
            "job_read: memory lookup falló job_id=%s err=%s",
            job_id,
            type(exc).__name__,
        )
        return None
    if not hit:
        return None
    return JobReadResult(job_id=job_id, payload=dict(hit), store="sharepoint_memory")


def read_any_job(
    job_id: str,
    *,
    memory_lookup: MemoryJobLookup | None = None,
) -> JobReadResult | None:
    found = read_job_manager(job_id)
    if found:
        return found
    return read_sharepoint_memory_job(job_id, lookup=memory_lookup)


def build_poll_paths(job_type: str, job_id: str) -> tuple[str | None, str]:
    return _graph_poll_path(job_type, job_id), f"/api/ui/v1/jobs/{job_id}"
