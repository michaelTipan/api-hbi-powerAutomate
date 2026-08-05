"""Tests U3-C2: Merge desde UI (capa API; sin SPA)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.adapters.primary.http.deps import init_graph_client
from app.adapters.primary.http.ui.router_v1 import (
    configure_ui_router_for_tests,
    reset_ui_router_test_hooks,
)
from app.application.job_manager import get_job_manager
from app.application.services import merge_queue_service as merge_queue_module
from app.application.services.generate_queue_service import reset_generate_queue_service_for_tests
from app.application.services.merge_queue_service import (
    MergeQueueAccepted,
    reset_merge_queue_service_for_tests,
)
from app.application.ui.feature_flags import (
    get_ui_feature_flags,
    reset_ui_fail_closed_log_for_tests,
)
from app.application.ui.login_rate_limit import reset_login_rate_limiter_for_tests
from app.application.ui.merge_readiness import MergeReadiness
from app.application.ui.password_hash import hash_password
from app.application.ui.session_repository import (
    InMemorySessionRepository,
    set_session_repository_for_tests,
)
from tests.ui_fixtures import make_snap
from tests.ui_test_app import create_ui_test_app

ORIGIN = "https://testserver"
PROCESS_KEY = "payment-validation|banco_bogota|2026-07-30|merge-test"


class _MockGraph:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def get(self, *args: object, **kwargs: object) -> dict[str, object]:
        self.calls.append("get")
        return {}

    async def get_bytes(self, *args: object, **kwargs: object) -> bytes:
        self.calls.append("get_bytes")
        return b""

    async def put_bytes(self, *args: object, **kwargs: object) -> dict[str, object]:
        self.calls.append("put_bytes")
        return {}

    async def post_json(
        self, *args: object, **kwargs: object
    ) -> tuple[dict[str, object], int]:
        self.calls.append("post_json")
        return {}, 202


def _enable_local(
    monkeypatch: pytest.MonkeyPatch,
    *,
    merge_enabled: bool = True,
) -> None:
    monkeypatch.setenv("UI_ENABLED", "true")
    monkeypatch.setenv("UI_WRITE_ENABLED", "true")
    monkeypatch.setenv("UI_MERGE_ENABLED", "true" if merge_enabled else "false")
    monkeypatch.setenv("UI_AUTH_MODE", "local_session")
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "sandbox")
    monkeypatch.setenv("UI_LOCAL_USERNAME", "operator")
    monkeypatch.setenv("UI_LOCAL_PASSWORD_HASH", hash_password("CorrectHorseBattery!"))
    monkeypatch.setenv("UI_LOCAL_ROLE", "operator")
    monkeypatch.setenv("UI_SESSION_TTL_MINUTES", "480")
    monkeypatch.setenv("UI_SESSION_IDLE_MINUTES", "60")
    monkeypatch.setenv("UI_LOGIN_MAX_ATTEMPTS", "5")
    monkeypatch.setenv("UI_LOGIN_WINDOW_SECONDS", "900")
    monkeypatch.setenv("UI_COOKIE_SECURE", "true")
    monkeypatch.setenv("UI_COOKIE_HTTPONLY", "true")
    monkeypatch.setenv("UI_COOKIE_SAMESITE", "strict")
    monkeypatch.setenv("UI_ALLOWED_ORIGINS", ORIGIN)
    monkeypatch.delenv("WEBSITE_INSTANCE_ID", raising=False)
    monkeypatch.delenv("WEBSITE_SITE_NAME", raising=False)


@pytest.fixture(autouse=True)
def _cleanup() -> None:
    reset_ui_router_test_hooks()
    reset_ui_fail_closed_log_for_tests()
    reset_login_rate_limiter_for_tests()
    set_session_repository_for_tests(InMemorySessionRepository())
    reset_generate_queue_service_for_tests()
    reset_merge_queue_service_for_tests()
    jm = get_job_manager()
    jm._validation_jobs.clear()
    jm._generate_active = False
    jm._finalize_active = False
    jm._notify_active = False
    jm._merge_active = False
    try:
        if jm._jobs_dir.is_dir():
            for path in jm._jobs_dir.glob("*.json"):
                path.unlink(missing_ok=True)
    except OSError:
        pass
    init_graph_client(_MockGraph())  # type: ignore[arg-type]
    yield
    reset_login_rate_limiter_for_tests()
    set_session_repository_for_tests(None)
    reset_generate_queue_service_for_tests()
    reset_merge_queue_service_for_tests()
    jm._validation_jobs.clear()
    jm._generate_active = False
    jm._finalize_active = False
    jm._notify_active = False
    jm._merge_active = False


def _ready_snap(**overrides: object):
    base = {
        "bank_code": "banco_bogota",
        "bank_name": "Banco de Bogotá",
        "process_key": PROCESS_KEY,
        "process_id": "merge-test",
        "estado_proceso": "PENDIENTE_ASIENTOS",
        "is_active": True,
        "historical_file_path": "02 HISTORICO/historico_banco_bogota.xlsx",
        "email_pdf_path": "04 CORREOS ENVIADOS/correo.pdf",
    }
    base.update(overrides)
    return make_snap(**base)


def _client_with_session(
    monkeypatch: pytest.MonkeyPatch,
    *,
    merge_enabled: bool = True,
    snap=None,
) -> tuple[TestClient, str]:
    _enable_local(monkeypatch, merge_enabled=merge_enabled)
    configure_ui_router_for_tests(control_loader=lambda _bc: snap or _ready_snap())
    client = TestClient(create_ui_test_app(), base_url=ORIGIN)
    login = client.post(
        "/api/ui/v1/auth/login",
        json={"username": "operator", "password": "CorrectHorseBattery!"},
        headers={"Origin": ORIGIN},
    )
    assert login.status_code == 200, login.text
    csrf = client.get("/api/ui/v1/auth/csrf", headers={"Origin": ORIGIN}).json()[
        "csrf_token"
    ]
    return client, csrf


def _headers(csrf: str, *, origin: str = ORIGIN) -> dict[str, str]:
    return {
        "Origin": origin,
        "Content-Type": "application/json",
        "X-CSRF-Token": csrf,
    }


def _ready_readiness() -> MergeReadiness:
    return MergeReadiness(
        status="ready",
        expected_groups=1,
        ready_groups=1,
        missing_groups=0,
        checked_at="2026-07-31T00:00:00-05:00",
        user_message="Los asientos contables están listos para consolidar.",
        next_action="Puede generar el PDF consolidado desde la UI.",
    )


def test_merge_flag_absent_or_invalid_is_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UI_ENABLED", "true")
    monkeypatch.setenv("UI_WRITE_ENABLED", "true")
    monkeypatch.setenv("UI_AUTH_MODE", "mock")
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "sandbox")
    monkeypatch.delenv("UI_MERGE_ENABLED", raising=False)
    assert get_ui_feature_flags().ui_merge_enabled is False
    monkeypatch.setenv("UI_MERGE_ENABLED", "invalid")
    assert get_ui_feature_flags().ui_merge_enabled is False


def test_merge_flag_false_blocks_before_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = _MockGraph()
    init_graph_client(graph)  # type: ignore[arg-type]
    called: list[str] = []

    async def _no_enqueue(*_a: object, **_k: object) -> MergeQueueAccepted:
        called.append("enqueue")
        raise AssertionError("enqueue no debe ejecutarse con flag false")

    monkeypatch.setattr(
        merge_queue_module.MergeQueueService, "enqueue", _no_enqueue
    )
    client, csrf = _client_with_session(monkeypatch, merge_enabled=False)
    jm = get_job_manager()
    res = client.post(
        "/api/ui/v1/processes/merge",
        json={"bank_code": "banco_bogota", "process_key": PROCESS_KEY},
        headers=_headers(csrf),
    )
    assert res.status_code == 403
    assert res.json()["detail"]["error_code"] == "ui_merge_disabled"
    assert not called
    assert not jm.is_merge_active()
    assert not jm._validation_jobs


def test_merge_already_merged_returns_409(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _ready(*_a: object, **_k: object) -> MergeReadiness:
        return _ready_readiness()

    monkeypatch.setattr(
        "app.adapters.primary.http.ui.router_v1.assess_merge_readiness", _ready
    )
    snap = _ready_snap(
        estado_proceso="CONSOLIDADO",
        merge_idempotency_key=PROCESS_KEY,
        merge_manifest_path="01 TRAZABILIDAD/merge_manifest.json",
    )
    client, csrf = _client_with_session(monkeypatch, snap=snap)
    res = client.post(
        "/api/ui/v1/processes/merge",
        json={"bank_code": "banco_bogota", "process_key": PROCESS_KEY},
        headers=_headers(csrf),
    )
    assert res.status_code == 409
    assert res.json()["detail"]["error_code"] == "already_merged"


def test_merge_busy_returns_409(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _ready(*_a: object, **_k: object) -> MergeReadiness:
        return _ready_readiness()

    monkeypatch.setattr(
        "app.adapters.primary.http.ui.router_v1.assess_merge_readiness", _ready
    )
    client, csrf = _client_with_session(monkeypatch)
    jm = get_job_manager()
    jm._generate_active = True
    res = client.post(
        "/api/ui/v1/processes/merge",
        json={"bank_code": "banco_bogota", "process_key": PROCESS_KEY},
        headers=_headers(csrf),
    )
    assert res.status_code == 409
    assert res.json()["detail"]["error_code"] == "merge_busy"


def test_merge_schema_rejects_extra_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    client, csrf = _client_with_session(monkeypatch)
    res = client.post(
        "/api/ui/v1/processes/merge",
        json={
            "bank_code": "banco_bogota",
            "process_key": PROCESS_KEY,
            "historical_file_path": "x/y.xlsx",
        },
        headers=_headers(csrf),
    )
    assert res.status_code == 422


def test_merge_force_rebuild_happy_path_when_consolidado(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def _ready(*_a: object, **_k: object) -> MergeReadiness:
        return MergeReadiness(
            status="already_merged",
            expected_groups=1,
            ready_groups=1,
            missing_groups=0,
            missing_items=[],
            folder_links=[],
            checked_at="2026-08-04T12:00:00Z",
            user_message="Ya consolidado.",
            next_action="",
        )

    async def _fake_enqueue(self: object, **kwargs: object) -> MergeQueueAccepted:
        captured.update(kwargs)
        return MergeQueueAccepted(
            job_id="merge-rebuild-1",
            bank_code="banco_bogota",
            process_key=PROCESS_KEY,
            status="queued",
        )

    monkeypatch.setattr(
        "app.adapters.primary.http.ui.router_v1.assess_merge_readiness", _ready
    )
    monkeypatch.setattr(
        merge_queue_module.MergeQueueService, "enqueue", _fake_enqueue
    )
    snap = _ready_snap(
        estado_proceso="CONSOLIDADO",
        merge_idempotency_key="merge-key-1",
        merge_manifest_path="04 CONSOLIDADO/manifest.json",
    )
    client, csrf = _client_with_session(monkeypatch, snap=snap)
    res = client.post(
        "/api/ui/v1/processes/merge",
        json={
            "bank_code": "banco_bogota",
            "process_key": PROCESS_KEY,
            "force_rebuild": True,
        },
        headers=_headers(csrf),
    )
    assert res.status_code == 202, res.text
    assert captured.get("force_rebuild") is True
    assert captured.get("ui_mode") is True


def test_merge_force_rebuild_blocked_on_amortizacion_parcial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snap = _ready_snap(estado_proceso="AMORTIZACION_PARCIAL")
    client, csrf = _client_with_session(monkeypatch, snap=snap)
    res = client.post(
        "/api/ui/v1/processes/merge",
        json={
            "bank_code": "banco_bogota",
            "process_key": PROCESS_KEY,
            "force_rebuild": True,
        },
        headers=_headers(csrf),
    )
    assert res.status_code == 409
    detail = res.json()["detail"]
    assert detail["error_code"] == "force_rebuild_partial_blocked"
    assert "parcial" in detail["user_message"].lower()


def test_merge_happy_path_enqueue_mocked(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def _ready(*_a: object, **_k: object) -> MergeReadiness:
        return _ready_readiness()

    async def _fake_enqueue(self: object, **kwargs: object) -> MergeQueueAccepted:
        captured.update(kwargs)
        return MergeQueueAccepted(
            job_id="merge-job-1",
            bank_code="banco_bogota",
            process_key=PROCESS_KEY,
            status="queued",
        )

    monkeypatch.setattr(
        "app.adapters.primary.http.ui.router_v1.assess_merge_readiness", _ready
    )
    monkeypatch.setattr(
        merge_queue_module.MergeQueueService, "enqueue", _fake_enqueue
    )
    client, csrf = _client_with_session(monkeypatch)
    res = client.post(
        "/api/ui/v1/processes/merge",
        json={"bank_code": "banco_bogota", "process_key": PROCESS_KEY},
        headers=_headers(csrf),
    )
    assert res.status_code == 202, res.text
    body = res.json()
    assert body["accepted"] is True
    assert body["action"] == "merge"
    assert body["job_id"] == "merge-job-1"
    assert body["process_key"] == PROCESS_KEY
    assert body["poll_url"] == "/api/ui/v1/jobs/merge-job-1"
    assert captured.get("ui_mode") is True
    assert captured.get("force_rebuild") is False
    assert captured.get("historical_file_path") == (
        "02 HISTORICO/historico_banco_bogota.xlsx"
    )
    assert captured.get("email_pdf_path") == "04 CORREOS ENVIADOS/correo.pdf"


def test_bootstrap_exposes_merge_allowed_false_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_local(monkeypatch, merge_enabled=False)
    client = TestClient(create_ui_test_app(), base_url=ORIGIN)
    res = client.get("/api/ui/v1/bootstrap", headers={"Origin": ORIGIN})
    assert res.status_code == 200
    assert res.json()["merge_allowed"] is False
