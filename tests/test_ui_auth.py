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


def test_entra_audience_check(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UI_ENABLED", "true")
    monkeypatch.setenv("UI_AUTH_MODE", "entra")
    monkeypatch.setenv("UI_ENTRA_AUDIENCE", "api://hbi-ui")
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "sandbox")
    client = TestClient(create_ui_test_app())
    bad = _jwt({"sub": "u1", "aud": "other", "tid": "t1", "oid": "o1"})
    res = client.get("/api/ui/v1/environment", headers={"Authorization": f"Bearer {bad}"})
    assert res.status_code == 401
    assert res.json()["error_code"] == "invalid_audience"

    good = _jwt({"sub": "u1", "aud": "api://hbi-ui", "tid": "t1", "oid": "o1", "name": "Op"})
    res2 = client.get("/api/ui/v1/environment", headers={"Authorization": f"Bearer {good}"})
    assert res2.status_code == 200
