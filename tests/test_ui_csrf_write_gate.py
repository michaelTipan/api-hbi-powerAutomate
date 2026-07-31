"""Tests U3-A: CSRF, Origin (UI_ALLOWED_ORIGINS) y puerta de escritura genérica.

No cubre el endpoint Generate en sí (ver test_ui_generate_action.py); aquí se
prueba el mecanismo CSRF/Origin/Content-Type reutilizable para cualquier POST
autenticado de la UI.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.adapters.primary.http.deps import init_graph_client
from app.adapters.primary.http.ui import write_deps
from app.adapters.primary.http.ui.router_v1 import reset_ui_router_test_hooks
from app.adapters.primary.http.ui.write_deps import require_write_access
from app.application.job_manager import JobManager
from app.application.ui.allowed_origins import is_origin_allowed, resolve_allowed_origins
from app.application.ui.feature_flags import reset_ui_fail_closed_log_for_tests
from app.application.ui.local_auth import AuthenticatedLocalUser
from app.application.ui.login_rate_limit import reset_login_rate_limiter_for_tests
from app.application.ui.password_hash import hash_password
from app.application.ui.session_repository import (
    InMemorySessionRepository,
    SessionRecord,
    get_session_repository,
    hash_session_token,
    mint_csrf_token,
    mint_session_token,
    set_session_repository_for_tests,
)
from tests.ui_test_app import create_ui_test_app

ORIGIN = "https://testserver"


def _seed_operator_session() -> tuple[AuthenticatedLocalUser, str]:
    """Crea una sesión operator válida en el repo y devuelve (user, csrf_token)."""
    token = mint_session_token()
    token_hash = hash_session_token(token)
    csrf = mint_csrf_token()
    record = SessionRecord(
        token_hash=token_hash,
        username="operator",
        role="operator",
        created_at=0.0,
        last_activity_at=0.0,
        expires_at=9_999_999_999.0,
        csrf_token=csrf,
        auth_mode="local_session",
    )
    get_session_repository().create(record)
    user = AuthenticatedLocalUser(
        username="operator",
        role="operator",
        auth_mode="local_session",
        expires_at=record.expires_at,
        token_hash=token_hash,
    )
    return user, csrf


def _fake_request(headers: dict[str, str], *, user: AuthenticatedLocalUser | None) -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/ui/v1/processes/generate",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "query_string": b"",
        "server": ("testserver", 443),
        "scheme": "https",
        "client": ("testclient", 123),
    }
    request = Request(scope)
    if user is not None:
        request.state.ui_local_user = user
    return request


@dataclass(frozen=True)
class _FakeFlags:
    ui_write_enabled: bool


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


def _enable_local(
    monkeypatch: pytest.MonkeyPatch,
    *,
    write_enabled: bool = False,
    active_environment: str = "sandbox",
    allowed_origins: str | None = None,
) -> str:
    encoded = hash_password("CorrectHorseBattery!")
    monkeypatch.setenv("UI_ENABLED", "true")
    monkeypatch.setenv("UI_WRITE_ENABLED", "true" if write_enabled else "false")
    monkeypatch.setenv("UI_AUTH_MODE", "local_session")
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", active_environment)
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
    if allowed_origins is None:
        monkeypatch.delenv("UI_ALLOWED_ORIGINS", raising=False)
    else:
        monkeypatch.setenv("UI_ALLOWED_ORIGINS", allowed_origins)
    return encoded


@pytest.fixture(autouse=True)
def _cleanup() -> None:
    reset_ui_router_test_hooks()
    reset_ui_fail_closed_log_for_tests()
    reset_login_rate_limiter_for_tests()
    set_session_repository_for_tests(InMemorySessionRepository())
    jm = JobManager()
    jm._validation_jobs.clear()
    jm._generate_active = False
    jm._finalize_active = False
    jm._notify_active = False
    init_graph_client(_MockGraph())  # type: ignore[arg-type]
    yield
    reset_login_rate_limiter_for_tests()
    set_session_repository_for_tests(None)
    jm._validation_jobs.clear()
    jm._generate_active = False
    jm._finalize_active = False
    jm._notify_active = False
    init_graph_client(_MockGraph())  # type: ignore[arg-type]


def _login(client: TestClient) -> None:
    res = client.post(
        "/api/ui/v1/auth/login",
        json={"username": "operator", "password": "CorrectHorseBattery!"},
        headers={"Origin": ORIGIN},
    )
    assert res.status_code == 200, res.text


def _csrf(client: TestClient) -> str:
    res = client.get("/api/ui/v1/auth/csrf", headers={"Origin": ORIGIN})
    assert res.status_code == 200, res.text
    return res.json()["csrf_token"]


# ─── UI_ALLOWED_ORIGINS: parseo + fail-closed ───────────────────────────────


def test_allowed_origins_exact_match_no_subdomain(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UI_ALLOWED_ORIGINS", "https://app.example.com,https://otro.example.com")
    cfg = resolve_allowed_origins()
    assert cfg.configured is True
    assert cfg.valid is True
    assert is_origin_allowed("https://app.example.com", cfg) is True
    # Sin startswith/subdominios: un subdominio o un origen con path no matchean.
    assert is_origin_allowed("https://evil.app.example.com", cfg) is False
    assert is_origin_allowed("https://app.example.com.evil.net", cfg) is False
    assert is_origin_allowed("http://app.example.com", cfg) is False  # scheme distinto


def test_allowed_origins_fail_closed_when_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UI_ALLOWED_ORIGINS", "   ")
    cfg = resolve_allowed_origins()
    assert cfg.configured is True
    assert cfg.valid is False
    assert cfg.origins == frozenset()
    # Ningún origen matchea con una config vacía/rota (fail-closed).
    assert is_origin_allowed("https://app-hbiauto-prod-001.azurewebsites.net", cfg) is False


def test_allowed_origins_fail_closed_when_invalid_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UI_ALLOWED_ORIGINS", "not-a-url, ftp://also-bad")
    cfg = resolve_allowed_origins()
    assert cfg.configured is True
    assert cfg.valid is False


def test_allowed_origins_not_configured_falls_back_to_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("UI_ALLOWED_ORIGINS", raising=False)
    cfg = resolve_allowed_origins()
    assert cfg.configured is False
    assert cfg.valid is False


# ─── CSRF ────────────────────────────────────────────────────────────────────


def test_csrf_no_rotate_between_two_gets(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_local(monkeypatch)
    client = TestClient(create_ui_test_app(), base_url="https://testserver")
    _login(client)
    first = _csrf(client)
    second = _csrf(client)
    assert first == second
    assert len(first) > 20


def test_csrf_missing_or_wrong_token_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_local(monkeypatch, write_enabled=True, allowed_origins=ORIGIN)
    client = TestClient(create_ui_test_app(), base_url="https://testserver")
    _login(client)

    no_csrf = client.post(
        "/api/ui/v1/processes/generate",
        json={"bank_code": "banco_bogota"},
        headers={"Origin": ORIGIN, "Content-Type": "application/json"},
    )
    assert no_csrf.status_code == 403
    assert no_csrf.json()["detail"]["error_code"] == "invalid_csrf_token"

    wrong_csrf = client.post(
        "/api/ui/v1/processes/generate",
        json={"bank_code": "banco_bogota"},
        headers={
            "Origin": ORIGIN,
            "Content-Type": "application/json",
            "X-CSRF-Token": "totally-wrong-token",
        },
    )
    assert wrong_csrf.status_code == 403
    assert wrong_csrf.json()["detail"]["error_code"] == "invalid_csrf_token"


# ─── Content-Type ────────────────────────────────────────────────────────────


def test_generate_charset_json_accepted_by_content_type_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El gate de Content-Type acepta 'application/json; charset=utf-8'.

    No exigimos que el POST resulte en 202 (podría chocar con otro chequeo),
    solo que no sea rechazado *por content-type*.
    """
    _enable_local(monkeypatch, write_enabled=True, allowed_origins=ORIGIN)
    client = TestClient(create_ui_test_app(), base_url="https://testserver")
    _login(client)
    csrf = _csrf(client)

    res = client.post(
        "/api/ui/v1/processes/generate",
        json={"bank_code": "banco_bogota"},
        headers={
            "Origin": ORIGIN,
            "Content-Type": "application/json; charset=utf-8",
            "X-CSRF-Token": csrf,
        },
    )
    assert res.status_code != 403 or res.json()["detail"]["error_code"] != "invalid_content_type"
    assert res.status_code == 202


def test_generate_non_json_content_type_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_local(monkeypatch, write_enabled=True, allowed_origins=ORIGIN)
    client = TestClient(create_ui_test_app(), base_url="https://testserver")
    _login(client)
    csrf = _csrf(client)

    res = client.post(
        "/api/ui/v1/processes/generate",
        content=b'{"bank_code": "banco_bogota"}',
        headers={
            "Origin": ORIGIN,
            "Content-Type": "text/plain",
            "X-CSRF-Token": csrf,
        },
    )
    assert res.status_code == 403
    assert res.json()["detail"]["error_code"] == "invalid_content_type"


# ─── Origin ausente ──────────────────────────────────────────────────────────


def test_missing_origin_rejected_on_write_path(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_local(monkeypatch, write_enabled=True, allowed_origins=ORIGIN)
    client = TestClient(create_ui_test_app(), base_url="https://testserver")
    _login(client)
    csrf = _csrf(client)

    res = client.post(
        "/api/ui/v1/processes/generate",
        json={"bank_code": "banco_bogota"},
        headers={"Content-Type": "application/json", "X-CSRF-Token": csrf},
    )
    assert res.status_code == 403
    assert res.json()["detail"]["error_code"] == "invalid_origin"


def test_missing_origin_rejected_on_login_when_azure(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_local(monkeypatch)
    monkeypatch.setenv("WEBSITE_INSTANCE_ID", "azure-instance-001")
    client = TestClient(create_ui_test_app(), base_url="https://testserver")
    res = client.post(
        "/api/ui/v1/auth/login",
        json={"username": "operator", "password": "CorrectHorseBattery!"},
    )
    assert res.status_code == 403
    assert res.json()["detail"]["error_code"] == "invalid_origin"


# ─── UI_WRITE_ENABLED / ACTIVE_ENVIRONMENT ──────────────────────────────────


def test_write_disabled_rejects_generate(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_local(monkeypatch, write_enabled=False, allowed_origins=ORIGIN)
    client = TestClient(create_ui_test_app(), base_url="https://testserver")
    _login(client)
    csrf = _csrf(client)

    res = client.post(
        "/api/ui/v1/processes/generate",
        json={"bank_code": "banco_bogota"},
        headers={
            "Origin": ORIGIN,
            "Content-Type": "application/json",
            "X-CSRF-Token": csrf,
        },
    )
    assert res.status_code == 403
    assert res.json()["detail"]["error_code"] == "ui_write_disabled"


def test_write_rejected_outside_sandbox_even_if_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Chequeo unitario de require_write_access: aísla la regla sandbox-only.

    En runtime real, UI_AUTH_MODE=local_session fuera de sandbox ya deja la UI
    entera fail-closed (feature_flags.py), así que esta regla es defensa en
    profundidad. Se prueba directo contra la dependencia, forzando
    ``ui_write_enabled=True`` para no chocar con ese fail-closed previo.
    """
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "production")
    monkeypatch.setenv("UI_ALLOWED_ORIGINS", ORIGIN)
    monkeypatch.setattr(write_deps, "get_ui_feature_flags", lambda: _FakeFlags(ui_write_enabled=True))

    user, csrf = _seed_operator_session()
    request = _fake_request(
        {
            "origin": ORIGIN,
            "content-type": "application/json",
            "x-csrf-token": csrf,
        },
        user=user,
    )
    with pytest.raises(HTTPException) as exc_info:
        require_write_access(request)
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["error_code"] == "write_only_in_sandbox"
