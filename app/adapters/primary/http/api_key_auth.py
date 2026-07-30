"""
Autenticación HTTP por API Key (header ``X-API-Key``).

Diseño aditivo y seguro para entrega bancaria:

* Si ``API_HTTP_KEY`` está vacío → no se exige clave (tests locales / arranque
  sin configurar). El comportamiento previo de la API se conserva.
* Si ``API_HTTP_KEY`` tiene valor → toda ruta exige el mismo valor en
  ``X-API-Key``, excepto las rutas públicas exactas documentadas abajo.

Power Automate: añadir header ``X-API-Key`` = valor del secreto en cada HTTP
(POST de cola y GET de jobs). URI, método y body no cambian.

Excepciones públicas (normalizadas, sin ``startswith("/api/ui")`` suelto):

* ``/health``
* ``/app`` y ``/app/*`` (SPA; Entra en el browser)
* ``/api/ui/v1`` y ``/api/ui/v1/*`` (protegidos por Bearer Entra, excepto bootstrap)
"""

from __future__ import annotations

import hmac
import logging
import os
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

ENV_API_HTTP_KEY = "API_HTTP_KEY"
HEADER_API_KEY = "x-api-key"

_PUBLIC_EXACT_PATHS = frozenset(
    {
        "/health",
        "/app",
        "/api/ui/v1/bootstrap",
    }
)


def resolve_configured_api_http_key() -> str:
    """Secreto configurado; cadena vacía = auth desactivada."""
    return (os.getenv(ENV_API_HTTP_KEY) or "").strip()


def normalize_request_path(path: str) -> str:
    normalized = (path or "").strip() or "/"
    if normalized != "/" and normalized.endswith("/"):
        normalized = normalized.rstrip("/")
    return normalized or "/"


def is_public_path(path: str) -> bool:
    """True si la ruta no exige API Key aunque la auth esté activa."""
    normalized = normalize_request_path(path)
    if normalized in _PUBLIC_EXACT_PATHS:
        return True
    if normalized.startswith("/app/"):
        return True
    # Solo el prefijo exacto /api/ui/v1 (no /api/ui, /api/ui2, /api/ui-extra).
    if normalized == "/api/ui/v1" or normalized.startswith("/api/ui/v1/"):
        return True
    return False


def _extract_presented_key(request: Request) -> str:
    return (request.headers.get(HEADER_API_KEY) or "").strip()


def keys_match(*, presented: str, expected: str) -> bool:
    """Comparación en tiempo constante (evita timing attacks básicos)."""
    if not presented or not expected:
        return False
    return hmac.compare_digest(presented.encode("utf-8"), expected.encode("utf-8"))


class ApiKeyAuthMiddleware(BaseHTTPMiddleware):
    """Middleware: exige ``X-API-Key`` solo si ``API_HTTP_KEY`` está definido."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        expected = resolve_configured_api_http_key()
        if not expected:
            return await call_next(request)

        if is_public_path(request.url.path):
            return await call_next(request)

        presented = _extract_presented_key(request)
        if not presented:
            logger.warning(
                "api_key_auth: missing X-API-Key path=%s method=%s",
                request.url.path,
                request.method,
            )
            return JSONResponse(
                status_code=401,
                content={
                    "detail": "missing_api_key",
                    "user_message": (
                        "Falta el encabezado de seguridad X-API-Key. "
                        "Configure la clave en Power Automate (Headers) y en la API."
                    ),
                },
            )

        if not keys_match(presented=presented, expected=expected):
            logger.warning(
                "api_key_auth: invalid X-API-Key path=%s method=%s",
                request.url.path,
                request.method,
            )
            return JSONResponse(
                status_code=401,
                content={
                    "detail": "invalid_api_key",
                    "user_message": (
                        "La clave X-API-Key no es válida. "
                        "Verifique que coincida con API_HTTP_KEY del servidor."
                    ),
                },
            )

        return await call_next(request)


def install_api_key_auth(app: object) -> None:
    """Registra el middleware en una app FastAPI/Starlette."""
    add_middleware = getattr(app, "add_middleware", None)
    if callable(add_middleware):
        add_middleware(ApiKeyAuthMiddleware)
