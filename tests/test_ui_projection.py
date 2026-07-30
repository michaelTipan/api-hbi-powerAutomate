from __future__ import annotations

from app.application.ui.job_read import JobReadResult
from app.application.ui.process_projection import (
    PaymentProcessProjectionService,
    ProjectionSources,
    derive_steps_from_control,
)
from tests.ui_fixtures import make_snap


def test_review_stage_from_revision_creada() -> None:
    snap = make_snap(estado_proceso="REVISION_CREADA")
    steps = {s.name: s for s in derive_steps_from_control(snap)}
    assert steps["generate"].status == "completed"
    assert steps["review"].status == "in_progress"
    assert steps["finalize"].status == "not_started"
    assert steps["notify"].status == "not_started"


def test_finalize_ok_notify_failed_retryable_no_rerun_finalize() -> None:
    snap = make_snap(
        estado_proceso="ERROR_NOTIFY",
        historical_file_path="historico/cartera.xlsx",
        secretary_file_path="historico/Asientos_Pendientes.xlsx",
        notify_idempotency_key="",
        email_pdf_path="",
    )
    detail = PaymentProcessProjectionService().project(ProjectionSources(snapshot=snap))
    by = {s.name: s for s in detail.steps}
    assert by["finalize"].status == "completed"
    assert by["notify"].status == "failed_retryable"
    assert by["notify"].can_retry is True
    assert by["notify"].retry_action == "retry_notify"
    assert detail.operational_status == "ERROR_RECUPERABLE"
    assert any(a.code == "retry_notify" for a in detail.next_actions)
    # Mutaciones no habilitadas en U1
    retry = next(a for a in detail.next_actions if a.code == "retry_notify")
    assert retry.enabled is False


def test_notify_completed_requires_persistent_control_not_memory_job() -> None:
    snap = make_snap(
        estado_proceso="FINALIZADO",
        historical_file_path="historico/cartera.xlsx",
        notify_idempotency_key="",
        email_pdf_path="",
    )
    # Job memoria “completed” NO debe marcar notify completed.
    memory_job = JobReadResult(
        job_id="j1",
        store="sharepoint_memory",
        payload={"type": "notify_validar_extractos", "status": "completed"},
    )
    steps = {s.name: s for s in derive_steps_from_control(snap, active_job=memory_job)}
    assert steps["notify"].status == "not_started"

    snap2 = make_snap(
        estado_proceso="PENDIENTE_ASIENTOS",
        historical_file_path="historico/cartera.xlsx",
        notify_idempotency_key="payment-validation|banco_bancolombia|2026-07-29|abc-123",
        email_pdf_path="correos/ABONOS.pdf",
        secretary_file_path="historico/Asientos_Pendientes.xlsx",
    )
    steps2 = {s.name: s for s in derive_steps_from_control(snap2)}
    assert steps2["notify"].status == "completed"


def test_merge_partial_blocks_dry_run() -> None:
    snap = make_snap(
        estado_proceso="MERGE_PARCIAL",
        historical_file_path="historico/cartera.xlsx",
        notify_idempotency_key="pk",
        email_pdf_path="correos/x.pdf",
        merge_manifest_path="trazabilidad/manifest.json",
        secretary_file_path="historico/Asientos.xlsx",
    )
    detail = PaymentProcessProjectionService().project(ProjectionSources(snapshot=snap))
    by = {s.name: s for s in detail.steps}
    assert by["merge"].status == "partial"
    assert by["dry_run"].status == "blocked"
    assert detail.operational_status == "FINALIZADO_PARCIALMENTE"
    assert detail.trigger_source is None
    assert detail.requested_by is None


def test_active_job_only_marks_in_progress() -> None:
    snap = make_snap(
        estado_proceso="FINALIZADO",
        historical_file_path="h.xlsx",
    )
    job = JobReadResult(
        job_id="n1",
        store="sharepoint_memory",
        payload={
            "type": "notify_validar_extractos",
            "status": "running",
            "started_at": "2026-07-29T12:00:00-05:00",
        },
    )
    detail = PaymentProcessProjectionService().project(
        ProjectionSources(snapshot=snap, active_job=job)
    )
    by = {s.name: s for s in detail.steps}
    assert by["notify"].status == "in_progress"
    assert detail.active_job is not None
    assert detail.active_job.store == "sharepoint_memory"
    assert detail.active_job.poll_path_ui == "/api/ui/v1/jobs/n1"


def test_legacy_compatible_without_trigger_fields() -> None:
    snap = make_snap()
    detail = PaymentProcessProjectionService().project(ProjectionSources(snapshot=snap))
    dumped = detail.model_dump()
    assert "trigger_source" in dumped
    assert dumped["trigger_source"] is None
    assert dumped["requested_by"] is None
