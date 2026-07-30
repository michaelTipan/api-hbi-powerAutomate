from __future__ import annotations

import pytest

from app.application.ui.environment import resolve_active_environment


def test_sandbox_label(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "sandbox")
    info = resolve_active_environment()
    assert info.environment == "sandbox"
    assert info.display_label == "SANDBOX / PRUEBAS"


def test_production_label(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "production")
    info = resolve_active_environment()
    assert info.environment == "production"
    assert info.display_label == "PRODUCCIÓN"


def test_unknown_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ACTIVE_ENVIRONMENT", raising=False)
    info = resolve_active_environment()
    assert info.environment == "unknown"
