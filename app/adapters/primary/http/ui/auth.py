"""Autenticación UI: mock | entra. Prohibido api_key.

Instalable en una app FastAPI aislada (tests / futura integración).
Nunca se registra desde app_factory en esta feature branch.
"""
from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from typing import Any, Callable

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from app.application.ui.environment import resolve_active_environment
from app.application.ui.feature_flags import get_ui_feature_flags


@dataclass(frozen=True)
class UiPrincipal:
    subject: str
    name: str | None
    roles: tuple[str, ...]
    auth_mode: str


def _unauthorized(detail: dict[str, Any], status: int = 401) -> JSONResponse:
    return JSONResponse(status_code=status, content=detail)


def _ui_disabled_response(*, fail_closed: bool, reason: str | None) -> JSONResponse:
    if fail_closed:
        return _unauthorized(
            {
                "error_code": "ui_misconfigured_fail_closed",
                "user_message": (
                    "La interfaz operativa está deshabilitada por configuración insegura "
                    "(producción no admite autenticación mock)."
                ),
                "next_action": (
                    "Configure UI_AUTH_MODE=entra en producción o use sandbox con mock. "
                    "Power Automate (/graph/*) no se ve afectado."
                ),
                "severity": "fatal",
                "fail_closed_reason": reason,
            },
            status=404,
        )
    return _unauthorized(
        {
            "error_code": "ui_disabled",
            "user_message": "La interfaz operativa no está habilitada.",
            "next_action": "Contacte a soporte o espere el despliegue con UI_ENABLED=true.",
            "severity": "fatal",
        },
        status=404,
    )


def _parse_bearer(request: Request) -> str | None:
    header = (request.headers.get("Authorization") or "").strip()
    if not header:
        return None
    parts = header.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None


def _decode_jwt_payload_unverified(token: str) -> dict[str, Any]:
    """Solo para modo mock / estructura; entra real validará firma en integración."""
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return {}
        payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
        raw = base64.urlsafe_b64decode(payload_b64.encode("ascii"))
        data = json.loads(raw.decode("utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def authenticate_mock(token: str) -> UiPrincipal:
    # Mock nunca autentica en producción (defensa en profundidad además del flag).
    if resolve_active_environment().environment == "production":
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "mock_forbidden_in_production",
                "user_message": "La autenticación mock no está permitida en producción.",
                "next_action": "Use UI_AUTH_MODE=entra con un token válido de Entra ID.",
                "severity": "fatal",
            },
        )
    if token in {"", "invalid"}:
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "invalid_bearer",
                "user_message": "Token Bearer inválido.",
                "next_action": "Use Authorization: Bearer mock-user en desarrollo local.",
                "severity": "fatal",
            },
        )
    payload = _decode_jwt_payload_unverified(token) if token.count(".") >= 2 else {}
    subject = str(payload.get("sub") or token or "mock-user")
    name = str(payload.get("name") or subject)
    roles_raw = payload.get("roles") or ["Operator"]
    if isinstance(roles_raw, str):
        roles = (roles_raw,)
    elif isinstance(roles_raw, list):
        roles = tuple(str(r) for r in roles_raw)
    else:
        roles = ("Operator",)
    return UiPrincipal(subject=subject, name=name, roles=roles, auth_mode="mock")


def authenticate_entra(token: str) -> UiPrincipal:
    """Validación mínima U1: estructura + audience/tenant si hay env.

    La validación criptográfica completa (JWKS) se cablea en integración.
    """
    if not token or token.count(".") < 2:
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "invalid_bearer",
                "user_message": "Token Entra inválido.",
                "next_action": "Inicie sesión de nuevo en la UI.",
                "severity": "fatal",
            },
        )
    payload = _decode_jwt_payload_unverified(token)
    expected_aud = (os.getenv("UI_ENTRA_AUDIENCE") or "").strip()
    expected_tid = (os.getenv("UI_ENTRA_TENANT_ID") or "").strip()
    aud = payload.get("aud")
    tid = str(payload.get("tid") or payload.get("tenant_id") or "")
    if expected_aud:
        aud_ok = aud == expected_aud or (
            isinstance(aud, list) and expected_aud in aud
        )
        if not aud_ok:
            raise HTTPException(
                status_code=401,
                detail={
                    "error_code": "invalid_audience",
                    "user_message": "El token no corresponde a esta API.",
                    "next_action": "Verifique la app registration / audience.",
                    "severity": "fatal",
                },
            )
    if expected_tid and tid and tid != expected_tid:
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "invalid_tenant",
                "user_message": "El token no pertenece al tenant configurado.",
                "next_action": "Use una cuenta del tenant de HBI Capital.",
                "severity": "fatal",
            },
        )
    subject = str(payload.get("oid") or payload.get("sub") or "")
    if not subject:
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "invalid_bearer",
                "user_message": "Token Entra sin identidad.",
                "next_action": "Inicie sesión de nuevo.",
                "severity": "fatal",
            },
        )
    roles_raw = payload.get("roles") or []
    roles = tuple(str(r) for r in roles_raw) if isinstance(roles_raw, list) else ()
    name = str(payload.get("name") or payload.get("preferred_username") or subject)
    return UiPrincipal(subject=subject, name=name, roles=roles, auth_mode="entra")


def resolve_principal(token: str) -> UiPrincipal:
    flags = get_ui_feature_flags()
    if flags.ui_auth_mode == "entra":
        return authenticate_entra(token)
    return authenticate_mock(token)


class UiAuthMiddleware(BaseHTTPMiddleware):
    """Exige Bearer solo bajo ``/api/ui``."""

    def __init__(self, app: ASGIApp, path_prefix: str = "/api/ui") -> None:
        super().__init__(app)
        self._prefix = path_prefix.rstrip("/") or "/api/ui"

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Any],
    ) -> Response:
        path = request.url.path or ""
        if not path.startswith(self._prefix):
            return await call_next(request)

        flags = get_ui_feature_flags()
        if not flags.ui_enabled:
            return _ui_disabled_response(
                fail_closed=flags.fail_closed,
                reason=flags.fail_closed_reason,
            )

        token = _parse_bearer(request)
        if not token:
            return _unauthorized(
                {
                    "error_code": "missing_bearer",
                    "user_message": "Falta Authorization Bearer.",
                    "next_action": "Inicie sesión en la UI.",
                    "severity": "fatal",
                }
            )
        try:
            principal = resolve_principal(token)
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {
                "error_code": "unauthorized",
                "user_message": str(exc.detail),
                "severity": "fatal",
            }
            return _unauthorized(detail, status=exc.status_code)

        request.state.ui_principal = principal
        return await call_next(request)


def install_ui_auth(app: Any, *, path_prefix: str = "/api/ui") -> None:
    """Registra middleware UI. Usar solo desde tests o rama de integración."""
    add_middleware = getattr(app, "add_middleware", None)
    if callable(add_middleware):
        add_middleware(UiAuthMiddleware, path_prefix=path_prefix)
