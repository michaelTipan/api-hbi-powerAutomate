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


def _env_bool_strict_default_false(name: str) -> bool:
    """Parseo estricto fail-closed: ausente o inválido → False."""
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return False
    if raw in {"1", "true", "yes", "on", "si", "sí"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return False


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
    ui_finalize_enabled: bool
    ui_notify_enabled: bool
    ui_merge_enabled: bool
    ui_amortization_enabled: bool
    ui_review_edit_enabled: bool
    ui_auth_mode: UiAuthMode
    fail_closed: bool = False
    fail_closed_reason: str | None = None

    @property
    def reads_allowed(self) -> bool:
        return self.ui_enabled

    @property
    def writes_allowed(self) -> bool:
        return self.ui_enabled and self.ui_write_enabled

    @property
    def finalize_allowed(self) -> bool:
        """Generate no depende de este flag; solo Finalize UI."""
        return self.writes_allowed and self.ui_finalize_enabled

    @property
    def notify_allowed(self) -> bool:
        """Independiente de Finalize; no habilita Merge/Dry-run/Apply."""
        return self.writes_allowed and self.ui_notify_enabled

    @property
    def merge_allowed(self) -> bool:
        """Independiente de Notify/Finalize; no habilita Dry-run/Apply."""
        return self.writes_allowed and self.ui_merge_enabled

    @property
    def amortization_allowed(self) -> bool:
        """Independiente de Merge/Notify/Finalize; acción única "Procesar amortización"."""
        return self.writes_allowed and self.ui_amortization_enabled

    @property
    def review_edit_allowed(self) -> bool:
        """Edición/guardado del Excel de revisión desde la UI (R1)."""
        return self.writes_allowed and self.ui_review_edit_enabled


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
    finalize = _env_bool_strict_default_false("UI_FINALIZE_ENABLED")
    notify = _env_bool_strict_default_false("UI_NOTIFY_ENABLED")
    merge = _env_bool_strict_default_false("UI_MERGE_ENABLED")
    amortization = _env_bool_strict_default_false("UI_AMORTIZATION_ENABLED")
    review_edit = _env_bool_strict_default_false("UI_REVIEW_EDIT_ENABLED")
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
        ui_finalize_enabled=finalize if effective_enabled else False,
        ui_notify_enabled=notify if effective_enabled else False,
        ui_merge_enabled=merge if effective_enabled else False,
        ui_amortization_enabled=amortization if effective_enabled else False,
        ui_review_edit_enabled=review_edit if effective_enabled else False,
        ui_auth_mode=auth_mode,
        fail_closed=fail_closed,
        fail_closed_reason=reason,
    )
