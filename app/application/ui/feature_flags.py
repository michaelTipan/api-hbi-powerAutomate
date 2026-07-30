"""Feature flags de la UI operativa.

No cablea rutas: solo lectura de entorno. El montaje real ocurre en
integration/performance-and-ui.

Fail-closed: en producción, UI_AUTH_MODE=mock deshabilita la UI de forma
efectiva (no tumba /graph/* ni el arranque de la API).
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Literal

from app.application.ui.environment import resolve_active_environment

UiAuthMode = Literal["mock", "entra"]

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
            "UI_AUTH_MODE=api_key está prohibido. Use mock (local) o entra (Azure)."
        )
    if raw == "entra":
        return "entra"
    return "mock"


@dataclass(frozen=True)
class UiFeatureFlags:
    ui_enabled: bool
    ui_write_enabled: bool
    ui_auth_mode: UiAuthMode
    """True si la config pedía UI pero se forzó apagado por seguridad."""
    fail_closed: bool = False
    fail_closed_reason: str | None = None

    @property
    def reads_allowed(self) -> bool:
        return self.ui_enabled

    @property
    def writes_allowed(self) -> bool:
        # U1: las mutaciones no están implementadas; este flag solo documenta intención.
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
    """Solo tests: permite volver a emitir el log crítico."""
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

    if env.environment == "production" and auth_mode == "mock":
        fail_closed = True
        reason = (
            "ACTIVE_ENVIRONMENT=production exige UI_AUTH_MODE=entra; "
            "UI_AUTH_MODE=mock está prohibido en producción."
        )
        effective_enabled = False
        _log_fail_closed_once(reason)

    return UiFeatureFlags(
        ui_enabled=effective_enabled,
        ui_write_enabled=write if effective_enabled else False,
        ui_auth_mode=auth_mode,
        fail_closed=fail_closed,
        fail_closed_reason=reason,
    )
