from __future__ import annotations

import logging

import pytest

from app.application.ui.feature_flags import (
    get_ui_feature_flags,
    reset_ui_fail_closed_log_for_tests,
    resolve_ui_auth_mode,
)


@pytest.fixture(autouse=True)
def _reset_fail_closed_log() -> None:
    reset_ui_fail_closed_log_for_tests()


def test_flags_default_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("UI_ENABLED", raising=False)
    monkeypatch.delenv("UI_WRITE_ENABLED", raising=False)
    monkeypatch.delenv("UI_FINALIZE_ENABLED", raising=False)
    monkeypatch.delenv("UI_NOTIFY_ENABLED", raising=False)
    monkeypatch.delenv("UI_MERGE_ENABLED", raising=False)
    monkeypatch.delenv("UI_AMORTIZATION_ENABLED", raising=False)
    monkeypatch.delenv("UI_REVIEW_EDIT_ENABLED", raising=False)
    monkeypatch.delenv("UI_ASIENTOS_UPLOAD_ENABLED", raising=False)
    monkeypatch.setenv("UI_AUTH_MODE", "mock")
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "sandbox")
    flags = get_ui_feature_flags()
    assert flags.ui_enabled is False
    assert flags.ui_write_enabled is False
    assert flags.ui_finalize_enabled is False
    assert flags.ui_notify_enabled is False
    assert flags.ui_merge_enabled is False
    assert flags.ui_amortization_enabled is False
    assert flags.ui_review_edit_enabled is False
    assert flags.ui_asientos_upload_enabled is False
    assert flags.reads_allowed is False
    assert flags.writes_allowed is False
    assert flags.finalize_allowed is False
    assert flags.notify_allowed is False
    assert flags.merge_allowed is False
    assert flags.amortization_allowed is False
    assert flags.review_edit_allowed is False
    assert flags.asientos_upload_allowed is False
    assert flags.fail_closed is False


def test_write_requires_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UI_ENABLED", "true")
    monkeypatch.setenv("UI_WRITE_ENABLED", "true")
    monkeypatch.delenv("UI_FINALIZE_ENABLED", raising=False)
    monkeypatch.delenv("UI_NOTIFY_ENABLED", raising=False)
    monkeypatch.delenv("UI_MERGE_ENABLED", raising=False)
    monkeypatch.delenv("UI_AMORTIZATION_ENABLED", raising=False)
    monkeypatch.setenv("UI_AUTH_MODE", "mock")
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "sandbox")
    flags = get_ui_feature_flags()
    assert flags.ui_enabled is True
    assert flags.ui_write_enabled is True
    assert flags.writes_allowed is True
    assert flags.ui_finalize_enabled is False
    assert flags.finalize_allowed is False
    assert flags.ui_notify_enabled is False
    assert flags.notify_allowed is False
    assert flags.ui_merge_enabled is False
    assert flags.merge_allowed is False
    assert flags.ui_amortization_enabled is False
    assert flags.amortization_allowed is False


def test_finalize_requires_write_and_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UI_ENABLED", "true")
    monkeypatch.setenv("UI_WRITE_ENABLED", "true")
    monkeypatch.setenv("UI_FINALIZE_ENABLED", "true")
    monkeypatch.setenv("UI_AUTH_MODE", "mock")
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "sandbox")
    flags = get_ui_feature_flags()
    assert flags.finalize_allowed is True


def test_notify_requires_write_and_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UI_ENABLED", "true")
    monkeypatch.setenv("UI_WRITE_ENABLED", "true")
    monkeypatch.setenv("UI_NOTIFY_ENABLED", "true")
    monkeypatch.setenv("UI_AUTH_MODE", "mock")
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "sandbox")
    flags = get_ui_feature_flags()
    assert flags.ui_notify_enabled is True
    assert flags.notify_allowed is True


def test_merge_requires_write_and_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UI_ENABLED", "true")
    monkeypatch.setenv("UI_WRITE_ENABLED", "true")
    monkeypatch.setenv("UI_MERGE_ENABLED", "true")
    monkeypatch.setenv("UI_AUTH_MODE", "mock")
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "sandbox")
    flags = get_ui_feature_flags()
    assert flags.ui_merge_enabled is True
    assert flags.merge_allowed is True
    assert flags.notify_allowed is False
    assert flags.finalize_allowed is False


def test_amortization_requires_write_and_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UI_ENABLED", "true")
    monkeypatch.setenv("UI_WRITE_ENABLED", "true")
    monkeypatch.setenv("UI_AMORTIZATION_ENABLED", "true")
    monkeypatch.setenv("UI_AUTH_MODE", "mock")
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "sandbox")
    flags = get_ui_feature_flags()
    assert flags.ui_amortization_enabled is True
    assert flags.amortization_allowed is True
    assert flags.merge_allowed is False
    assert flags.notify_allowed is False
    assert flags.finalize_allowed is False


def test_amortization_flag_absent_or_invalid_is_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("UI_ENABLED", "true")
    monkeypatch.setenv("UI_WRITE_ENABLED", "true")
    monkeypatch.setenv("UI_AUTH_MODE", "mock")
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "sandbox")
    monkeypatch.delenv("UI_AMORTIZATION_ENABLED", raising=False)
    assert get_ui_feature_flags().ui_amortization_enabled is False
    monkeypatch.setenv("UI_AMORTIZATION_ENABLED", "invalid")
    assert get_ui_feature_flags().ui_amortization_enabled is False


def test_asientos_upload_requires_write_and_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("UI_ENABLED", "true")
    monkeypatch.setenv("UI_WRITE_ENABLED", "true")
    monkeypatch.setenv("UI_ASIENTOS_UPLOAD_ENABLED", "true")
    monkeypatch.setenv("UI_AUTH_MODE", "mock")
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "sandbox")
    flags = get_ui_feature_flags()
    assert flags.ui_asientos_upload_enabled is True
    assert flags.asientos_upload_allowed is True
    assert flags.merge_allowed is False
    assert flags.finalize_allowed is False


def test_asientos_upload_flag_absent_or_invalid_is_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("UI_ENABLED", "true")
    monkeypatch.setenv("UI_WRITE_ENABLED", "true")
    monkeypatch.setenv("UI_AUTH_MODE", "mock")
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "sandbox")
    monkeypatch.delenv("UI_ASIENTOS_UPLOAD_ENABLED", raising=False)
    assert get_ui_feature_flags().ui_asientos_upload_enabled is False
    monkeypatch.setenv("UI_ASIENTOS_UPLOAD_ENABLED", "invalid")
    assert get_ui_feature_flags().ui_asientos_upload_enabled is False


def test_write_flag_ignored_when_ui_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UI_ENABLED", "false")
    monkeypatch.setenv("UI_WRITE_ENABLED", "true")
    monkeypatch.setenv("UI_FINALIZE_ENABLED", "true")
    monkeypatch.setenv("UI_AUTH_MODE", "mock")
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "sandbox")
    flags = get_ui_feature_flags()
    assert flags.ui_write_enabled is False
    assert flags.ui_finalize_enabled is False


def test_api_key_auth_mode_forbidden(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UI_AUTH_MODE", "api_key")
    with pytest.raises(ValueError, match="prohibido"):
        resolve_ui_auth_mode()


def test_production_mock_fail_closed_disables_ui(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "production")
    monkeypatch.setenv("UI_AUTH_MODE", "mock")
    monkeypatch.setenv("UI_ENABLED", "true")
    monkeypatch.setenv("UI_WRITE_ENABLED", "true")
    with caplog.at_level(logging.CRITICAL, logger="app.application.ui.feature_flags"):
        flags = get_ui_feature_flags()
    assert flags.ui_enabled is False
    assert flags.ui_write_enabled is False
    assert flags.fail_closed is True
    assert flags.ui_auth_mode == "mock"
    assert "mock" in (flags.fail_closed_reason or "").lower()
    assert any("fail-closed" in r.message.lower() for r in caplog.records)


def test_production_entra_allows_ui_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "production")
    monkeypatch.setenv("UI_AUTH_MODE", "entra")
    monkeypatch.setenv("UI_ENABLED", "true")
    flags = get_ui_feature_flags()
    assert flags.ui_enabled is True
    assert flags.fail_closed is False


def test_production_local_session_allows_ui_when_runtime_valid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """local_session + production + UI_ENABLED + runtime OK → UI ON."""
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "production")
    monkeypatch.setenv("UI_AUTH_MODE", "local_session")
    monkeypatch.setenv("UI_ENABLED", "true")
    monkeypatch.setenv("UI_WRITE_ENABLED", "true")
    monkeypatch.setenv("UI_LOCAL_USERNAME", "operator")
    # Hash PBKDF2 válido (iteraciones seguras); no se usa para login aquí.
    from app.application.ui.password_hash import hash_password

    monkeypatch.setenv("UI_LOCAL_PASSWORD_HASH", hash_password("CorrectHorseBattery!"))
    monkeypatch.setenv("UI_COOKIE_SECURE", "true")
    monkeypatch.setenv("UI_COOKIE_HTTPONLY", "true")
    monkeypatch.setenv("UI_COOKIE_SAMESITE", "strict")
    monkeypatch.delenv("WEBSITE_INSTANCE_ID", raising=False)
    monkeypatch.delenv("WEBSITE_SITE_NAME", raising=False)
    flags = get_ui_feature_flags()
    assert flags.ui_enabled is True
    assert flags.writes_allowed is True
    assert flags.fail_closed is False


def test_unknown_env_local_session_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "staging")
    monkeypatch.setenv("UI_AUTH_MODE", "local_session")
    monkeypatch.setenv("UI_ENABLED", "true")
    flags = get_ui_feature_flags()
    assert flags.ui_enabled is False
    assert flags.fail_closed is True
    assert "sandbox o production" in (flags.fail_closed_reason or "")
