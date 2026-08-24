"""Job completed sin evidencia en Control → sync_pending / SINCRONIZANDO.

No debe proyectarse como failed_business ni CORRECCION_REQUERIDA.
"""
from __future__ import annotations

from app.application.ui.job_read import JobReadResult
from app.application.ui.process_projection import (
    PaymentProcessProjectionService,
    ProjectionSources,
    TechnicalJobEvidence,
    derive_steps_from_control,
)
from tests.ui_fixtures import make_snap


def _jm(type_name: str, status: str = "completed") -> TechnicalJobEvidence:
    job = JobReadResult(
        job_id="j-sync",
        store="job_manager",
        payload={"type": type_name, "status": status},
    )
    key = type_name.split("_")[0] if "_" in type_name else type_name
    return TechnicalJobEvidence(job_manager_by_type={key: job})


def test_generate_completed_without_review_path_is_sync_pending() -> None:
    snap = make_snap(
        estado_proceso="GENERANDO",
        validation_file_path="",
        is_active=True,
    )
    steps = {
        s.name: s
        for s in derive_steps_from_control(
            snap, jobs=_jm("payment_validation_generate")
        )
    }
    assert steps["generate"].status == "sync_pending"
    detail = PaymentProcessProjectionService().project(
        ProjectionSources(snapshot=snap, jobs=_jm("payment_validation_generate"))
    )
    assert detail.operational_status == "SINCRONIZANDO"
    assert detail.operational_status != "CORRECCION_REQUERIDA"


def test_finalize_completed_without_historical_is_sync_pending() -> None:
    snap = make_snap(
        estado_proceso="REVISION_CREADA",
        historical_file_path="",
        validation_file_path="rev.xlsx",
    )
    evidence = _jm("payment_validation_finalize")
    steps = {s.name: s for s in derive_steps_from_control(snap, jobs=evidence)}
    assert steps["finalize"].status == "sync_pending"
    detail = PaymentProcessProjectionService().project(
        ProjectionSources(snapshot=snap, jobs=evidence)
    )
    assert detail.operational_status == "SINCRONIZANDO"


def test_notify_completed_without_control_evidence_is_sync_pending() -> None:
    snap = make_snap(
        estado_proceso="FINALIZADO",
        historical_file_path="hist.xlsx",
        notify_idempotency_key="",
        email_pdf_path="",
    )
    memory = JobReadResult(
        job_id="n1",
        store="sharepoint_memory",
        payload={"type": "notify_validar_extractos", "status": "completed"},
    )
    steps = {
        s.name: s
        for s in derive_steps_from_control(
            snap, jobs=TechnicalJobEvidence(memory_job=memory)
        )
    }
    assert steps["notify"].status == "sync_pending"
    detail = PaymentProcessProjectionService().project(
        ProjectionSources(
            snapshot=snap, jobs=TechnicalJobEvidence(memory_job=memory)
        )
    )
    assert detail.operational_status == "SINCRONIZANDO"


def test_merge_completed_while_control_still_pendiente_asientos_is_sync_pending() -> None:
    """PENDIENTE_ASIENTOS previo no debe ocultar el desfase tras Merge completed."""
    snap = make_snap(
        estado_proceso="PENDIENTE_ASIENTOS",
        historical_file_path="hist.xlsx",
        notify_idempotency_key="nk",
        email_pdf_path="mail.pdf",
        merge_manifest_path="",
        merge_idempotency_key="",
        secretary_file_path="asientos.xlsx",
    )
    evidence = _jm("merge_composite_validado_pdfs")
    steps = {s.name: s for s in derive_steps_from_control(snap, jobs=evidence)}
    assert steps["merge"].status == "sync_pending"
    assert steps["merge"].status != "blocked"
    detail = PaymentProcessProjectionService().project(
        ProjectionSources(snapshot=snap, jobs=evidence)
    )
    assert detail.operational_status == "SINCRONIZANDO"
    assert detail.operational_status != "ESPERANDO_SOPORTES"


def test_apply_completed_without_amortizacion_aplicada_is_sync_pending() -> None:
    """Sin outcome (o applied): desfase real job↔Control → sync_pending."""
    pk = "payment-validation|banco_bancolombia|2026-07-29|abc-123"
    snap = make_snap(
        process_key=pk,
        estado_proceso="CONSOLIDADO",
        historical_file_path="hist.xlsx",
        notify_idempotency_key=pk,
        email_pdf_path="mail.pdf",
        merge_manifest_path="m.json",
        merge_idempotency_key=pk,
        apply_idempotency_key="",
        secretary_file_path="asientos.xlsx",
    )
    evidence = TechnicalJobEvidence(
        job_manager_by_type={
            "amortization": JobReadResult(
                job_id="a1",
                store="job_manager",
                payload={"type": "amortization_process", "status": "completed"},
            )
        }
    )
    steps = {s.name: s for s in derive_steps_from_control(snap, jobs=evidence)}
    assert steps["apply"].status == "sync_pending"
    detail = PaymentProcessProjectionService().project(
        ProjectionSources(snapshot=snap, jobs=evidence)
    )
    assert detail.operational_status == "SINCRONIZANDO"


def test_apply_completed_requires_correction_is_not_sync_pending() -> None:
    """requires_correction no deja SINCRONIZANDO eterno al reabrir la pestaña."""
    pk = "payment-validation|banco_bancolombia|2026-08-21|d01a537c-5393-4f4b-ad54-0dd6485da59d"
    snap = make_snap(
        process_key=pk,
        estado_proceso="CONSOLIDADO",
        historical_file_path="hist.xlsx",
        notify_idempotency_key=pk,
        email_pdf_path="mail.pdf",
        merge_manifest_path="m.json",
        merge_idempotency_key=pk,
        apply_idempotency_key="",
        secretary_file_path="asientos.xlsx",
    )
    evidence = TechnicalJobEvidence(
        job_manager_by_type={
            "amortization": JobReadResult(
                job_id="a-corr",
                store="job_manager",
                payload={
                    "type": "amortization_process",
                    "status": "completed",
                    "result_summary": {"outcome": "requires_correction"},
                },
            )
        }
    )
    steps = {s.name: s for s in derive_steps_from_control(snap, jobs=evidence)}
    assert steps["apply"].status == "not_started"
    assert steps["apply"].can_retry is True
    detail = PaymentProcessProjectionService().project(
        ProjectionSources(snapshot=snap, jobs=evidence)
    )
    assert detail.operational_status == "LISTO_PARA_APLICAR"
    assert detail.operational_status != "SINCRONIZANDO"


def test_apply_completed_applied_outcome_without_control_is_sync_pending() -> None:
    """outcome=applied sin AMORTIZACION_APLICADA sigue siendo desfase temporal."""
    pk = "payment-validation|banco_bancolombia|2026-08-21|abc-applied"
    snap = make_snap(
        process_key=pk,
        estado_proceso="CONSOLIDADO",
        historical_file_path="hist.xlsx",
        notify_idempotency_key=pk,
        email_pdf_path="mail.pdf",
        merge_manifest_path="m.json",
        merge_idempotency_key=pk,
        apply_idempotency_key="",
        secretary_file_path="asientos.xlsx",
    )
    evidence = TechnicalJobEvidence(
        job_manager_by_type={
            "amortization": JobReadResult(
                job_id="a-ok",
                store="job_manager",
                payload={
                    "type": "amortization_process",
                    "status": "completed",
                    "result_summary": {"outcome": "applied"},
                },
            )
        }
    )
    steps = {s.name: s for s in derive_steps_from_control(snap, jobs=evidence)}
    assert steps["apply"].status == "sync_pending"
    detail = PaymentProcessProjectionService().project(
        ProjectionSources(snapshot=snap, jobs=evidence)
    )
    assert detail.operational_status == "SINCRONIZANDO"


def test_real_missing_review_file_still_failed_business() -> None:
    """Archivo ausente con Control que ya indica revisión = error real."""
    snap = make_snap(
        estado_proceso="REVISION_CREADA",
        validation_file_path="missing.xlsx",
    )
    steps = {
        s.name: s
        for s in derive_steps_from_control(
            snap, artifact_exists={"missing.xlsx": False}
        )
    }
    assert steps["generate"].status == "failed_business"
