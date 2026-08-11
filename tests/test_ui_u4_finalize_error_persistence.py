"""U4-A0: reproducir pérdida de error Finalize recuperable en proyección UI.

Estos tests documentan el comportamiento DESEADO. Fallan mientras el defecto
esté activo (REVISION_CREADA + finalize failed → EN_REVISION sin errores).
"""
from __future__ import annotations

import pytest

from app.application.ui.job_read import JobReadResult
from app.application.ui.process_projection import (
    PaymentProcessProjectionService,
    ProjectionSources,
    TechnicalJobEvidence,
    derive_operational_status,
    derive_steps_from_control,
)
from tests.ui_fixtures import make_snap

PROCESS_KEY = "payment-validation|banco_bancolombia|2026-07-29|abc-123"


def _failed_finalize_job(
    *,
    job_id: str = "fin-fail-1",
    error_code: str = "invalid_estado_pago",
    message: str | None = None,
) -> JobReadResult:
    msg = message or (
        'invalid_estado_pago|{"excel_row":8,"field":"Estado Pago",'
        '"value_found":"PAGADO","sheet":"Aplicacion_Pagos"}'
    )
    return JobReadResult(
        job_id=job_id,
        store="job_manager",
        payload={
            "job_id": job_id,
            "type": "finalize",
            "status": "failed",
            "process_key": PROCESS_KEY,
            "bank_code": "banco_bancolombia",
            "started_at": "2026-07-31T10:00:00-05:00",
            "finished_at": "2026-07-31T10:00:12-05:00",
            "trigger_source": "web_ui",
            "requested_by": "operador_hbi",
            "error": {
                "type": "ValueError",
                "message": msg,
                "error_code": error_code,
                "user_message": (
                    "Hay un Estado Pago escrito a mano o un valor que no está "
                    "en la lista permitida."
                ),
                "next_action": (
                    "Use solo la lista desplegable: ADELANTADO, ATRASADO, "
                    "NORMAL, REVISIÓN MANUAL. Guarde y vuelva a finalizar."
                ),
                "severity": "warning",
            },
        },
    )


def test_revision_creada_failed_finalize_is_not_en_revision() -> None:
    """Defecto: hoy queda EN_REVISION; debe ser CORRECCION_REQUERIDA."""
    snap = make_snap(estado_proceso="REVISION_CREADA", process_key=PROCESS_KEY)
    job = _failed_finalize_job()
    evidence = TechnicalJobEvidence(job_manager_by_type={"finalize": job})
    steps = derive_steps_from_control(snap, jobs=evidence)
    status = derive_operational_status(snap, steps)
    assert status == "CORRECCION_REQUERIDA"


def test_revision_creada_failed_finalize_step_is_failed_business() -> None:
    """Defecto: hoy finalize queda not_started; debe ser failed_business."""
    snap = make_snap(estado_proceso="REVISION_CREADA", process_key=PROCESS_KEY)
    job = _failed_finalize_job()
    evidence = TechnicalJobEvidence(job_manager_by_type={"finalize": job})
    by = {s.name: s for s in derive_steps_from_control(snap, jobs=evidence)}
    assert by["finalize"].status == "failed_business"
    assert by["finalize"].can_retry is True
    assert by["finalize"].retry_action in {"finalize", "retry_finalize"}
    # Control intacto: review sigue pendiente
    assert by["review"].status == "in_progress"


def test_projection_exposes_errors_and_last_attempt_after_failed_finalize() -> None:
    """Defecto: errors vacío y sin last_attempt; debe proyectar el fallo."""
    snap = make_snap(estado_proceso="REVISION_CREADA", process_key=PROCESS_KEY)
    job = _failed_finalize_job()
    evidence = TechnicalJobEvidence(job_manager_by_type={"finalize": job})
    detail = PaymentProcessProjectionService().project(
        ProjectionSources(snapshot=snap, jobs=evidence)
    )
    assert detail.control_estado_proceso == "REVISION_CREADA"
    assert detail.operational_status == "CORRECCION_REQUERIDA"
    assert len(detail.errors) >= 1
    assert detail.errors[0].error_code == "invalid_estado_pago"
    assert detail.errors[0].user_message
    assert detail.errors[0].next_action
    assert detail.last_attempt is not None
    assert detail.last_attempt.stage == "finalize"
    assert detail.last_attempt.status == "failed"
    assert detail.last_attempt.recoverable is True
    assert detail.last_attempt.error_code == "invalid_estado_pago"
    assert detail.active_job is None  # terminal no es activo
    assert "finalize" in detail.latest_attempts_by_stage
    assert detail.latest_attempts_by_stage["finalize"].job_id == "fin-fail-1"


def test_summary_counts_attention_for_failed_finalize() -> None:
    snap = make_snap(estado_proceso="REVISION_CREADA", process_key=PROCESS_KEY)
    job = _failed_finalize_job()
    evidence = TechnicalJobEvidence(job_manager_by_type={"finalize": job})
    detail = PaymentProcessProjectionService().project(
        ProjectionSources(snapshot=snap, jobs=evidence)
    )
    summary = PaymentProcessProjectionService().summarize(detail)
    assert summary.error_count >= 1
    assert summary.operational_status == "CORRECCION_REQUERIDA"


def test_successful_later_finalize_clears_correction() -> None:
    """Un intento completed posterior no debe dejar corrección activa."""
    snap = make_snap(
        estado_proceso="FINALIZADO",
        process_key=PROCESS_KEY,
        historical_file_path="historico/cartera.xlsx",
        secretary_file_path="historico/Asientos.xlsx",
    )
    completed = JobReadResult(
        job_id="fin-ok-2",
        store="job_manager",
        payload={
            "job_id": "fin-ok-2",
            "type": "finalize",
            "status": "completed",
            "process_key": PROCESS_KEY,
            "finished_at": "2026-07-31T11:00:00-05:00",
            "result": {"status": "success"},
        },
    )
    evidence = TechnicalJobEvidence(job_manager_by_type={"finalize": completed})
    detail = PaymentProcessProjectionService().project(
        ProjectionSources(snapshot=snap, jobs=evidence)
    )
    by = {s.name: s for s in detail.steps}
    assert by["finalize"].status == "completed"
    assert detail.operational_status == "PENDIENTE_NOTIFICACION"
    assert detail.operational_message == "La revisión fue finalizada correctamente."
    assert not any(
        (e.error_code or "") == "invalid_estado_pago" for e in detail.errors
    )


def test_temporary_finalize_failure_is_error_recuperable() -> None:
    snap = make_snap(estado_proceso="REVISION_CREADA", process_key=PROCESS_KEY)
    job = _failed_finalize_job(
        error_code="excel_locked",
        message="excel_locked|El archivo está abierto en Excel Online",
    )
    # Sobrescribir mensajes enriquecidos temporales
    job.payload["error"] = {
        "type": "RuntimeError",
        "message": "excel_locked|El archivo está abierto en Excel Online",
        "error_code": "excel_locked",
        "user_message": "No pudimos completar la operación porque el archivo está bloqueado.",
        "next_action": "Cierre el archivo y vuelva a intentarlo.",
        "severity": "recoverable",
    }
    evidence = TechnicalJobEvidence(job_manager_by_type={"finalize": job})
    detail = PaymentProcessProjectionService().project(
        ProjectionSources(snapshot=snap, jobs=evidence)
    )
    by = {s.name: s for s in detail.steps}
    assert by["finalize"].status == "failed_retryable"
    assert detail.operational_status == "ERROR_RECUPERABLE"


@pytest.mark.parametrize(
    "error_code",
    [
        "review_has_open_errors",
        "empty_estado_pago",
        "invalid_estado_pago",
        "no_validar_requires_observation",
        "amount_mismatch",
        "missing_abono_capital",
    ],
)
def test_business_finalize_codes_are_correction_required(error_code: str) -> None:
    snap = make_snap(estado_proceso="REVISION_CREADA", process_key=PROCESS_KEY)
    job = _failed_finalize_job(error_code=error_code, message=error_code)
    job.payload["error"]["error_code"] = error_code
    job.payload["error"]["message"] = error_code
    evidence = TechnicalJobEvidence(job_manager_by_type={"finalize": job})
    detail = PaymentProcessProjectionService().project(
        ProjectionSources(snapshot=snap, jobs=evidence)
    )
    assert detail.operational_status == "CORRECCION_REQUERIDA"
    by = {s.name: s for s in detail.steps}
    assert by["finalize"].status == "failed_business"
