"""
Prueba de capacidad: ítems en listas técnicas ya creadas a mano.

No crea el contenedor de lista (403 conocido). Solo localiza
``INDICE_EXTRACTOS`` / ``CONTROL_INDICE_EXTRACTOS``, crea un ítem temporal,
lo lee y lo borra.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.application.sharepoint_resolution import resolve_sharepoint_from_env
from app.domain.ports.graph import GraphApiPort

TARGET_LISTS: tuple[str, ...] = ("INDICE_EXTRACTOS", "CONTROL_INDICE_EXTRACTOS")
TEST_ITEM_TITLE = "_HBI_LIST_ITEM_CAPABILITY_TEST_DELETE_ME"


async def _find_list_by_display_name(
    graph: GraphApiPort, site_id: str, display_name: str
) -> dict[str, Any] | None:
    endpoint = f"/sites/{site_id}/lists?$top=100"
    while endpoint:
        page = await graph.get(endpoint)
        for item in page.get("value") or []:
            if str(item.get("displayName") or "") == display_name:
                return item
        next_link = page.get("@odata.nextLink")
        if not next_link or not isinstance(next_link, str):
            break
        marker = "/v1.0/"
        endpoint = (
            next_link.split(marker, 1)[1] if marker in next_link else next_link.lstrip("/")
        )
    return None


async def probe_existing_lists_item_crud(graph: GraphApiPort) -> dict[str, Any]:
    """Ejecuta el sondeo create/read/delete de ítems sobre las dos listas objetivo."""
    try:
        ctx = await resolve_sharepoint_from_env(graph)
    except Exception as exc:
        return {
            "status": "error",
            "phase": "resolve_site",
            "error_type": exc.__class__.__name__,
            "detail": str(exc)[:600],
            "capability_result": "FAIL",
        }

    site_id = ctx["site_id"]
    results: list[dict[str, Any]] = []

    for list_name in TARGET_LISTS:
        entry: dict[str, Any] = {"list_display_name": list_name}
        found = await _find_list_by_display_name(graph, site_id, list_name)
        if not found:
            entry["status"] = "missing"
            entry["detail"] = "Lista no encontrada en el sitio Operaciones."
            results.append(entry)
            continue

        list_id = str(found.get("id") or "")
        entry["list_id"] = list_id
        entry["web_url"] = found.get("webUrl")

        try:
            created, create_http = await graph.post_json(
                f"/sites/{site_id}/lists/{list_id}/items",
                {"fields": {"Title": TEST_ITEM_TITLE}},
            )
        except httpx.HTTPStatusError as exc:
            entry["status"] = "fail_create_item"
            entry["http_status"] = exc.response.status_code
            entry["detail"] = (exc.response.text or "")[:600]
            results.append(entry)
            continue
        except Exception as exc:
            entry["status"] = "fail_create_item"
            entry["error_type"] = exc.__class__.__name__
            entry["detail"] = str(exc)[:600]
            results.append(entry)
            continue

        item_id = str(created.get("id") or "")
        entry["create_http"] = create_http
        entry["item_id"] = item_id
        if not item_id:
            entry["status"] = "fail_create_item"
            entry["detail"] = "Graph no devolvió id de ítem"
            results.append(entry)
            continue

        try:
            read = await graph.get(
                f"/sites/{site_id}/lists/{list_id}/items/{item_id}?$expand=fields"
            )
            fields = read.get("fields") if isinstance(read.get("fields"), dict) else {}
            entry["read_title"] = fields.get("Title")
        except Exception as exc:
            entry["status"] = "fail_read_item"
            entry["detail"] = str(exc)[:600]
            entry["manual_cleanup_item"] = item_id
            results.append(entry)
            continue

        try:
            await graph.delete(f"/sites/{site_id}/lists/{list_id}/items/{item_id}")
            entry["deleted"] = True
        except httpx.HTTPStatusError as exc:
            entry["status"] = "fail_delete_item"
            entry["http_status"] = exc.response.status_code
            entry["detail"] = (exc.response.text or "")[:400]
            entry["manual_cleanup_item"] = item_id
            results.append(entry)
            continue

        entry["status"] = "ok"
        results.append(entry)

    failed = [r["list_display_name"] for r in results if r.get("status") != "ok"]
    missing = [r["list_display_name"] for r in results if r.get("status") == "missing"]
    all_ok = len(results) == len(TARGET_LISTS) and not failed

    return {
        "status": "ok" if all_ok else "error",
        "capability_result": "PASS" if all_ok else "FAIL",
        "mode": "item_crud_on_existing_lists",
        "site_id_prefix": site_id[:32],
        "lists": results,
        "missing_lists": missing,
        "failed_lists": failed,
        "note": (
            "Prueba de ítems (crear/leer/borrar) sobre listas ya existentes. "
            "No intenta crear el contenedor de lista (403 conocido)."
        ),
    }
