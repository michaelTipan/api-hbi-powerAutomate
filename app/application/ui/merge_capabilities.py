"""Cálculo puro de ``available_actions.merge`` para la UI.

Sin efectos secundarios de escritura: no adquiere locks, no une PDFs, no
escribe control. Consulta evidencia local de JobManager para la ventana stale
tras un Merge exitoso.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.application.job_manager import get_job_manager
from app.application.use_cases.merge_composite_validado_pdfs import (
    MERGE_RUNNABLE_STATES,
)
from app.application.use_cases.payment_validation_process_control import (
    ProcessControlSnapshot,
)

_REASON_WRITE_DISABLED = (
    "Las escrituras desde la UI están deshabilitadas en este ambiente."
)
_REASON_MERGE_DISABLED = (
    "Merge desde la UI todavía no está habilitado."
)
_REASON_NOT_SANDBOX = (
    "Merge desde la UI no está permitido en este ambiente."
)
_REASON_LOCK_ACTIVE = (
    "Ya hay un Generate, Finalize, Notify o Merge en curso. Espere a que termine."
)
_REASON_NO_ACTIVE = (
    "No hay un proceso activo listo para consolidar en este banco."
)
_REASON_KEY_MISMATCH = (
    "El ProcessKey no coincide con el proceso activo del control."
)
_REASON_STATE = (
    "El control no está en un estado que permita consolidar soportes."
)
_REASON_NO_HISTORICAL = (
    "Falta HistoricalFilePath en el Excel de control."
)
_REASON_NO_EMAIL_PDF = (
    "Falta EmailPdfPath en el Excel de control (correo de Notify)."
)
_REASON_ALREADY = (
    "Los soportes de este proceso ya fueron consolidados."
)
_REASON_INCOMPLETE = "Faltan soportes contables."
_REASON_UNKNOWN = (
    "No se pudo verificar si los soportes están completos. "
    "Actualice e intente nuevamente."
)


@dataclass(frozen=True)
class MergeAvailability:
    allowed: bool
    reason: str | None


def control_indicates_already_merged(snap: ProcessControlSnapshot) -> bool:
    """Evidencia de control: CONSOLIDADO + clave o manifiesto de merge."""
    estado = (snap.estado_proceso or "").strip().upper()
    if estado != "CONSOLIDADO":
        return False
    has_idem = bool((snap.merge_idempotency_key or "").strip())
    has_manifest = bool((snap.merge_manifest_path or "").strip())
    return has_idem or has_manifest


def compute_merge_availability(
    *,
    write_allowed: bool,
    merge_enabled: bool,
    sandbox: bool,
    mutation_active: bool,
    snap: ProcessControlSnapshot | None,
    expected_process_key: str | None = None,
    readiness_status: str | None = None,
) -> MergeAvailability:
    """Evalúa si la UI puede ofrecer Merge (informativo; el POST revalida).

    ``readiness_status`` None se trata como ``unknown`` (fail-closed).
    """
    if not write_allowed:
        return MergeAvailability(False, _REASON_WRITE_DISABLED)
    if not merge_enabled:
        return MergeAvailability(False, _REASON_MERGE_DISABLED)
    if not sandbox:
        return MergeAvailability(False, _REASON_NOT_SANDBOX)
    if mutation_active:
        return MergeAvailability(False, _REASON_LOCK_ACTIVE)
    if snap is None:
        return MergeAvailability(False, _REASON_NO_ACTIVE)
    if not snap.is_active:
        return MergeAvailability(False, _REASON_NO_ACTIVE)

    pk = (expected_process_key or snap.process_key or "").strip()

    # Ya consolidado: control fresco o evidencia JobManager.
    if control_indicates_already_merged(snap):
        return MergeAvailability(False, _REASON_ALREADY)
    if pk and get_job_manager().has_completed_merge(pk):
        return MergeAvailability(False, _REASON_ALREADY)

    estado = (snap.estado_proceso or "").strip().upper()
    if estado not in MERGE_RUNNABLE_STATES:
        return MergeAvailability(False, _REASON_STATE)
    # CONSOLIDADO sin evidencia ya se filtró; si llega aquí sin evidencia, no es runnable útil.
    if estado == "CONSOLIDADO":
        return MergeAvailability(False, _REASON_ALREADY)

    if not (snap.historical_file_path or "").strip():
        return MergeAvailability(False, _REASON_NO_HISTORICAL)
    if not (snap.email_pdf_path or "").strip():
        return MergeAvailability(False, _REASON_NO_EMAIL_PDF)

    if expected_process_key is not None:
        want = (expected_process_key or "").strip()
        got = (snap.process_key or "").strip()
        if not want or want != got:
            return MergeAvailability(False, _REASON_KEY_MISMATCH)
    elif not (snap.process_key or "").strip():
        return MergeAvailability(False, _REASON_NO_ACTIVE)

    # Readiness: None → unknown (fail-closed).
    status = (readiness_status or "unknown").strip().lower()
    if status == "already_merged":
        return MergeAvailability(False, _REASON_ALREADY)
    if status == "incomplete":
        return MergeAvailability(False, _REASON_INCOMPLETE)
    if status == "unknown":
        return MergeAvailability(False, _REASON_UNKNOWN)
    if status != "ready":
        return MergeAvailability(False, _REASON_UNKNOWN)

    # CONSOLIDANDO solo con readiness ready y sin mutación (reintento stale).
    if estado == "CONSOLIDANDO" and mutation_active:
        return MergeAvailability(False, _REASON_LOCK_ACTIVE)

    return MergeAvailability(True, None)
