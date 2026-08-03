"""Tests de /health con marcador de release U4-RC."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.adapters.primary.http.app_factory import create_app
from app.application.ui.feature_flags import UiFeatureFlags
from app import build_info


def test_health_exposes_build_environment_and_ui_flag(monkeypatch) -> None:
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "sandbox")
    monkeypatch.setattr(build_info, "BUILD_ID", "u4-rc-sandbox-ui-deadbeef")
    monkeypatch.setattr(build_info, "COMMIT", "deadbeefcafebabe")
    monkeypatch.setattr(
        "app.adapters.primary.http.routers.health.get_ui_feature_flags",
        lambda: UiFeatureFlags(
            ui_enabled=True,
            ui_write_enabled=False,
            ui_finalize_enabled=False,
            ui_notify_enabled=False,
            ui_merge_enabled=False,
            ui_amortization_enabled=False,
            ui_review_edit_enabled=False,
            ui_asientos_upload_enabled=False,
            ui_auth_mode="local_session",
        ),
    )
    monkeypatch.setattr(
        "app.adapters.primary.http.app_factory.get_ui_feature_flags",
        lambda: UiFeatureFlags(
            ui_enabled=False,
            ui_write_enabled=False,
            ui_finalize_enabled=False,
            ui_notify_enabled=False,
            ui_merge_enabled=False,
            ui_amortization_enabled=False,
            ui_review_edit_enabled=False,
            ui_asientos_upload_enabled=False,
            ui_auth_mode="local_session",
        ),
    )

    client = TestClient(create_app())
    res = client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["build"] == "u4-rc-sandbox-ui-deadbeef"
    assert body["commit"] == "deadbeefcafebabe"
    assert body["environment"] == "sandbox"
    assert body["ui_enabled"] is True
    assert "password" not in res.text.lower()


def test_health_reports_ui_disabled(monkeypatch) -> None:
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "sandbox")
    monkeypatch.setenv("UI_ENABLED", "false")
    monkeypatch.setattr(build_info, "BUILD_ID", "u4-rc-sandbox-ui-abc")
    client = TestClient(create_app())
    body = client.get("/health").json()
    assert body["ui_enabled"] is False
    assert body["build"].startswith("u4-rc-sandbox-ui-")
