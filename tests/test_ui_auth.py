from __future__ import annotations

import base64
import json

import pytest
from fastapi.testclient import TestClient

from app.adapters.primary.http.ui.router_v1 import reset_ui_router_test_hooks
from tests.ui_test_app import create_ui_test_app


def _jwt(payload: dict) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').decode().rstrip("=")
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"{header}.{body}.x"


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_ui_router_test_hooks()


def test_mock_bearer_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UI_ENABLED", "true")
    monkeypatch.setenv("UI_AUTH_MODE", "mock")
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "sandbox")
    client = TestClient(create_ui_test_app())
    res = client.get(
        "/api/ui/v1/environment",
        headers={"Authorization": "Bearer mock-user"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["environment"] == "sandbox"
    assert body["display_label"] == "Entorno de validación"
    assert body["ui_write_enabled"] is False


def test_missing_bearer_401(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UI_ENABLED", "true")
    monkeypatch.setenv("UI_AUTH_MODE", "mock")
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "sandbox")
    client = TestClient(create_ui_test_app())
    res = client.get("/api/ui/v1/environment")
    assert res.status_code == 401
    assert res.json()["error_code"] == "missing_bearer"


def test_ui_disabled_404(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UI_ENABLED", "false")
    monkeypatch.setenv("UI_AUTH_MODE", "mock")
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "sandbox")
    client = TestClient(create_ui_test_app())
    res = client.get(
        "/api/ui/v1/environment",
        headers={"Authorization": "Bearer mock-user"},
    )
    assert res.status_code == 404
    assert res.json()["error_code"] == "ui_disabled"


def test_production_mock_fail_closed_blocks_routes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("UI_ENABLED", "true")
    monkeypatch.setenv("UI_AUTH_MODE", "mock")
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "production")
    client = TestClient(create_ui_test_app())
    res = client.get(
        "/api/ui/v1/environment",
        headers={"Authorization": "Bearer mock-user"},
    )
    assert res.status_code == 404
    assert res.json()["error_code"] == "ui_misconfigured_fail_closed"


def test_mock_never_authenticates_production(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi import HTTPException

    from app.adapters.primary.http.ui.auth import authenticate_mock

    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "production")
    with pytest.raises(HTTPException) as exc:
        authenticate_mock("mock-user")
    assert exc.value.status_code == 401
    assert exc.value.detail["error_code"] == "mock_forbidden_in_production"


def test_entra_requires_jwks_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sin JWKS/fake, un JWT sin firma real no autentica (fail-closed)."""
    from app.application.ui.entra_jwt import (
        reset_jwks_clients_for_tests,
        set_jwks_client_factory_for_tests,
    )
    from tests.ui_entra_jwt_helpers import install_entra_env, install_fake_jwks

    monkeypatch.setenv("UI_ENABLED", "true")
    monkeypatch.setenv("UI_AUTH_MODE", "entra")
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "sandbox")
    install_entra_env(monkeypatch)
    install_fake_jwks(fail=True)
    client = TestClient(create_ui_test_app())
    bad = _jwt({"sub": "u1", "aud": "api://hbi-ui", "tid": "t1", "oid": "o1"})
    res = client.get("/api/ui/v1/environment", headers={"Authorization": f"Bearer {bad}"})
    assert res.status_code == 401
    assert res.json()["error_code"] == "jwks_unavailable"
    reset_jwks_clients_for_tests()
    set_jwks_client_factory_for_tests(None)


def test_bootstrap_public_without_bearer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UI_ENABLED", "true")
    monkeypatch.setenv("UI_AUTH_MODE", "mock")
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "sandbox")
    client = TestClient(create_ui_test_app())
    res = client.get("/api/ui/v1/bootstrap")
    assert res.status_code == 200
    body = res.json()
    assert body["ui_enabled"] is True
    assert body["writes_allowed"] is False
    assert body["auth_mode"] == "mock"
    assert body.get("login_required") is False
    assert "GRAPH_" not in json.dumps(body)


def test_mock_me_and_generate_gate_accept_bearer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sandbox local: mock Bearer debe autenticar /me y pasar el write gate."""
    from app.adapters.primary.http.deps import init_graph_client
    from app.application.job_manager import JobManager
    from app.application.services.generate_queue_service import (
        reset_generate_queue_service_for_tests,
    )

    class _MockGraph:
        async def get(self, *a, **k):
            return {}

        async def get_bytes(self, *a, **k):
            return b""

        async def put_bytes(self, *a, **k):
            return {}

        async def delete(self, *a, **k):
            return None

        async def post_json(self, *a, **k):
            return {}, 202

    async def _fake_generate(graph, process_date, *, bank_code, job_id):
        return {
            "process_key": f"payment-validation|{bank_code}|mock",
            "status": "ok",
        }

    monkeypatch.setenv("UI_ENABLED", "true")
    monkeypatch.setenv("UI_WRITE_ENABLED", "true")
    monkeypatch.setenv("UI_AUTH_MODE", "mock")
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "sandbox")
    monkeypatch.setenv("UI_ALLOWED_ORIGINS", "http://localhost:5173")
    monkeypatch.delenv("WEBSITE_INSTANCE_ID", raising=False)
    monkeypatch.delenv("WEBSITE_SITE_NAME", raising=False)
    monkeypatch.setattr(
        "app.application.services.generate_queue_service.generate_payment_validation",
        _fake_generate,
    )
    reset_generate_queue_service_for_tests()
    jm = JobManager()
    jm._validation_jobs.clear()
    jm._generate_active = False
    init_graph_client(_MockGraph())  # type: ignore[arg-type]

    client = TestClient(create_ui_test_app())
    auth = {"Authorization": "Bearer mock-user"}
    me = client.get("/api/ui/v1/auth/me", headers=auth)
    assert me.status_code == 200, me.text
    assert me.json()["auth_mode"] == "mock"
    assert me.json()["authenticated"] is True

    gen = client.post(
        "/api/ui/v1/processes/generate",
        json={"bank_code": "banco_bancolombia"},
        headers={
            **auth,
            "Origin": "http://localhost:5173",
            "Content-Type": "application/json",
        },
    )
    assert gen.status_code == 202, gen.text
    assert gen.json()["accepted"] is True
    assert gen.json()["action"] == "generate"