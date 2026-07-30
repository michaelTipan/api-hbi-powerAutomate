#!/usr/bin/env python
"""Smoke read-only U1.5 contra SharePoint sandbox.

DESHABILITADO por defecto. No forma parte de pytest.

Requisitos:
  UI_SHAREPOINT_SMOKE=1
  ACTIVE_ENVIRONMENT=sandbox
  Credenciales Graph en entorno (GRAPH_CREDENTIAL_SOURCE=env con TENANT/CLIENT/SECRET)
  o bootstrap Device Code / archivo temporal %TEMP%/kv_fetch_result.json

Uso:
  python scripts/ui_sharepoint_read_smoke.py
  python scripts/ui_sharepoint_read_smoke.py --banks banco_bogota,banco_bancolombia --runs 2
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


SANDBOX_MARKER = "03 COMWARE PRUEBAS- INFORMACION CREDITOS CLIENTES"
PROD_MARKERS = (
    "02 COMWARE AUTOMATIZACION - INFORMACION CREDITOS CLIENTES",
    "HBICapitalContabilidad",
)


def _load_dotenv_files() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    root = Path(__file__).resolve().parents[1]
    workspace = root.parent
    for candidate in (
        workspace / "api-hbi-powerAutomate.env",
        root / ".env",
    ):
        if candidate.is_file():
            load_dotenv(candidate, override=False)


def _bootstrap_credentials_from_temp() -> bool:
    """Carga tenant/client/secret desde %TEMP%/kv_fetch_result.json si existe."""
    path = Path(os.environ.get("TEMP") or os.environ.get("TMP") or "/tmp") / "kv_fetch_result.json"
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    if not data.get("ok"):
        return False
    tenant = (data.get("tenant") or "").strip()
    client = (data.get("client") or "").strip()
    secret = (data.get("secret") or "").strip()
    if not (tenant and client and secret):
        return False
    os.environ["GRAPH_CREDENTIAL_SOURCE"] = "env"
    os.environ["GRAPH_TENANT_ID"] = tenant
    os.environ["GRAPH_CLIENT_ID"] = client
    os.environ["GRAPH_CLIENT_SECRET"] = secret
    print(
        "bootstrap: credentials from temp file "
        f"(lens tenant={len(tenant)} client={len(client)} secret={len(secret)})"
    )
    return True


def _bootstrap_credentials_device_code() -> bool:
    """Device Code interactivo hacia Key Vault (solo si UI_SMOKE_DEVICE_CODE=1)."""
    if (os.getenv("UI_SMOKE_DEVICE_CODE") or "").strip() != "1":
        return False
    try:
        from azure.identity import DeviceCodeCredential
        from azure.keyvault.secrets import SecretClient
    except Exception as exc:
        print(f"device_code import fail: {type(exc).__name__}")
        return False

    vault = (
        os.getenv("GRAPH_KEY_VAULT_URI") or "https://keyvaulthbiautoprod001.vault.azure.net/"
    ).strip()

    def _prompt(url: str, code: str, expires) -> None:
        print(f"DEVICE_LOGIN url={url} code={code} expires={expires}", flush=True)

    cred = DeviceCodeCredential(prompt_callback=_prompt)
    client = SecretClient(vault, cred)
    tenant = (client.get_secret("tenantid").value or "").strip()
    secret = (client.get_secret("secretid-app-hbiautoprod-001").value or "").strip()
    app_id = (
        os.getenv("GRAPH_CLIENT_ID") or "fc73002d-d261-468b-888b-6ede9cc1f3db"
    ).strip()
    os.environ["GRAPH_CREDENTIAL_SOURCE"] = "env"
    os.environ["GRAPH_TENANT_ID"] = tenant
    os.environ["GRAPH_CLIENT_ID"] = app_id
    os.environ["GRAPH_CLIENT_SECRET"] = secret
    out = Path(os.environ.get("TEMP") or "/tmp") / "kv_fetch_result.json"
    out.write_text(
        json.dumps(
            {
                "ok": True,
                "tenant": tenant,
                "client": app_id,
                "secret": secret,
                "lens": {"tenant": len(tenant), "client": len(app_id), "secret": len(secret)},
            }
        ),
        encoding="utf-8",
    )
    print(f"bootstrap: device_code ok lenses={json.loads(out.read_text())['lens']}")
    return True


@dataclass
class GraphCallMetrics:
    get_json: int = 0
    get_bytes: int = 0
    bytes_downloaded: int = 0
    post: int = 0
    put: int = 0
    patch: int = 0
    delete: int = 0
    other_mutating: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    expected_404: int = 0
    unexpected_errors: list[str] = field(default_factory=list)
    per_source_ms: dict[str, float] = field(default_factory=dict)
    paths_seen: list[str] = field(default_factory=list)

    @property
    def total_graph_calls(self) -> int:
        return self.get_json + self.get_bytes + self.post + self.put + self.patch + self.delete


class CountingGraphHttp:
    """Envuelve MsGraphClient contando solo GET y fallando ante mutaciones."""

    def __init__(self, inner: Any, metrics: GraphCallMetrics) -> None:
        self._inner = inner
        self._metrics = metrics

    async def get(self, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._metrics.get_json += 1
        try:
            return await self._inner.get(endpoint, params=params)
        except Exception as exc:
            msg = f"{type(exc).__name__}:{str(exc)[:160]}"
            if "404" in msg or "NotFound" in msg or "itemNotFound" in msg:
                self._metrics.expected_404 += 1
            else:
                self._metrics.unexpected_errors.append(msg)
            raise

    async def get_bytes(self, endpoint: str, params: dict[str, Any] | None = None) -> bytes:
        self._metrics.get_bytes += 1
        try:
            data = await self._inner.get_bytes(endpoint, params=params)
        except Exception as exc:
            msg = f"{type(exc).__name__}:{str(exc)[:160]}"
            if "404" in msg or "NotFound" in msg or "itemNotFound" in msg:
                self._metrics.expected_404 += 1
            else:
                self._metrics.unexpected_errors.append(msg)
            raise
        self._metrics.bytes_downloaded += len(data)
        return data

    def __getattr__(self, name: str) -> Any:
        banned = {
            "put_bytes",
            "post_json",
            "patch_json",
            "delete",
            "upload",
            "send_mail",
        }
        if name in banned:
            self._metrics.other_mutating += 1

            async def _blocked(*_a: Any, **_k: Any) -> None:
                raise RuntimeError(f"smoke forbids mutating call: {name}")

            return _blocked
        return getattr(self._inner, name)


class CountingCache:
    def __init__(self, inner: Any, metrics: GraphCallMetrics) -> None:
        self._inner = inner
        self._metrics = metrics

    def bind_environment(self, environment: str) -> None:
        return self._inner.bind_environment(environment)

    def get(self, key: str, *, etag: str | None = None) -> Any:
        hit = self._inner.get(key, etag=etag)
        if hit is None:
            self._metrics.cache_misses += 1
        else:
            self._metrics.cache_hits += 1
        return hit

    def put(self, key: str, value: Any, *, etag: str | None = None, environment: str | None = None) -> None:
        return self._inner.put(key, value, etag=etag, environment=environment)

    def clear(self) -> None:
        return self._inner.clear()


def _assert_sandbox_path(path: str, warnings: list[str]) -> None:
    norm = (path or "").replace("\\", "/")
    base = (os.getenv("GRAPH_CLIENTS_BASE_PATH") or "").replace("\\", "/")
    if any(bad in norm for bad in PROD_MARKERS) and SANDBOX_MARKER not in norm:
        warnings.append(f"path_has_non_sandbox_marker:{_sanitize_path(norm)}")
        return
    if norm.startswith("INFORMACION ") or "CREDITOS-CLIENTES/" in norm:
        if SANDBOX_MARKER not in norm and (not base or not norm.startswith(base)):
            warnings.append(f"path_outside_active_base:{_sanitize_path(norm)}")


def _sanitize_path(path: str) -> str:
    """Oculta prefijos largos; deja cola relativa bajo sandbox."""
    norm = (path or "").replace("\\", "/")
    idx = norm.find(SANDBOX_MARKER)
    if idx >= 0:
        return "…/" + norm[idx:]
    parts = [p for p in norm.split("/") if p]
    return "…/" + "/".join(parts[-3:])


async def _project_bank(
    bank: str,
    reader: Any,
    metrics: GraphCallMetrics,
    path_warnings: list[str],
) -> dict[str, Any]:
    from app.application.ui.process_query import UiProcessQueryService

    t0 = time.perf_counter()
    try:
        detail = await UiProcessQueryService(reader).project_bank(bank)
        err = None
    except Exception as exc:
        detail = None
        err = f"{type(exc).__name__}:{str(exc)[:240]}"
        metrics.unexpected_errors.append(f"{bank}:{err}")
    elapsed = (time.perf_counter() - t0) * 1000
    metrics.per_source_ms[bank] = metrics.per_source_ms.get(bank, 0.0) + elapsed

    if detail is None:
        return {
            "bank": bank,
            "absent": True,
            "error": err,
            "ms": round(elapsed, 1),
        }

    paths = []
    files = detail.files
    for attr in (
        "control_file_path",
        "validation_file_path",
        "historical_file_path",
        "email_pdf_path",
        "merge_manifest_path",
        "secretary_file_path",
    ):
        p = getattr(files, attr, None)
        if p:
            paths.append(p)
            _assert_sandbox_path(p, path_warnings)
            metrics.paths_seen.append(p)

    return {
        "bank": bank,
        "absent": False,
        "process_key": detail.process_key,
        "operational_status": detail.operational_status,
        "control_estado": detail.control_estado_proceso,
        "steps": [(s.name, s.status) for s in detail.steps],
        "links": [(l.rel, bool(l.web_url)) for l in detail.links],
        "paths": [_sanitize_path(p) for p in paths],
        "ms": round(elapsed, 1),
        "error": None,
    }


def _run_fail_closed_local() -> list[tuple[str, str]]:
    from app.application.ui.download_limits import UiDownloadTooLargeError, assert_download_size_allowed
    from app.application.ui.graph_endpoint import UiGraphEndpointError, assert_relative_graph_endpoint
    from app.application.ui.path_guard import UiAllowedRoots, UiPathEscapeError, assert_path_allowed
    from app.application.ui.process_key import UiInvalidProcessKeyError, assert_ui_process_key

    roots = UiAllowedRoots(
        environment="sandbox",
        roots=(f"INFORMACION CREDITOS-CLIENTES/{SANDBOX_MARKER}",),
    )
    results: list[tuple[str, str]] = []
    try:
        assert_path_allowed(
            f"INFORMACION CREDITOS-CLIENTES/{SANDBOX_MARKER}/../secret",
            roots=roots,
        )
        results.append(("traversal", "FAIL_ALLOWED"))
    except UiPathEscapeError as exc:
        results.append(("traversal", exc.reason))
    try:
        assert_path_allowed(
            "INFORMACION CREDITOS-CLIENTES/02 INFORMACION CREDITOS CLIENTES/x.xlsx",
            roots=roots,
        )
        results.append(("prod_path", "FAIL_ALLOWED"))
    except UiPathEscapeError as exc:
        results.append(("prod_path", exc.reason))
    try:
        assert_ui_process_key("https://graph.microsoft.com/v1.0/sites/x")
        results.append(("graph_url", "FAIL_ALLOWED"))
    except UiInvalidProcessKeyError as exc:
        results.append(("graph_url", exc.reason))
    try:
        assert_relative_graph_endpoint("https://graph.microsoft.com/v1.0/me")
        results.append(("abs_endpoint", "FAIL_ALLOWED"))
    except UiGraphEndpointError as exc:
        results.append(("abs_endpoint", exc.reason))
    try:
        assert_download_size_allowed("fake.xlsx", 20_000_000, limit=1024)
        results.append(("size_limit", "FAIL_ALLOWED"))
    except UiDownloadTooLargeError:
        results.append(("size_limit", "too_large"))
    return results


def main() -> int:
    _load_dotenv_files()

    if (os.getenv("UI_SHAREPOINT_SMOKE") or "").strip() != "1":
        print(
            "Smoke deshabilitado. Exporte UI_SHAREPOINT_SMOKE=1 para ejecutar "
            "(solo sandbox, solo lectura).",
            file=sys.stderr,
        )
        return 2

    if (os.getenv("ACTIVE_ENVIRONMENT") or "").strip().lower() != "sandbox":
        print("Fail-closed: ACTIVE_ENVIRONMENT debe ser sandbox.", file=sys.stderr)
        return 2

    # Flags operativos pedidos
    os.environ.setdefault("UI_ENABLED", "false")
    os.environ.setdefault("UI_WRITE_ENABLED", "false")
    os.environ.setdefault("EXTRACT_INDEX_MODE", "off")
    os.environ.setdefault("EXTRACT_INDEX_BOOTSTRAP_ENABLED", "false")

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--banks",
        default="banco_bogota,banco_bancolombia",
        help="Lista separada por comas",
    )
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument("--bank", default="", help="Compat: un solo banco")
    args = parser.parse_args()

    banks = [b.strip() for b in (args.bank or args.banks).split(",") if b.strip()]
    if not banks:
        banks = ["banco_bancolombia"]

    has_graph_env = bool(
        (os.getenv("GRAPH_TENANT_ID") or "").strip()
        and (os.getenv("GRAPH_CLIENT_SECRET") or "").strip()
    )
    if not (
        has_graph_env
        or _bootstrap_credentials_from_temp()
        or _bootstrap_credentials_device_code()
    ):
        api_key = (os.getenv("API_HTTP_KEY") or "").strip()
        app_url = (
            os.getenv("UI_SMOKE_APP_BASE_URL")
            or "https://app-hbiauto-prod-001-afawg2g7frgte8c5.eastus-01.azurewebsites.net"
        ).strip()
        if not api_key:
            print(
                "Sin credenciales Graph locales ni API_HTTP_KEY.\n"
                "Opciones:\n"
                "  1) UI_SMOKE_DEVICE_CODE=1\n"
                "  2) GRAPH_CREDENTIAL_SOURCE=env + TENANT/CLIENT/SECRET\n"
                "  3) API_HTTP_KEY en sesión (smoke vía App Service GET)\n"
                "  4) %TEMP%/kv_fetch_result.json",
                file=sys.stderr,
            )
            return 3
        os.environ["UI_SMOKE_VIA_APP_SERVICE"] = "1"
        os.environ["UI_SMOKE_APP_BASE_URL"] = app_url
        print("bootstrap: using App Service Graph GET proxy (X-API-Key), no local Graph secrets")
    elif os.getenv("GRAPH_TENANT_ID") and os.getenv("GRAPH_CLIENT_SECRET"):
        os.environ["GRAPH_CREDENTIAL_SOURCE"] = "env"

    base = (os.getenv("GRAPH_CLIENTS_BASE_PATH") or "").replace("\\", "/")
    if SANDBOX_MARKER not in base:
        print(f"Fail-closed: GRAPH_CLIENTS_BASE_PATH no es sandbox: {base}", file=sys.stderr)
        return 2

    print("=== fail-closed local ===")
    for name, result in _run_fail_closed_local():
        print(f"  {name}: {result}")

    # production gate del propio script
    prev = os.environ.get("ACTIVE_ENVIRONMENT")
    os.environ["ACTIVE_ENVIRONMENT"] = "production"
    # no re-entrar main; solo documentar que el check existe
    os.environ["ACTIVE_ENVIRONMENT"] = prev or "sandbox"
    print("  production_gate: script rejects ACTIVE_ENVIRONMENT=production (checked at start)")

    metrics = GraphCallMetrics()
    run_reports: list[dict[str, Any]] = []
    path_warnings: list[str] = []

    async def _all() -> None:
        from app.adapters.secondary.ui_sharepoint_read import UiSharePointReadAdapter
        from app.application.ui.read_cache import UiReadCache

        via_app = (os.getenv("UI_SMOKE_VIA_APP_SERVICE") or "").strip() == "1"
        if via_app:
            # Herramienta exclusiva de smoke (no adaptador productivo).
            from scripts.support.ui_appservice_graph_http import AppServiceGraphHttp

            http: Any = AppServiceGraphHttp(
                base_url=os.environ["UI_SMOKE_APP_BASE_URL"],
                api_key=os.environ["API_HTTP_KEY"],
                metrics=metrics,
            )
            print(
                "note: metrics are App Service proxy smoke timings, "
                "not final integrated UI performance"
            )
        else:
            from app.adapters.secondary.ms_graph_client import MsGraphClient

            http = CountingGraphHttp(MsGraphClient(), metrics)

        cache = CountingCache(UiReadCache(ttl_seconds=60.0), metrics)
        reader = UiSharePointReadAdapter(http, cache=cache)  # type: ignore[arg-type]

        try:
            for run_idx in range(1, max(1, args.runs) + 1):
                print(f"=== run {run_idx}/{args.runs} ===")
                for bank in banks:
                    print(f"-- {bank} --")
                    report = await _project_bank(bank, reader, metrics, path_warnings)
                    run_reports.append({"run": run_idx, **report})
                    if report.get("absent"):
                        print("  ABSENT/ERROR:", report.get("error"))
                    else:
                        print("  process_key=", report.get("process_key"))
                        print("  operational_status=", report.get("operational_status"))
                        print("  steps=", report.get("steps"))
                        print("  paths=", report.get("paths"))
                        print("  links_with_weburl=", report.get("links"))
        finally:
            closer = getattr(http, "aclose", None)
            if callable(closer):
                await closer()

    t0 = time.perf_counter()
    asyncio.run(_all())
    total_ms = (time.perf_counter() - t0) * 1000

    print("=== metrics ===")
    print(
        json.dumps(
            {
                "total_graph_calls": metrics.total_graph_calls,
                "get_json": metrics.get_json,
                "get_bytes": metrics.get_bytes,
                "bytes_downloaded": metrics.bytes_downloaded,
                "cache_hits": metrics.cache_hits,
                "cache_misses": metrics.cache_misses,
                "expected_404": metrics.expected_404,
                "unexpected_errors": metrics.unexpected_errors,
                "post": metrics.post,
                "put": metrics.put,
                "patch": metrics.patch,
                "delete": metrics.delete,
                "other_mutating": metrics.other_mutating,
                "per_bank_ms": metrics.per_source_ms,
                "total_ms": round(total_ms, 1),
                "paths_sanitized": sorted({_sanitize_path(p) for p in metrics.paths_seen}),
                "path_warnings": path_warnings,
            },
            indent=2,
            ensure_ascii=False,
        )
    )

    if metrics.post or metrics.put or metrics.patch or metrics.delete or metrics.other_mutating:
        print("FAIL: se detectaron mutaciones", file=sys.stderr)
        return 4

    # Comparación run1 vs run2 por banco
    if args.runs >= 2:
        print("=== run comparison ===")
        for bank in banks:
            r1 = next((r for r in run_reports if r["run"] == 1 and r["bank"] == bank), None)
            r2 = next((r for r in run_reports if r["run"] == 2 and r["bank"] == bank), None)
            if not r1 or not r2:
                print(f"  {bank}: missing run")
                continue
            same = (
                r1.get("process_key") == r2.get("process_key")
                and r1.get("operational_status") == r2.get("operational_status")
                and r1.get("steps") == r2.get("steps")
            )
            print(
                f"  {bank}: same_projection={same} "
                f"ms=({r1.get('ms')},{r2.get('ms')}) "
                f"cache_hits_total={metrics.cache_hits}"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
