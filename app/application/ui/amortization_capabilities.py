"""Cálculo puro de ``available_actions.amortization`` para la UI.

Sin efectos secundarios de escritura: no adquiere locks, no ejecuta dry-run ni
Apply. Consulta evidencia local de JobManager para detectar aplicación previa.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.application.job_manager import get_job_manager
from app.application.use_cases.amortization_fill_dry_run import (
    AMORTIZATION_RUNNABLE_STATES,
)
from app.application.use_cases.payment_validation_process_control import (
    ProcessControlSnapshot,
)

_REASON_WRITE_DISABLED = (
    "Las escrituras desde la UI están deshabilitadas en este ambiente."
)
_REASON_AMORTIZATION_DISABLED = (
    "Procesar amortización desde la UI todavía no está habilitado."
)
_REASON_NOT_SANDBOX = (
    "Procesar amortización desde la UI solo está permitido en sandbox."
)
_REASON_LOCK_ACTIVE = (
    "Ya hay un Generate, Finalize, Notify, Merge o Amortización en curso. "
    "Espere a que termine."
)
_REASON_NO_ACTIVE = (
    "No hay un proceso activo listo para amortizar en este banco."
)
_REASON_KEY_MISMATCH = (
    "El ProcessKey no coincide con el proceso activo del control."
)
_REASON_STATE = (
    "El control no está en un estado que permita procesar amortización."
)
_REASON_MERGE_INCOMPLETE = (
    "La consolidación de soportes quedó parcial; complétela antes de amortizar."
)
_REASON_NO_MANIFEST = (
    "Falta MergeManifestPath en el Excel de control."
)
_REASON_NO_HISTORICAL = (
    "Falta HistoricalFilePath en el Excel de control."
)
_REASON_ALREADY = (
    "La amortización de este proceso ya fue aplicada anteriormente."
)
_REASON_INCOMPLETE = "Faltan soportes o el manifiesto de consolidación está incompleto."
_REASON_UNKNOWN = (
    "No se pudo verificar si la información está lista para amortizar. "
    "Actualice e intente nuevamente."
)


@dataclass(frozen=True)
class AmortizationAvailability:
    allowed: bool
    reason: str | None


def control_indicates_already_applied(snap: ProcessControlSnapshot) -> bool:
    """Evidencia de control: AMORTIZACION_APLICADA + ApplyIdempotencyKey==ProcessKey."""
    estado = (snap.estado_proceso or "").strip().upper()
    if estado != "AMORTIZACION_APLICADA":
        return False
    apply_key = (snap.apply_idempotency_key or "").strip()
    process_key = (snap.process_key or "").strip()
    return bool(apply_key) and bool(process_key) and apply_key == process_key


def compute_amortization_availability(
    *,
    write_allowed: bool,
    amortization_enabled: bool,
    sandbox: bool,
    mutation_active: bool,
    snap: ProcessControlSnapshot | None,
    expected_process_key: str | None = None,
    readiness_status: str | None = None,
) -> AmortizationAvailability:
    """Evalúa si la UI puede ofrecer "Procesar amortización" (informativo; el POST revalida).

    ``readiness_status`` None se trata como ``unknown`` (fail-closed).
    """
    if not write_allowed:
        return AmortizationAvailability(False, _REASON_WRITE_DISABLED)
    if not amortization_enabled:
        return AmortizationAvailability(False, _REASON_AMORTIZATION_DISABLED)
    if not sandbox:
        return AmortizationAvailability(False, _REASON_NOT_SANDBOX)
    if mutation_active:
        return AmortizationAvailability(False, _REASON_LOCK_ACTIVE)
    if snap is None or not snap.is_active:
        return AmortizationAvailability(False, _REASON_NO_ACTIVE)

    pk = (expected_process_key or snap.process_key or "").strip()

    # Ya aplicada: control fresco o evidencia JobManager.
    if control_indicates_already_applied(snap):
        return AmortizationAvailability(False, _REASON_ALREADY)
    if pk and get_job_manager().has_completed_amortization(pk):
        return AmortizationAvailability(False, _REASON_ALREADY)

    estado = (snap.estado_proceso or "").strip().upper()
    if estado not in AMORTIZATION_RUNNABLE_STATES:
        return AmortizationAvailability(False, _REASON_STATE)
    # MERGE_PARCIAL es "detectable" pero el gate de manifest bloquea siempre.
    if estado == "MERGE_PARCIAL":
        return AmortizationAvailability(False, _REASON_MERGE_INCOMPLETE)

    if not (snap.merge_manifest_path or "").strip():
        return AmortizationAvailability(False, _REASON_NO_MANIFEST)
    if not (snap.historical_file_path or "").strip():
        return AmortizationAvailability(False, _REASON_NO_HISTORICAL)

    if expected_process_key is not None:
        want = (expected_process_key or "").strip()
        got = (snap.process_key or "").strip()
        if not want or want != got:
            return AmortizationAvailability(False, _REASON_KEY_MISMATCH)
    elif not (snap.process_key or "").strip():
        return AmortizationAvailability(False, _REASON_NO_ACTIVE)

    # Readiness: None → unknown (fail-closed).
    status = (readiness_status or "unknown").strip().lower()
    if status == "already_applied":
        return AmortizationAvailability(False, _REASON_ALREADY)
    if status == "incomplete":
        return AmortizationAvailability(False, _REASON_INCOMPLETE)
    if status == "unknown":
        return AmortizationAvailability(False, _REASON_UNKNOWN)
    if status != "ready":
        return AmortizationAvailability(False, _REASON_UNKNOWN)

    return AmortizationAvailability(True, None)
