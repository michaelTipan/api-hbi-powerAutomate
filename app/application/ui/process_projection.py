"""PaymentProcessProjectionService — agrega fuentes reales (read-only).

Fuente de verdad del estado de proceso: Control SharePoint (+ paths/artefactos).
Jobs vivos aportan progreso técnico; Notify/Merge no se marcan completed
solo por un job en memoria.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from app.application.job_manager import get_job_manager
from app.application.ui.amortization_capabilities import (
    compute_amortization_availability,
)
from app.application.ui.amortization_readiness import AmortizationReadiness
from app.application.ui.environment import resolve_active_environment
from app.application.ui.feature_flags import get_ui_feature_flags
from app.application.ui.finalize_capabilities import compute_finalize_availability
from app.application.ui.merge_capabilities import compute_merge_availability
from app.application.ui.merge_readiness import MergeReadiness
from app.application.ui.notify_capabilities import compute_notify_availability
from app.application.ui.finalize_checklist import build_finalize_operator_checklist
from app.application.ui.job_read import JobReadResult, build_poll_paths
from app.application.ui.job_stage_types import classify_finalize_failure
from app.application.ui.last_attempt import (
    build_attempts_from_jobs,
    build_operational_issues_from_finalize_job,
    collect_jobs_for_stages,
    latest_attempts_by_stage,
    parse_finalize_error_details,
    pick_last_attempt,
)
from app.application.ui.legacy_paths import collect_legacy_path_fields
from app.application.ui.schemas import (
    OperationalStatus,
    StepName,
    StepStatus,
    UiActionAvailability,
    UiActiveJob,
    UiAmortizationReadiness,
    UiError,
    UiIdempotencyKeys,
    UiLastAttempt,
    UiLink,
    UiMergeReadiness,
    UiNextAction,
    UiOperationalIssue,
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
class ManifestOutputRef:
    """PDF consolidado operativo (desde manifest ``outputs[]``)."""

    path: str
    credito: str | None = None
    id_pago: str | None = None
    web_url: str | None = None


@dataclass(frozen=True)
class ManifestEvidence:
    exists: bool
    status: str | None = None
    incomplete_group_count: int = 0
    complete_group_count: int = 0
    primary_output_path: str | None = None
    output_pdfs: tuple[ManifestOutputRef, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class TechnicalJobEvidence:
    """Jobs técnicos opcionales (persistidos + memoria)."""

    job_manager_by_type: dict[str, JobReadResult] = field(default_factory=dict)
    memory_job: JobReadResult | None = None


@dataclass(frozen=True)
class ProjectionSources:
    """Entrada pura para proyectar (inyectable en tests)."""

    snapshot: ProcessControlSnapshot
    active_job: JobReadResult | None = None
    items: tuple[UiProcessItem, ...] = ()
    web_urls: dict[str, str] | None = None
    jobs: TechnicalJobEvidence | None = None
    manifest: ManifestEvidence | None = None
    # Artefactos que el puerto confirmó existentes (path -> exists)
    artifact_exists: dict[str, bool] | None = None
    # Readiness Merge (None → unknown fail-closed en availability)
    merge_readiness: MergeReadiness | None = None
    merge_readiness_status: str | None = None
    # Readiness Amortización (None → unknown fail-closed en availability)
    amortization_readiness: AmortizationReadiness | None = None
    amortization_readiness_status: str | None = None


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


def _merge_pdf_operator_labels(outputs: Sequence[ManifestOutputRef]) -> list[str]:
    """Etiquetas operativas; distingue varios PDFs del mismo crédito sin UUID."""
    total = len(outputs)
    credito_totals: dict[str, int] = {}
    for out in outputs:
        c = (out.credito or "").strip()
        if c:
            credito_totals[c] = credito_totals.get(c, 0) + 1
    credito_seen: dict[str, int] = {}
    labels: list[str] = []
    for idx, out in enumerate(outputs):
        c = (out.credito or "").strip()
        if c:
            if credito_totals.get(c, 0) > 1:
                n = credito_seen.get(c, 0) + 1
                credito_seen[c] = n
                labels.append(f"Abrir PDF consolidado · Crédito {c} · Pago {n}")
            else:
                labels.append(f"Abrir PDF consolidado · Crédito {c}")
        elif total > 1:
            labels.append(f"Abrir PDF consolidado · Archivo {idx + 1}")
        else:
            labels.append("Abrir PDF consolidado")
    return labels


def _merge_output_refs(manifest: ManifestEvidence | None) -> list[ManifestOutputRef]:
    """Fuente de PDFs: ``outputs[]``; ``primary_output_path`` solo si no hay outputs."""
    if not manifest:
        return []
    if manifest.output_pdfs:
        # No reinyectar primary: ya viene (o debería) dentro de outputs[].
        return list(manifest.output_pdfs)
    primary = _nz(manifest.primary_output_path)
    if primary and primary.lower().endswith(".pdf"):
        return [ManifestOutputRef(path=primary)]
    return []


def derive_steps_from_control(
    snap: ProcessControlSnapshot,
    *,
    active_job: JobReadResult | None = None,
    jobs: TechnicalJobEvidence | None = None,
    manifest: ManifestEvidence | None = None,
    artifact_exists: dict[str, bool] | None = None,
) -> list[UiStepState]:
    """
    Precedencia:
    1) Evidencia persistente (Control / manifest / paths)
    2) Jobs JobManager (progreso Generate/Finalize/Dry-run/Apply)
    3) Job memoria vivo (Notify/Merge in_progress)
    4) Ausencia de job ≠ not_started si hay evidencia persistente
    """
    estado = (snap.estado_proceso or "").strip().upper()
    process_key = _nz(snap.process_key) or ""
    has_review = bool(_nz(snap.validation_file_path))
    has_historical = bool(_nz(snap.historical_file_path))
    raw_notify_key = _nz(snap.notify_idempotency_key) or ""
    raw_merge_key = _nz(snap.merge_idempotency_key) or ""
    raw_apply_key = _nz(snap.apply_idempotency_key) or ""
    # Ignorar claves de un ProcessKey anterior (fuga entre lotes del mismo banco).
    has_notify_key = bool(raw_notify_key) and (
        not process_key or raw_notify_key == process_key
    )
    has_email_pdf = bool(_nz(snap.email_pdf_path)) and has_notify_key
    has_merge_key = bool(raw_merge_key) and (
        not process_key or raw_merge_key == process_key
    )
    has_manifest_path = bool(_nz(snap.merge_manifest_path)) and has_merge_key
    has_apply_key = bool(raw_apply_key) and (
        not process_key or raw_apply_key == process_key
    )
    artifacts = artifact_exists or {}

    def exists(path: str | None) -> bool | None:
        p = _nz(path)
        if not p:
            return None
        if p in artifacts:
            return bool(artifacts[p])
        return None

    review_file_ok = exists(snap.validation_file_path)
    email_pdf_ok = exists(snap.email_pdf_path)
    manifest_ok = exists(snap.merge_manifest_path)
    if manifest is not None:
        manifest_ok = manifest.exists

    jm = (jobs.job_manager_by_type if jobs else None) or {}
    memory = (jobs.memory_job if jobs else None) or active_job

    def jm_job(*type_tokens: str) -> JobReadResult | None:
        for key, job in jm.items():
            payload_type = str(job.payload.get("type") or key).lower()
            if any(t in payload_type for t in type_tokens):
                return job
        return None

    def jm_status(*type_tokens: str) -> str | None:
        job = jm_job(*type_tokens)
        if not job:
            return None
        return str(job.payload.get("status") or "").lower()

    def memory_in_progress(*types: str) -> bool:
        if not memory:
            return False
        st = str(memory.payload.get("status") or "").lower()
        if st not in {"queued", "running"}:
            return False
        jt = str(memory.payload.get("type") or "").lower()
        return any(t in jt for t in types)

    def jm_in_progress(*types: str) -> bool:
        st = jm_status(*types)
        return st in {"queued", "running"}

    def job_in_progress(*types: str) -> bool:
        return jm_in_progress(*types) or memory_in_progress(*types)

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
    elif review_file_ok is False and (estado in _GENERATE_DONE or has_review):
        generate = _step(
            "generate",
            "failed_business",
            summary="Control indica revisión pero el archivo no existe.",
            can_retry=True,
            retry_action="retry_generate",
        )
    elif estado in _GENERATE_DONE or has_review:
        generate = _step("generate", "completed", summary="Excel de revisión disponible.")
    elif jm_status("generate") == "completed" and not has_review:
        # Desfase job↔Control: no es fallo de negocio.
        generate = _step(
            "generate",
            "sync_pending",
            summary="Job Generate completed; esperando ValidationFilePath en control.",
        )
    elif not estado or estado in {"VACIO", ""}:
        generate = _step("generate", "not_started")
    else:
        generate = _step("generate", "not_started")

    # --- review ---
    if generate.status not in {"completed"}:
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
            retry_action="finalize",
        )
    elif jm_status("finalize") == "failed":
        fin_job = jm_job("finalize")
        parsed = parse_finalize_error_details(fin_job.payload if fin_job else {})
        kind = classify_finalize_failure(
            parsed.get("error_code"), severity=parsed.get("severity")
        )
        finalize = _step(
            "finalize",
            kind,  # type: ignore[arg-type]
            summary=(
                "La revisión requiere correcciones."
                if kind == "failed_business"
                else "No se pudo finalizar por un problema temporal."
            ),
            can_retry=True,
            retry_action="finalize",
        )
    elif estado in _FINALIZE_DONE or has_historical:
        finalize = _step(
            "finalize",
            "completed",
            summary="La revisión fue finalizada correctamente.",
        )
    elif jm_status("finalize") == "completed" and not has_historical:
        # Desfase job↔Control: no es fallo de negocio.
        finalize = _step(
            "finalize",
            "sync_pending",
            summary="Job Finalize completed; esperando histórico en control.",
        )
    else:
        finalize = _step("finalize", "not_started")

    # --- notify (persistente primero; job 404 no borra completed) ---
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
        if email_pdf_ok is False and has_email_pdf:
            notify = _step(
                "notify",
                "failed_business",
                summary="Control apunta a PDF de correo inexistente.",
                can_retry=True,
                retry_action="retry_notify",
            )
        else:
            notify = _step(
                "notify",
                "completed",
                summary="Correo confirmado en control (job memoria irrelevante si 404).",
            )
    elif (
        jm_status("notify") == "completed"
        or (
            memory
            and "notify" in str(memory.payload.get("type") or "").lower()
            and str(memory.payload.get("status") or "").lower() == "completed"
        )
    ) and not (has_notify_key or has_email_pdf):
        # Desfase job↔Control: no es fallo de negocio.
        notify = _step(
            "notify",
            "sync_pending",
            summary="Job Notify completed; esperando evidencia en control.",
        )
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

    # --- merge ---
    manifest_partial = bool(
        estado == "MERGE_PARCIAL"
        or (manifest and manifest.status and "PARTIAL" in manifest.status.upper())
        or (manifest and manifest.incomplete_group_count > 0)
    )
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
    elif manifest_partial or estado == "MERGE_PARCIAL":
        merge = _step(
            "merge",
            "partial",
            summary="Consolidación parcial; faltan soportes (reintentable).",
            can_retry=True,
            retry_action="retry_merge",
        )
    elif estado in _MERGE_DONE or (has_merge_key and has_manifest_path):
        if manifest_ok is False:
            merge = _step(
                "merge",
                "failed_business",
                summary="Control/job indican Merge pero el manifest no existe.",
                can_retry=True,
                retry_action="retry_merge",
            )
        else:
            merge = _step("merge", "completed", summary="PDFs consolidados.")
    elif (
        jm_status("merge") == "completed"
        or (
            memory
            and "merge" in str(memory.payload.get("type") or "").lower()
            and str(memory.payload.get("status") or "").lower() == "completed"
        )
    ) and not (has_merge_key or has_manifest_path):
        # Desfase job↔Control (p. ej. aún PENDIENTE_ASIENTOS): no es fallo de Merge.
        merge = _step(
            "merge",
            "sync_pending",
            summary="Job Merge completed; esperando manifest/idempotency en control.",
        )
    elif estado == "CONSOLIDANDO":
        merge = _step("merge", "in_progress", summary="Consolidación en control.")
    elif estado == "PENDIENTE_ASIENTOS":
        merge = _step(
            "merge",
            "blocked",
            summary="Esperando documentos contables.",
            can_retry=True,
            retry_action="retry_merge",
        )
    else:
        merge = _step("merge", "not_started")

    # --- dry_run ---
    if job_in_progress("amortization_dry_run", "dry_run"):
        dry_run = _step("dry_run", "in_progress", summary="Validando amortización.")
    elif merge.status == "partial":
        dry_run = _step("dry_run", "blocked", summary="Bloqueado hasta completar Merge.")
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
    elif estado in _APPLY_DONE or (has_apply_key and estado == "AMORTIZACION_APLICADA"):
        apply = _step("apply", "completed", summary="Tablas actualizadas.")
    elif (
        jm_status("amortization_apply", "amortization_process", "apply") == "completed"
        and estado not in _APPLY_DONE
    ):
        # Desfase job↔Control: no es fallo de amortización.
        apply = _step(
            "apply",
            "sync_pending",
            summary="Job Apply completed; esperando AMORTIZACION_APLICADA en control.",
        )
    else:
        apply = _step("apply", "not_started")

    return [generate, review, finalize, notify, merge, dry_run, apply]


def derive_operational_status(
    snap: ProcessControlSnapshot,
    steps: Sequence[UiStepState],
) -> OperationalStatus:
    """Prioridad: fatal/corrección → temporal → parcial → activo → pendiente → completado.

    DESCONOCIDO solo para datos corruptos o combinaciones imposibles.
    """
    estado = (snap.estado_proceso or "").strip().upper()
    by_name = {s.name: s for s in steps}

    if estado in {"", "VACIO"}:
        return "NUEVO"
    if estado == "CANCELADO":
        return "CANCELADO"

    # 1-2) Corrección / negocio
    for name in ("generate", "finalize", "notify", "merge", "apply", "dry_run"):
        st = by_name[name].status
        if st == "failed_business":
            return "CORRECCION_REQUERIDA"

    # 3) Temporal recuperable
    for name in ("generate", "finalize", "notify", "merge", "apply", "dry_run"):
        if by_name[name].status == "failed_retryable":
            return "ERROR_RECUPERABLE"

    # 3b) Job completed pero Control aún sin evidencia (desfase temporal).
    for name in ("generate", "finalize", "notify", "merge", "apply"):
        if by_name[name].status == "sync_pending":
            return "SINCRONIZANDO"

    # 4) Parcial
    if (
        by_name["merge"].status == "partial"
        or by_name["apply"].status == "partial"
        or estado in {"MERGE_PARCIAL", "AMORTIZACION_PARCIAL"}
    ):
        return "FINALIZADO_PARCIALMENTE"

    # 5) Operación activa (pasos o EstadoProceso transitorio)
    if by_name["generate"].status == "in_progress" or estado == "GENERANDO":
        return "GENERANDO"
    if by_name["finalize"].status == "in_progress" or estado == "FINALIZANDO":
        return "FINALIZANDO"
    if by_name["notify"].status == "in_progress" or estado == "NOTIFICANDO":
        return "NOTIFICANDO"
    if by_name["merge"].status == "in_progress" or estado == "CONSOLIDANDO":
        return "CONSOLIDANDO"
    if by_name["dry_run"].status == "in_progress":
        return "VALIDANDO_AMORTIZACION"
    if by_name["apply"].status == "in_progress" or estado == "APLICANDO_AMORTIZACION":
        return "APLICANDO"

    # Estado de control no reconocido: no inventar EN_REVISION ni otros.
    _known_control = frozenset(
        {
            "VACIO",
            "GENERANDO",
            "REVISION_CREADA",
            "ERROR_GENERATE",
            "FINALIZANDO",
            "FINALIZADO",
            "ERROR_FINALIZE",
            "NOTIFICANDO",
            "ERROR_NOTIFY",
            "PENDIENTE_ASIENTOS",
            "CONSOLIDANDO",
            "MERGE_PARCIAL",
            "ERROR_MERGE",
            "CONSOLIDADO",
            "APLICANDO_AMORTIZACION",
            "ERROR_APPLY",
            "AMORTIZACION_PARCIAL",
            "AMORTIZACION_APLICADA",
            "CANCELADO",
        }
    )
    if estado and estado not in _known_control:
        return "DESCONOCIDO"

    # 6) Siguiente etapa / espera
    if by_name["merge"].status == "blocked" or estado == "PENDIENTE_ASIENTOS":
        return "ESPERANDO_SOPORTES"
    if by_name["review"].status == "in_progress" or estado == "REVISION_CREADA":
        return "EN_REVISION"

    # Finalize OK, correo aún no enviado (caso U4-RC bloqueante).
    if (
        by_name["finalize"].status == "completed"
        and by_name["notify"].status == "not_started"
        and estado == "FINALIZADO"
    ):
        return "PENDIENTE_NOTIFICACION"

    # Notify ya confirmado; Merge aún no (incl. control stale en FINALIZADO).
    if by_name["notify"].status == "completed" and by_name["merge"].status in {
        "not_started",
        "blocked",
    }:
        return "ESPERANDO_SOPORTES"

    if (
        by_name["merge"].status == "completed"
        and by_name["apply"].status == "not_started"
    ) or estado == "CONSOLIDADO":
        return "LISTO_PARA_APLICAR"

    if by_name["dry_run"].status == "not_started" and by_name["merge"].status == "completed":
        return "LISTO_PARA_APLICAR"

    # 7) Completado
    if by_name["apply"].status == "completed" or estado == "AMORTIZACION_APLICADA":
        return "COMPLETADO"

    # Mapa residual de estados de control conocidos (no deberían llegar aquí).
    known_control: dict[str, OperationalStatus] = {
        "ERROR_GENERATE": "ERROR_RECUPERABLE",
        "ERROR_FINALIZE": "ERROR_RECUPERABLE",
        "ERROR_NOTIFY": "ERROR_RECUPERABLE",
        "ERROR_MERGE": "ERROR_RECUPERABLE",
        "ERROR_APPLY": "ERROR_RECUPERABLE",
        "FINALIZADO": "PENDIENTE_NOTIFICACION",
        "REVISION_CREADA": "EN_REVISION",
        "PENDIENTE_ASIENTOS": "ESPERANDO_SOPORTES",
        "CONSOLIDADO": "LISTO_PARA_APLICAR",
        "MERGE_PARCIAL": "FINALIZADO_PARCIALMENTE",
        "AMORTIZACION_PARCIAL": "FINALIZADO_PARCIALMENTE",
        "AMORTIZACION_APLICADA": "COMPLETADO",
        "GENERANDO": "GENERANDO",
        "FINALIZANDO": "FINALIZANDO",
        "NOTIFICANDO": "NOTIFICANDO",
        "CONSOLIDANDO": "CONSOLIDANDO",
        "APLICANDO_AMORTIZACION": "APLICANDO",
        "CANCELADO": "CANCELADO",
        "VACIO": "NUEVO",
    }
    if estado in known_control:
        return known_control[estado]

    return "DESCONOCIDO"


def derive_operational_guidance(
    status: OperationalStatus,
    *,
    control_estado: str | None = None,
) -> tuple[str, str, str | None]:
    """Título, mensaje operativo y referencia técnica (solo DESCONOCIDO)."""
    catalog: dict[str, tuple[str, str]] = {
        "NUEVO": (
            "Sin proceso activo",
            "Aún no hay una validación iniciada para este banco.",
        ),
        "GENERANDO": (
            "Preparando la revisión",
            "Se está generando el archivo de revisión.",
        ),
        "EN_REVISION": (
            "Revisión pendiente",
            "Revise el Excel en SharePoint y complete la validación de pagos.",
        ),
        "FINALIZANDO": (
            "Cerrando la revisión",
            "Se está verificando y cerrando el archivo de revisión.",
        ),
        "PENDIENTE_NOTIFICACION": (
            "Validación finalizada",
            "La revisión fue finalizada correctamente.",
        ),
        "NOTIFICANDO": (
            "Enviando la validación",
            "Se está enviando el correo de validación.",
        ),
        "ESPERANDO_SOPORTES": (
            "Esperando documentos contables",
            "La validación y el correo ya fueron completados. Revise los documentos "
            "contables cargados antes de generar el PDF consolidado.",
        ),
        "CONSOLIDANDO": (
            "Consolidando soportes",
            "Se están consolidando los PDF de soportes.",
        ),
        "VALIDANDO_AMORTIZACION": (
            "Verificando amortización",
            "Se está verificando la información antes de aplicar.",
        ),
        "LISTO_PARA_APLICAR": (
            "Listo para amortización",
            "Los soportes están consolidados. Puede procesar la amortización.",
        ),
        "APLICANDO": (
            "Aplicando amortización",
            "Se están actualizando las tablas de amortización.",
        ),
        "COMPLETADO": (
            "Proceso completado",
            "La validación y la amortización quedaron aplicadas.",
        ),
        "FINALIZADO_PARCIALMENTE": (
            "Avance parcial",
            "Hay avances parciales; revise lo pendiente y continúe.",
        ),
        "SINCRONIZANDO": (
            "Sincronizando resultados",
            "El trabajo terminó; estamos confirmando el estado actualizado del proceso.",
        ),
        "ERROR_RECUPERABLE": (
            "Requiere atención",
            "Ocurrió un problema temporal. Puede reintentar la operación.",
        ),
        "CORRECCION_REQUERIDA": (
            "Requiere corrección",
            "Hay datos que deben corregirse antes de continuar.",
        ),
        "REVISION_MANUAL": (
            "Revisión manual",
            "Este caso requiere revisión manual del operador.",
        ),
        "CANCELADO": (
            "Proceso cancelado",
            "El proceso fue cancelado y no continúa.",
        ),
        "DESCONOCIDO": (
            "Estado no determinado",
            "No se pudo determinar el estado del proceso.",
        ),
    }
    title, message = catalog.get(
        status,
        (
            "Estado no determinado",
            "No se pudo determinar el estado del proceso.",
        ),
    )
    technical_ref: str | None = None
    if status == "DESCONOCIDO":
        raw = (control_estado or "").strip() or "(vacío)"
        technical_ref = f"EstadoProceso={raw}"
    return title, message, technical_ref


def derive_next_actions(
    snap: ProcessControlSnapshot,
    steps: Sequence[UiStepState],
    *,
    links: Sequence[UiLink],
) -> list[UiNextAction]:
    by_name = {s.name: s for s in steps}
    estado = (snap.estado_proceso or "").strip().upper()
    actions: list[UiNextAction] = []
    has_review_link = any(l.rel == "review_excel" for l in links)

    if by_name["review"].status == "in_progress" and has_review_link:
        actions.append(
            UiNextAction(
                code="open_review_excel",
                label="Abrir archivo de revisión",
                enabled=True,
            )
        )
    if by_name["finalize"].status in {"failed_business", "failed_retryable"}:
        actions.append(
            UiNextAction(
                code="retry_finalize",
                label="Verificar nuevamente",
                enabled=True,
                reason=None,
            )
        )
    if (
        by_name["finalize"].status == "completed"
        and by_name["notify"].status == "not_started"
        and estado == "FINALIZADO"
    ):
        actions.append(
            UiNextAction(
                code="notify",
                label="Enviar correo.",
                enabled=True,
                reason="La revisión fue finalizada correctamente.",
            )
        )
    if by_name["notify"].status == "failed_retryable":
        actions.append(
            UiNextAction(
                code="retry_notify",
                label="Reintentar envío de validación",
                enabled=True,
                reason="El correo no se envió; la revisión finalizada se conserva.",
            )
        )
    if by_name["merge"].status in {"partial", "blocked", "failed_retryable"}:
        actions.append(
            UiNextAction(
                code="open_asientos_pendientes",
                label="Ver archivos del proceso",
                enabled=True,
                reason="Revise los documentos contables y extractos ya asociados.",
            )
        )
        actions.append(
            UiNextAction(
                code="refresh_documents",
                label="Actualizar documentos",
                enabled=True,
                reason="Consulta de solo lectura: vuelve a detectar archivos en SharePoint.",
            )
        )
        actions.append(
            UiNextAction(
                code="retry_merge",
                label="Generar PDF consolidado",
                enabled=True,
                reason=(
                    "Reúne el PDF del correo enviado, los extractos y los documentos "
                    "contables en un único PDF para continuar con la amortización."
                ),
            )
        )
    if (
        by_name["merge"].status == "completed"
        and by_name["apply"].status == "not_started"
        and estado == "CONSOLIDADO"
    ):
        actions.append(
            UiNextAction(
                code="amortization",
                label="Procesar amortización",
                enabled=True,
                reason="Registra los movimientos validados en las tablas de amortización.",
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
                label="Iniciar validación",
                enabled=True,
                reason="No hay un proceso activo para este banco.",
            )
        )
    # dry_run / apply no son acciones de operador (solo steps internos).
    return [
        a
        for a in actions
        if a.code
        not in {
            "start_dry_run",
            "retry_dry_run",
            "start_apply",
            "retry_apply",
            "dry_run",
            "apply",
        }
    ]


def derive_errors(
    snap: ProcessControlSnapshot,
    steps: Sequence[UiStepState],
    *,
    jobs: TechnicalJobEvidence | None = None,
) -> list[UiError]:
    errors: list[UiError] = []
    estado = (snap.estado_proceso or "").strip().upper()
    by_name = {s.name: s for s in steps}
    jm = (jobs.job_manager_by_type if jobs else None) or {}

    if by_name["finalize"].status in {"failed_business", "failed_retryable"}:
        fin = None
        for key, job in jm.items():
            if "finalize" in str(job.payload.get("type") or key).lower():
                fin = job
                break
        parsed = parse_finalize_error_details(fin.payload if fin else {})
        code = parsed.get("error_code") or "finalize_failed"
        severity = (
            "recoverable"
            if by_name["finalize"].status == "failed_retryable"
            else "business"
        )
        errors.append(
            UiError(
                stage="finalize",
                severity=severity,  # type: ignore[arg-type]
                error_code=code,
                user_message=parsed.get("user_message")
                or "No se pudo finalizar el archivo de revisión.",
                next_action=parsed.get("next_action")
                or "Corrija el Excel de revisión, guarde y vuelva a verificar.",
            )
        )

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

    legacy_fields = collect_legacy_path_fields(
        {
            "validation_file_path": snap.validation_file_path,
            "historical_file_path": snap.historical_file_path,
            "secretary_file_path": snap.secretary_file_path,
            "email_pdf_path": snap.email_pdf_path,
            "merge_manifest_path": snap.merge_manifest_path,
        }
    )
    if legacy_fields:
        errors.append(
            UiError(
                stage="review",
                severity="warning",
                error_code="legacy_sandbox_path",
                user_message=(
                    "Este proceso conserva rutas SharePoint del árbol sandbox anterior "
                    "(pre-rename Comware). La proyección sigue operativa; "
                    "algunos enlaces webUrl pueden no resolverse bajo el overlay actual."
                ),
                next_action=(
                    "No reescribir Control manualmente desde la UI. "
                    "En una corrida nueva Generate/Finalize usará el overlay sandbox vigente."
                ),
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
        steps = derive_steps_from_control(
            snap,
            active_job=sources.active_job,
            jobs=sources.jobs,
            manifest=sources.manifest,
            artifact_exists=sources.artifact_exists,
        )
        operational = derive_operational_status(snap, steps)
        op_title, op_message, tech_ref = derive_operational_guidance(
            operational,
            control_estado=_nz(snap.estado_proceso),
        )

        web_urls = sources.web_urls or {}
        links: list[UiLink] = []
        # Solo documentos operativos editables/consultables por el operador.
        # Control técnico y logs de ejecución los usan los endpoints; nunca se
        # exponen como enlace en la UI.
        for rel, label, path in (
            ("review_excel", "Abrir archivo de revisión", snap.validation_file_path),
            ("historical", "Abrir histórico", snap.historical_file_path),
            ("secretary_file", "Abrir asientos pendientes", snap.secretary_file_path),
            ("email_pdf", "Ver correo enviado", snap.email_pdf_path),
            # Solo web_url (path resuelto en process_query); FE lo muestra en fase Notify.
            ("correos", "Revisar destinatarios", None),
        ):
            item = _link(rel, label, path, web_urls)
            if item:
                links.append(item)
        # PDFs reales del merge (todos los de outputs[]; nunca el JSON del manifiesto).
        merge_outputs = _merge_output_refs(sources.manifest)
        merge_labels = _merge_pdf_operator_labels(merge_outputs)
        total_merge = len(merge_outputs)
        for idx, out in enumerate(merge_outputs):
            rel = "merge_pdf" if total_merge == 1 else f"merge_pdf:{idx}"
            label = merge_labels[idx]
            # Preferir web_url ya resuelto; si el manifest trae URL, inyectarla.
            # Sin URL Graph: el enlace se mantiene (path) para no ocultar PDFs hermanos.
            urls_for_link = dict(web_urls)
            if out.web_url and rel not in urls_for_link:
                urls_for_link[rel] = out.web_url
            item = _link(rel, label, out.path, urls_for_link)
            if item:
                links.append(item)

        review_link = next((l for l in links if l.rel == "review_excel"), None)
        file_name = None
        if snap.validation_file_path:
            file_name = str(snap.validation_file_path).rsplit("/", 1)[-1]

        staged_jobs = collect_jobs_for_stages(
            (sources.jobs.job_manager_by_type if sources.jobs else {}) or {}
        )
        by_stage_attempts = latest_attempts_by_stage(staged_jobs)
        last_attempt = pick_last_attempt(by_stage_attempts)

        operational_issues: list[UiOperationalIssue] = []
        fin_job = staged_jobs.get("finalize")
        if fin_job and str(fin_job.payload.get("status") or "").lower() == "failed":
            operational_issues.extend(
                build_operational_issues_from_finalize_job(
                    fin_job,
                    review_link=review_link,
                    file_name=file_name,
                )
            )

        attempts = build_attempts_from_jobs(list(staged_jobs.values()))

        # active_job: solo queued/running
        active_src = sources.active_job
        if active_src and str(active_src.payload.get("status") or "").lower() not in {
            "queued",
            "running",
        }:
            active_src = None

        process_date = None
        if snap.process_key:
            d = process_date_from_process_key(snap.process_key)
            if d:
                process_date = d.isoformat()

        flags = get_ui_feature_flags()
        write_allowed = flags.writes_allowed and env.environment == "sandbox"
        mutation_active = get_job_manager().is_generate_or_finalize_active()
        readiness = sources.merge_readiness
        readiness_status = sources.merge_readiness_status
        if readiness is not None and not readiness_status:
            readiness_status = readiness.status
        fin_av = compute_finalize_availability(
            write_allowed=write_allowed,
            finalize_enabled=flags.ui_finalize_enabled,
            sandbox=env.environment == "sandbox",
            generate_or_finalize_active=mutation_active,
            snap=snap,
            expected_process_key=_nz(snap.process_key) or None,
        )
        notify_av = compute_notify_availability(
            write_allowed=write_allowed,
            notify_enabled=flags.ui_notify_enabled,
            sandbox=env.environment == "sandbox",
            mutation_active=mutation_active,
            snap=snap,
            expected_process_key=_nz(snap.process_key) or None,
        )
        merge_av = compute_merge_availability(
            write_allowed=write_allowed,
            merge_enabled=flags.ui_merge_enabled,
            sandbox=env.environment == "sandbox",
            mutation_active=mutation_active,
            snap=snap,
            expected_process_key=_nz(snap.process_key) or None,
            readiness_status=readiness_status,
        )
        amort_readiness = sources.amortization_readiness
        amort_readiness_status = sources.amortization_readiness_status
        if amort_readiness is not None and not amort_readiness_status:
            amort_readiness_status = amort_readiness.status
        amort_av = compute_amortization_availability(
            write_allowed=write_allowed,
            amortization_enabled=flags.ui_amortization_enabled,
            sandbox=env.environment == "sandbox",
            mutation_active=mutation_active,
            snap=snap,
            expected_process_key=_nz(snap.process_key) or None,
            readiness_status=amort_readiness_status,
        )
        # Solo acciones de operador U3: finalize / notify / merge / amortization.
        # dry_run y apply quedan fuera de available_actions.
        available_actions = {
            "finalize": UiActionAvailability(
                allowed=fin_av.allowed, reason=fin_av.reason
            ),
            "notify": UiActionAvailability(
                allowed=notify_av.allowed, reason=notify_av.reason
            ),
            "merge": UiActionAvailability(
                allowed=merge_av.allowed, reason=merge_av.reason
            ),
            "amortization": UiActionAvailability(
                allowed=amort_av.allowed, reason=amort_av.reason
            ),
        }

        merge_readiness_dto: UiMergeReadiness | None = None
        if readiness is not None:
            merge_readiness_dto = UiMergeReadiness(
                status=readiness.status,  # type: ignore[arg-type]
                expected_groups=readiness.expected_groups,
                ready_groups=readiness.ready_groups,
                missing_groups=readiness.missing_groups,
                missing_items=list(readiness.missing_items),
                folder_links=list(readiness.folder_links),
                checked_at=readiness.checked_at or None,
                user_message=readiness.user_message,
                next_action=readiness.next_action,
            )

        amortization_readiness_dto: UiAmortizationReadiness | None = None
        if amort_readiness is not None:
            amortization_readiness_dto = UiAmortizationReadiness(
                status=amort_readiness.status,  # type: ignore[arg-type]
                can_start=amort_readiness.can_start,
                expected_items=amort_readiness.expected_items,
                ready_items=amort_readiness.ready_items,
                missing_items=list(amort_readiness.missing_items),
                warnings=list(amort_readiness.warnings),
                checked_at=amort_readiness.checked_at or None,
                user_message=amort_readiness.user_message,
                next_action=amort_readiness.next_action,
            )

        next_actions = derive_next_actions(snap, steps, links=links)
        # Alinear enabled con available_actions reales (flags + entorno).
        action_gate = {
            "notify": available_actions["notify"],
            "retry_notify": available_actions["notify"],
            "retry_finalize": available_actions["finalize"],
            "finalize": available_actions["finalize"],
            "retry_merge": available_actions["merge"],
            "merge": available_actions["merge"],
            "amortization": available_actions["amortization"],
            "retry_amortization": available_actions["amortization"],
        }
        gated: list[UiNextAction] = []
        for action in next_actions:
            gate = action_gate.get(action.code)
            if gate is None:
                gated.append(action)
                continue
            gated.append(
                action.model_copy(
                    update={
                        "enabled": bool(gate.allowed),
                        "reason": (
                            action.reason
                            if gate.allowed
                            else (
                                " ".join(
                                    dict.fromkeys(
                                        p
                                        for p in (action.reason, gate.reason)
                                        if p
                                    )
                                )
                                or None
                            )
                        ),
                    }
                )
            )

        return UiProcessDetail(
            process_key=_nz(snap.process_key) or "",
            process_id=_nz(snap.process_id),
            bank_code=_nz(snap.bank_code) or "",
            bank_name=_nz(snap.bank_name),
            process_date=process_date,
            environment=env.environment,
            operational_status=operational,
            operational_title=op_title,
            operational_message=op_message,
            control_estado_proceso=_nz(snap.estado_proceso),
            is_active=bool(snap.is_active),
            steps=steps,
            items=list(sources.items),
            active_job=_active_job_dto(active_src),
            last_attempt=last_attempt,
            latest_attempts_by_stage=by_stage_attempts,
            attempts=attempts,
            next_actions=gated,
            available_actions=available_actions,
            errors=derive_errors(snap, steps, jobs=sources.jobs),
            operational_issues=operational_issues,
            technical_status_reference=tech_ref,
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
            operator_checklist=build_finalize_operator_checklist(),
            merge_readiness=merge_readiness_dto,
            amortization_readiness=amortization_readiness_dto,
        )

    def summarize(self, detail: UiProcessDetail) -> UiProcessSummary:
        return UiProcessSummary(
            process_key=detail.process_key,
            bank_code=detail.bank_code,
            process_date=detail.process_date,
            environment=detail.environment,
            operational_status=detail.operational_status,
            operational_title=detail.operational_title,
            operational_message=detail.operational_message,
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
