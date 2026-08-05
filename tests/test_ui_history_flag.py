"""UI_HISTORY_ENABLED: Historial UI/API fail-closed por defecto."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.adapters.primary.http.ui import deps as ui_deps
from app.application.ui.feature_flags import (
    UiFeatureFlags,
    get_ui_feature_flags,
    reset_ui_fail_closed_log_for_tests,
)
from app.application.ui.password_hash import hash_password


@pytest.fixture(autouse=True)
def _reset_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_ui_fail_closed_log_for_tests()
    encoded = hash_password("CorrectHorseBattery!")
    monkeypatch.setenv("UI_ENABLED", "true")
    monkeypatch.setenv("UI_WRITE_ENABLED", "true")
    monkeypatch.setenv("UI_AUTH_MODE", "local_session")
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "sandbox")
    monkeypatch.setenv("UI_LOCAL_USERNAME", "operator")
    monkeypatch.setenv("UI_LOCAL_PASSWORD_HASH", encoded)
    monkeypatch.setenv("UI_COOKIE_SECURE", "false")
    monkeypatch.setenv("UI_COOKIE_HTTPONLY", "true")
    monkeypatch.setenv("UI_COOKIE_SAMESITE", "strict")
    monkeypatch.delenv("WEBSITE_INSTANCE_ID", raising=False)
    monkeypatch.delenv("WEBSITE_SITE_NAME", raising=False)
    monkeypatch.delenv("UI_HISTORY_ENABLED", raising=False)


def test_history_disabled_by_default() -> None:
    flags = get_ui_feature_flags()
    assert flags.ui_history_enabled is False
    assert flags.history_allowed is False


def test_history_enabled_when_flag_true(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UI_HISTORY_ENABLED", "true")
    flags = get_ui_feature_flags()
    assert flags.ui_history_enabled is True
    assert flags.history_allowed is True


def test_require_history_enabled_raises_when_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        ui_deps,
        "require_ui_enabled",
        lambda: UiFeatureFlags(
            ui_enabled=True,
            ui_write_enabled=True,
            ui_finalize_enabled=True,
            ui_notify_enabled=True,
            ui_merge_enabled=True,
            ui_amortization_enabled=True,
            ui_history_enabled=False,
            ui_auth_mode="local_session",
        ),
    )
    with pytest.raises(HTTPException) as exc:
        ui_deps.require_history_enabled()
    assert exc.value.status_code == 404
    detail = exc.value.detail
    assert isinstance(detail, dict)
    assert detail.get("error_code") == "ui_history_disabled"


def test_require_history_enabled_ok_when_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        ui_deps,
        "require_ui_enabled",
        lambda: UiFeatureFlags(
            ui_enabled=True,
            ui_write_enabled=True,
            ui_finalize_enabled=True,
            ui_notify_enabled=True,
            ui_merge_enabled=True,
            ui_amortization_enabled=True,
            ui_history_enabled=True,
            ui_auth_mode="local_session",
        ),
    )
    flags = ui_deps.require_history_enabled()
    assert flags.history_allowed is True
