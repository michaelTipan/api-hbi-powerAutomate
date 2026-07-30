"""Smoke: create_app de producción no monta UI y sigue importable."""
from __future__ import annotations

import pytest

from app.adapters.primary.http.app_factory import create_app


def test_production_create_app_has_no_ui_routes() -> None:
    app = create_app()
    paths = {getattr(r, "path", "") for r in app.routes}
    assert not any(str(p).startswith("/api/ui") for p in paths)
    assert any(str(p).startswith("/graph/sharepoint/payment-validation") for p in paths)
    assert "/health" in paths or any(str(p) == "/health" for p in paths)


def test_production_mock_fail_closed_does_not_break_create_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mala config UI no debe tumbar la API ni /graph/*."""
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "production")
    monkeypatch.setenv("UI_AUTH_MODE", "mock")
    monkeypatch.setenv("UI_ENABLED", "true")
    app = create_app()
    from fastapi.testclient import TestClient

    client = TestClient(app)
    assert client.get("/health").status_code == 200
    # Rutas UI no montadas; health sigue OK.
    assert not any(
        str(getattr(r, "path", "")).startswith("/api/ui") for r in app.routes
    )
