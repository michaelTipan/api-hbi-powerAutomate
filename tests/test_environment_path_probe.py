"""
Tests del sondeo solo-lectura de rutas (`/graph/diagnostics/paths-probe`).

Garantiza dos cosas: que el sondeo detecta rutas faltantes y que **nunca** escribe en
SharePoint (cualquier PUT/POST/PATCH/DELETE hace fallar la prueba).
"""

from __future__ import annotations

from datetime import date

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.adapters.primary.http.deps import get_graph_client
from app.adapters.primary.http.routers.diagnostics import router
from app.application.services import environment_path_probe as probe
from tests.test_environment_overlays import apply_overlay

SITE_ID = "site-ops"
DRIVE_ID = "drive-ops"
ACCOUNTING_SITE_ID = "site-cont"
ACCOUNTING_DRIVE_ID = "drive-cont"


def _http_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://graph.microsoft.com/test")
    response = httpx.Response(status, request=request, text=f"HTTP {status}")
    return httpx.HTTPStatusError("err", request=request, response=response)


class ReadOnlyMockGraph:
    """Graph simulado que solo admite lecturas y guarda las rutas consultadas."""

    def __init__(self, folders: set[str], files: set[str]) -> None:
        self.folders = folders
        self.files = files
        self.get_endpoints: list[str] = []

    @staticmethod
    def _decoded_path(endpoint: str) -> str:
        from urllib.parse import unquote

        marker = "/root:/"
        tail = endpoint.split(marker, 1)[1] if marker in endpoint else ""
        return unquote(tail)

    async def get(self, endpoint: str, params=None):
        self.get_endpoints.append(endpoint)
        path = self._decoded_path(endpoint)
        if path in self.folders:
            return {"name": path.rsplit("/", 1)[-1], "folder": {}, "webUrl": "https://x/f"}
        if path in self.files:
            return {"name": path.rsplit("/", 1)[-1], "file": {}, "webUrl": "https://x/a.xlsx"}
        raise _http_error(404)

    async def get_bytes(self, endpoint: str, params=None):
        raise AssertionError("El sondeo no debe descargar contenido")

    async def put_bytes(self, endpoint: str, content: bytes, content_type: str = ""):
        raise AssertionError("El sondeo no debe escribir en SharePoint")

    async def post_json(self, endpoint: str, body):
        raise AssertionError("El sondeo no debe crear elementos en SharePoint")

    async def patch_json(self, endpoint: str, body):
        raise AssertionError("El sondeo no debe modificar elementos en SharePoint")

    async def delete(self, endpoint: str):
        raise AssertionError("El sondeo no debe borrar elementos en SharePoint")


@pytest.fixture
def production_env(monkeypatch: pytest.MonkeyPatch) -> None:
    apply_overlay(monkeypatch, "production")
    monkeypatch.setenv("GRAPH_OPERATIONS_SITE_HOSTNAME", "gecolsacat.sharepoint.com")
    monkeypatch.setenv("GRAPH_OPERATIONS_SITE_PATH", "sites/OperacionesHBICapital")
    monkeypatch.setenv("GRAPH_OPERATIONS_DRIVE_NAME", "Documentos")


@pytest.fixture
def stub_contexts(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_operations(_client):
        return {"site_id": SITE_ID, "drive_id": DRIVE_ID, "file_path": "x"}

    async def fake_accounting(_client):
        return {"site_id": ACCOUNTING_SITE_ID, "drive_id": ACCOUNTING_DRIVE_ID}

    monkeypatch.setattr(probe, "resolve_sharepoint_from_env", fake_operations)
    monkeypatch.setattr(probe, "resolve_accounting_context", fake_accounting)


def _all_production_paths() -> tuple[set[str], set[str]]:
    folders = {t.path for t in probe.build_operations_probe_targets() if t.kind == probe.KIND_FOLDER}
    files = {t.path for t in probe.build_operations_probe_targets() if t.kind == probe.KIND_FILE}
    folders |= {t.path for t in probe.build_accounting_probe_targets(date(2026, 7, 29))}
    return folders, files


def test_probe_reports_ok_when_every_path_exists(production_env, stub_contexts):
    import asyncio

    folders, files = _all_production_paths()
    graph = ReadOnlyMockGraph(folders, files)

    result = asyncio.run(probe.probe_environment_paths(graph, date(2026, 7, 29)))

    assert result["status"] == probe.STATUS_OK
    assert result["read_only"] is True
    assert result["active_environment"] == "production"
    assert result["accounting_configured"] is True
    assert result["summary"]["required_failures"] == []
    assert all(":/content" not in ep for ep in graph.get_endpoints)


def test_probe_flags_missing_required_folder(production_env, stub_contexts):
    import asyncio

    folders, files = _all_production_paths()
    missing = f"{probe.build_operations_probe_targets()[0].path}"
    folders.discard(missing)
    graph = ReadOnlyMockGraph(folders, files)

    result = asyncio.run(probe.probe_environment_paths(graph, date(2026, 7, 29)))

    assert result["status"] == "degraded"
    assert "clients_base" in result["summary"]["required_failures"]
    failed = next(c for c in result["checks"] if c["name"] == "clients_base")
    assert failed["status"] == probe.STATUS_MISSING
    assert failed["http_status"] == 404


def test_probe_requires_accounting_bank_folder(production_env, stub_contexts):
    import asyncio

    folders, files = _all_production_paths()
    bank_target = next(
        t
        for t in probe.build_accounting_probe_targets(date(2026, 7, 29))
        if t.name.endswith("banco_bogota")
    )
    folders.discard(bank_target.path)
    graph = ReadOnlyMockGraph(folders, files)

    result = asyncio.run(probe.probe_environment_paths(graph, date(2026, 7, 29)))

    assert bank_target.required is True
    assert "accounting_bank_folder_banco_bogota" in result["summary"]["required_failures"]


def test_probe_skips_operations_merge_folder_when_accounting_enabled(production_env):
    names = {t.name for t in probe.build_operations_probe_targets()}
    assert "merge_output_operations" not in names


def test_probe_checks_operations_merge_folder_in_sandbox(monkeypatch: pytest.MonkeyPatch):
    apply_overlay(monkeypatch, "sandbox")
    names = {t.name for t in probe.build_operations_probe_targets()}
    assert "merge_output_operations" in names


def test_router_paths_probe_endpoint(production_env, stub_contexts):
    folders, files = _all_production_paths()
    graph = ReadOnlyMockGraph(folders, files)

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_graph_client] = lambda: graph
    client = TestClient(app)

    response = client.get("/graph/diagnostics/paths-probe?report_date=2026-07-29")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == probe.STATUS_OK
    assert body["report_date"] == "2026-07-29"
    assert body["clients_excluded_folders"] == [
        "03 COMWARE PRUEBAS- INFORMACION CREDITOS CLIENTES"
    ]


def test_router_paths_probe_rejects_bad_date(production_env, stub_contexts):
    graph = ReadOnlyMockGraph(set(), set())
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_graph_client] = lambda: graph
    client = TestClient(app)

    response = client.get("/graph/diagnostics/paths-probe?report_date=29-07-2026")

    assert response.status_code == 400
