"""R3: upload asientos — validación PDF, naming, path server-side."""
from __future__ import annotations

import base64
import io
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.adapters.primary.http.deps import init_graph_client
from app.adapters.primary.http.ui.router_v1 import (
    configure_ui_router_for_tests,
    reset_ui_router_test_hooks,
)
from app.application.services.review_schema import (
    DistribucionCols,
    ReviewSheets,
)
from app.application.ui.asientos_upload import (
    AsientosUploadError,
    build_asiento_filename,
    decode_pdf_base64,
)
from app.application.ui.feature_flags import reset_ui_fail_closed_log_for_tests
from app.application.ui.login_rate_limit import reset_login_rate_limiter_for_tests
from app.application.ui.password_hash import hash_password
from app.application.ui.path_guard import UiAllowedRoots
from app.application.ui.ports import UiDriveItemMeta
from app.application.ui.session_repository import (
    InMemorySessionRepository,
    set_session_repository_for_tests,
)
from tests.fakes.ui_sharepoint_fake import FakeUiSharePointRead, make_fake_control
from tests.ui_fixtures import make_snap
from tests.ui_test_app import create_ui_test_app

ORIGIN = "https://testserver"
ROOT = "INFORMACION CREDITOS-CLIENTES/03 COMWARE PRUEBAS- INFORMACION CREDITOS CLIENTES"
HIST_PATH = f"{ROOT}/02 VALIDACION PAGOS/03 HISTORICO/cartera_validada_demo.xlsx"
CONTROL_PATH = (
    f"{ROOT}/02 VALIDACION PAGOS/90 ACCESO RESTRINGIDO/03 CONTROL TECNICO/control.xlsx"
)
ASIENTOS_DIR = f"{ROOT}/CLIENTE DEMO/CREDITO 265/ASIENTOS CONTABLES CRED 265"
PROCESS_KEY = "payment-validation|banco_bogota|2026-07-30|bb40fcea-r3"


def test_decode_pdf_rejects_non_pdf() -> None:
    with pytest.raises(AsientosUploadError) as ei:
        decode_pdf_base64(base64.b64encode(b"not-a-pdf").decode())
    assert ei.value.code == "invalid_pdf"


def test_decode_pdf_ok() -> None:
    raw = b"%PDF-1.4 fake"
    out = decode_pdf_base64(base64.b64encode(raw).decode())
    assert out.startswith(b"%PDF")


def test_build_filename_contains_isolated_credit() -> None:
    name = build_asiento_filename(
        credito_digits="265",
        tipo_aplicacion="PAGO",
        cliente="EQUINORTE",
        process_date="2026-07-30",
        existing_names=[],
    )
    assert "CRED 265" in name
    assert name.lower().endswith(".pdf")
    # Colisión → sufijo evento
    name2 = build_asiento_filename(
        credito_digits="265",
        tipo_aplicacion="PAGO",
        cliente="EQUINORTE",
        process_date="2026-07-30",
        existing_names=[name],
    )
    assert "evento-2" in name2.casefold()


def _minimal_hist_bytes() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = ReviewSheets.DISTRIBUCION_PAGOS
    ws.append(["b"])
    ws.append(["b2"])
    headers = [
        DistribucionCols.ID_PAGO,
        DistribucionCols.CLIENTE,
        DistribucionCols.CREDITO,
        DistribucionCols.MONTO_BANCO,
        DistribucionCols.ESTADO_PAGO,
        DistribucionCols.VALIDAR_PAGO,
        DistribucionCols.RUTA_ASIENTOS_CONTABLES,
        DistribucionCols.TIPO_APLICACION_ORIGINAL,
    ]
    ws.append(headers)
    ws.append(
        [
            "pago-1",
            "EQUINORTE",
            "265",
            1000,
            "NORMAL",
            "SI",
            ASIENTOS_DIR,
            "PAGO CUOTA",
        ]
    )
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class _Graph:
    def __init__(self) -> None:
        self.put_calls: list[tuple[str, bytes]] = []
        self.children: list[dict] = []

    async def get(self, endpoint, *a, **k):
        if "/children" in endpoint:
            return {"value": self.children}
        return {}

    async def get_bytes(self, *a, **k):
        return _minimal_hist_bytes()

    async def put_bytes(self, endpoint, content, content_type=None):
        self.put_calls.append((endpoint, content))
        return {"webUrl": "https://sharepoint.example/asiento.pdf"}

    async def post_json(self, *a, **k):
        return {}, 201


def _enable(monkeypatch: pytest.MonkeyPatch, *, upload: bool = True) -> None:
    encoded = hash_password("CorrectHorseBattery!")
    monkeypatch.setenv("UI_ENABLED", "true")
    monkeypatch.setenv("UI_WRITE_ENABLED", "true")
    monkeypatch.setenv("UI_ASIENTOS_UPLOAD_ENABLED", "true" if upload else "false")
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
    monkeypatch.setenv("PAYMENT_VALIDATION_BASE_FOLDER", f"{ROOT}/02 VALIDACION PAGOS")
    reset_ui_fail_closed_log_for_tests()
    reset_login_rate_limiter_for_tests()
    set_session_repository_for_tests(InMemorySessionRepository())


def _reader(*, estado: str = "PENDIENTE_ASIENTOS") -> FakeUiSharePointRead:
    snap = make_snap(
        control_file_path=CONTROL_PATH,
        historical_file_path=HIST_PATH,
        email_pdf_path=f"{ROOT}/email.pdf",
        validation_file_path=f"{ROOT}/review.xlsx",
        process_key=PROCESS_KEY,
        bank_code="banco_bogota",
        bank_name="Bogotá",
        estado_proceso=estado,
        is_active=True,
    )
    return FakeUiSharePointRead(
        roots=UiAllowedRoots(environment="sandbox", roots=(ROOT,)),
        controls={"banco_bogota": make_fake_control(snap)},
        files={HIST_PATH: _minimal_hist_bytes()},
        metas={
            HIST_PATH: UiDriveItemMeta(
                path=HIST_PATH, name="h.xlsx", etag='"1"', exists=True
            )
        },
    )


def _login_csrf(client: TestClient) -> str:
    client.post(
        "/api/ui/v1/auth/login",
        json={"username": "operator", "password": "CorrectHorseBattery!"},
        headers={"Origin": ORIGIN},
    )
    return client.get("/api/ui/v1/auth/csrf", headers={"Origin": ORIGIN}).json()[
        "csrf_token"
    ]


def test_upload_flag_off_403(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable(monkeypatch, upload=False)
    init_graph_client(_Graph())  # type: ignore[arg-type]
    reset_ui_router_test_hooks()
    configure_ui_router_for_tests(sharepoint_reader=_reader())
    client = TestClient(create_ui_test_app(), base_url=ORIGIN)
    csrf = _login_csrf(client)
    res = client.post(
        f"/api/ui/v1/processes/{PROCESS_KEY}/asientos",
        json={
            "id_pago": "pago-1",
            "credito": "265",
            "content_base64": base64.b64encode(b"%PDF-1.4 x").decode(),
        },
        headers={
            "Origin": ORIGIN,
            "X-CSRF-Token": csrf,
            "Content-Type": "application/json",
        },
    )
    assert res.status_code == 403
    assert res.json()["detail"]["error_code"] == "ui_asientos_upload_disabled"


def test_upload_rejects_client_path_query(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable(monkeypatch, upload=True)
    init_graph_client(_Graph())  # type: ignore[arg-type]
    reset_ui_router_test_hooks()
    configure_ui_router_for_tests(sharepoint_reader=_reader())
    client = TestClient(create_ui_test_app(), base_url=ORIGIN)
    csrf = _login_csrf(client)
    res = client.post(
        f"/api/ui/v1/processes/{PROCESS_KEY}/asientos?path=/evil",
        json={
            "id_pago": "pago-1",
            "credito": "265",
            "content_base64": base64.b64encode(b"%PDF-1.4 x").decode(),
        },
        headers={
            "Origin": ORIGIN,
            "X-CSRF-Token": csrf,
            "Content-Type": "application/json",
        },
    )
    assert res.status_code == 400
    assert res.json()["detail"]["error_code"] == "client_path_forbidden"


def test_upload_wrong_control_state_409(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable(monkeypatch, upload=True)
    init_graph_client(_Graph())  # type: ignore[arg-type]
    reset_ui_router_test_hooks()
    configure_ui_router_for_tests(sharepoint_reader=_reader(estado="EN_REVISION"))
    client = TestClient(create_ui_test_app(), base_url=ORIGIN)
    csrf = _login_csrf(client)
    res = client.post(
        f"/api/ui/v1/processes/{PROCESS_KEY}/asientos",
        json={
            "id_pago": "pago-1",
            "credito": "265",
            "content_base64": base64.b64encode(b"%PDF-1.4 content").decode(),
        },
        headers={
            "Origin": ORIGIN,
            "X-CSRF-Token": csrf,
            "Content-Type": "application/json",
        },
    )
    assert res.status_code == 409
    assert res.json()["detail"]["error_code"] == "control_not_ready_for_asientos"


def test_upload_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable(monkeypatch, upload=True)
    graph = _Graph()
    init_graph_client(graph)  # type: ignore[arg-type]
    reset_ui_router_test_hooks()
    configure_ui_router_for_tests(sharepoint_reader=_reader())
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
    csrf = _login_csrf(client)
    # extra=forbid: path del cliente en body → 422
    res = client.post(
        f"/api/ui/v1/processes/{PROCESS_KEY}/asientos",
        json={
            "id_pago": "pago-1",
            "credito": "265",
            "tipo_aplicacion": "PAGO CUOTA",
            "content_base64": base64.b64encode(b"%PDF-1.4 content").decode(),
            "source_filename": "local.pdf",
            "path": "should-be-rejected-by-extra-forbid",
        },
        headers={
            "Origin": ORIGIN,
            "X-CSRF-Token": csrf,
            "Content-Type": "application/json",
        },
    )
    assert res.status_code == 422
    res2 = client.post(
        f"/api/ui/v1/processes/{PROCESS_KEY}/asientos",
        json={
            "id_pago": "pago-1",
            "credito": "265",
            "tipo_aplicacion": "PAGO CUOTA",
            "content_base64": base64.b64encode(b"%PDF-1.4 content").decode(),
            "source_filename": "local.pdf",
        },
        headers={
            "Origin": ORIGIN,
            "X-CSRF-Token": csrf,
            "Content-Type": "application/json",
        },
    )
    assert res2.status_code == 201, res2.text
    body = res2.json()
    assert body["credito"] == "265"
    assert "265" in body["filename"]
    assert body["folder_path"] == ASIENTOS_DIR
    assert len(graph.put_calls) == 1
    assert graph.put_calls[0][1].startswith(b"%PDF")
    # Path Graph incluye carpeta server-side, no path del cliente
    assert ASIENTOS_DIR.replace(" ", "%20") in graph.put_calls[0][0] or "ASIENTOS" in graph.put_calls[0][0]


def test_bootstrap_asientos_default_off(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable(monkeypatch, upload=False)
    init_graph_client(_Graph())  # type: ignore[arg-type]
    reset_ui_router_test_hooks()
    client = TestClient(create_ui_test_app(), base_url=ORIGIN)
    res = client.get("/api/ui/v1/bootstrap")
    assert res.status_code == 200
    assert res.json().get("asientos_upload_allowed") is False
