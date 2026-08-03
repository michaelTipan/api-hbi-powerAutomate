"""Puerta de escritura U3-A para endpoints POST autenticados de la UI.

Orden de chequeo (401 solo por sesión; el resto son 403 fatal):
sesión válida → rol operator → Origin permitido → Content-Type JSON →
CSRF (``hmac.compare_digest``) → ``UI_WRITE_ENABLED`` → ``ACTIVE_ENVIRONMENT=sandbox``.
"""
from __future__ import annotations

from fastapi import HTTPException, Request

from app.application.ui.environment import resolve_active_environment
from app.application.ui.feature_flags import get_ui_feature_flags
from app.application.ui.local_auth import (
    AuthenticatedLocalUser,
    resolve_session_from_request,
    validate_csrf_header,
    validate_same_origin,
)


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


def require_write_access(request: Request) -> AuthenticatedLocalUser:
    """Dependencia FastAPI para POST de escritura (``Depends(require_write_access)``)."""
    user = getattr(request.state, "ui_local_user", None)
    if user is None:
        user = resolve_session_from_request(request)
    if user is None:
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

    if not validate_csrf_header(request, user):
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
    """Gate Finalize: write gate + ``UI_FINALIZE_ENABLED`` (fail-closed).

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
    """Gate Notify: write gate + ``UI_NOTIFY_ENABLED``.

    Destinatarios efectivos: ``CORREOS.xlsx`` (igual que Power Automate sin
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
    """Gate Merge: write gate + ``UI_MERGE_ENABLED`` (fail-closed).

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
    """Gate Amortización: write gate + ``UI_AMORTIZATION_ENABLED`` (fail-closed).

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
    """Gate edición revisión R1: write gate + ``UI_REVIEW_EDIT_ENABLED``."""
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
