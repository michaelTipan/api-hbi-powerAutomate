"""Feature flags de la UI operativa.

Fail-closed:
- producción + mock → UI apagada;
- Azure + mock → UI apagada;
- local_session incompleto / cookie insegura → UI apagada;
- local_session + UI enabled fuera de sandbox → UI apagada (fase D2).
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Literal

from app.application.ui.environment import resolve_active_environment
from app.application.ui.local_session_config import (
    is_running_on_azure,
    validate_local_session_runtime,
)

UiAuthMode = Literal["mock", "entra", "local_session"]

logger = logging.getLogger(__name__)

_LOGGED_FAIL_CLOSED = False


def _env_bool(name: str, default: bool = False) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on", "si", "sí"}


def resolve_ui_auth_mode() -> UiAuthMode:
    raw = (os.getenv("UI_AUTH_MODE") or "mock").strip().lower()
    if raw == "api_key":
        raise ValueError(
            "UI_AUTH_MODE=api_key está prohibido. "
            "Use mock (local), local_session o entra."
        )
    if raw == "entra":
        return "entra"
    if raw in {"local_session", "local", "session"}:
        return "local_session"
    return "mock"


@dataclass(frozen=True)
class UiFeatureFlags:
    ui_enabled: bool
    ui_write_enabled: bool
    ui_auth_mode: UiAuthMode
    fail_closed: bool = False
    fail_closed_reason: str | None = None

    @property
    def reads_allowed(self) -> bool:
        return self.ui_enabled

    @property
    def writes_allowed(self) -> bool:
        return self.ui_enabled and self.ui_write_enabled


def _log_fail_closed_once(reason: str) -> None:
    global _LOGGED_FAIL_CLOSED
    if _LOGGED_FAIL_CLOSED:
        return
    _LOGGED_FAIL_CLOSED = True
    logger.critical(
        "UI fail-closed: %s. La API y /graph/* siguen operativos; "
        "rutas /api/ui no deben usarse hasta corregir la configuración.",
        reason,
    )


def reset_ui_fail_closed_log_for_tests() -> None:
    global _LOGGED_FAIL_CLOSED
    _LOGGED_FAIL_CLOSED = False


def get_ui_feature_flags() -> UiFeatureFlags:
    requested_enabled = _env_bool("UI_ENABLED", default=False)
    write = _env_bool("UI_WRITE_ENABLED", default=False)
    auth_mode = resolve_ui_auth_mode()
    env = resolve_active_environment()

    fail_closed = False
    reason: str | None = None
    effective_enabled = requested_enabled

    if auth_mode == "mock" and (
        env.environment == "production" or is_running_on_azure()
    ):
        fail_closed = True
        reason = (
            "UI_AUTH_MODE=mock está prohibido en Azure/producción. "
            "Use local_session (operativo) o entra (migración futura)."
        )
        effective_enabled = False
        _log_fail_closed_once(reason)

    if effective_enabled and auth_mode == "local_session":
        if env.environment != "sandbox":
            fail_closed = True
            reason = (
                "UI_AUTH_MODE=local_session con UI_ENABLED=true solo se admite "
                "en ACTIVE_ENVIRONMENT=sandbox durante D2."
            )
            effective_enabled = False
            _log_fail_closed_once(reason)
        else:
            ok, local_reason = validate_local_session_runtime()
            if not ok:
                fail_closed = True
                reason = local_reason
                effective_enabled = False
                _log_fail_closed_once(reason or "local_session misconfigured")

    return UiFeatureFlags(
        ui_enabled=effective_enabled,
        ui_write_enabled=write if effective_enabled else False,
        ui_auth_mode=auth_mode,
        fail_closed=fail_closed,
        fail_closed_reason=reason,
    )
