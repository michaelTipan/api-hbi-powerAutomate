"""Dependencias del router UI v1."""
from __future__ import annotations

from typing import Annotated, Callable

from fastapi import Header, HTTPException, Request

from app.adapters.primary.http.ui.auth import UiPrincipal, resolve_principal
from app.application.ui.feature_flags import UiFeatureFlags, get_ui_feature_flags
from app.application.ui.process_projection import PaymentProcessProjectionService


def require_ui_enabled() -> UiFeatureFlags:
    flags = get_ui_feature_flags()
    if not flags.ui_enabled:
        if flags.fail_closed:
            raise HTTPException(
                status_code=404,
                detail={
                    "error_code": "ui_misconfigured_fail_closed",
                    "user_message": (
                        "La interfaz operativa está deshabilitada por configuración insegura "
                        "(producción no admite autenticación mock)."
                    ),
                    "next_action": (
                        "Configure UI_AUTH_MODE=entra en producción. "
                        "Power Automate (/graph/*) no se ve afectado."
                    ),
                    "severity": "fatal",
                    "fail_closed_reason": flags.fail_closed_reason,
                },
            )
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "ui_disabled",
                "user_message": "La interfaz operativa no está habilitada.",
                "next_action": "Espere activación UI_ENABLED o use Power Automate.",
                "severity": "fatal",
            },
        )
    return flags


def require_history_enabled() -> UiFeatureFlags:
    """Historial UI/API: fail-closed si UI_HISTORY_ENABLED no es true."""
    flags = require_ui_enabled()
    if not flags.history_allowed:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "ui_history_disabled",
                "user_message": "El historial de procesos no está habilitado.",
                "next_action": "Use el Panel para procesos activos.",
                "severity": "fatal",
            },
        )
    return flags


def get_ui_principal(request: Request) -> UiPrincipal:
    principal = getattr(request.state, "ui_principal", None)
    if isinstance(principal, UiPrincipal):
        return principal
    # Permite tests que no montan middleware pero envían Bearer.
    auth = (request.headers.get("Authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        return resolve_principal(auth.split(None, 1)[1].strip())
    raise HTTPException(
        status_code=401,
        detail={
            "error_code": "missing_bearer",
            "user_message": "Falta Authorization Bearer.",
            "next_action": "Inicie sesión en la UI.",
            "severity": "fatal",
        },
    )


def get_projection_service() -> PaymentProcessProjectionService:
    return PaymentProcessProjectionService()


ControlSnapshotLoader = Callable[[str], object]
