"""Descarga de PDFs de extracto vía Graph con reintentos acotados (fail-closed al final)."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_RETRYABLE_HTTP_STATUS = frozenset({429, 500, 502, 503, 504})
_GRAPH_DOWNLOAD_MAX_ATTEMPTS = 3
_GRAPH_DOWNLOAD_BACKOFF_SEC = (0.5, 1.5)


def graph_download_error_detail(exc: BaseException) -> str:
    if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
        return f"HTTP {exc.response.status_code}"
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    return type(exc).__name__


def is_transient_graph_download_error(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
        return exc.response.status_code in _RETRYABLE_HTTP_STATUS
    return False


async def get_graph_bytes_with_retry(
    client: Any,
    endpoint: str,
    *,
    max_attempts: int = _GRAPH_DOWNLOAD_MAX_ATTEMPTS,
) -> bytes:
    """Reintenta solo errores transitorios; propaga el último error si agota intentos."""
    last_exc: BaseException | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return await client.get_bytes(endpoint)
        except Exception as exc:
            last_exc = exc
            if attempt >= max_attempts or not is_transient_graph_download_error(exc):
                raise
            delay = _GRAPH_DOWNLOAD_BACKOFF_SEC[
                min(attempt - 1, len(_GRAPH_DOWNLOAD_BACKOFF_SEC) - 1)
            ]
            logger.warning(
                "graph_download_retry attempt=%s/%s detail=%s",
                attempt,
                max_attempts,
                graph_download_error_detail(exc),
            )
            await asyncio.sleep(delay)
    assert last_exc is not None
    raise last_exc
