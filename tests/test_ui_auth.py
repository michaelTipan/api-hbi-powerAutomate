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
    assert body["display_label"] == "SANDBOX / PRUEBAS"
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
    assert "entra_spa_client_id" in body
    assert "GRAPH_" not in json.dumps(body)