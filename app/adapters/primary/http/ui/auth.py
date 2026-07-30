"""Autenticación UI: mock | entra | local_session. Prohibido api_key."""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any, Callable

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from app.application.ui.entra_jwt import EntraTokenError, validate_entra_access_token
from app.application.ui.environment import resolve_active_environment
from app.application.ui.feature_flags import get_ui_feature_flags
from app.application.ui.local_auth import resolve_session_from_request

_PUBLIC_UI_EXACT = frozenset(
    {
        "/api/ui/v1/bootstrap",
        "/api/ui/v1/auth/login",
    }
)
# Logout: exige Origin en el handler; sesión opcional (idempotente).
_SESSION_OPTIONAL_EXACT = frozenset({"/api/ui/v1/auth/logout"})


@dataclass(frozen=True)
class UiPrincipal:
    subject: str
    name: str | None
    roles: tuple[str, ...]
    auth_mode: str


def _normalize_path(path: str) -> str:
    normalized = (path or "").strip() or "/"
    if normalized != "/" and normalized.endswith("/"):
        normalized = normalized.rstrip("/")
    return normalized or "/"


def is_ui_bootstrap_path(path: str) -> bool:
    return _normalize_path(path) == "/api/ui/v1/bootstrap"


def is_ui_public_auth_path(path: str) -> bool:
    return _normalize_path(path) in _PUBLIC_UI_EXACT


def _unauthorized(detail: dict[str, Any], status: int = 401) -> JSONResponse:
    return JSONResponse(status_code=status, content=detail)


def _ui_disabled_response(*, fail_closed: bool, reason: str | None) -> JSONResponse:
    if fail_closed:
        return _unauthorized(
            {
                "error_code": "ui_misconfigured_fail_closed",
                "user_message": (
                    "La interfaz operativa está deshabilitada por configuración insegura."
                ),
                "next_action": (
                    "Corrija UI_AUTH_MODE / credenciales locales o Entra. "
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


def _http_from_entra_error(exc: EntraTokenError) -> HTTPException:
    status = 403 if exc.error_code == "insufficient_scope_or_role" else 401
    return HTTPException(
        status_code=status,
        detail={
            "error_code": exc.error_code,
            "user_message": exc.user_message,
            "next_action": exc.next_action,
            "severity": "fatal",
        },
    )


def authenticate_mock(token: str) -> UiPrincipal:
    if resolve_active_environment().environment == "production":
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "mock_forbidden_in_production",
                "user_message": "La autenticación mock no está permitida en producción.",
                "next_action": "Use UI_AUTH_MODE=local_session o entra.",
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
    try:
        payload = validate_entra_access_token(token)
    except EntraTokenError as exc:
        raise _http_from_entra_error(exc) from exc

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
    if flags.ui_auth_mode == "local_session":
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "session_required",
                "user_message": "Se requiere sesión local (cookie), no Bearer.",
                "next_action": "Inicie sesión en /app.",
                "severity": "fatal",
            },
        )
    return authenticate_mock(token)


class UiAuthMiddleware(BaseHTTPMiddleware):
    """Auth UI bajo ``/api/ui``: sesión local, Bearer Entra o mock."""

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

        if is_ui_public_auth_path(path):
            return await call_next(request)

        if flags.ui_auth_mode == "local_session":
            if _normalize_path(path) in _SESSION_OPTIONAL_EXACT:
                user = resolve_session_from_request(request)
                if user is not None:
                    request.state.ui_principal = UiPrincipal(
                        subject=user.username,
                        name=user.username,
                        roles=(user.role,),
                        auth_mode="local_session",
                    )
                    request.state.ui_local_user = user
                return await call_next(request)
            user = resolve_session_from_request(request)
            if user is None:
                return _unauthorized(
                    {
                        "error_code": "missing_or_invalid_session",
                        "user_message": "Sesión no válida o expirada.",
                        "next_action": "Inicie sesión de nuevo en la UI.",
                        "severity": "fatal",
                    }
                )
            request.state.ui_principal = UiPrincipal(
                subject=user.username,
                name=user.username,
                roles=(user.role,),
                auth_mode="local_session",
            )
            request.state.ui_local_user = user
            return await call_next(request)

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
    add_middleware = getattr(app, "add_middleware", None)
    if callable(add_middleware):
        add_middleware(UiAuthMiddleware, path_prefix=path_prefix)
