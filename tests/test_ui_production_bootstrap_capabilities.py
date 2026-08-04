"""Bootstrap/capabilities en production: respetan UI_*_ENABLED (no hard-sandbox)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.adapters.primary.http.ui.router_v1 import reset_ui_router_test_hooks
from app.application.ui.feature_flags import reset_ui_fail_closed_log_for_tests
from app.application.ui.login_rate_limit import reset_login_rate_limiter_for_tests
from app.application.ui.password_hash import hash_password
from app.application.ui.session_repository import (
    InMemorySessionRepository,
    set_session_repository_for_tests,
)
from tests.ui_test_app import create_ui_test_app

ORIGIN = "https://testserver"


def _enable_local_session(
    monkeypatch: pytest.MonkeyPatch,
    *,
    environment: str,
    write_enabled: bool = True,
    finalize: bool = True,
    notify: bool = True,
    merge: bool = True,
    amortization: bool = True,
) -> None:
    monkeypatch.setenv("UI_ENABLED", "true")
    monkeypatch.setenv("UI_WRITE_ENABLED", "true" if write_enabled else "false")
    monkeypatch.setenv("UI_FINALIZE_ENABLED", "true" if finalize else "false")
    monkeypatch.setenv("UI_NOTIFY_ENABLED", "true" if notify else "false")
    monkeypatch.setenv("UI_MERGE_ENABLED", "true" if merge else "false")
    monkeypatch.setenv("UI_AMORTIZATION_ENABLED", "true" if amortization else "false")
    monkeypatch.setenv("UI_AUTH_MODE", "local_session")
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", environment)
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
    yield
    reset_login_rate_limiter_for_tests()
    set_session_repository_for_tests(None)


def test_production_bootstrap_exposes_action_flags_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """production-ui-enabled: finalize/notify/merge/amortization_allowed siguen a flags."""
    _enable_local_session(monkeypatch, environment="production")
    client = TestClient(create_ui_test_app(), base_url=ORIGIN)
    res = client.get("/api/ui/v1/bootstrap", headers={"Origin": ORIGIN})
    assert res.status_code == 200
    body = res.json()
    assert body["active_environment"] == "production"
    assert body["writes_allowed"] is True
    assert body["finalize_allowed"] is True
    assert body["notify_allowed"] is True
    assert body["merge_allowed"] is True
    assert body["amortization_allowed"] is True


def test_production_bootstrap_fail_closed_when_write_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """UI_WRITE_ENABLED=false apaga acciones aunque los flags de acción estén on."""
    _enable_local_session(monkeypatch, environment="production", write_enabled=False)
    client = TestClient(create_ui_test_app(), base_url=ORIGIN)
    res = client.get("/api/ui/v1/bootstrap", headers={"Origin": ORIGIN})
    assert res.status_code == 200
    body = res.json()
    assert body["active_environment"] == "production"
    assert body["writes_allowed"] is False
    assert body["finalize_allowed"] is False
    assert body["notify_allowed"] is False
    assert body["merge_allowed"] is False
    assert body["amortization_allowed"] is False


def test_unknown_environment_bootstrap_fail_closed_actions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ambiente desconocido: sin escrituras UI aunque flags digan true."""
    _enable_local_session(monkeypatch, environment="staging")
    client = TestClient(create_ui_test_app(), base_url=ORIGIN)
    # local_session + UI fuera de sandbox|production → fail-closed (UI apagada).
    res = client.get("/api/ui/v1/bootstrap", headers={"Origin": ORIGIN})
    assert res.status_code in {404, 403, 200}
    if res.status_code == 200:
        body = res.json()
        assert body["finalize_allowed"] is False
        assert body["notify_allowed"] is False
        assert body["merge_allowed"] is False
        assert body["amortization_allowed"] is False


def test_production_banks_generate_respects_write_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET /banks: generate no queda AND-gated solo a sandbox."""
    _enable_local_session(monkeypatch, environment="production")
    client = TestClient(create_ui_test_app(), base_url=ORIGIN)
    login = client.post(
        "/api/ui/v1/auth/login",
        json={"username": "operator", "password": "CorrectHorseBattery!"},
        headers={"Origin": ORIGIN},
    )
    assert login.status_code == 200
    res = client.get("/api/ui/v1/banks", headers={"Origin": ORIGIN})
    assert res.status_code == 200
    banks = res.json()
    assert isinstance(banks, list) and banks
    generate = banks[0]["available_actions"]["generate"]
    reason = (generate.get("reason") or "").lower()
    assert "no está permitido en este ambiente" not in reason
    assert generate["allowed"] is True
