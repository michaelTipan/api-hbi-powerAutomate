"""available_actions.force_rebuild alineado con assess_ui_force_rebuild."""

from __future__ import annotations

import pytest

from app.application.ui.feature_flags import reset_ui_fail_closed_log_for_tests
from app.application.ui.merge_force_rebuild import (
    assess_ui_force_rebuild,
    compute_force_rebuild_availability,
)
from app.application.ui.process_projection import (
    PaymentProcessProjectionService,
    ProjectionSources,
)
from tests.ui_fixtures import make_snap


@pytest.fixture(autouse=True)
def _ui_writes_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UI_ENABLED", "true")
    monkeypatch.setenv("UI_WRITE_ENABLED", "true")
    monkeypatch.setenv("UI_MERGE_ENABLED", "true")
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "sandbox")
    monkeypatch.delenv("WEBSITE_INSTANCE_ID", raising=False)
    reset_ui_fail_closed_log_for_tests()

def test_assess_force_rebuild_consolidado_ok() -> None:
    snap = make_snap(
        estado_proceso="CONSOLIDADO",
        historical_file_path="historico/cartera.xlsx",
        email_pdf_path="correos/x.pdf",
        merge_idempotency_key="pk",
    )
    gate = assess_ui_force_rebuild(snap)
    assert gate.allowed is True


def test_assess_force_rebuild_parcial_sin_formato_bloqueado() -> None:
    snap = make_snap(
        estado_proceso="AMORTIZACION_PARCIAL",
        historical_file_path="historico/cartera.xlsx",
        email_pdf_path="correos/x.pdf",
        last_amortization_attempt_json='{"credits":[]}',
    )
    gate = assess_ui_force_rebuild(snap)
    assert gate.allowed is False
    assert gate.error_code == "force_rebuild_partial_blocked"


def test_compute_force_rebuild_respects_env_gates() -> None:
    snap = make_snap(
        estado_proceso="CONSOLIDADO",
        historical_file_path="historico/cartera.xlsx",
        email_pdf_path="correos/x.pdf",
        merge_idempotency_key="pk",
    )
    av = compute_force_rebuild_availability(
        write_allowed=False,
        merge_enabled=True,
        sandbox=True,
        mutation_active=False,
        snap=snap,
    )
    assert av.allowed is False
    assert "no permite hacer cambios" in (av.reason or "").lower()


def test_projection_exposes_force_rebuild_on_consolidado() -> None:
    snap = make_snap(
        estado_proceso="CONSOLIDADO",
        historical_file_path="historico/cartera.xlsx",
        email_pdf_path="correos/x.pdf",
        notify_idempotency_key="pk",
        merge_idempotency_key="pk",
        merge_manifest_path="trazabilidad/manifest.json",
        secretary_file_path="historico/Asientos.xlsx",
    )
    detail = PaymentProcessProjectionService().project(ProjectionSources(snapshot=snap))
    merge = detail.available_actions["merge"]
    force = detail.available_actions["force_rebuild"]
    assert merge.allowed is False
    assert force.allowed is True
    assert force.reason is None


def test_projection_force_rebuild_blocked_on_parcial_sin_formato() -> None:
    snap = make_snap(
        estado_proceso="AMORTIZACION_PARCIAL",
        historical_file_path="historico/cartera.xlsx",
        email_pdf_path="correos/x.pdf",
        notify_idempotency_key="pk",
        merge_idempotency_key="pk",
        merge_manifest_path="trazabilidad/manifest.json",
        secretary_file_path="historico/Asientos.xlsx",
        last_amortization_attempt_json='{"credits":[]}',
    )
    detail = PaymentProcessProjectionService().project(ProjectionSources(snapshot=snap))
    force = detail.available_actions["force_rebuild"]
    assert force.allowed is False
    assert force.reason
    assert "parcial" in force.reason.lower()
