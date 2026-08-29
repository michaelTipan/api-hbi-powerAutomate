"""Tests GET /api/ui/v1/dashboard."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.adapters.primary.http.ui.router_v1 import (
    configure_ui_router_for_tests,
    reset_ui_router_test_hooks,
)
from tests.ui_fixtures import make_snap
from tests.ui_test_app import create_ui_test_app

AUTH = {"Authorization": "Bearer mock-user"}


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("UI_ENABLED", "true")
    monkeypatch.setenv("UI_WRITE_ENABLED", "false")
    monkeypatch.setenv("UI_AUTH_MODE", "mock")
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "sandbox")
    reset_ui_router_test_hooks()
    yield
    reset_ui_router_test_hooks()


def test_dashboard_unified_single_projection_per_bank() -> None:
    snap = make_snap()
    configure_ui_router_for_tests(control_loader=lambda bc: snap)
    client = TestClient(create_ui_test_app())

    dash = client.get("/api/ui/v1/dashboard", headers=AUTH)
    assert dash.status_code == 200
    body = dash.json()
    assert body["environment"] == "sandbox"
    assert len(body["banks"]) == 2
    assert len(body["items"]) >= 1
    assert body["items"][0]["process_key"] == snap.process_key

    listed = client.get("/api/ui/v1/processes", headers=AUTH)
    banks = client.get("/api/ui/v1/banks", headers=AUTH)
    assert listed.status_code == 200
    assert banks.status_code == 200
    assert listed.json()["items"][0]["process_key"] == body["items"][0]["process_key"]
    bog = next(b for b in body["banks"] if b["bank_code"] == "banco_bogota")
    assert bog["bank_code"] == "banco_bogota"


def test_parse_bank_from_process_key_direct_get() -> None:
    snap = make_snap()
    configure_ui_router_for_tests(control_loader=lambda bc: snap)
    client = TestClient(create_ui_test_app())

    detail = client.get(
        f"/api/ui/v1/processes/{snap.process_key}",
        headers=AUTH,
    )
    assert detail.status_code == 200
    assert detail.json()["process_key"] == snap.process_key
