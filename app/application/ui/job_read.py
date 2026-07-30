"""Lectura opcional de jobs para la UI (sin migrar stores).

- Generate / Finalize / Dry-run / Apply → JobManager (disco).
- Notify / Merge → dict in-memory de sharepoint (solo si el proceso sigue vivo).

La proyección de negocio NO debe depender de estos stores como verdad.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal

from app.application.job_manager import JobManager

JobStoreName = Literal["job_manager", "sharepoint_memory", "none"]


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


def read_sharepoint_memory_job(
    job_id: str,
    *,
    lookup: Callable[[str], dict[str, Any] | None] | None = None,
) -> JobReadResult | None:
    """Busca un job Notify/Merge vivo. ``lookup`` inyectable en tests."""
    if lookup is None:
        try:
            from app.adapters.primary.http.routers import sharepoint as sp

            lookup = lambda jid: sp._validation_jobs.get(jid)  # noqa: E731
        except Exception:
            return None
    hit = lookup(job_id) if lookup else None
    if not hit:
        return None
    return JobReadResult(job_id=job_id, payload=dict(hit), store="sharepoint_memory")


def read_any_job(
    job_id: str,
    *,
    memory_lookup: Callable[[str], dict[str, Any] | None] | None = None,
) -> JobReadResult | None:
    found = read_job_manager(job_id)
    if found:
        return found
    return read_sharepoint_memory_job(job_id, lookup=memory_lookup)


def build_poll_paths(job_type: str, job_id: str) -> tuple[str | None, str]:
    return _graph_poll_path(job_type, job_id), f"/api/ui/v1/jobs/{job_id}"
