"""Utilidades compartidas para repositorios de listas técnicas."""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any, Callable, Awaitable

import httpx

from app.application.services.extract_index.odata import and_filters, eq_string
from app.domain.exceptions import ExtractIndexError
from app.domain.ports.graph import GraphApiPort

logger = logging.getLogger(__name__)


async def find_list_id_by_display_name(
    graph: GraphApiPort, *, site_id: str, display_name: str
) -> str:
    endpoint: str | None = f"/sites/{site_id}/lists?$top=100"
    while endpoint:
        page = await graph.get(endpoint)
        for item in page.get("value") or []:
            if str(item.get("displayName") or "") == display_name:
                list_id = str(item.get("id") or "").strip()
                if not list_id:
                    raise ExtractIndexError(
                        f"Lista {display_name!r} sin id en Graph"
                    )
                return list_id
        next_link = page.get("@odata.nextLink")
        if not next_link or not isinstance(next_link, str):
            break
        marker = "/v1.0/"
        endpoint = (
            next_link.split(marker, 1)[1] if marker in next_link else next_link.lstrip("/")
        )
    raise ExtractIndexError(
        f"Lista {display_name!r} no encontrada en el sitio (no se creará automáticamente)"
    )


def next_endpoint_from_page(page: dict[str, Any]) -> str | None:
    next_link = page.get("@odata.nextLink")
    if not next_link or not isinstance(next_link, str):
        return None
    marker = "/v1.0/"
    return next_link.split(marker, 1)[1] if marker in next_link else next_link.lstrip("/")


async def paginate_list_items(
    graph: GraphApiPort,
    *,
    site_id: str,
    list_id: str,
    filter_expr: str | None = None,
    expand_fields: bool = True,
    page_size: int = 100,
) -> list[dict[str, Any]]:
    """Lee todos los ítems con filtro OData y paginación @odata.nextLink."""
    parts: list[str] = []
    if expand_fields:
        parts.append("$expand=fields")
    if filter_expr:
        parts.append(f"$filter={filter_expr}")
    parts.append(f"$top={page_size}")
    qs = "&".join(parts)
    endpoint: str | None = f"/sites/{site_id}/lists/{list_id}/items?{qs}"
    items: list[dict[str, Any]] = []
    while endpoint:
        page = await graph.get(endpoint)
        items.extend(page.get("value") or [])
        endpoint = next_endpoint_from_page(page)
    return items


def environment_and_field_filter(
    *, environment: str, field_name: str, field_value: str
) -> str:
    return and_filters(
        eq_string("ENVIRONMENT", environment),
        eq_string(field_name, field_value),
    )


async def with_graph_retries(
    operation: Callable[[], Awaitable[Any]],
    *,
    max_retries: int,
    base_seconds: float,
    label: str,
) -> Any:
    """Reintentos ante 429 / 503 / 504; no oculta 403/401/400 de permisos/schema."""
    last_exc: BaseException | None = None
    for attempt in range(max_retries):
        try:
            return await operation()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status in (401, 403):
                raise ExtractIndexError(
                    f"{label}: permiso denegado HTTP {status}: "
                    f"{(exc.response.text or '')[:400]}"
                ) from exc
            if status in (400, 404):
                raise ExtractIndexError(
                    f"{label}: error cliente HTTP {status}: "
                    f"{(exc.response.text or '')[:400]}"
                ) from exc
            if status in (429, 503, 504) and attempt < max_retries - 1:
                retry_after = exc.response.headers.get("Retry-After")
                try:
                    delay = float(retry_after) if retry_after else base_seconds * (2**attempt)
                except ValueError:
                    delay = base_seconds * (2**attempt)
                delay = min(60.0, delay + random.uniform(0, 0.25))
                logger.warning(
                    "extract_index_graph_retry label=%s status=%s attempt=%s delay=%.2f",
                    label,
                    status,
                    attempt + 1,
                    delay,
                )
                await asyncio.sleep(delay)
                last_exc = exc
                continue
            raise
        except httpx.TransportError as exc:
            if attempt < max_retries - 1:
                delay = min(60.0, base_seconds * (2**attempt) + random.uniform(0, 0.25))
                logger.warning(
                    "extract_index_graph_transport_retry label=%s attempt=%s delay=%.2f",
                    label,
                    attempt + 1,
                    delay,
                )
                await asyncio.sleep(delay)
                last_exc = exc
                continue
            raise ExtractIndexError(f"{label}: error de transporte Graph") from exc
    assert last_exc is not None
    raise last_exc
