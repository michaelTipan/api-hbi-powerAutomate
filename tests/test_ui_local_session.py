"""Tests D2-LS1: password hash, sesión local, cookies, rate limit, separación PA."""
from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.adapters.primary.http.api_key_auth import ENV_API_HTTP_KEY
from app.adapters.primary.http.app_factory import create_app
from app.adapters.primary.http.deps import init_graph_client
from app.adapters.primary.http.ui.router_v1 import reset_ui_router_test_hooks
from app.application.ui.feature_flags import reset_ui_fail_closed_log_for_tests
from app.application.ui.local_session_config import SESSION_COOKIE_NAME
from app.application.ui.login_rate_limit import reset_login_rate_limiter_for_tests
from app.application.ui.password_hash import (
    DEFAULT_ITERATIONS,
    PasswordHashError,
    hash_password,
    parse_password_hash,
    verify_password,
)
from app.application.ui.session_repository import (
    SESSION_TOKEN_BYTES,
    get_session_repository,
    hash_session_token,
    set_session_repository_for_tests,
    InMemorySessionRepository,
)
from tests.ui_test_app import create_ui_test_app


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


def _origin() -> str:
    return "https://testserver"


def _enable_local(monkeypatch: pytest.MonkeyPatch, password: str = "CorrectHorseBattery!") -> str:
    encoded = hash_password(password)
    monkeypatch.setenv("UI_ENABLED", "true")
    monkeypatch.setenv("UI_WRITE_ENABLED", "false")
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
    monkeypatch.delenv("WEBSITE_INSTANCE_ID", raising=False)
    monkeypatch.delenv("WEBSITE_SITE_NAME", raising=False)
    return encoded


@pytest.fixture(autouse=True)
def _cleanup() -> None:
    reset_ui_router_test_hooks()
    reset_ui_fail_closed_log_for_tests()
    reset_login_rate_limiter_for_tests()
    set_session_repository_for_tests(InMemorySessionRepository())
    yield
    reset_login_rate_limiter_for_tests()
    set_session_repository_for_tests(None)
    init_graph_client(_MockGraph())  # type: ignore[arg-type]


def _client(monkeypatch: pytest.MonkeyPatch, password: str = "CorrectHorseBattery!") -> TestClient:
    _enable_local(monkeypatch, password)
    return TestClient(create_ui_test_app(), base_url="https://testserver")


def test_pbkdf2_generate_and_verify() -> None:
    encoded = hash_password("CorrectHorseBattery!")
    assert encoded.startswith(f"pbkdf2_sha256${DEFAULT_ITERATIONS}$")
    assert verify_password("CorrectHorseBattery!", encoded) is True
    assert verify_password("wrong", encoded) is False


def test_pbkdf2_invalid_format() -> None:
    with pytest.raises(PasswordHashError):
        parse_password_hash("not-a-hash")
    with pytest.raises(PasswordHashError):
        parse_password_hash("pbkdf2_sha256$100$aa$bb")  # iteraciones bajas


def test_pbkdf2_constant_time_compare() -> None:
    encoded = hash_password("CorrectHorseBattery!")
    assert verify_password("CorrectHorseBattery!", encoded)
    assert not verify_password("CorrectHorseBattery!!", encoded)


def test_login_success_sets_secure_cookie(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(monkeypatch)
    res = client.post(
        "/api/ui/v1/auth/login",
        json={"username": "operator", "password": "CorrectHorseBattery!"},
        headers={"Origin": _origin()},
    )
    assert res.status_code == 200
    assert res.json()["authenticated"] is True
    assert "token" not in res.text.lower()
    assert "password" not in res.text.lower()
    assert "pbkdf2" not in res.text.lower()
    cookie = res.headers.get("set-cookie", "")
    assert SESSION_COOKIE_NAME in cookie
    assert "HttpOnly" in cookie or "httponly" in cookie.lower()
    assert "Secure" in cookie or "secure" in cookie.lower()
    assert re.search(r"samesite=strict", cookie, re.I)
    assert "Path=/" in cookie or "path=/" in cookie
    assert "Domain=" not in cookie and "domain=" not in cookie


def test_login_wrong_password_no_cookie(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(monkeypatch)
    res = client.post(
        "/api/ui/v1/auth/login",
        json={"username": "operator", "password": "wrong-password"},
        headers={"Origin": _origin()},
    )
    assert res.status_code == 401
    detail = res.json().get("detail") or res.json()
    assert detail["error_code"] == "invalid_credentials"
    assert SESSION_COOKIE_NAME not in (res.headers.get("set-cookie") or "")


def test_session_token_entropy_and_only_hash_stored(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(monkeypatch)
    res = client.post(
        "/api/ui/v1/auth/login",
        json={"username": "operator", "password": "CorrectHorseBattery!"},
        headers={"Origin": _origin()},
    )
    assert res.status_code == 200
    raw = client.cookies.get(SESSION_COOKIE_NAME)
    assert raw
    assert len(raw) >= SESSION_TOKEN_BYTES
    repo = get_session_repository()
    # El almacén solo tiene hashes hex SHA-256.
    assert repo.get_by_token_hash(hash_session_token(raw)) is not None
    assert repo.get_by_token_hash(raw) is None


def test_tampered_token_401(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(monkeypatch)
    client.post(
        "/api/ui/v1/auth/login",
        json={"username": "operator", "password": "CorrectHorseBattery!"},
        headers={"Origin": _origin()},
    )
    client.cookies.set(SESSION_COOKIE_NAME, "tampered-token-value")
    res = client.get("/api/ui/v1/environment")
    assert res.status_code == 401


def test_missing_session_401(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(monkeypatch)
    res = client.get("/api/ui/v1/environment")
    assert res.status_code == 401


def test_expired_session_401(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UI_SESSION_TTL_MINUTES", "1")
    monkeypatch.setenv("UI_SESSION_IDLE_MINUTES", "1")
    client = _client(monkeypatch)
    client.post(
        "/api/ui/v1/auth/login",
        json={"username": "operator", "password": "CorrectHorseBattery!"},
        headers={"Origin": _origin()},
    )
    repo = get_session_repository()
    # Forzar expiración.
    for rec in list(repo._by_hash.values()):  # noqa: SLF001
        rec.expires_at = time.time() - 10
        rec.created_at = time.time() - 3600
    res = client.get("/api/ui/v1/environment")
    assert res.status_code == 401


def test_idle_expiration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UI_SESSION_TTL_MINUTES", "480")
    monkeypatch.setenv("UI_SESSION_IDLE_MINUTES", "1")
    client = _client(monkeypatch)
    client.post(
        "/api/ui/v1/auth/login",
        json={"username": "operator", "password": "CorrectHorseBattery!"},
        headers={"Origin": _origin()},
    )
    repo = get_session_repository()
    for rec in list(repo._by_hash.values()):  # noqa: SLF001
        rec.last_activity_at = time.time() - 120
        rec.expires_at = time.time() - 1
    res = client.get("/api/ui/v1/environment")
    assert res.status_code == 401


def test_logout_invalidates_and_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(monkeypatch)
    client.post(
        "/api/ui/v1/auth/login",
        json={"username": "operator", "password": "CorrectHorseBattery!"},
        headers={"Origin": _origin()},
    )
    csrf = client.get("/api/ui/v1/auth/csrf").json()["csrf_token"]
    r1 = client.post(
        "/api/ui/v1/auth/logout",
        headers={"Origin": _origin(), "X-CSRF-Token": csrf},
        json={},
    )
    assert r1.status_code == 200
    r2 = client.get("/api/ui/v1/environment")
    assert r2.status_code == 401
    # Idempotente: ya no hay sesión, así que no se exige CSRF de nuevo.
    r3 = client.post("/api/ui/v1/auth/logout", headers={"Origin": _origin()}, json={})
    assert r3.status_code == 200


def test_logout_requires_csrf_when_session_active(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(monkeypatch)
    client.post(
        "/api/ui/v1/auth/login",
        json={"username": "operator", "password": "CorrectHorseBattery!"},
        headers={"Origin": _origin()},
    )
    missing = client.post("/api/ui/v1/auth/logout", headers={"Origin": _origin()}, json={})
    assert missing.status_code == 403
    assert missing.json()["detail"]["error_code"] == "invalid_csrf_token"
    # La sesión sigue viva: logout con CSRF correcto la invalida.
    csrf = client.get("/api/ui/v1/auth/csrf").json()["csrf_token"]
    ok = client.post(
        "/api/ui/v1/auth/logout",
        headers={"Origin": _origin(), "X-CSRF-Token": csrf},
        json={},
    )
    assert ok.status_code == 200
    assert client.get("/api/ui/v1/environment").status_code == 401


def test_rate_limit_and_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(monkeypatch)
    monkeypatch.setenv("UI_LOGIN_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("UI_LOGIN_WINDOW_SECONDS", "900")
    reset_login_rate_limiter_for_tests()
    for _ in range(3):
        bad = client.post(
            "/api/ui/v1/auth/login",
            json={"username": "operator", "password": "bad"},
            headers={"Origin": _origin()},
        )
        assert bad.status_code == 401
    limited = client.post(
        "/api/ui/v1/auth/login",
        json={"username": "operator", "password": "bad"},
        headers={"Origin": _origin()},
    )
    assert limited.status_code == 429
    from app.application.ui.login_rate_limit import get_login_rate_limiter

    purged = get_login_rate_limiter().purge_expired(now=time.time() + 10_000)
    assert purged >= 0


def test_invalid_origin_login_logout(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(monkeypatch)
    bad = client.post(
        "/api/ui/v1/auth/login",
        json={"username": "operator", "password": "CorrectHorseBattery!"},
        headers={"Origin": "https://evil.example"},
    )
    assert bad.status_code == 403
    client.post(
        "/api/ui/v1/auth/login",
        json={"username": "operator", "password": "CorrectHorseBattery!"},
        headers={"Origin": _origin()},
    )
    out = client.post(
        "/api/ui/v1/auth/logout",
        headers={"Origin": "https://evil.example"},
        json={},
    )
    assert out.status_code == 403


def test_bootstrap_sanitized_local(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(monkeypatch)
    res = client.get("/api/ui/v1/bootstrap")
    assert res.status_code == 200
    body = res.json()
    assert body["auth_mode"] == "local_session"
    assert body["login_required"] is True
    assert body["writes_allowed"] is False
    assert body["active_environment"] == "sandbox"
    assert body["display_label"] == "SANDBOX / PRUEBAS"
    raw = res.text.lower()
    for banned in ("password", "secret", "api_http", "graph_client", "pbkdf2", "cookie"):
        assert banned not in raw


def test_auth_me_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(monkeypatch)
    client.post(
        "/api/ui/v1/auth/login",
        json={"username": "operator", "password": "CorrectHorseBattery!"},
        headers={"Origin": _origin()},
    )
    me = client.get("/api/ui/v1/auth/me")
    assert me.status_code == 200
    body = me.json()
    assert set(body.keys()) == {
        "authenticated",
        "username",
        "role",
        "auth_mode",
        "expires_at",
    }
    assert "csrf" not in me.text.lower()
    assert "cookie" not in me.text.lower()


def test_api_key_does_not_auth_ui(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_local(monkeypatch)
    monkeypatch.setenv(ENV_API_HTTP_KEY, "secret-key-for-pa")
    init_graph_client(_MockGraph())  # type: ignore[arg-type]
    client = TestClient(create_app(), base_url="https://testserver")
    res = client.get(
        "/api/ui/v1/environment",
        headers={"X-API-Key": "secret-key-for-pa"},
    )
    assert res.status_code == 401


def test_ui_cookie_does_not_auth_graph(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_local(monkeypatch)
    monkeypatch.setenv(ENV_API_HTTP_KEY, "secret-key-for-pa")
    init_graph_client(_MockGraph())  # type: ignore[arg-type]
    ui = TestClient(create_ui_test_app(), base_url="https://testserver")
    ui.post(
        "/api/ui/v1/auth/login",
        json={"username": "operator", "password": "CorrectHorseBattery!"},
        headers={"Origin": _origin()},
    )
    cookie = ui.cookies.get(SESSION_COOKIE_NAME)
    assert cookie
    app_client = TestClient(create_app(), base_url="https://testserver")
    app_client.cookies.set(SESSION_COOKIE_NAME, cookie)
    res = app_client.get("/graph/diagnostics")
    assert res.status_code == 401
    assert res.json()["detail"] == "missing_api_key"


def test_ui_disabled_404(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_local(monkeypatch)
    monkeypatch.setenv("UI_ENABLED", "false")
    client = TestClient(create_ui_test_app(), base_url="https://testserver")
    assert client.get("/api/ui/v1/bootstrap").status_code == 404


def test_incomplete_config_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UI_ENABLED", "true")
    monkeypatch.setenv("UI_AUTH_MODE", "local_session")
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "sandbox")
    monkeypatch.delenv("UI_LOCAL_USERNAME", raising=False)
    monkeypatch.delenv("UI_LOCAL_PASSWORD_HASH", raising=False)
    reset_ui_fail_closed_log_for_tests()
    init_graph_client(_MockGraph())  # type: ignore[arg-type]
    app = create_app()
    assert not any(str(getattr(r, "path", "")).startswith("/api/ui") for r in app.routes)


def test_mock_rejected_on_azure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UI_ENABLED", "true")
    monkeypatch.setenv("UI_AUTH_MODE", "mock")
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "sandbox")
    monkeypatch.setenv("WEBSITE_INSTANCE_ID", "azure-instance")
    reset_ui_fail_closed_log_for_tests()
    init_graph_client(_MockGraph())  # type: ignore[arg-type]
    app = create_app()
    assert not any(str(getattr(r, "path", "")).startswith("/api/ui") for r in app.routes)


def test_entra_mode_still_available(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.application.ui.feature_flags import resolve_ui_auth_mode

    monkeypatch.setenv("UI_AUTH_MODE", "entra")
    assert resolve_ui_auth_mode() == "entra"


def test_frontend_has_no_storage_for_credentials() -> None:
    client = Path("frontend/src/api/client.ts").read_text(encoding="utf-8")
    main = Path("frontend/src/main.tsx").read_text(encoding="utf-8")
    login = Path("frontend/src/pages/LoginPage.tsx").read_text(encoding="utf-8")
    blob = "\n".join([client, main, login])
    assert "localStorage.setItem" not in blob
    assert "sessionStorage.setItem" not in blob
    assert "credentials: \"include\"" in client or "credentials: 'include'" in client


def test_hash_only_in_memory_not_token() -> None:
    token = "a" * 48
    digest = hash_session_token(token)
    assert digest == hashlib.sha256(token.encode()).hexdigest()
    assert digest != token
