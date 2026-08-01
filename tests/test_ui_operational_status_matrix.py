"""U4-RC: matriz EstadoProceso × jobs → operational_status conocido."""
from __future__ import annotations

import pytest

from app.application.ui.job_read import JobReadResult
from app.application.ui.process_projection import (
    PaymentProcessProjectionService,
    ProjectionSources,
    TechnicalJobEvidence,
    derive_operational_guidance,
    derive_operational_status,
    derive_steps_from_control,
)
from tests.ui_fixtures import make_snap


def _project(**snap_kwargs):
    snap = make_snap(**snap_kwargs)
    return PaymentProcessProjectionService().project(ProjectionSources(snapshot=snap))


def test_finalizado_sin_notify_no_es_desconocido() -> None:
    detail = _project(
        estado_proceso="FINALIZADO",
        historical_file_path="historico/cartera.xlsx",
        secretary_file_path="historico/Asientos.xlsx",
        notify_idempotency_key="",
        email_pdf_path="",
    )
    assert detail.operational_status == "PENDIENTE_NOTIFICACION"
    assert detail.operational_status != "DESCONOCIDO"
    assert detail.operational_status != "COMPLETADO"
    assert "ERROR" not in detail.operational_status
    assert detail.operational_message == "La revisión fue finalizada correctamente."
    assert any(a.code == "notify" for a in detail.next_actions)
    notify_action = next(a for a in detail.next_actions if a.code == "notify")
    assert notify_action.label == "Enviar validación."
    by = {s.name: s for s in detail.steps}
    assert by["finalize"].status == "completed"
    assert by["notify"].status == "not_started"


def test_finalizado_sin_notify_bucket_activos() -> None:
    """No debe clasificarse como completado ni error (bucket dashboard = activos)."""
    detail = _project(
        estado_proceso="FINALIZADO",
        historical_file_path="historico/cartera.xlsx",
    )
    summary = PaymentProcessProjectionService().summarize(detail)
    assert summary.operational_status == "PENDIENTE_NOTIFICACION"
    assert summary.error_count == 0


@pytest.mark.parametrize(
    ("estado", "extra", "expected"),
    [
        ("VACIO", {}, "NUEVO"),
        ("", {}, "NUEVO"),
        ("REVISION_CREADA", {}, "EN_REVISION"),
        ("ERROR_GENERATE", {}, "ERROR_RECUPERABLE"),
        ("ERROR_FINALIZE", {"historical_file_path": ""}, "ERROR_RECUPERABLE"),
        (
            "FINALIZADO",
            {
                "historical_file_path": "h.xlsx",
                "notify_idempotency_key": "",
                "email_pdf_path": "",
            },
            "PENDIENTE_NOTIFICACION",
        ),
        ("ERROR_NOTIFY", {"historical_file_path": "h.xlsx"}, "ERROR_RECUPERABLE"),
        (
            "PENDIENTE_ASIENTOS",
            {
                "historical_file_path": "h.xlsx",
                "notify_idempotency_key": "pk",
                "email_pdf_path": "c.pdf",
                "secretary_file_path": "a.xlsx",
            },
            "ESPERANDO_SOPORTES",
        ),
        (
            "MERGE_PARCIAL",
            {
                "historical_file_path": "h.xlsx",
                "notify_idempotency_key": "pk",
                "email_pdf_path": "c.pdf",
                "merge_manifest_path": "m.json",
                "secretary_file_path": "a.xlsx",
            },
            "FINALIZADO_PARCIALMENTE",
        ),
        ("ERROR_MERGE", {"historical_file_path": "h.xlsx"}, "ERROR_RECUPERABLE"),
        (
            "CONSOLIDADO",
            {
                "historical_file_path": "h.xlsx",
                "notify_idempotency_key": "pk",
                "email_pdf_path": "c.pdf",
                "merge_manifest_path": "m.json",
                "merge_idempotency_key": "mk",
            },
            "LISTO_PARA_APLICAR",
        ),
        (
            "AMORTIZACION_PARCIAL",
            {
                "historical_file_path": "h.xlsx",
                "notify_idempotency_key": "pk",
                "email_pdf_path": "c.pdf",
                "merge_manifest_path": "m.json",
                "merge_idempotency_key": "mk",
            },
            "FINALIZADO_PARCIALMENTE",
        ),
        (
            "AMORTIZACION_APLICADA",
            {
                "historical_file_path": "h.xlsx",
                "notify_idempotency_key": "pk",
                "email_pdf_path": "c.pdf",
                "merge_manifest_path": "m.json",
                "merge_idempotency_key": "mk",
                "apply_idempotency_key": "ak",
            },
            "COMPLETADO",
        ),
        ("CANCELADO", {}, "CANCELADO"),
        ("GENERANDO", {}, "GENERANDO"),
        ("FINALIZANDO", {"validation_file_path": "r.xlsx"}, "FINALIZANDO"),
        ("NOTIFICANDO", {"historical_file_path": "h.xlsx"}, "NOTIFICANDO"),
        ("CONSOLIDANDO", {"historical_file_path": "h.xlsx"}, "CONSOLIDANDO"),
        (
            "APLICANDO_AMORTIZACION",
            {
                "historical_file_path": "h.xlsx",
                "notify_idempotency_key": "pk",
                "email_pdf_path": "c.pdf",
                "merge_manifest_path": "m.json",
                "merge_idempotency_key": "mk",
            },
            "APLICANDO",
        ),
    ],
)
def test_known_control_estados_map_to_known_operational(
    estado: str, extra: dict, expected: str
) -> None:
    kwargs = {"estado_proceso": estado, **extra}
    detail = _project(**kwargs)
    assert detail.operational_status == expected
    assert detail.operational_status != "DESCONOCIDO" or expected == "DESCONOCIDO"
    title, message, _ref = derive_operational_guidance(detail.operational_status)
    assert title
    assert message


def test_corrupt_estado_is_desconocido_with_reference() -> None:
    detail = _project(estado_proceso="ESTADO_IMPOSIBLE_XYZ")
    assert detail.operational_status == "DESCONOCIDO"
    assert detail.operational_message == "No se pudo determinar el estado del proceso."
    assert detail.technical_status_reference == "EstadoProceso=ESTADO_IMPOSIBLE_XYZ"


def test_active_notify_job_overrides_finalizado() -> None:
    snap = make_snap(estado_proceso="FINALIZADO", historical_file_path="h.xlsx")
    job = JobReadResult(
        job_id="n1",
        store="job_manager",
        payload={"type": "notify_validar_extractos", "status": "running"},
    )
    detail = PaymentProcessProjectionService().project(
        ProjectionSources(snapshot=snap, active_job=job)
    )
    assert detail.operational_status == "NOTIFICANDO"


def test_failed_finalize_on_revision_creada() -> None:
    snap = make_snap(estado_proceso="REVISION_CREADA", process_key="pk-1")
    job = JobReadResult(
        job_id="f1",
        store="job_manager",
        payload={
            "type": "finalize",
            "status": "failed",
            "error": {
                "error_code": "invalid_estado_pago",
                "user_message": "Estado inválido",
                "severity": "warning",
                "message": "invalid_estado_pago",
            },
        },
    )
    evidence = TechnicalJobEvidence(job_manager_by_type={"finalize": job})
    steps = derive_steps_from_control(snap, jobs=evidence)
    assert derive_operational_status(snap, steps) == "CORRECCION_REQUERIDA"
