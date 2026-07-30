"""PaymentProcessProjectionService — agrega fuentes reales (read-only).

Fuente de verdad del estado de proceso: Control SharePoint (+ paths/artefactos).
Jobs vivos aportan progreso técnico; Notify/Merge no se marcan completed
solo por un job en memoria.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Sequence

from app.application.ui.environment import resolve_active_environment
from app.application.ui.job_read import JobReadResult, build_poll_paths
from app.application.ui.schemas import (
    OperationalStatus,
    StepName,
    StepStatus,
    UiActiveJob,
    UiError,
    UiIdempotencyKeys,
    UiLink,
    UiNextAction,
    UiProcessDetail,
    UiProcessFiles,
    UiProcessItem,
    UiProcessSummary,
    UiStepState,
)
from app.application.use_cases.payment_validation_process_control import (
    ProcessControlSnapshot,
)
from app.application.use_cases.setup_merge_control_workbook import (
    process_date_from_process_key,
)

STEP_ORDER: tuple[StepName, ...] = (
    "generate",
    "review",
    "finalize",
    "notify",
    "merge",
    "dry_run",
    "apply",
)

# Estados de control observados en el flujo productivo.
_GENERATE_DONE = frozenset(
    {
        "REVISION_CREADA",
        "FINALIZADO",
        "ERROR_NOTIFY",
        "PENDIENTE_ASIENTOS",
        "CONSOLIDANDO",
        "CONSOLIDADO",
        "MERGE_PARCIAL",
        "ERROR_MERGE",
        "APLICANDO_AMORTIZACION",
        "AMORTIZACION_PARCIAL",
        "AMORTIZACION_APLICADA",
        "ERROR_APPLY",
        "ERROR_FINALIZE",
    }
)
_FINALIZE_DONE = frozenset(
    {
        "FINALIZADO",
        "ERROR_NOTIFY",
        "PENDIENTE_ASIENTOS",
        "CONSOLIDANDO",
        "CONSOLIDADO",
        "MERGE_PARCIAL",
        "ERROR_MERGE",
        "APLICANDO_AMORTIZACION",
        "AMORTIZACION_PARCIAL",
        "AMORTIZACION_APLICADA",
        "ERROR_APPLY",
    }
)
_NOTIFY_DONE_HINT = frozenset(
    {
        "PENDIENTE_ASIENTOS",
        "CONSOLIDANDO",
        "CONSOLIDADO",
        "MERGE_PARCIAL",
        "ERROR_MERGE",
        "APLICANDO_AMORTIZACION",
        "AMORTIZACION_PARCIAL",
        "AMORTIZACION_APLICADA",
        "ERROR_APPLY",
    }
)
_MERGE_DONE = frozenset(
    {
        "CONSOLIDADO",
        "APLICANDO_AMORTIZACION",
        "AMORTIZACION_PARCIAL",
        "AMORTIZACION_APLICADA",
        "ERROR_APPLY",
    }
)
_APPLY_DONE = frozenset({"AMORTIZACION_APLICADA"})


@dataclass(frozen=True)
class ProjectionSources:
    """Entrada pura para proyectar (inyectable en tests)."""

    snapshot: ProcessControlSnapshot
    active_job: JobReadResult | None = None
    items: tuple[UiProcessItem, ...] = ()
    web_urls: dict[str, str] | None = None


def _nz(value: str | None) -> str | None:
    text = str(value or "").strip()
    return text or None


def _step(
    name: StepName,
    status: StepStatus,
    *,
    summary: str | None = None,
    can_retry: bool = False,
    retry_action: str | None = None,
) -> UiStepState:
    return UiStepState(
        name=name,
        status=status,
        summary=summary,
        can_retry=can_retry,
        retry_action=retry_action,
    )


def _link(
    rel: str,
    label: str,
    path: str | None,
    web_urls: dict[str, str] | None,
) -> UiLink | None:
    p = _nz(path)
    if not p and not (web_urls or {}).get(rel):
        return None
    return UiLink(
        rel=rel,
        label=label,
        path=p,
        web_url=(web_urls or {}).get(rel),
    )


def derive_steps_from_control(
    snap: ProcessControlSnapshot,
    *,
    active_job: JobReadResult | None = None,
) -> list[UiStepState]:
    estado = (snap.estado_proceso or "").strip().upper()
    has_review = bool(_nz(snap.validation_file_path))
    has_historical = bool(_nz(snap.historical_file_path))
    has_notify_key = bool(_nz(snap.notify_idempotency_key))
    has_email_pdf = bool(_nz(snap.email_pdf_path))
    has_merge_key = bool(_nz(snap.merge_idempotency_key))
    has_manifest = bool(_nz(snap.merge_manifest_path))
    has_apply_key = bool(_nz(snap.apply_idempotency_key))

    job_type = ""
    job_status = ""
    if active_job:
        job_type = str(active_job.payload.get("type") or "").strip().lower()
        job_status = str(active_job.payload.get("status") or "").strip().lower()

    def job_in_progress(*types: str) -> bool:
        if job_status not in {"queued", "running"}:
            return False
        return any(t in job_type for t in types)

    # --- generate ---
    if job_in_progress("generate"):
        generate = _step("generate", "in_progress", summary="Generando Excel de revisión.")
    elif estado == "ERROR_GENERATE":
        generate = _step(
            "generate",
            "failed_retryable",
            summary="Falló la generación.",
            can_retry=True,
            retry_action="retry_generate",
        )
    elif estado in _GENERATE_DONE or has_review:
        generate = _step("generate", "completed", summary="Excel de revisión disponible.")
    elif not estado or estado in {"VACIO", ""}:
        generate = _step("generate", "not_started")
    else:
        generate = _step("generate", "not_started")

    # --- review ---
    if generate.status != "completed":
        review = _step("review", "not_started")
    elif estado == "REVISION_CREADA":
        review = _step(
            "review",
            "in_progress",
            summary="Pendiente revisión humana en SharePoint.",
        )
    elif estado in _FINALIZE_DONE or estado == "ERROR_FINALIZE":
        review = _step("review", "completed", summary="Revisión cerrada.")
    else:
        review = _step("review", "in_progress", summary="Revisión en curso.")

    # --- finalize ---
    if job_in_progress("finalize"):
        finalize = _step("finalize", "in_progress", summary="Finalizando validación.")
    elif estado == "ERROR_FINALIZE":
        finalize = _step(
            "finalize",
            "failed_retryable",
            summary="Falló la finalización.",
            can_retry=True,
            retry_action="retry_finalize",
        )
    elif estado in _FINALIZE_DONE or has_historical:
        finalize = _step("finalize", "completed", summary="Histórico formalizado.")
    else:
        finalize = _step("finalize", "not_started")

    # --- notify (Control-first) ---
    if job_in_progress("notify"):
        notify = _step("notify", "in_progress", summary="Enviando correo.")
    elif estado == "ERROR_NOTIFY":
        notify = _step(
            "notify",
            "failed_retryable",
            summary="Correo no enviado; Finalize se conserva.",
            can_retry=True,
            retry_action="retry_notify",
        )
    elif has_notify_key or has_email_pdf or estado in _NOTIFY_DONE_HINT:
        # Persistente: clave/PDF/estado posterior a notify.
        notify = _step("notify", "completed", summary="Correo registrado en control.")
    elif finalize.status == "completed" and estado == "FINALIZADO":
        notify = _step(
            "notify",
            "not_started",
            summary="Finalize listo; correo aún no confirmado en control.",
            can_retry=True,
            retry_action="retry_notify",
        )
    else:
        notify = _step("notify", "not_started")

    # --- merge (Control-first) ---
    if job_in_progress("merge"):
        merge = _step("merge", "in_progress", summary="Consolidando PDFs.")
    elif estado == "ERROR_MERGE":
        merge = _step(
            "merge",
            "failed_retryable",
            summary="Falló la consolidación.",
            can_retry=True,
            retry_action="retry_merge",
        )
    elif estado == "MERGE_PARCIAL":
        merge = _step(
            "merge",
            "partial",
            summary="Consolidación parcial; faltan soportes.",
            can_retry=True,
            retry_action="retry_merge",
        )
    elif estado in _MERGE_DONE or (has_merge_key and has_manifest and estado != "CONSOLIDANDO"):
        if estado == "CONSOLIDANDO" and not has_manifest:
            merge = _step("merge", "in_progress", summary="Consolidación en control.")
        else:
            merge = _step("merge", "completed", summary="PDFs consolidados.")
    elif estado == "CONSOLIDANDO":
        merge = _step("merge", "in_progress", summary="Consolidación en control.")
    elif estado == "PENDIENTE_ASIENTOS":
        merge = _step(
            "merge",
            "blocked",
            summary="Esperando asientos/soportes.",
            can_retry=True,
            retry_action="retry_merge",
        )
    else:
        merge = _step("merge", "not_started")

    # --- dry_run ---
    if job_in_progress("amortization_dry_run", "dry_run"):
        dry_run = _step("dry_run", "in_progress", summary="Validando amortización.")
    elif merge.status == "partial":
        dry_run = _step(
            "dry_run",
            "blocked",
            summary="Bloqueado hasta completar Merge.",
        )
    elif estado in {"APLICANDO_AMORTIZACION", "AMORTIZACION_PARCIAL", "AMORTIZACION_APLICADA", "ERROR_APPLY"}:
        dry_run = _step("dry_run", "completed", summary="Preflight ejecutado.")
    elif merge.status == "completed":
        dry_run = _step("dry_run", "not_started", summary="Listo para dry-run.")
    else:
        dry_run = _step("dry_run", "not_started")

    # --- apply ---
    if job_in_progress("amortization_apply", "apply"):
        apply = _step("apply", "in_progress", summary="Aplicando tablas.")
    elif estado == "ERROR_APPLY":
        apply = _step(
            "apply",
            "failed_retryable",
            summary="Falló la aplicación.",
            can_retry=True,
            retry_action="retry_apply",
        )
    elif estado == "AMORTIZACION_PARCIAL":
        apply = _step(
            "apply",
            "partial",
            summary="Aplicación parcial.",
            can_retry=True,
            retry_action="retry_apply",
        )
    elif estado in _APPLY_DONE or has_apply_key and estado == "AMORTIZACION_APLICADA":
        apply = _step("apply", "completed", summary="Tablas actualizadas.")
    else:
        apply = _step("apply", "not_started")

    return [generate, review, finalize, notify, merge, dry_run, apply]


def derive_operational_status(
    snap: ProcessControlSnapshot,
    steps: Sequence[UiStepState],
) -> OperationalStatus:
    estado = (snap.estado_proceso or "").strip().upper()
    by_name = {s.name: s for s in steps}

    if estado == "VACIO" or not estado:
        return "NUEVO"
    if by_name["generate"].status == "in_progress":
        return "GENERANDO"
    if by_name["generate"].status == "failed_retryable":
        return "ERROR_RECUPERABLE"
    if by_name["review"].status == "in_progress":
        return "EN_REVISION"
    if by_name["finalize"].status == "in_progress":
        return "FINALIZANDO"
    if by_name["finalize"].status == "failed_retryable":
        return "ERROR_RECUPERABLE"
    if by_name["notify"].status == "in_progress":
        return "NOTIFICANDO"
    if by_name["notify"].status == "failed_retryable":
        return "ERROR_RECUPERABLE"
    if by_name["merge"].status == "blocked" or estado == "PENDIENTE_ASIENTOS":
        return "ESPERANDO_SOPORTES"
    if by_name["merge"].status == "in_progress":
        return "CONSOLIDANDO"
    if by_name["merge"].status == "partial":
        return "FINALIZADO_PARCIALMENTE"
    if by_name["merge"].status == "failed_retryable":
        return "ERROR_RECUPERABLE"
    if by_name["dry_run"].status == "in_progress":
        return "VALIDANDO_AMORTIZACION"
    if by_name["dry_run"].status == "not_started" and by_name["merge"].status == "completed":
        return "LISTO_PARA_APLICAR"
    if by_name["apply"].status == "in_progress":
        return "APLICANDO"
    if by_name["apply"].status == "partial":
        return "FINALIZADO_PARCIALMENTE"
    if by_name["apply"].status == "failed_retryable":
        return "ERROR_RECUPERABLE"
    if by_name["apply"].status == "completed":
        return "COMPLETADO"
    if estado == "REVISION_CREADA":
        return "EN_REVISION"
    return "DESCONOCIDO"


def derive_next_actions(
    snap: ProcessControlSnapshot,
    steps: Sequence[UiStepState],
    *,
    links: Sequence[UiLink],
) -> list[UiNextAction]:
    by_name = {s.name: s for s in steps}
    actions: list[UiNextAction] = []
    has_review_link = any(l.rel == "review_excel" for l in links)

    if by_name["review"].status == "in_progress" and has_review_link:
        actions.append(
            UiNextAction(
                code="open_review_excel",
                label="Abrir Excel de revisión en SharePoint",
                enabled=True,
            )
        )
    if by_name["notify"].status == "failed_retryable":
        actions.append(
            UiNextAction(
                code="retry_notify",
                label="Reintentar correo (Notify)",
                enabled=False,
                reason="Mutaciones no habilitadas en Fase U1 (solo lectura).",
            )
        )
    if by_name["merge"].status in {"partial", "blocked", "failed_retryable"}:
        actions.append(
            UiNextAction(
                code="open_asientos_pendientes",
                label="Revisar asientos / soportes pendientes",
                enabled=any(l.rel == "secretary_file" for l in links),
            )
        )
        actions.append(
            UiNextAction(
                code="retry_merge",
                label="Reintentar consolidación (Merge)",
                enabled=False,
                reason="Mutaciones no habilitadas en Fase U1 (solo lectura).",
            )
        )
    if by_name["apply"].status == "completed":
        actions.append(
            UiNextAction(
                code="review_amortization_tables",
                label="Revisar tablas de amortización",
                enabled=True,
            )
        )
    if not actions and by_name["generate"].status == "not_started":
        actions.append(
            UiNextAction(
                code="start_generate",
                label="Iniciar generación (no disponible en U1)",
                enabled=False,
                reason="Mutaciones no habilitadas en Fase U1 (solo lectura).",
            )
        )
    return actions


def derive_errors(
    snap: ProcessControlSnapshot,
    steps: Sequence[UiStepState],
) -> list[UiError]:
    errors: list[UiError] = []
    estado = (snap.estado_proceso or "").strip().upper()
    by_name = {s.name: s for s in steps}

    if by_name["notify"].status == "failed_retryable" or estado == "ERROR_NOTIFY":
        errors.append(
            UiError(
                stage="notify",
                severity="recoverable",
                error_code="ERROR_NOTIFY",
                user_message=(
                    "El correo de pagos no quedó confirmado. "
                    "La finalización del Excel se conserva."
                ),
                next_action=(
                    "Corrija destinatarios o el fallo de envío y reintente solo Notify "
                    "cuando las mutaciones estén habilitadas."
                ),
            )
        )
    if by_name["merge"].status == "partial" or estado == "MERGE_PARCIAL":
        errors.append(
            UiError(
                stage="merge",
                severity="business",
                error_code="MERGE_PARCIAL",
                user_message="La consolidación quedó parcial: faltan soportes en uno o más créditos.",
                next_action="Complete asientos/extractos faltantes y reintente Merge.",
            )
        )
    if by_name["generate"].status == "failed_retryable" or estado == "ERROR_GENERATE":
        errors.append(
            UiError(
                stage="generate",
                severity="recoverable",
                error_code="ERROR_GENERATE",
                user_message="No se pudo generar el Excel de revisión.",
                next_action="Revise el correo/log de error, corrija insumos y reintente Generate.",
            )
        )
    return errors


def _active_job_dto(job: JobReadResult | None) -> UiActiveJob | None:
    if not job:
        return None
    jtype = str(job.payload.get("type") or "")
    graph_path, ui_path = build_poll_paths(jtype, job.job_id)
    return UiActiveJob(
        job_id=job.job_id,
        type=jtype or "unknown",
        status=str(job.payload.get("status") or "unknown"),
        store=job.store,
        poll_path_graph=graph_path,
        poll_path_ui=ui_path,
        started_at=_nz(str(job.payload.get("started_at") or "")) or None,
        progress=job.payload.get("progress")
        if isinstance(job.payload.get("progress"), dict)
        else None,
    )


class PaymentProcessProjectionService:
    """Proyección read-only a partir de Control (+ job técnico opcional)."""

    def project(self, sources: ProjectionSources) -> UiProcessDetail:
        snap = sources.snapshot
        env = resolve_active_environment()
        steps = derive_steps_from_control(snap, active_job=sources.active_job)
        operational = derive_operational_status(snap, steps)

        web_urls = sources.web_urls or {}
        links: list[UiLink] = []
        for rel, label, path in (
            ("review_excel", "Abrir Excel de revisión", snap.validation_file_path),
            ("historical", "Abrir histórico del día", snap.historical_file_path),
            ("secretary_file", "Abrir Asientos_Pendientes", snap.secretary_file_path),
            ("email_pdf", "Abrir PDF del correo", snap.email_pdf_path),
            ("merge_manifest", "Abrir manifest Merge", snap.merge_manifest_path),
            ("control", "Abrir control de proceso", snap.control_file_path),
            ("execution_log", "Abrir bitácora de ejecución", snap.execution_log_path),
        ):
            item = _link(rel, label, path, web_urls)
            if item:
                links.append(item)

        process_date = None
        if snap.process_key:
            d = process_date_from_process_key(snap.process_key)
            if d:
                process_date = d.isoformat()

        return UiProcessDetail(
            process_key=_nz(snap.process_key) or "",
            process_id=_nz(snap.process_id),
            bank_code=_nz(snap.bank_code) or "",
            bank_name=_nz(snap.bank_name),
            process_date=process_date,
            environment=env.environment,
            operational_status=operational,
            control_estado_proceso=_nz(snap.estado_proceso),
            is_active=bool(snap.is_active),
            steps=steps,
            items=list(sources.items),
            active_job=_active_job_dto(sources.active_job),
            attempts=[],
            next_actions=derive_next_actions(snap, steps, links=links),
            errors=derive_errors(snap, steps),
            links=links,
            files=UiProcessFiles(
                validation_file_path=_nz(snap.validation_file_path),
                historical_file_path=_nz(snap.historical_file_path),
                secretary_file_path=_nz(snap.secretary_file_path),
                email_pdf_path=_nz(snap.email_pdf_path),
                merge_manifest_path=_nz(snap.merge_manifest_path),
                control_file_path=_nz(snap.control_file_path),
                execution_log_path=_nz(snap.execution_log_path),
            ),
            idempotency=UiIdempotencyKeys(
                notify_idempotency_key=_nz(snap.notify_idempotency_key),
                merge_idempotency_key=_nz(snap.merge_idempotency_key),
                apply_idempotency_key=_nz(snap.apply_idempotency_key),
            ),
            trigger_source=None,
            requested_by=None,
        )

    def summarize(self, detail: UiProcessDetail) -> UiProcessSummary:
        return UiProcessSummary(
            process_key=detail.process_key,
            bank_code=detail.bank_code,
            process_date=detail.process_date,
            environment=detail.environment,
            operational_status=detail.operational_status,
            control_estado_proceso=detail.control_estado_proceso,
            is_active=detail.is_active,
            error_count=len(detail.errors),
            next_actions=detail.next_actions[:3],
        )


ControlReader = Callable[[str], ProcessControlSnapshot]


def project_from_bank(
    bank_code: str,
    *,
    read_control: ControlReader,
    active_job: JobReadResult | None = None,
    service: PaymentProcessProjectionService | None = None,
) -> UiProcessDetail:
    snap = read_control(bank_code)
    svc = service or PaymentProcessProjectionService()
    return svc.project(ProjectionSources(snapshot=snap, active_job=active_job))
