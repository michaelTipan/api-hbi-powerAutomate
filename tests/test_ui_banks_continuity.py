"""GET /banks con Control: Retomar vs Iniciar (continuidad R3.3)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.adapters.primary.http.deps import init_graph_client
from app.adapters.primary.http.ui.router_v1 import (
    configure_ui_router_for_tests,
    reset_ui_router_test_hooks,
)
from app.application.ui.path_guard import UiAllowedRoots
from tests.fakes.ui_sharepoint_fake import FakeUiSharePointRead, make_fake_control
from tests.ui_fixtures import make_snap
from tests.ui_test_app import create_ui_test_app

AUTH = {"Authorization": "Bearer mock-user"}
ROOT = "INFORMACION CREDITOS-CLIENTES/03 COMWARE PRUEBAS- INFORMACION CREDITOS CLIENTES"
CONTROL_PATH = (
    f"{ROOT}/02 VALIDACION PAGOS/90 ACCESO RESTRINGIDO/03 CONTROL TECNICO/control.xlsx"
)


class _MockGraph:
    async def get(self, *a, **k):
        return {}

    async def get_bytes(self, *a, **k):
        return b""


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("UI_ENABLED", "true")
    monkeypatch.setenv("UI_WRITE_ENABLED", "true")
    monkeypatch.setenv("UI_AUTH_MODE", "mock")
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "sandbox")
    init_graph_client(_MockGraph())  # type: ignore[arg-type]
    reset_ui_router_test_hooks()
    yield
    reset_ui_router_test_hooks()


def test_banks_resume_when_active_process() -> None:
    snap = make_snap(
        control_file_path=CONTROL_PATH,
        estado_proceso="PENDIENTE_ASIENTOS",
        historical_file_path=f"{ROOT}/02 VALIDACION PAGOS/03 HISTORICO/cartera.xlsx",
        notify_idempotency_key="pk-notify",
        email_pdf_path=f"{ROOT}/02 VALIDACION PAGOS/04 CORREOS ENVIADOS/mail.pdf",
        bank_code="banco_bancolombia",
    )
    fake = FakeUiSharePointRead(
        roots=UiAllowedRoots(environment="sandbox", roots=(ROOT,)),
        controls={
            "banco_bancolombia": make_fake_control(snap, notify_job_id="n1"),
            "banco_bogota": make_fake_control(
                make_snap(
                    control_file_path=CONTROL_PATH.replace("bancolombia", "bogota"),
                    estado_proceso="VACIO",
                    process_key="",
                    is_active=False,
                    bank_code="banco_bogota",
                    bank_name="Banco de Bogotá",
                    validation_file_path="",
                )
            ),
        },
    )
    configure_ui_router_for_tests(sharepoint_reader=fake)
    client = TestClient(create_ui_test_app())

    res = client.get("/api/ui/v1/banks", headers=AUTH)
    assert res.status_code == 200
    by_bank = {b["bank_code"]: b for b in res.json()}

    bc = by_bank["banco_bancolombia"]
    assert bc["dashboard_primary_action"] == "resume"
    assert bc["available_actions"]["generate"]["allowed"] is False
    assert bc["active_process_key"] == snap.process_key
    assert "validación activa" in (bc["available_actions"]["generate"]["reason"] or "").lower()
    assert "|" not in (bc["available_actions"]["generate"]["reason"] or "")

    bog = by_bank["banco_bogota"]
    assert bog["dashboard_primary_action"] == "generate"
    assert bog["available_actions"]["generate"]["allowed"] is True


def test_banks_generate_when_amortization_applied() -> None:
    """Tras COMPLETADO/AMORTIZACION_APLICADA el banco debe permitir un lote nuevo."""
    snap = make_snap(
        control_file_path=CONTROL_PATH,
        estado_proceso="AMORTIZACION_APLICADA",
        is_active=True,
        historical_file_path=f"{ROOT}/02 VALIDACION PAGOS/03 HISTORICO/cartera.xlsx",
        apply_idempotency_key="payment-validation|banco_bancolombia|2026-07-29|abc-123",
        bank_code="banco_bancolombia",
        validation_file_path="",
    )
    fake = FakeUiSharePointRead(
        roots=UiAllowedRoots(environment="sandbox", roots=(ROOT,)),
        controls={
            "banco_bancolombia": make_fake_control(snap),
            "banco_bogota": make_fake_control(
                make_snap(
                    control_file_path=CONTROL_PATH.replace("bancolombia", "bogota"),
                    estado_proceso="VACIO",
                    process_key="",
                    is_active=False,
                    bank_code="banco_bogota",
                    bank_name="Banco de Bogotá",
                    validation_file_path="",
                )
            ),
        },
    )
    configure_ui_router_for_tests(sharepoint_reader=fake)
    client = TestClient(create_ui_test_app())

    res = client.get("/api/ui/v1/banks", headers=AUTH)
    assert res.status_code == 200
    by_bank = {b["bank_code"]: b for b in res.json()}

    bc = by_bank["banco_bancolombia"]
    assert bc["dashboard_primary_action"] == "generate"
    assert bc["available_actions"]["generate"]["allowed"] is True
    assert bc["active_process_key"] is None
    assert bc["active_operational_status"] is None

    bog = by_bank["banco_bogota"]
    assert bog["dashboard_primary_action"] == "generate"
    assert bog["available_actions"]["generate"]["allowed"] is True


def test_banks_retry_read_when_control_unreadable() -> None:
    class Exploding(FakeUiSharePointRead):
        async def read_process_control(self, bank_code: str):
            raise RuntimeError("boom")

    configure_ui_router_for_tests(
        sharepoint_reader=Exploding(roots=UiAllowedRoots(environment="sandbox", roots=(ROOT,)))
    )
    client = TestClient(create_ui_test_app())
    res = client.get("/api/ui/v1/banks", headers=AUTH)
    assert res.status_code == 200
    for item in res.json():
        assert item["dashboard_primary_action"] == "retry_read"
        assert item["available_actions"]["generate"]["allowed"] is False
        assert item["control_readable"] is False
