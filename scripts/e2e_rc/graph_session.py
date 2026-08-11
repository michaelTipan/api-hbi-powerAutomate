"""Cliente Graph vía App Service (X-API-Key) con guarda de paths sandbox."""
from __future__ import annotations

import base64
import logging
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from scripts.e2e_rc.path_guard import (
    AUTHORIZED_CLIENTS_BASE,
    assert_runtime_clients_base,
    assert_sandbox_mutable_path,
)

DEFAULT_BASE = (
    "https://app-hbiauto-prod-001-afawg2g7frgte8c5.eastus-01.azurewebsites.net"
)
PACK_ENV = Path(r"D:\CMC\HBI_Capital\api-hbi-powerAutomate.env")
logger = logging.getLogger(__name__)

_RETRYABLE = (
    httpx.ReadTimeout,
    httpx.ConnectTimeout,
    httpx.ConnectError,
    httpx.ReadError,
    httpx.RemoteProtocolError,
    httpx.WriteTimeout,
    httpx.PoolTimeout,
)


def load_api_key(env_path: Path = PACK_ENV) -> str:
    text = env_path.read_text(encoding="utf-8")
    m = re.search(r"^API_HTTP_KEY=(.+)$", text, re.M)
    if not m:
        raise RuntimeError("API_HTTP_KEY missing")
    return m.group(1).strip()


def _default_timeout(timeout: float | httpx.Timeout) -> httpx.Timeout:
    if isinstance(timeout, httpx.Timeout):
        return timeout
    # Connect corto; read/write largos (jobs + SharePoint grandes).
    return httpx.Timeout(timeout, connect=45.0, read=timeout, write=timeout, pool=45.0)


class SandboxGraphSession:
    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE,
        api_key: str | None = None,
        timeout: float | httpx.Timeout = 300.0,
        max_retries: int = 4,
    ) -> None:
        self.base = base_url.rstrip("/")
        self._max_retries = max(0, int(max_retries))
        self._client = httpx.Client(
            timeout=_default_timeout(timeout),
            headers={"X-API-Key": api_key or load_api_key(), "Accept": "application/json"},
        )
        self.drive_id: str | None = None
        self.clients_base = AUTHORIZED_CLIENTS_BASE

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> SandboxGraphSession:
        self.ensure_sandbox()
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _request(
        self,
        method: str,
        url: str,
        *,
        timeout: float | httpx.Timeout | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """HTTP con reintentos ante cortes/timeouts (E16/E23/E30/E38 flake)."""
        delays = (0.0, 2.0, 5.0, 12.0, 25.0)
        attempts = 1 + self._max_retries
        last_exc: BaseException | None = None
        for attempt in range(attempts):
            if attempt > 0:
                time.sleep(delays[min(attempt, len(delays) - 1)])
            try:
                kw = dict(kwargs)
                if timeout is not None:
                    kw["timeout"] = timeout
                return self._client.request(method, url, **kw)
            except _RETRYABLE as exc:
                last_exc = exc
                logger.warning(
                    "graph_session retry %s/%s %s %s: %s",
                    attempt + 1,
                    attempts,
                    method,
                    url,
                    exc,
                )
                continue
        assert last_exc is not None
        raise last_exc

    def ensure_sandbox(self) -> dict[str, Any]:
        health = self._request("GET", f"{self.base}/health").json()
        if health.get("environment") != "sandbox":
            raise RuntimeError(f"not_sandbox_environment:{health.get('environment')}")
        if health.get("ui_enabled") is not True:
            raise RuntimeError("ui_not_enabled")
        resolved = self._request(
            "GET", f"{self.base}/graph/sharepoint/resolve-env"
        ).json()
        runtime_base = ""
        file_path = str(((resolved.get("resolved") or {}).get("file_path") or ""))
        if file_path:
            # Derivar clients base desde path bancario conocido
            marker = "03 COMWARE PRUEBAS- INFORMACION CREDITOS CLIENTES"
            if marker in file_path:
                runtime_base = file_path.split("/01 CARGA")[0]
        if not runtime_base:
            probe = self._request(
                "GET", f"{self.base}/graph/diagnostics/paths-probe"
            ).json()
            for check in probe.get("checks") or []:
                if check.get("name") == "clients_base":
                    runtime_base = str(check.get("path") or "")
                    break
        assert_runtime_clients_base(str(runtime_base))
        self.drive_id = str((resolved.get("resolved") or {}).get("drive_id") or "")
        if not self.drive_id:
            raise RuntimeError("drive_id_missing")
        return {"health": health, "clients_base": runtime_base, "drive_id": self.drive_id}

    def children(self, folder_item_id: str = "root") -> list[dict[str, Any]]:
        assert self.drive_id
        r = self._request(
            "GET",
            f"{self.base}/graph/sharepoint/drives/{quote(self.drive_id, safe='')}/children",
            params={"folder_item_id": folder_item_id},
        )
        r.raise_for_status()
        return list((r.json() or {}).get("value") or [])

    def walk(self, relative_path: str) -> str:
        guarded = assert_sandbox_mutable_path(relative_path)
        cur = "root"
        for part in guarded.split("/"):
            hit = next((i for i in self.children(cur) if i.get("name") == part), None)
            if not hit:
                raise FileNotFoundError(guarded)
            cur = str(hit["id"])
        return cur

    def download_item(self, item_id: str) -> bytes:
        assert self.drive_id
        r = self._request(
            "GET",
            f"{self.base}/graph/sharepoint/drives/{quote(self.drive_id, safe='')}/item-content",
            params={"item_id": item_id},
            timeout=180.0,
        )
        r.raise_for_status()
        return base64.b64decode(r.json()["content_base64"])

    def upload_item(self, item_id: str, raw: bytes, *, path_for_guard: str) -> None:
        assert_sandbox_mutable_path(path_for_guard)
        assert self.drive_id
        r = self._request(
            "PUT",
            f"{self.base}/graph/sharepoint/drives/{quote(self.drive_id, safe='')}/item-content",
            params={"item_id": item_id},
            json={"content_base64": base64.b64encode(raw).decode("ascii")},
            timeout=180.0,
        )
        r.raise_for_status()

    def upload_by_path(self, relative_path: str, raw: bytes) -> None:
        """Crea o sobrescribe por path relativo (solo PRUEBAS)."""
        guarded = assert_sandbox_mutable_path(relative_path)
        assert self.drive_id
        r = self._request(
            "PUT",
            f"{self.base}/graph/sharepoint/drives/{quote(self.drive_id, safe='')}/path-content",
            params={"item_path": guarded},
            json={"content_base64": base64.b64encode(raw).decode("ascii")},
            timeout=180.0,
        )
        r.raise_for_status()

    def delete_item(self, item_id: str, *, path_for_guard: str) -> None:
        """Elimina ítem; path_for_guard debe estar bajo PRUEBAS."""
        assert_sandbox_mutable_path(path_for_guard)
        assert self.drive_id
        r = self._request(
            "DELETE",
            f"{self.base}/graph/sharepoint/drives/{quote(self.drive_id, safe='')}/items/{quote(item_id, safe='')}",
        )
        r.raise_for_status()

    def queue_and_poll(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        timeout_s: int = 1800,
        poll_s: float = 8.0,
    ) -> dict[str, Any]:
        r = self._request(
            "POST",
            f"{self.base}{path}",
            json=payload,
            timeout=120.0,
        )
        if r.status_code not in (200, 202):
            return {
                "http_status": r.status_code,
                "body": r.json() if r.content else r.text,
                "status": "http_error",
            }
        body = r.json()
        job_id = body.get("job_id")
        if not job_id:
            return body
        t0 = time.time()
        while time.time() - t0 < timeout_s:
            jr = self._request(
                "GET",
                f"{self.base}/graph/sharepoint/payment-validation/jobs/{job_id}",
                timeout=120.0,
            )
            if jr.status_code != 200:
                time.sleep(poll_s)
                continue
            done = jr.json()
            st = done.get("status")
            if st in ("completed", "failed", "error"):
                return done
            time.sleep(poll_s)
        raise TimeoutError(f"job_timeout:{job_id}")
