"""Fake GraphApiPort para tests del índice (sin red)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs

import httpx


@dataclass
class FakeGraphCall:
    method: str
    endpoint: str
    body: dict[str, Any] | None = None


@dataclass
class FakeMsGraph:
    """Implementa GraphApiPort en memoria con soporte de listas e ítems."""

    lists_by_display: dict[str, str] = field(default_factory=dict)
    columns_by_list: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    items_by_list: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    calls: list[FakeGraphCall] = field(default_factory=list)
    document_gets: list[str] = field(default_factory=list)
    fail_statuses: list[int] = field(default_factory=list)
    _next_item_id: int = 1

    def document_mutation_count(self) -> int:
        return sum(
            1
            for c in self.calls
            if c.method in ("POST", "PUT", "PATCH", "DELETE")
            and "/drives/" in c.endpoint
            and "/lists/" not in c.endpoint
        )

    async def get(
        self, endpoint: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        self._maybe_fail("GET", endpoint)
        self.calls.append(FakeGraphCall("GET", endpoint))
        path = endpoint.split("?", 1)[0]
        query = endpoint.split("?", 1)[1] if "?" in endpoint else ""

        if "/lists?" in endpoint or endpoint.rstrip("/").endswith("/lists"):
            return {
                "value": [
                    {"id": lid, "displayName": name}
                    for name, lid in self.lists_by_display.items()
                ]
            }

        if "/columns" in path:
            list_id = path.split("/lists/")[1].split("/")[0]
            return {"value": list(self.columns_by_list.get(list_id, []))}

        if "/items" in path and "/lists/" in path:
            list_id = path.split("/lists/")[1].split("/")[0]
            items = list(self.items_by_list.get(list_id, []))
            filter_expr = parse_qs(query).get("$filter", [None])[0]
            if filter_expr:
                items = [it for it in items if self._matches_filter(it, filter_expr)]
            # Paginación simple: $top + continuation via fake nextLink header in state
            top_raw = parse_qs(query).get("$top", ["100"])[0]
            try:
                top = int(top_raw or "100")
            except ValueError:
                top = 100
            skip_token = parse_qs(query).get("$skiptoken", ["0"])[0]
            try:
                skip = int(skip_token or "0")
            except ValueError:
                skip = 0
            page = items[skip : skip + top]
            result: dict[str, Any] = {"value": page}
            if skip + top < len(items):
                base = path
                result["@odata.nextLink"] = (
                    f"https://graph.microsoft.com/v1.0{base}"
                    f"?$expand=fields&$filter={filter_expr or ''}"
                    f"&$top={top}&$skiptoken={skip + top}"
                )
            return result

        if "/drives/" in path:
            self.document_gets.append(endpoint)
            return {"id": "drive-item", "name": "readonly"}

        return {"value": []}

    async def get_bytes(
        self, endpoint: str, params: dict[str, Any] | None = None
    ) -> bytes:
        self._maybe_fail("GET_BYTES", endpoint)
        self.calls.append(FakeGraphCall("GET_BYTES", endpoint))
        self.document_gets.append(endpoint)
        return b"%PDF-fake"

    async def put_bytes(
        self,
        endpoint: str,
        content: bytes,
        content_type: str = "application/octet-stream",
        if_match: str | None = None,
    ) -> dict[str, Any]:
        self._maybe_fail("PUT", endpoint)
        self.calls.append(FakeGraphCall("PUT", endpoint))
        return {"ok": True}

    async def post_json(
        self, endpoint: str, body: dict[str, Any]
    ) -> tuple[dict[str, Any], int]:
        self._maybe_fail("POST", endpoint)
        self.calls.append(FakeGraphCall("POST", endpoint, body))
        if "/lists/" in endpoint and endpoint.rstrip("/").endswith("/items"):
            list_id = endpoint.split("/lists/")[1].split("/")[0]
            item_id = str(self._next_item_id)
            self._next_item_id += 1
            item = {"id": item_id, "fields": dict(body.get("fields") or {})}
            self.items_by_list.setdefault(list_id, []).append(item)
            return item, 201
        return {}, 201

    async def patch_json(self, endpoint: str, body: dict[str, Any]) -> dict[str, Any]:
        self._maybe_fail("PATCH", endpoint)
        self.calls.append(FakeGraphCall("PATCH", endpoint, body))
        # /sites/.../lists/{id}/items/{itemId}/fields
        if "/lists/" in endpoint and "/items/" in endpoint:
            list_id = endpoint.split("/lists/")[1].split("/")[0]
            item_id = endpoint.split("/items/")[1].split("/")[0]
            for it in self.items_by_list.get(list_id, []):
                if str(it.get("id")) == item_id:
                    fields = it.setdefault("fields", {})
                    fields.update(body)
                    return {"id": item_id, "fields": fields}
        return body

    async def delete(self, endpoint: str) -> None:
        self._maybe_fail("DELETE", endpoint)
        self.calls.append(FakeGraphCall("DELETE", endpoint))

    def _maybe_fail(self, method: str, endpoint: str) -> None:
        if not self.fail_statuses:
            return
        status = self.fail_statuses.pop(0)
        request = httpx.Request(method, f"https://graph.microsoft.com/v1.0/{endpoint}")
        response = httpx.Response(status, request=request, text=f"forced {status}")
        raise httpx.HTTPStatusError(
            f"forced {status}", request=request, response=response
        )

    def _matches_filter(self, item: dict[str, Any], filter_expr: str) -> bool:
        """Soporta predicados simples fields/X eq 'Y' unidos por and."""
        fields = item.get("fields") or {}
        # Quitar paréntesis
        expr = filter_expr.replace("(", "").replace(")", "")
        parts = [p.strip() for p in expr.split(" and ")]
        for part in parts:
            if " eq " not in part:
                continue
            left, right = part.split(" eq ", 1)
            field_name = left.replace("fields/", "").strip()
            value = right.strip()
            if value.startswith("'") and value.endswith("'"):
                value = value[1:-1].replace("''", "'")
            actual = str(fields.get(field_name) or "")
            if actual != value:
                return False
        return True
