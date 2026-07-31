"""Tests U2: montaje create_app, bootstrap, SPA, API key vs Entra."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.adapters.primary.http.api_key_auth import ENV_API_HTTP_KEY, is_public_path
from app.adapters.primary.http.app_factory import create_app
from app.adapters.primary.http.deps import get_graph_client, init_graph_client
from app.adapters.primary.http.ui.router_v1 import (
    reset_ui_router_test_hooks,
    router as ui_router,
)
from app.adapters.secondary.ms_graph_client import MsGraphClient
from app.application.ui.entra_jwt import (
    reset_jwks_clients_for_tests,
    set_jwks_client_factory_for_tests,
)
from tests.ui_entra_jwt_helpers import install_entra_env, install_fake_jwks, mint_token


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


@pytest.fixture(autouse=True)
def _cleanup() -> None:
    reset_ui_router_test_hooks()
    reset_jwks_clients_for_tests()
    set_jwks_client_factory_for_tests(None)
    yield
    reset_ui_router_test_hooks()
    reset_jwks_clients_for_tests()
    set_jwks_client_factory_for_tests(None)
    init_graph_client(_MockGraph())  # type: ignore[arg-type]


def _enable_ui(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("UI_ENABLED", "true")
    monkeypatch.setenv("UI_WRITE_ENABLED", "false")
    monkeypatch.setenv("UI_AUTH_MODE", "entra")
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "sandbox")
    install_entra_env(monkeypatch)
    install_fake_jwks()
    spa = tmp_path / "spa"
    (spa / "assets").mkdir(parents=True)
    (spa / "index.html").write_text("<html>ui</html>", encoding="utf-8")
    (spa / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    monkeypatch.setenv("UI_STATIC_DIR", str(spa))
    monkeypatch.delenv(ENV_API_HTTP_KEY, raising=False)
    return spa


def test_public_path_exemptions_exact() -> None:
    assert is_public_path("/health") is True
    assert is_public_path("/health/") is True
    assert is_public_path("/app") is True
    assert is_public_path("/app/") is True
    assert is_public_path("/app/processes/x") is True
    assert is_public_path("/api/ui/v1/bootstrap") is True
    assert is_public_path("/api/ui/v1/environment") is True
    assert is_public_path("/api/ui/v1/processes") is True
    # No aceptar prefijos ambiguos.
    assert is_public_path("/api/ui") is False
    assert is_public_path("/api/ui/") is False
    assert is_public_path("/api/ui2/v1/bootstrap") is False
    assert is_public_path("/api/ui-extra") is False
    assert is_public_path("/graph/diagnostics") is False


def test_merge_routers_graph_intact(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _enable_ui(monkeypatch, tmp_path)
    init_graph_client(_MockGraph())  # type: ignore[arg-type]
    app = create_app()
    paths = {getattr(r, "path", "") for r in app.routes}
    assert any(str(p).startswith("/graph/sharepoint/payment-validation") for p in paths)
    assert any("/api/ui/v1" in str(p) for p in paths)
    client = TestClient(app, raise_server_exceptions=False)
    assert client.get("/health").status_code == 200


def test_health_public_with_api_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _enable_ui(monkeypatch, tmp_path)
    monkeypatch.setenv(ENV_API_HTTP_KEY, "secret-key")
    init_graph_client(_MockGraph())  # type: ignore[arg-type]
    client = TestClient(create_app(), raise_server_exceptions=False)
    assert client.get("/health").status_code == 200


def test_app_public_only_when_ui_enabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("UI_ENABLED", "false")
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "sandbox")
    monkeypatch.setenv("UI_AUTH_MODE", "entra")
    init_graph_client(_MockGraph())  # type: ignore[arg-type]
    client = TestClient(create_app(), raise_server_exceptions=False)
    assert client.get("/app").status_code == 404
    assert client.get("/app/").status_code == 404
    assert client.get("/api/ui/v1/bootstrap").status_code == 404

    _enable_ui(monkeypatch, tmp_path)
    init_graph_client(_MockGraph())  # type: ignore[arg-type]
    client2 = TestClient(create_app(), raise_server_exceptions=False)
    r = client2.get("/app", follow_redirects=False)
    assert r.status_code in {307, 302}
    assert client2.get("/app/").status_code == 200
    assert "ui" in client2.get("/app/").text


def test_spa_fallback_react_routes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _enable_ui(monkeypatch, tmp_path)
    init_graph_client(_MockGraph())  # type: ignore[arg-type]
    client = TestClient(create_app(), raise_server_exceptions=False)
    r = client.get("/app/processes/payment-validation%7Cbanco_bogota%7Cx")
    assert r.status_code == 200
    assert "ui" in r.text
    assets = client.get("/app/assets/app.js")
    assert assets.status_code == 200
    assert "console.log" in assets.text


def test_spa_does_not_intercept_api_graph_health(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _enable_ui(monkeypatch, tmp_path)
    init_graph_client(_MockGraph())  # type: ignore[arg-type]
    client = TestClient(create_app(), raise_server_exceptions=False)
    assert client.get("/health").json()["status"] == "ok"
    # /api/ui sin bearer → 401 (no index.html)
    env = client.get("/api/ui/v1/environment")
    assert env.status_code == 401
    assert env.headers.get("content-type", "").startswith("application/json")


def test_bootstrap_public_sanitized(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _enable_ui(monkeypatch, tmp_path)
    monkeypatch.setenv(ENV_API_HTTP_KEY, "secret-key")
    init_graph_client(_MockGraph())  # type: ignore[arg-type]
    client = TestClient(create_app(), raise_server_exceptions=False)
    res = client.get("/api/ui/v1/bootstrap")
    assert res.status_code == 200
    body = res.json()
    assert body["ui_enabled"] is True
    assert body["writes_allowed"] is False
    assert body["active_environment"] == "sandbox"
    assert body["display_label"] == "SANDBOX / PRUEBAS"
    assert body["entra_spa_client_id"] == "spa-client-id"
    assert "api://hbi-operator-ui/access_as_user" in body["entra_api_scope"]
    raw = json.dumps(body)
    for banned in (
        "client_secret",
        "API_HTTP_KEY",
        "GRAPH_CLIENT",
        "sharepoint",
        "password",
        "private_key",
    ):
        assert banned.lower() not in raw.lower()


def test_ui_endpoints_require_bearer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _enable_ui(monkeypatch, tmp_path)
    init_graph_client(_MockGraph())  # type: ignore[arg-type]
    client = TestClient(create_app(), raise_server_exceptions=False)
    assert client.get("/api/ui/v1/environment").status_code == 401
    token = mint_token()
    ok = client.get(
        "/api/ui/v1/environment",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert ok.status_code == 200


def test_api_key_alone_does_not_auth_ui(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _enable_ui(monkeypatch, tmp_path)
    monkeypatch.setenv(ENV_API_HTTP_KEY, "secret-key")
    init_graph_client(_MockGraph())  # type: ignore[arg-type]
    client = TestClient(create_app(), raise_server_exceptions=False)
    res = client.get(
        "/api/ui/v1/environment",
        headers={"X-API-Key": "secret-key"},
    )
    assert res.status_code == 401
    assert res.json()["error_code"] == "missing_bearer"


def test_bearer_does_not_auth_graph(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _enable_ui(monkeypatch, tmp_path)
    monkeypatch.setenv(ENV_API_HTTP_KEY, "secret-key")
    init_graph_client(_MockGraph())  # type: ignore[arg-type]
    client = TestClient(create_app(), raise_server_exceptions=False)
    token = mint_token()
    res = client.get(
        "/graph/diagnostics",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 401
    assert res.json()["detail"] == "missing_api_key"


def test_prod_mock_does_not_mount_ui(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "production")
    monkeypatch.setenv("UI_AUTH_MODE", "mock")
    monkeypatch.setenv("UI_ENABLED", "true")
    monkeypatch.delenv(ENV_API_HTTP_KEY, raising=False)
    init_graph_client(_MockGraph())  # type: ignore[arg-type]
    app = create_app()
    assert not any(
        str(getattr(r, "path", "")).startswith("/api/ui") for r in app.routes
    )
    client = TestClient(app)
    assert client.get("/health").status_code == 200
    assert client.get("/app").status_code == 404


def test_ui_write_disabled_zero_post_routes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _enable_ui(monkeypatch, tmp_path)
    monkeypatch.delenv("UI_NOTIFY_ENABLED", raising=False)
    init_graph_client(_MockGraph())  # type: ignore[arg-type]
    create_app()
    posts = [
        r
        for r in ui_router.routes
        if getattr(r, "methods", None) and "POST" in r.methods
    ]
    # Lista explícita: auth + generate + finalize + notify + merge (U3-C2).
    # Registradas siempre; gateadas en runtime. Sin Dry-run/Apply POST.
    allowed_process_suffixes = (
        "/processes/generate",
        "/processes/finalize",
        "/processes/notify",
        "/processes/merge",
    )
    assert posts
    for r in posts:
        path = str(getattr(r, "path", "") or "")
        ok_auth = "/auth/" in path
        ok_process = any(path.endswith(suf) for suf in allowed_process_suffixes)
        assert ok_auth or ok_process, f"POST no autorizado en allowlist: {path}"


def test_ui_notify_post_blocked_when_flag_false(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Ruta Notify registrada pero UI_NOTIFY_ENABLED=false → 403 sin efectos."""
    from app.adapters.primary.http.ui.router_v1 import configure_ui_router_for_tests
    from app.application.job_manager import get_job_manager
    from app.application.ui.login_rate_limit import reset_login_rate_limiter_for_tests
    from app.application.ui.password_hash import hash_password
    from app.application.ui.session_repository import (
        InMemorySessionRepository,
        set_session_repository_for_tests,
    )
    from tests.ui_fixtures import make_snap

    origin = "https://testserver"
    encoded = hash_password("CorrectHorseBattery!")
    monkeypatch.setenv("UI_ENABLED", "true")
    monkeypatch.setenv("UI_WRITE_ENABLED", "true")
    monkeypatch.setenv("UI_FINALIZE_ENABLED", "true")
    monkeypatch.setenv("UI_NOTIFY_ENABLED", "false")
    monkeypatch.delenv("UI_NOTIFY_SANDBOX_TO", raising=False)
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
    monkeypatch.setenv("UI_ALLOWED_ORIGINS", origin)
    monkeypatch.delenv("WEBSITE_INSTANCE_ID", raising=False)
    monkeypatch.delenv("WEBSITE_SITE_NAME", raising=False)
    spa = tmp_path / "spa"
    (spa / "assets").mkdir(parents=True)
    (spa / "index.html").write_text("<html>ui</html>", encoding="utf-8")
    monkeypatch.setenv("UI_STATIC_DIR", str(spa))
    monkeypatch.delenv(ENV_API_HTTP_KEY, raising=False)

    reset_login_rate_limiter_for_tests()
    set_session_repository_for_tests(InMemorySessionRepository())
    process_key = "payment-validation|banco_bogota|2026-07-30|u2-notify-guard"
    configure_ui_router_for_tests(
        control_loader=lambda _bc: make_snap(
            bank_code="banco_bogota",
            process_key=process_key,
            estado_proceso="FINALIZADO",
            is_active=True,
            historical_file_path="03 HISTORICO/h.xlsx",
        )
    )
    graph = _MockGraph()
    init_graph_client(graph)  # type: ignore[arg-type]
    jm = get_job_manager()
    jm._validation_jobs.clear()
    jm._generate_active = False
    jm._finalize_active = False
    jm._notify_active = False
    jobs_before = len(jm._validation_jobs)

    app = create_app()
    client = TestClient(app, base_url=origin)
    login = client.post(
        "/api/ui/v1/auth/login",
        json={"username": "operator", "password": "CorrectHorseBattery!"},
        headers={"Origin": origin},
    )
    assert login.status_code == 200, login.text
    csrf = client.get("/api/ui/v1/auth/csrf", headers={"Origin": origin}).json()[
        "csrf_token"
    ]
    res = client.post(
        "/api/ui/v1/processes/notify",
        json={"bank_code": "banco_bogota", "process_key": process_key},
        headers={
            "Origin": origin,
            "Content-Type": "application/json",
            "X-CSRF-Token": csrf,
        },
    )
    assert res.status_code == 403
    assert res.json()["detail"]["error_code"] == "ui_notify_disabled"
    assert len(jm._validation_jobs) == jobs_before
    assert jm.is_generate_or_finalize_active() is False
    assert jm.is_notify_active() is False

    set_session_repository_for_tests(None)
    reset_login_rate_limiter_for_tests()


def test_graph_client_reused_not_second_instance(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _enable_ui(monkeypatch, tmp_path)
    factory_src = Path("app/adapters/primary/http/app_factory.py").read_text(
        encoding="utf-8"
    )
    assert factory_src.count("MsGraphClient()") == 1
    assert "get_graph_client()" in factory_src
    assert "UiSharePointReadAdapter(graph)" in factory_src

    app = create_app()
    assert any(
        str(getattr(r, "path", "")).startswith("/api/ui") for r in app.routes
    )
    from app.adapters.primary.http.ui import router_v1

    reader = router_v1._sharepoint_reader
    assert reader is not None
    assert reader._http is get_graph_client()
    assert isinstance(get_graph_client(), MsGraphClient)


def test_frontend_build_included_in_package_script() -> None:
    script = Path("scripts/build-azure-package.ps1").read_text(encoding="utf-8")
    assert "npm ci" in script
    assert "npm run build" in script
    assert "static\\operator-ui" in script or "static/operator-ui" in script
    assert "_frontend-build" in script
    assert "verify-azure-package.ps1" in script
    assert Path("scripts/verify-azure-package.ps1").is_file()
