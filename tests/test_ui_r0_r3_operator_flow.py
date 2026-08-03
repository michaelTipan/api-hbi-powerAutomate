"""Flujo local operador R0–R3 (TestClient, sin Azure).

Cadena: GET review → PATCH guardar → preflight → Finalize atómico → upload asiento.
Generate/Notify/Merge clásicos ya tienen suites propias; aquí se valida el cableado nuevo.
"""
from __future__ import annotations

import base64
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.adapters.primary.http.deps import init_graph_client
from app.adapters.primary.http.ui.router_v1 import (
    configure_ui_router_for_tests,
    reset_ui_router_test_hooks,
)
from app.application.services import finalize_queue_service as finalize_queue_module
from app.application.services.finalize_queue_service import (
    reset_finalize_queue_service_for_tests,
)
from app.application.ui.feature_flags import reset_ui_fail_closed_log_for_tests
from app.application.ui.login_rate_limit import reset_login_rate_limiter_for_tests
from app.application.ui.path_guard import UiAllowedRoots
from app.application.ui.ports import UiDriveItemMeta
from app.application.ui.session_repository import (
    InMemorySessionRepository,
    set_session_repository_for_tests,
)
from tests.fakes.ui_sharepoint_fake import FakeUiSharePointRead, make_fake_control
from tests.test_ui_asientos_upload_r3 import (
    ASIENTOS_DIR,
    HIST_PATH,
    PROCESS_KEY as ASIENTOS_KEY,
    _Graph as AsientosGraph,
    _minimal_hist_bytes,
)
from tests.test_ui_review_edit_r1 import (
    ORIGIN,
    PROCESS_KEY,
    REVIEW_PATH,
    _MockGraph,
    _ready_reader,
)
from tests.ui_fixtures import make_snap
from tests.ui_test_app import create_ui_test_app

CONTROL_PATH = (
    "INFORMACION CREDITOS-CLIENTES/03 COMWARE PRUEBAS- INFORMACION CREDITOS CLIENTES"
    "/02 VALIDACION PAGOS/90 ACCESO RESTRINGIDO/03 CONTROL TECNICO/control.xlsx"
)
ROOT = (
    "INFORMACION CREDITOS-CLIENTES/03 COMWARE PRUEBAS- INFORMACION CREDITOS CLIENTES"
)


@pytest.fixture(autouse=True)
def _reset():
    reset_finalize_queue_service_for_tests()
    reset_ui_fail_closed_log_for_tests()
    reset_login_rate_limiter_for_tests()
    set_session_repository_for_tests(InMemorySessionRepository())
    yield
    reset_finalize_queue_service_for_tests()
    reset_ui_router_test_hooks()


def _login(client: TestClient) -> str:
    client.post(
        "/api/ui/v1/auth/login",
        json={"username": "operator", "password": "CorrectHorseBattery!"},
        headers={"Origin": ORIGIN},
    )
    return client.get("/api/ui/v1/auth/csrf", headers={"Origin": ORIGIN}).json()[
        "csrf_token"
    ]


def test_operator_flow_review_edit_preflight_finalize(monkeypatch: pytest.MonkeyPatch) -> None:
    """R0→R2: leer → editar → preflight → Finalize atómico."""
    from tests.test_ui_review_edit_r1 import _client, _fake_resolve_sp, _write_headers

    reader = _ready_reader()
    graph = _MockGraph(reader)
    monkeypatch.setenv("UI_FINALIZE_ENABLED", "true")
    client, csrf = _client(monkeypatch, reader, graph)
    monkeypatch.setattr(
        "app.application.ui.review_finalize.resolve_sharepoint_from_env",
        _fake_resolve_sp,
    )
    monkeypatch.setattr(
        "app.application.ui.review_finalize.collect_preflight_issues_from_workbook",
        lambda _wb: [],
    )
    monkeypatch.setattr(
        "app.application.ui.review_preflight.collect_preflight_issues_from_workbook",
        lambda _wb: [],
    )

    async def _fake_fin(graph, **k):
        return {"status": "ok", "process_key": PROCESS_KEY, "already_finalized": False}

    monkeypatch.setattr(finalize_queue_module, "finalize_payment_validation", _fake_fin)

    headers = _write_headers(csrf)

    # R0 — lectura
    r0 = client.get(f"/api/ui/v1/processes/{PROCESS_KEY}/review", headers={"Origin": ORIGIN})
    assert r0.status_code == 200, r0.text
    body0 = r0.json()
    assert body0["etag"]
    assert body0["pagos"]
    row_key = body0["pagos"][0]["row_key"]
    etag = body0["etag"]

    # R1 — guardar borrador
    patch = client.patch(
        f"/api/ui/v1/processes/{PROCESS_KEY}/review",
        json={
            "changes": [
                {
                    "row_key": row_key,
                    "fields": {"observacion": "flujo-local-r0-r3"},
                }
            ]
        },
        headers={**headers, "If-Match": etag},
    )
    assert patch.status_code == 200, patch.text
    etag2 = patch.json()["etag"]
    assert etag2
    assert len(graph.put_calls) >= 1

    # R1 — preflight
    pre = client.post(
        f"/api/ui/v1/processes/{PROCESS_KEY}/review/preflight",
        json={},
        headers=headers,
    )
    assert pre.status_code == 200, pre.text
    assert pre.json()["ok"] is True

    # R2 — Finalize atómico
    fin = client.post(
        f"/api/ui/v1/processes/{PROCESS_KEY}/review/finalize",
        json={"changes": []},
        headers={**headers, "If-Match": etag2},
    )
    assert fin.status_code == 202, fin.text
    assert fin.json()["job_id"]


def test_operator_flow_asientos_upload_after_pendiente(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R3: tras PENDIENTE_ASIENTOS, upload PDF sin path del cliente."""
    from app.application.ui.password_hash import hash_password

    encoded = hash_password("CorrectHorseBattery!")
    monkeypatch.setenv("UI_ENABLED", "true")
    monkeypatch.setenv("UI_WRITE_ENABLED", "true")
    monkeypatch.setenv("UI_ASIENTOS_UPLOAD_ENABLED", "true")
    monkeypatch.setenv("UI_AUTH_MODE", "local_session")
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "sandbox")
    monkeypatch.setenv("UI_LOCAL_USERNAME", "operator")
    monkeypatch.setenv("UI_LOCAL_PASSWORD_HASH", encoded)
    monkeypatch.setenv("UI_LOCAL_ROLE", "operator")
    monkeypatch.setenv("UI_SESSION_TTL_MINUTES", "480")
    monkeypatch.setenv("UI_SESSION_IDLE_MINUTES", "60")
    monkeypatch.setenv("UI_LOGIN_MAX_ATTEMPTS", "5")
    monkeypatch.setenv("UI_LOGIN_WINDOW_SECONDS", "900")
    monkeypatch.setenv("UI_COOKIE_SECURE", "true")
    monkeypatch.setenv("UI_COOKIE_HTTPONLY", "true")
    monkeypatch.setenv("UI_COOKIE_SAMESITE", "strict")
    monkeypatch.setenv("UI_ALLOWED_ORIGINS", ORIGIN)
    monkeypatch.setenv("GRAPH_CLIENTS_BASE_PATH", ROOT)
    monkeypatch.setenv(
        "PAYMENT_VALIDATION_BASE_FOLDER", f"{ROOT}/02 VALIDACION PAGOS"
    )

    snap = make_snap(
        control_file_path=CONTROL_PATH,
        historical_file_path=HIST_PATH,
        email_pdf_path=f"{ROOT}/email.pdf",
        validation_file_path=REVIEW_PATH,
        process_key=ASIENTOS_KEY,
        bank_code="banco_bogota",
        bank_name="Bogotá",
        estado_proceso="PENDIENTE_ASIENTOS",
        is_active=True,
    )
    reader = FakeUiSharePointRead(
        roots=UiAllowedRoots(environment="sandbox", roots=(ROOT,)),
        controls={"banco_bogota": make_fake_control(snap)},
        files={HIST_PATH: _minimal_hist_bytes()},
        metas={
            HIST_PATH: UiDriveItemMeta(
                path=HIST_PATH, name="h.xlsx", etag='"1"', exists=True
            )
        },
    )
    graph = AsientosGraph()
    init_graph_client(graph)  # type: ignore[arg-type]
    reset_ui_router_test_hooks()
    configure_ui_router_for_tests(sharepoint_reader=reader)
    monkeypatch.setattr(
        "app.application.ui.asientos_upload.resolve_sharepoint_from_env",
        AsyncMock(return_value={"site_id": "s", "drive_id": "d"}),
    )
    monkeypatch.setattr(
        "app.application.ui.asientos_upload._graph_download_by_path",
        AsyncMock(return_value=_minimal_hist_bytes()),
    )
    monkeypatch.setattr(
        "app.application.ui.asientos_upload._list_drive_folder_children",
        AsyncMock(return_value=[]),
    )
    row = {
        "id_pago": "pago-1",
        "cliente": "EQUINORTE",
        "credito_digits": "265",
        "ruta_asientos_cell": ASIENTOS_DIR,
        "tipo_aplicacion_original": "PAGO CUOTA",
    }
    monkeypatch.setattr(
        "app.application.ui.asientos_upload.read_validated_payment_rows",
        lambda *a, **k: [row],
    )
    monkeypatch.setattr(
        "app.application.ui.asientos_upload.read_validated_abono_rows",
        lambda *a, **k: [],
    )

    client = TestClient(create_ui_test_app(), base_url=ORIGIN)
    csrf = _login(client)
    res = client.post(
        f"/api/ui/v1/processes/{ASIENTOS_KEY}/asientos",
        json={
            "id_pago": "pago-1",
            "credito": "265",
            "tipo_aplicacion": "PAGO CUOTA",
            "content_base64": base64.b64encode(b"%PDF-1.4 flujo-local").decode(),
            "source_filename": "asiento.pdf",
        },
        headers={
            "Origin": ORIGIN,
            "X-CSRF-Token": csrf,
            "Content-Type": "application/json",
        },
    )
    assert res.status_code == 201, res.text
    assert res.json()["folder_path"] == ASIENTOS_DIR
    assert "265" in res.json()["filename"]
    assert len(graph.put_calls) == 1
