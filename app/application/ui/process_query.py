"""Orquestación read-only: puerto SharePoint + jobs → proyección."""
from __future__ import annotations

import logging
from typing import Any, Callable, Protocol

from app.application.ui.amortization_readiness import (
    AmortizationReadiness,
    assess_amortization_readiness,
)
from app.application.ui.job_read import JobReadResult, read_any_job, read_job_manager
from app.application.ui.merge_readiness import MergeReadiness, assess_merge_readiness
from app.application.ui.ports import UiControlReadResult, UiSharePointReadPort
from app.application.ui.process_projection import (
    ManifestEvidence,
    PaymentProcessProjectionService,
    ProjectionSources,
    TechnicalJobEvidence,
)
from app.application.ui.schemas import UiProcessDetail
from app.application.use_cases.amortization_fill_dry_run import (
    AMORTIZATION_RUNNABLE_STATES,
)
from app.application.use_cases.merge_composite_validado_pdfs import (
    MERGE_RUNNABLE_STATES,
)

logger = logging.getLogger(__name__)

MemoryJobLookup = Callable[[str], dict | None]


class _GraphLike(Protocol):
    async def get(self, *a: Any, **k: Any) -> Any: ...
    async def get_bytes(self, *a: Any, **k: Any) -> Any: ...


class UiProcessQueryService:
    """Consulta acotada por banco / process_key. Sin barridos de clientes."""

    def __init__(
        self,
        reader: UiSharePointReadPort,
        *,
        projection: PaymentProcessProjectionService | None = None,
        memory_job_lookup: MemoryJobLookup | None = None,
        graph: _GraphLike | None = None,
        assess_merge: bool = False,
        assess_amortization: bool = False,
    ) -> None:
        self._reader = reader
        self._projection = projection or PaymentProcessProjectionService()
        self._memory_lookup = memory_job_lookup
        self._graph = graph
        self._assess_merge = assess_merge
        self._assess_amortization = assess_amortization

    async def _jobs_for_control(self, control: UiControlReadResult) -> TechnicalJobEvidence:
        by_type: dict[str, JobReadResult] = {}
        mapping = {
            "generate": control.generate_job_id,
            "finalize": control.finalize_job_id,
            "amortization_dry_run": control.dry_run_job_id,
            "amortization_apply": control.apply_job_id,
        }
        for type_name, job_id in mapping.items():
            if not job_id:
                continue
            found = read_job_manager(job_id)
            if found:
                by_type[type_name] = found

        memory: JobReadResult | None = None
        for job_id in (control.notify_job_id, control.merge_job_id):
            if not job_id:
                continue
            found = read_any_job(job_id, memory_lookup=self._memory_lookup)
            if found:
                # Persistidos van a by_type; memoria a memory_job.
                if found.store == "job_manager":
                    by_type[str(found.payload.get("type") or job_id)] = found
                else:
                    memory = found
                    break

        # U4-A: jobs terminales (p. ej. Finalize failed) no dejan ID en Control.
        # Recuperar el último por ProcessKey + tipo desde JobManager.
        process_key = (control.snapshot.process_key or "").strip()
        if process_key:
            from app.application.job_manager import get_job_manager
            from app.application.ui.job_stage_types import STAGE_JOB_TYPES

            jm = get_job_manager()
            stage_keys = {
                "generate": "generate",
                "finalize": "finalize",
                "notify": "notify",
                "merge": "merge",
                "amortization": "amortization",
            }
            for stage, type_key in stage_keys.items():
                types = STAGE_JOB_TYPES.get(stage, ())
                latest = jm.find_latest_job_by_process_and_types(process_key, types)
                if not latest:
                    continue
                job_id = str(latest.get("job_id") or "").strip()
                if not job_id:
                    continue
                # No sobrescribir un job más reciente ya cargado por ID de control
                # salvo que el de disco sea más nuevo.
                existing = by_type.get(type_key) or by_type.get(stage)
                if existing:
                    ex_ts = str(
                        existing.payload.get("finished_at")
                        or existing.payload.get("updated_at")
                        or ""
                    )
                    new_ts = str(
                        latest.get("finished_at") or latest.get("updated_at") or ""
                    )
                    if ex_ts and new_ts and new_ts < ex_ts:
                        continue
                by_type[stage] = JobReadResult(
                    job_id=job_id,
                    store="job_manager",
                    payload=latest,
                )

        return TechnicalJobEvidence(job_manager_by_type=by_type, memory_job=memory)

    async def _web_urls(self, control: UiControlReadResult) -> dict[str, str]:
        snap = control.snapshot
        urls: dict[str, str] = {}
        if control.meta.web_url:
            urls["control"] = control.meta.web_url
        pairs = (
            ("review_excel", snap.validation_file_path),
            ("historical", snap.historical_file_path),
            ("secretary_file", snap.secretary_file_path),
            ("email_pdf", snap.email_pdf_path),
            ("merge_manifest", snap.merge_manifest_path),
            ("execution_log", snap.execution_log_path),
        )
        for rel, path in pairs:
            p = (path or "").strip()
            if not p:
                continue
            try:
                url = await self._reader.get_web_url(p)
            except Exception as exc:
                logger.info("ui_query: webUrl skip rel=%s err=%s", rel, type(exc).__name__)
                continue
            if url:
                urls[rel] = url
        return urls

    async def _artifact_exists(self, control: UiControlReadResult) -> dict[str, bool]:
        snap = control.snapshot
        out: dict[str, bool] = {}
        for path in (
            snap.validation_file_path,
            snap.historical_file_path,
            snap.email_pdf_path,
            snap.merge_manifest_path,
            snap.secretary_file_path,
        ):
            p = (path or "").strip()
            if not p:
                continue
            try:
                meta = await self._reader.get_item_meta(p)
                out[p] = bool(meta.exists)
            except Exception:
                out[p] = False
        return out

    async def _manifest(self, control: UiControlReadResult) -> ManifestEvidence | None:
        path = (control.snapshot.merge_manifest_path or "").strip()
        if not path:
            return None
        try:
            summary = await self._reader.read_merge_manifest_summary(path)
        except Exception as exc:
            logger.info("ui_query: manifest skip err=%s", type(exc).__name__)
            return ManifestEvidence(exists=False)
        return ManifestEvidence(
            exists=summary.exists,
            status=summary.status,
            incomplete_group_count=summary.incomplete_group_count,
            complete_group_count=summary.complete_group_count,
        )

    async def _maybe_merge_readiness(
        self, control: UiControlReadResult
    ) -> MergeReadiness | None:
        """Evalúa readiness solo en detalle (assess_merge=True) y estados runnable."""
        if not self._assess_merge or self._graph is None:
            return None
        snap = control.snapshot
        estado = (snap.estado_proceso or "").strip().upper()
        if estado not in MERGE_RUNNABLE_STATES:
            return None
        try:
            return await assess_merge_readiness(
                self._graph, snap, (snap.bank_code or "").strip()
            )
        except Exception:
            logger.info(
                "ui_query: merge_readiness skip err",
                exc_info=True,
            )
            return None

    async def _maybe_amortization_readiness(
        self, control: UiControlReadResult
    ) -> AmortizationReadiness | None:
        """Evalúa readiness solo en detalle (assess_amortization=True) y estados runnable."""
        if not self._assess_amortization or self._graph is None:
            return None
        snap = control.snapshot
        estado = (snap.estado_proceso or "").strip().upper()
        if estado not in AMORTIZATION_RUNNABLE_STATES:
            return None
        try:
            return await assess_amortization_readiness(
                self._graph, snap, (snap.bank_code or "").strip()
            )
        except Exception:
            logger.info(
                "ui_query: amortization_readiness skip err",
                exc_info=True,
            )
            return None

    async def project_bank(self, bank_code: str) -> UiProcessDetail:
        control = await self._reader.read_process_control(bank_code)
        jobs = await self._jobs_for_control(control)
        active = jobs.memory_job
        if not active and jobs.job_manager_by_type:
            # Preferir job en curso del JobManager como active_job técnico.
            for job in jobs.job_manager_by_type.values():
                if str(job.payload.get("status") or "").lower() in {"queued", "running"}:
                    active = job
                    break
        readiness = await self._maybe_merge_readiness(control)
        amort_readiness = await self._maybe_amortization_readiness(control)
        sources = ProjectionSources(
            snapshot=control.snapshot,
            active_job=active,
            jobs=jobs,
            web_urls=await self._web_urls(control),
            manifest=await self._manifest(control),
            artifact_exists=await self._artifact_exists(control),
            merge_readiness=readiness,
            merge_readiness_status=readiness.status if readiness else None,
            amortization_readiness=amort_readiness,
            amortization_readiness_status=amort_readiness.status if amort_readiness else None,
        )
        return self._projection.project(sources)

    async def project_process_key(self, process_key: str, banks: tuple[str, ...]) -> UiProcessDetail:
        key = (process_key or "").strip()
        last_exc: Exception | None = None
        for bank in banks:
            try:
                detail = await self.project_bank(bank)
            except Exception as exc:
                last_exc = exc
                continue
            if (detail.process_key or "").strip() == key:
                return detail
        if last_exc:
            raise last_exc
        raise KeyError(key)
