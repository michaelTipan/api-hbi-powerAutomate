"""Regresión U4-RC-R3.2: un NotifyJobId/MergeJobId en Control no debe romper la UI.

Bug observado en sandbox: ``read_sharepoint_memory_job`` accedía a
``sharepoint._validation_jobs`` (atributo retirado en la migración a JobManager)
fuera del ``try``. Con cualquier proceso que ya hubiera pasado por Notify o
Merge, la proyección lanzaba AttributeError y la UI mostraba lista vacía
(``items: []``) y 500 en el detalle, sin ninguna vía de recuperación.
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.adapters.primary.http.deps import init_graph_client
from app.adapters.primary.http.ui.router_v1 import (
    configure_ui_router_for_tests,
    reset_ui_router_test_hooks,
)
from app.application.ui.job_read import read_any_job, read_sharepoint_memory_job
from app.application.ui.path_guard import UiAllowedRoots
from app.application.ui.process_query import UiProcessQueryService
from tests.fakes.ui_sharepoint_fake import FakeUiSharePointRead, make_fake_control
from tests.ui_fixtures import make_snap
from tests.ui_test_app import create_ui_test_app

AUTH = {"Authorization": "Bearer mock-user"}
ROOT = "INFORMACION CREDITOS-CLIENTES/03 COMWARE PRUEBAS- INFORMACION CREDITOS CLIENTES"
CONTROL_PATH = (
    f"{ROOT}/02 VALIDACION PAGOS/90 ACCESO RESTRINGIDO/03 CONTROL TECNICO/control.xlsx"
)


class _MockGraph:
    """Graph inerte: el detalle depende de GraphClientDep aunque no lo use."""

    async def get(self, *a, **k):
        return {}

    async def get_bytes(self, *a, **k):
        return b""


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("UI_ENABLED", "true")
    monkeypatch.setenv("UI_WRITE_ENABLED", "false")
    monkeypatch.setenv("UI_AUTH_MODE", "mock")
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "sandbox")
    init_graph_client(_MockGraph())  # type: ignore[arg-type]
    reset_ui_router_test_hooks()
    yield
    reset_ui_router_test_hooks()


def _pending_asientos_snap():
    """Proceso que ya notificó: es el caso que rompía la proyección."""
    return make_snap(
        control_file_path=CONTROL_PATH,
        estado_proceso="PENDIENTE_ASIENTOS",
        historical_file_path=f"{ROOT}/02 VALIDACION PAGOS/03 HISTORICO/cartera.xlsx",
        notify_idempotency_key="pk-notify",
        email_pdf_path=f"{ROOT}/02 VALIDACION PAGOS/04 CORREOS ENVIADOS/mail.pdf",
    )


def _fake_reader(snap, **control_kwargs) -> FakeUiSharePointRead:
    return FakeUiSharePointRead(
        roots=UiAllowedRoots(environment="sandbox", roots=(ROOT,)),
        controls={"banco_bancolombia": make_fake_control(snap, **control_kwargs)},
    )


def test_legacy_memory_store_ausente_no_rompe_lectura(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.adapters.primary.http.routers import sharepoint as sp

    monkeypatch.delattr(sp, "_validation_jobs", raising=False)

    assert read_sharepoint_memory_job("notify-job-1") is None
    assert read_any_job("notify-job-1") is None


def test_lookup_inyectado_que_falla_no_rompe_lectura() -> None:
    def broken(_job_id: str) -> dict[str, object] | None:
        raise RuntimeError("store caído")

    assert read_sharepoint_memory_job("notify-job-1", lookup=broken) is None


def test_project_bank_con_notify_job_id_no_lanza(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.adapters.primary.http.routers import sharepoint as sp

    monkeypatch.delattr(sp, "_validation_jobs", raising=False)
    snap = _pending_asientos_snap()
    fake = _fake_reader(snap, notify_job_id="notify-job-1", merge_job_id="merge-job-1")

    detail = asyncio.run(UiProcessQueryService(fake).project_bank("banco_bancolombia"))

    assert detail.process_key == snap.process_key
    assert detail.control_estado_proceso == "PENDIENTE_ASIENTOS"


def test_lista_incluye_proceso_con_notify_job_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.adapters.primary.http.routers import sharepoint as sp

    monkeypatch.delattr(sp, "_validation_jobs", raising=False)
    snap = _pending_asientos_snap()
    configure_ui_router_for_tests(
        sharepoint_reader=_fake_reader(
            snap, notify_job_id="notify-job-1", merge_job_id="merge-job-1"
        )
    )
    client = TestClient(create_ui_test_app())

    listed = client.get(
        "/api/ui/v1/processes",
        headers=AUTH,
        params={"bank_code": "banco_bancolombia"},
    )

    assert listed.status_code == 200
    body = listed.json()
    assert [i["process_key"] for i in body["items"]] == [snap.process_key]
    assert body["unavailable_banks"] == []


def test_lista_reporta_banco_no_disponible_en_vez_de_silenciar() -> None:
    class ExplodingReader(FakeUiSharePointRead):
        async def read_process_control(self, bank_code: str):
            raise RuntimeError("control ilegible")

    configure_ui_router_for_tests(
        sharepoint_reader=ExplodingReader(
            roots=UiAllowedRoots(environment="sandbox", roots=(ROOT,))
        )
    )
    client = TestClient(create_ui_test_app())

    listed = client.get(
        "/api/ui/v1/processes",
        headers=AUTH,
        params={"bank_code": "banco_bancolombia"},
    )

    assert listed.status_code == 200
    body = listed.json()
    assert body["items"] == []
    assert body["unavailable_banks"] == ["banco_bancolombia"]


def test_detalle_ilegible_responde_503_con_mensaje() -> None:
    class ExplodingReader(FakeUiSharePointRead):
        async def read_process_control(self, bank_code: str):
            raise RuntimeError("control ilegible")

    configure_ui_router_for_tests(
        sharepoint_reader=ExplodingReader(
            roots=UiAllowedRoots(environment="sandbox", roots=(ROOT,))
        )
    )
    client = TestClient(create_ui_test_app(), raise_server_exceptions=False)

    res = client.get(
        "/api/ui/v1/processes/payment-validation|banco_bancolombia|2026-07-31|abc-123",
        headers=AUTH,
    )

    assert res.status_code == 503
    detail = res.json()["detail"]
    assert detail["error_code"] == "process_read_failed"
    assert detail["user_message"]
    assert detail["next_action"]
