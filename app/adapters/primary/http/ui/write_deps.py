"""Puerta de escritura U3-A para endpoints POST autenticados de la UI.

Orden de chequeo (401 solo por sesión/Bearer; el resto son 403 fatal):
identidad válida (cookie local_session o Bearer mock en sandbox) →
rol operator → Origin permitido → Content-Type JSON →
CSRF (solo local_session) → `UI_WRITE_ENABLED` → `ACTIVE_ENVIRONMENT=sandbox`.
"""
from __future__ import annotations

import time

from fastapi import HTTPException, Request

from app.application.ui.environment import resolve_active_environment
from app.application.ui.feature_flags import get_ui_feature_flags
from app.application.ui.local_auth import (
    AuthenticatedLocalUser,
    resolve_session_from_request,
    validate_csrf_header,
    validate_same_origin,
)

# TTL sintético para operador mock (solo sandbox local; no hay cookie).
_MOCK_WRITE_TTL_SECONDS = 8 * 3600


def _err(status: int, error_code: str, user_message: str, next_action: str) -> HTTPException:
    return HTTPException(
        status_code=status,
        detail={
            "error_code": error_code,
            "user_message": user_message,
            "next_action": next_action,
            "severity": "fatal",
        },
    )


def _content_type_is_json(request: Request) -> bool:
    raw = (request.headers.get("content-type") or "").strip().lower()
    if not raw:
        return False
    # "application/json" o "application/json; charset=utf-8" (cualquier charset).
    media = raw.split(";", 1)[0].strip()
    return media == "application/json"


def _roles_include_operator(roles: tuple[str, ...] | list[str]) -> bool:
    return any(str(role).strip().lower() == "operator" for role in roles)


def _mock_operator_from_principal(principal: object) -> AuthenticatedLocalUser | None:
    """Operador sintético desde Bearer mock (sandbox local; sin CSRF)."""
    auth_mode = str(getattr(principal, "auth_mode", "") or "")
    if auth_mode != "mock":
        return None
    roles_raw = getattr(principal, "roles", ()) or ()
    roles = tuple(str(r) for r in roles_raw)
    if not _roles_include_operator(roles):
        return None
    subject = str(getattr(principal, "subject", None) or "mock-user")
    return AuthenticatedLocalUser(
        username=subject,
        role="operator",
        auth_mode="mock",
        expires_at=time.time() + _MOCK_WRITE_TTL_SECONDS,
        token_hash="mock-bearer",
    )


def _resolve_write_user(request: Request) -> AuthenticatedLocalUser | None:
    user = getattr(request.state, "ui_local_user", None)
    if user is not None:
        return user
    user = resolve_session_from_request(request)
    if user is not None:
        return user
    flags = get_ui_feature_flags()
    if flags.ui_auth_mode != "mock":
        return None
    env = resolve_active_environment()
    if env.environment != "sandbox":
        return None
    principal = getattr(request.state, "ui_principal", None)
    if principal is None:
        return None
    return _mock_operator_from_principal(principal)


def require_write_access(request: Request) -> AuthenticatedLocalUser:
    """Dependencia FastAPI para POST de escritura (`Depends(require_write_access)`)."""
    user = _resolve_write_user(request)
    if user is None:
        flags = get_ui_feature_flags()
        if flags.ui_auth_mode == "mock":
            raise _err(
                401,
                "missing_or_invalid_session",
                "No hay identidad de operador válida (Bearer mock).",
                "Use Authorization: Bearer mock-user en desarrollo local sandbox.",
            )
        raise _err(
            401,
            "missing_or_invalid_session",
            "Sesión no válida o expirada.",
            "Inicie sesión de nuevo en la UI.",
        )

    if (user.role or "").strip().lower() != "operator":
        raise _err(
            403,
            "role_not_allowed",
            "Su rol no tiene permiso para esta acción.",
            "Contacte a un administrador si necesita permisos de operador.",
        )

    if not validate_same_origin(request):
        raise _err(
            403,
            "invalid_origin",
            "Origen de la petición no permitido.",
            "Acceda a la UI desde el host autorizado.",
        )

    if not _content_type_is_json(request):
        raise _err(
            403,
            "invalid_content_type",
            "El cuerpo de la petición debe enviarse como JSON.",
            "Envíe el header Content-Type: application/json.",
        )

    # CSRF solo aplica a cookie local_session; mock Bearer no tiene token CSRF.
    if user.auth_mode != "mock" and not validate_csrf_header(request, user):
        raise _err(
            403,
            "invalid_csrf_token",
            "Token CSRF inválido o ausente.",
            "Solicite un token vigente en GET /api/ui/v1/auth/csrf y reintente.",
        )

    flags = get_ui_feature_flags()
    if not flags.ui_write_enabled:
        raise _err(
            403,
            "ui_write_disabled",
            "Las escrituras desde la UI están deshabilitadas en este ambiente.",
            "Contacte a soporte para activar la escritura UI en sandbox.",
        )

    env = resolve_active_environment()
    if env.environment != "sandbox":
        raise _err(
            403,
            "write_only_in_sandbox",
            "Las escrituras desde la UI solo están habilitadas en sandbox.",
            "No continúe; esta fase no admite escritura en producción.",
        )

    return user


def require_finalize_access(request: Request) -> AuthenticatedLocalUser:
    """Gate Finalize: write gate + `UI_FINALIZE_ENABLED` (fail-closed).

    Con flag false: 403 **antes** de lock, job o Graph.
    """
    user = require_write_access(request)
    flags = get_ui_feature_flags()
    if not flags.ui_finalize_enabled:
        raise _err(
            403,
            "ui_finalize_disabled",
            "Finalize desde la UI todavía no está habilitado.",
            "Espere la activación controlada de UI_FINALIZE_ENABLED en sandbox.",
        )
    return user


def require_notify_access(request: Request) -> AuthenticatedLocalUser:
    """Gate Notify: write gate + `UI_NOTIFY_ENABLED`.

    Destinatarios efectivos: `CORREOS.xlsx` (igual que Power Automate sin
    override). Con flag false: 403 **antes** de lock, job, Graph o sendMail.
    """
    user = require_write_access(request)
    flags = get_ui_feature_flags()
    if not flags.ui_notify_enabled:
        raise _err(
            403,
            "ui_notify_disabled",
            "Notify desde la UI todavía no está habilitado.",
            "Espere la activación controlada de UI_NOTIFY_ENABLED en sandbox.",
        )
    return user


def require_merge_access(request: Request) -> AuthenticatedLocalUser:
    """Gate Merge: write gate + `UI_MERGE_ENABLED` (fail-closed).

    Con flag false: 403 **antes** de lock, job, Graph, readiness o archivos.
    No habilita Dry-run ni Apply.
    """
    user = require_write_access(request)
    flags = get_ui_feature_flags()
    if not flags.ui_merge_enabled:
        raise _err(
            403,
            "ui_merge_disabled",
            "Merge desde la UI todavía no está habilitado.",
            "Espere la activación controlada de UI_MERGE_ENABLED en sandbox.",
        )
    return user


def require_amortization_access(request: Request) -> AuthenticatedLocalUser:
    """Gate Amortización: write gate + `UI_AMORTIZATION_ENABLED` (fail-closed).

    Con flag false: 403 **antes** de lock, job, Graph, readiness o archivos.
    Única acción de operador; no habilita Dry-run ni Apply por separado.
    """
    user = require_write_access(request)
    flags = get_ui_feature_flags()
    if not flags.ui_amortization_enabled:
        raise _err(
            403,
            "ui_amortization_disabled",
            "Procesar amortización desde la UI todavía no está habilitado.",
            "Espere la activación controlada de UI_AMORTIZATION_ENABLED en sandbox.",
        )
    return user


def require_review_edit_access(request: Request) -> AuthenticatedLocalUser:
    """Gate edición revisión R1: write gate + `UI_REVIEW_EDIT_ENABLED`."""
    user = require_write_access(request)
    flags = get_ui_feature_flags()
    if not flags.ui_review_edit_enabled:
        raise _err(
            403,
            "ui_review_edit_disabled",
            "La edición de la revisión desde la UI todavía no está habilitada.",
            "Espere la activación controlada de UI_REVIEW_EDIT_ENABLED en sandbox.",
        )
    return user


def require_review_finalize_access(request: Request) -> AuthenticatedLocalUser:
    """Gate Finalize atómico R2: write + review edit + finalize flags."""
    user = require_review_edit_access(request)
    flags = get_ui_feature_flags()
    if not flags.ui_finalize_enabled:
        raise _err(
            403,
            "ui_finalize_disabled",
            "Finalize desde la UI todavía no está habilitado.",
            "Espere la activación controlada de UI_FINALIZE_ENABLED en sandbox.",
        )
    return user


def require_asientos_upload_access(request: Request) -> AuthenticatedLocalUser:
    """Gate upload asientos R3: write gate + `UI_ASIENTOS_UPLOAD_ENABLED`."""
    user = require_write_access(request)
    flags = get_ui_feature_flags()
    if not flags.ui_asientos_upload_enabled:
        raise _err(
            403,
            "ui_asientos_upload_disabled",
            "La carga de asientos desde la UI todavía no está habilitada.",
            "Espere la activación controlada de UI_ASIENTOS_UPLOAD_ENABLED en sandbox.",
        )
    return user
