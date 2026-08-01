"""Smoke de arranque estilo Oryx: application path + create_app sin run.sh."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.adapters.primary.http.app_factory import create_app
from app.application.ui.password_hash import hash_password
from application import ensure_packaged_site_packages


def test_oryx_style_application_app_registers_ui_routes(monkeypatch) -> None:
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "sandbox")
    monkeypatch.setenv("UI_ENABLED", "true")
    monkeypatch.setenv("UI_WRITE_ENABLED", "false")
    monkeypatch.setenv("UI_FINALIZE_ENABLED", "false")
    monkeypatch.setenv("UI_NOTIFY_ENABLED", "false")
    monkeypatch.setenv("UI_MERGE_ENABLED", "false")
    monkeypatch.setenv("UI_AMORTIZATION_ENABLED", "false")
    monkeypatch.setenv("UI_AUTH_MODE", "local_session")
    monkeypatch.setenv("UI_LOCAL_USERNAME", "operador_hbi")
    monkeypatch.setenv(
        "UI_LOCAL_PASSWORD_HASH",
        hash_password("CorrectHorseBattery!"),
    )
    monkeypatch.setenv("UI_COOKIE_SECURE", "false")
    monkeypatch.setenv("UI_COOKIE_HTTPONLY", "true")
    monkeypatch.setenv("UI_COOKIE_SAMESITE", "strict")
    monkeypatch.setenv("UI_ALLOWED_ORIGINS", "http://testserver")
    monkeypatch.setenv("API_HTTP_KEY", "test-key-not-for-prod")
    dist = Path(__file__).resolve().parents[1] / "frontend" / "dist"
    monkeypatch.setenv("UI_STATIC_DIR", str(dist))
    monkeypatch.delenv("WEBSITE_INSTANCE_ID", raising=False)
    monkeypatch.delenv("WEBSITE_SITE_NAME", raising=False)

    # Equivalente al preámbulo de application.py (path deps) + factory.
    ensure_packaged_site_packages()
    app = create_app()
    client = TestClient(app)

    health = client.get("/health")
    assert health.status_code == 200
    body = health.json()
    assert body["status"] == "ok"
    assert body["environment"] == "sandbox"
    assert body["ui_enabled"] is True
    assert "build" in body

    boot = client.get("/api/ui/v1/bootstrap")
    assert boot.status_code == 200
    boot_body = boot.json()
    assert boot_body["active_environment"] == "sandbox"
    assert boot_body["auth_mode"] == "local_session"
    assert boot_body["writes_allowed"] is False

    app_page = client.get("/app/")
    assert app_page.status_code == 200
    assert "text/html" in app_page.headers.get("content-type", "")
    html = app_page.text
    # El hash del bundle Vite cambia en cada build; se toma del HTML montado.
    marker = '/app/assets/index-'
    assert marker in html
    start = html.index(marker)
    end = html.index('.js', start)
    asset_path = html[start : end + 3]
    js = client.get(asset_path)
    assert js.status_code == 200
    assert "X-CSRF-Token" in js.text
    assert "auth/csrf" in js.text

    diag = client.get("/graph/diagnostics")
    assert diag.status_code in {401, 403}

    oa = client.get("/openapi.json", headers={"X-API-Key": "test-key-not-for-prod"})
    assert oa.status_code == 200
    paths = oa.json().get("paths", {})
    assert "/api/ui/v1/bootstrap" in paths
    assert any(p.startswith("/graph/") for p in paths)

    muted = client.post(
        "/api/ui/v1/processes/generate",
        json={"bank_code": "banco_bogota", "process_date": "2026-08-01"},
    )
    assert muted.status_code in {401, 403, 422}
