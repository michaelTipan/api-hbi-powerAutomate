"""Cliente Graph GET-only exclusivo del smoke UI vía App Service.

NO es adaptador productivo. No importar desde ``app/``.
Requiere ``UI_SHAREPOINT_SMOKE=1``. Solo GET relativos vía API desplegada.
"""
from __future__ import annotations

import base64
import os
from typing import Any
from urllib.parse import unquote

import httpx


class AppServiceGraphHttp:
    """Proxy read-only para smoke: X-API-Key → endpoints GET /graph/* existentes."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        metrics: Any | None = None,
        timeout: float = 120.0,
    ) -> None:
        if (os.getenv("UI_SHAREPOINT_SMOKE") or "").strip() != "1":
            raise RuntimeError(
                "AppServiceGraphHttp solo puede usarse con UI_SHAREPOINT_SMOKE=1"
            )
        key = (api_key or "").strip()
        if not key:
            raise RuntimeError("API_HTTP_KEY requerido para smoke vía App Service")
        # Nunca loguear api_key / base con query secrets.
        self._base = base_url.rstrip("/")
        self._metrics = metrics
        self._site_id: str | None = None
        self._drive_id: str | None = None
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={"X-API-Key": key, "Accept": "application/json"},
        )

    def __repr__(self) -> str:
        return f"AppServiceGraphHttp(base={self._base!r}, key=***)"

    async def aclose(self) -> None:
        await self._client.aclose()

    def _count_get_json(self) -> None:
        if self._metrics is not None:
            self._metrics.get_json += 1

    def _count_get_bytes(self, n: int) -> None:
        if self._metrics is not None:
            self._metrics.get_bytes += 1
            self._metrics.bytes_downloaded += n

    def _reject_absolute(self, endpoint: str) -> str:
        ep = (endpoint or "").strip()
        if not ep:
            raise ValueError("graph_endpoint_empty")
        lower = ep.lower()
        if lower.startswith("http://") or lower.startswith("https://") or "://" in ep:
            raise ValueError("graph_absolute_url_forbidden")
        if "graph.microsoft.com" in lower:
            raise ValueError("graph_host_forbidden")
        if not ep.startswith("/"):
            raise ValueError("graph_endpoint_must_be_relative")
        return ep

    async def _ensure_ids(self) -> tuple[str, str]:
        if self._site_id and self._drive_id:
            return self._site_id, self._drive_id
        self._count_get_json()
        r = await self._client.get(f"{self._base}/graph/diagnostics")
        r.raise_for_status()
        data = r.json()
        ops = data.get("operations_site") or {}
        site_id = str(ops.get("site_id") or "")
        drive_id = str(ops.get("drive_id") or "")
        if not site_id or not drive_id:
            raise RuntimeError("diagnostics missing operations_site ids")
        self._site_id = site_id
        self._drive_id = drive_id
        return site_id, drive_id

    async def _resolve_item_by_path(self, drive_id: str, relative_path: str) -> dict[str, Any]:
        parts = [p for p in relative_path.strip("/").split("/") if p]
        item_id = "root"
        current: dict[str, Any] = {"id": "root", "name": "root"}
        for part in parts:
            self._count_get_json()
            r = await self._client.get(
                f"{self._base}/graph/sharepoint/drives/{drive_id}/children",
                params={"folder_item_id": item_id},
            )
            if r.status_code == 404:
                if self._metrics is not None:
                    self._metrics.expected_404 += 1
                raise FileNotFoundError(relative_path)
            r.raise_for_status()
            values = (r.json() or {}).get("value") or []
            match = next(
                (v for v in values if str(v.get("name") or "").strip() == part),
                None,
            )
            if match is None:
                if self._metrics is not None:
                    self._metrics.expected_404 += 1
                raise FileNotFoundError(f"{relative_path} (missing segment {part})")
            current = match
            item_id = str(match.get("id") or "")
            if not item_id:
                raise RuntimeError(f"child without id at {part}")
        return current

    def _parse_root_path(self, endpoint: str) -> tuple[str, str, bool]:
        marker = "/drives/"
        idx = endpoint.find(marker)
        if idx < 0:
            raise ValueError(f"unsupported endpoint: {endpoint}")
        rest = endpoint[idx + len(marker) :]
        drive_id, _, tail = rest.partition("/")
        if not tail.startswith("root:/"):
            raise ValueError(f"unsupported drive endpoint: {endpoint}")
        body = tail[len("root:/") :]
        is_content = False
        if body.endswith(":/content"):
            is_content = True
            body = body[: -len(":/content")]
        elif body.endswith(":"):
            body = body[:-1]
        relative = "/".join(unquote(p) for p in body.split("/") if p)
        return drive_id, relative, is_content

    async def get(self, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        ep = self._reject_absolute(endpoint)
        site_id, drive_id = await self._ensure_ids()

        if ep.startswith("/sites/") and ":/" in ep and "/drives/" not in ep:
            self._count_get_json()
            return {"id": site_id}

        if ep.startswith("/sites/") and ep.endswith("/drives"):
            self._count_get_json()
            r = await self._client.get(f"{self._base}/graph/sharepoint/sites/{site_id}/drives")
            r.raise_for_status()
            return r.json()

        if "/root:/" in ep:
            d_id, relative, is_content = self._parse_root_path(ep)
            if is_content:
                raise ValueError("use get_bytes for content endpoints")
            item = await self._resolve_item_by_path(d_id or drive_id, relative)
            return {
                "id": item.get("id"),
                "name": item.get("name"),
                "webUrl": item.get("webUrl"),
                "eTag": item.get("eTag"),
                "cTag": item.get("cTag"),
                "size": item.get("size"),
                "lastModifiedDateTime": item.get("lastModifiedDateTime"),
            }

        if ep.startswith("/sites") and "search" in (params or {}):
            self._count_get_json()
            r = await self._client.get(
                f"{self._base}/graph/sharepoint/sites-search",
                params={"search": params.get("search")},
            )
            r.raise_for_status()
            return r.json()

        raise ValueError(f"AppServiceGraphHttp unsupported GET: {ep}")

    async def get_bytes(self, endpoint: str, params: dict[str, Any] | None = None) -> bytes:
        ep = self._reject_absolute(endpoint)
        _, drive_id = await self._ensure_ids()
        d_id, relative, is_content = self._parse_root_path(ep)
        if not is_content:
            raise ValueError("get_bytes expects :/content endpoint")
        item = await self._resolve_item_by_path(d_id or drive_id, relative)
        item_id = str(item.get("id") or "")
        r = await self._client.get(
            f"{self._base}/graph/sharepoint/drives/{d_id or drive_id}/item-content",
            params={"item_id": item_id},
        )
        if r.status_code == 404:
            if self._metrics is not None:
                self._metrics.expected_404 += 1
            raise FileNotFoundError(relative)
        r.raise_for_status()
        payload = r.json()
        raw = base64.b64decode(payload.get("content_base64") or "")
        self._count_get_bytes(len(raw))
        return raw

    # Mutaciones explícitamente ausentes: no definir put/post/patch/delete.
