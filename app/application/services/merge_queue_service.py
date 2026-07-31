"""Orquestación compartida de cola Merge (Power Automate + UI).

Única implementación de lock → job queued → background → use case → finish.
Los routers solo adaptan HTTP; no duplican runners ni hacen HTTP interno a /graph.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Protocol

from fastapi import BackgroundTasks

from app.application.job_manager import JobManager, get_job_manager
from app.application.services.colombia_time import now_colombia_iso
from app.application.services.execution_log_hooks import try_record_step_event
from app.application.use_cases.merge_composite_validado_pdfs import (
    MergeCompositeValidadoPdfsResult,
    merge_composite_validado_pdfs,
)

logger = logging.getLogger(__name__)


class GraphLike(Protocol):
    async def get(self, *a: Any, **k: Any) -> Any: ...
    async def get_bytes(self, *a: Any, **k: Any) -> Any: ...
    async def put_bytes(self, *a: Any, **k: Any) -> Any: ...
    async def post_json(self, *a: Any, **k: Any) -> Any: ...


class MergeQueueBusyError(Exception):
    """Lock Generate/Finalize/Notify/Merge ocupado."""


class MergeAlreadyMergedError(Exception):
    """ProcessKey ya tiene Merge exitoso completo (evidencia JobManager). Sin job nuevo."""

    def __init__(self, process_key: str, prior_job_id: str | None = None) -> None:
        self.process_key = process_key
        self.prior_job_id = prior_job_id
        super().__init__("Los soportes de este proceso ya fueron consolidados.")


@dataclass(frozen=True)
class MergeQueueAccepted:
    job_id: str
    bank_code: str | None
    process_key: str | None = None
    status: str = "queued"
    reused_prior: bool = False


def _utc_now_iso() -> str:
    return now_colombia_iso()


def _result_to_dict(result: MergeCompositeValidadoPdfsResult) -> dict[str, Any]:
    """Serializa el resultado del use case con la misma forma histórica del runner PA."""
    return {
        "status": "ok",
        "message": "Ejecutado con éxito",
        "report_date_iso": result.report_date_iso,
        "historico_excel_path": result.historico_excel_path,
        "estado_linea_contains": result.estado_linea_contains,
        "email_pdf_used": result.email_pdf_used,
        "outputs": [
            {
                "id_pago": o.id_pago,
                "cliente": o.cliente,
                "credito": o.credito,
                "tipo_aplicacion": o.tipo_aplicacion,
                "requiere_extracto": o.requiere_extracto,
                "monto_banco": o.monto_banco,
                "fecha_banco": o.fecha_banco,
                "creditos_seleccionados": list(o.creditos_seleccionados),
                "email_pdf_path": o.email_pdf_path,
                "asiento_pdf_path": o.asiento_pdf_path,
                "asiento_pdf_paths": list(o.asiento_pdf_paths),
                "extracto_pdf_path": o.extracto_pdf_path,
                "credit_items": [dict(ci) for ci in o.credit_items],
                "output_relative_path": o.output_relative_path,
                "output_web_url": o.output_web_url,
                "output_folder_web_url": o.output_folder_web_url,
                "output_folder_relative_path": o.output_folder_relative_path,
                "bytes_written": o.bytes_written,
                "sources_summary": o.sources_summary,
            }
            for o in result.outputs
        ],
        "skipped": list(result.skipped),
        "merge_control_file_path": result.merge_control_file_path,
        "merge_control_updated": result.merge_control_updated,
        "merge_control_status": result.merge_control_status,
        "merge_manifest_path": result.merge_manifest_path,
        "outputs_count": result.outputs_count,
        "skipped_count": result.skipped_count,
        "consolidation_folder_web_url": result.consolidation_folder_web_url,
        "consolidation_folder_relative_path": result.consolidation_folder_relative_path,
        "bank_code": result.bank_code,
        "bank_name": result.bank_name,
        "bank_code_source": result.bank_code_source,
        "ready_banks_detected": list(result.ready_banks_detected),
        "process_key": result.process_key,
        "process_control_file_path": result.process_control_file_path,
        "process_control_updated": result.process_control_updated,
        "process_control_estado": result.process_control_estado,
        "historical_file_source": result.historical_file_source,
        "email_pdf_source": result.email_pdf_source,
        "already_merged": result.already_merged,
        "file_action": result.file_action,
        "merge_idempotency_key": result.merge_idempotency_key,
        "pdf_created": result.pdf_created,
        "pdf_reused": result.pdf_reused,
        "already_consolidated": result.already_consolidated,
        "force_rebuild_used": result.force_rebuild_used,
        "payment_outputs_count": result.payment_outputs_count,
        "abono_outputs_count": result.abono_outputs_count,
        "payment_skipped_count": result.payment_skipped_count,
        "abono_skipped_count": result.abono_skipped_count,
        "extracts_not_required_count": result.extracts_not_required_count,
    }


class MergeQueueService:
    """Cola Merge compartida. Usa el JobManager singleton de PA/Generate/Finalize/Notify."""

    def __init__(self, job_manager: JobManager | None = None) -> None:
        self._jm = job_manager if job_manager is not None else get_job_manager()

    @property
    def job_manager(self) -> JobManager:
        return self._jm

    def _accepted_from_prior(
        self,
        process_key: str | None,
        bank_code: str | None,
    ) -> MergeQueueAccepted:
        """Reutiliza job Merge exitoso previo (PA 202 compatible; sin adquirir lock)."""
        prior = self._jm.find_successful_merge_by_process_key(
            (process_key or "").strip()
        )
        prior_id = ""
        prior_status = "queued"
        if prior is not None:
            prior_id = str(prior.get("job_id") or "") or ""
            st = str(prior.get("status") or "").strip().lower()
            if st:
                prior_status = st
        return MergeQueueAccepted(
            job_id=prior_id,
            bank_code=bank_code,
            process_key=process_key,
            status=prior_status,
            reused_prior=True,
        )

    def _raise_already_merged(self, process_key: str) -> None:
        prior = self._jm.find_successful_merge_by_process_key(process_key)
        prior_id = None
        if prior is not None:
            prior_id = str(prior.get("job_id") or "") or None
        raise MergeAlreadyMergedError(process_key, prior_job_id=prior_id)

    async def enqueue(
        self,
        *,
        graph: GraphLike,
        background_tasks: BackgroundTasks,
        bank_code: str | None = None,
        historical_file_path: str | None = None,
        email_pdf_path: str | None = None,
        force_rebuild: bool = False,
        process_key: str | None = None,
        trigger_source: str = "power_automate",
        requested_by: str | None = None,
        ui_request_id: str | None = None,
        ui_mode: bool = False,
    ) -> MergeQueueAccepted:
        # UI nunca fuerza rebuild; solo PA puede pasar force_rebuild=True.
        if ui_mode:
            force_rebuild = False

        # Atómico: busy vs already_merged vs claim.
        claim = self._jm.try_claim_merge_for_process(
            process_key, force_rebuild=force_rebuild
        )
        if claim == "busy":
            raise MergeQueueBusyError(
                "Ya existe un proceso generate, finalize, notify o merge activo. "
                "Consulta /jobs/{job_id}."
            )
        if claim == "already_merged":
            pk = (process_key or "").strip()
            if ui_mode:
                self._raise_already_merged(pk)
            return self._accepted_from_prior(process_key, bank_code)

        lock_held = True
        try:
            # Si PA no envió process_key, resolverlo del control para la evidencia JM.
            pk = (process_key or "").strip()
            if not pk and (bank_code or "").strip():
                try:
                    from app.application.use_cases.sharepoint_from_env import (
                        resolve_sharepoint_from_env,
                    )
                    from app.application.use_cases.payment_validation_process_control import (
                        read_process_control_snapshot,
                    )

                    ctx = await resolve_sharepoint_from_env(graph)
                    snap_pk = await read_process_control_snapshot(
                        graph,
                        ctx["site_id"],
                        ctx["drive_id"],
                        bank_code=bank_code.strip(),
                    )
                    pk = (snap_pk.process_key or "").strip()
                    if pk:
                        process_key = pk
                except Exception:
                    logger.warning(
                        "merge enqueue: no se pudo resolver process_key desde control",
                        exc_info=True,
                    )

            if pk and not force_rebuild and self._jm.has_completed_merge(pk):
                self._jm.finish_merge()
                lock_held = False
                if ui_mode:
                    self._raise_already_merged(pk)
                return self._accepted_from_prior(process_key, bank_code)

            job_id = str(uuid.uuid4())
            initial: dict[str, Any] = {
                "job_id": job_id,
                "type": "merge_composite_validado_pdfs",
                "status": "queued",
                "queued_at": _utc_now_iso(),
                "created_at": _utc_now_iso(),
                "updated_at": _utc_now_iso(),
                "started_at": None,
                "finished_at": None,
                "result": None,
                "error": None,
                "force_rebuild": force_rebuild,
                "trigger_source": trigger_source,
            }
            if bank_code:
                initial["bank_code"] = bank_code
            if process_key:
                initial["process_key"] = process_key
            if requested_by:
                initial["requested_by"] = requested_by
            if ui_request_id:
                initial["ui_request_id"] = ui_request_id

            await self._jm.set_job(job_id, initial)

            background_tasks.add_task(
                self._run_merge_job,
                job_id,
                graph,
                force_rebuild,
                bank_code,
                historical_file_path,
                email_pdf_path,
                trigger_source,
                requested_by,
                ui_request_id,
                process_key,
            )
            lock_held = False
            logger.info(
                "job %s: merge encolado trigger=%s by=%s force_rebuild=%s",
                job_id,
                trigger_source,
                requested_by or "",
                force_rebuild,
            )
            return MergeQueueAccepted(
                job_id=job_id,
                bank_code=bank_code,
                process_key=process_key,
                status="queued",
            )
        except (MergeQueueBusyError, MergeAlreadyMergedError):
            raise
        except Exception:
            if lock_held:
                self._jm.finish_merge()
            raise

    async def _run_merge_job(
        self,
        job_id: str,
        graph: GraphLike,
        force_rebuild: bool = False,
        bank_code: str | None = None,
        historical_file_path: str | None = None,
        email_pdf_path: str | None = None,
        trigger_source: str = "power_automate",
        requested_by: str | None = None,
        ui_request_id: str | None = None,
        process_key: str | None = None,
    ) -> None:
        await self._jm.set_job(
            job_id,
            {
                "type": "merge_composite_validado_pdfs",
                "status": "running",
                "started_at": _utc_now_iso(),
                "updated_at": _utc_now_iso(),
                "force_rebuild": force_rebuild,
                "trigger_source": trigger_source,
                **({"process_key": process_key} if process_key else {}),
                **({"bank_code": bank_code} if bank_code else {}),
                **({"requested_by": requested_by} if requested_by else {}),
                **({"ui_request_id": ui_request_id} if ui_request_id else {}),
            },
        )
        logger.info("job %s: merge_composite_validado_pdfs iniciado", job_id)
        started_ts = perf_counter()
        await try_record_step_event(
            graph, step="MERGE", status="STARTED", job_id=job_id, bank_code=bank_code
        )
        try:
            result = await merge_composite_validado_pdfs(
                graph,
                force_rebuild=force_rebuild,
                bank_code=bank_code,
                historical_file_path=historical_file_path,
                email_pdf_path=email_pdf_path,
                job_id=job_id,
            )
            elapsed_ms = round((perf_counter() - started_ts) * 1000, 2)
            terminal = "SKIPPED_IDEMPOTENT" if result.already_merged else "SUCCEEDED"
            if result.skipped_count and result.outputs_count:
                terminal = "PARTIAL"
            await try_record_step_event(
                graph,
                step="MERGE",
                status=terminal,
                job_id=job_id,
                bank_code=result.bank_code or bank_code,
                process_key=result.process_key or process_key,
                metrics={
                    "elapsed_ms": elapsed_ms,
                    "outputs_count": result.outputs_count,
                    "skipped_count": result.skipped_count,
                    "trigger_source": trigger_source,
                },
                artifacts=[
                    {
                        "role": "MERGE_MANIFEST",
                        "path": result.merge_manifest_path or "",
                        "file_name": "",
                        "action": "UPDATED",
                        "status": "SUCCEEDED",
                    }
                ]
                if result.merge_manifest_path
                else None,
            )
            result_dict = _result_to_dict(result)
            result_dict["elapsed_ms"] = elapsed_ms
            result_dict["trigger_source"] = trigger_source
            if requested_by:
                result_dict["requested_by"] = requested_by
            if ui_request_id:
                result_dict["ui_request_id"] = ui_request_id

            pk_final = (result.process_key or process_key or "").strip() or None
            await self._jm.set_job(
                job_id,
                {
                    "status": "completed",
                    "finished_at": _utc_now_iso(),
                    "updated_at": _utc_now_iso(),
                    "elapsed_ms": elapsed_ms,
                    "result": result_dict,
                    "error": None,
                    "force_rebuild": force_rebuild,
                    "trigger_source": trigger_source,
                    **({"process_key": pk_final} if pk_final else {}),
                    **(
                        {"bank_code": result.bank_code or bank_code}
                        if (result.bank_code or bank_code)
                        else {}
                    ),
                },
            )
            logger.info("job %s: merge_composite_validado_pdfs completado", job_id)
        except Exception as exc:
            await try_record_step_event(
                graph,
                step="MERGE",
                status="FAILED",
                job_id=job_id,
                bank_code=bank_code,
                error={
                    "error_code": type(exc).__name__,
                    "exception_type": type(exc).__name__,
                    "technical_message": str(exc)[:4000],
                },
            )
            # Forma histórica del error en poll PA: string (enrichment lo normaliza).
            await self._jm.set_job(
                job_id,
                {
                    "status": "failed",
                    "finished_at": _utc_now_iso(),
                    "updated_at": _utc_now_iso(),
                    "result": None,
                    "error": str(exc),
                    "trigger_source": trigger_source,
                    **({"process_key": process_key} if process_key else {}),
                    **({"requested_by": requested_by} if requested_by else {}),
                    **({"ui_request_id": ui_request_id} if ui_request_id else {}),
                },
            )
            logger.exception(
                "job %s: merge_composite_validado_pdfs falló: %s", job_id, exc
            )
        finally:
            self._jm.finish_merge()


_default_service: MergeQueueService | None = None


def get_merge_queue_service() -> MergeQueueService:
    """Singleton del servicio de cola (comparte JobManager con PA/UI)."""
    global _default_service
    if _default_service is None:
        _default_service = MergeQueueService(get_job_manager())
    return _default_service


def reset_merge_queue_service_for_tests() -> None:
    global _default_service
    _default_service = None
