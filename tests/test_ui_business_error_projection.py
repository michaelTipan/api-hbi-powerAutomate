"""Proyección UI: errores de job fallido (contrato Jonathan + overlay Comware)."""

from __future__ import annotations

from app.application.ui.job_read import JobReadResult
from app.application.ui.process_projection import (
    TechnicalJobEvidence,
    derive_errors,
    derive_steps_from_control,
)
from tests.ui_fixtures import make_snap


def test_finalize_failed_job_surfaces_business_error() -> None:
    snap = make_snap(estado_proceso="REVISION_CREADA")
    fin_job = JobReadResult(
        job_id="f1",
        store="job_manager",
        payload={
            "type": "finalize",
            "status": "failed",
            "error": {
                "error_code": "amount_mismatch",
                "user_message": "Los valores distribuidos no coinciden con el monto registrado por el banco.",
                "next_action": "Revise Distribucion_Pagos y vuelva a finalizar.",
                "message": "amount_mismatch",
            },
        },
    )
    steps = derive_steps_from_control(
        snap,
        jobs=TechnicalJobEvidence(job_manager_by_type={"finalize": fin_job}),
    )
    errors = derive_errors(
        snap,
        steps,
        jobs=TechnicalJobEvidence(job_manager_by_type={"finalize": fin_job}),
    )
    assert any(e.error_code == "amount_mismatch" for e in errors)
    assert steps[2].name == "finalize"
    # amount_mismatch es corrección de datos → failed_business (no reintento ciego).
    assert steps[2].status == "failed_business"
