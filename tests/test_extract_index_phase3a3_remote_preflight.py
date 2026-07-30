"""Fase 3A3: auth admin + preflight remoto RO con fakes (sin Graph real de red)."""

from __future__ import annotations

import asyncio
import os
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.adapters.primary.http.api_key_auth import install_api_key_auth
from app.adapters.primary.http.app_factory import create_app
from app.adapters.primary.http.extract_index_admin_deps import ExtractIndexAdminState
from app.adapters.primary.http.routers import extract_index_admin
from app.application.config.extract_index_settings import (
    ExtractIndexMode,
    ExtractIndexSettings,
)
from app.application.services.extract_index.bootstrap_wiring import compose_bootstrap_wiring
from app.application.services.extract_index.column_specs import (
    CONTROL_INDICE_COLUMNS,
    INDICE_EXTRACTOS_COLUMNS,
)
from app.application.services.extract_index.remote_preflight import (
    ReadOnlyGraphProbe,
    MutationCounters,
    run_remote_sandbox_preflight,
)
from app.domain.models.extract_index import ExtractIndexEnvironment
from tests.fakes.fake_bootstrap import (
    FakeBootstrapScope,
    FakeReadonlyDocumentTree,
    InMemoryBootstrapControlRepository,
    InMemoryExtractIndexRepository,
)
from tests.fakes.fake_extract_index_graph import FakeMsGraph

API_KEY = "phase3a3-admin-key"


def _settings(**kw: Any) -> ExtractIndexSettings:
    base = dict(
        mode=ExtractIndexMode.OFF,
        environment=ExtractIndexEnvironment.SANDBOX,
        bootstrap_enabled=True,
        max_clients_per_chunk=3,
        max_seconds_per_chunk=180,
        shadow_max_credits=None,
        shadow_sample_pct=None,
        shadow_allowed_banks=frozenset(),
        shadow_allowed_dates=frozenset(),
        shadow_timeout_seconds=8.0,
        shadow_total_budget_seconds=45.0,
        indice_list_display_name="INDICE_EXTRACTOS",
        control_list_display_name="CONTROL_INDICE_EXTRACTOS",
        graph_retry_max=2,
        graph_retry_base_seconds=0.01,
    )
    base.update(kw)
    return ExtractIndexSettings(**base)


def _cols(specs) -> list[dict]:
    out = []
    for spec in specs:
        e: dict = {"name": spec.internal_name, "displayName": spec.display_name}
        e[spec.column_type if spec.column_type != "dateTime" else "dateTime"] = {}
        if spec.column_type == "text":
            e = {"name": spec.internal_name, "displayName": spec.display_name, "text": {}}
        elif spec.column_type == "number":
            e = {"name": spec.internal_name, "displayName": spec.display_name, "number": {}}
        elif spec.column_type == "boolean":
            e = {"name": spec.internal_name, "displayName": spec.display_name, "boolean": {}}
        else:
            e = {"name": spec.internal_name, "displayName": spec.display_name, "dateTime": {}}
        if spec.must_be_indexed:
            e["indexed"] = True
        out.append(e)
    return out


def _admin_app(settings: ExtractIndexSettings | None = None) -> TestClient:
    os.environ["API_HTTP_KEY"] = API_KEY
    os.environ["EXTRACT_INDEX_REMOTE_PREFLIGHT"] = "false"
    os.environ["EXTRACT_INDEX_BOOTSTRAP_CHUNKS_ENABLED"] = "false"
    os.environ["ACTIVE_ENVIRONMENT"] = "sandbox"
    os.environ["EXTRACT_INDEX_MODE"] = "off"
    os.environ["EXTRACT_INDEX_BOOTSTRAP_ENABLED"] = "true"
    wiring = compose_bootstrap_wiring(
        scope=FakeBootstrapScope(units=[]),
        index_repo=InMemoryExtractIndexRepository(),
        control_repo=InMemoryBootstrapControlRepository(),
        document_tree=FakeReadonlyDocumentTree(),
        settings=settings or _settings(),
    )
    app = FastAPI()
    install_api_key_auth(app)
    app.include_router(extract_index_admin.router)
    app.state.extract_index_admin = ExtractIndexAdminState(wiring=wiring)
    return TestClient(app, raise_server_exceptions=False)


def test_admin_routes_require_api_key_missing() -> None:
    client = _admin_app()
    r = client.post("/extract-index/admin/preflight")
    assert r.status_code == 401


def test_admin_routes_require_api_key_wrong() -> None:
    client = _admin_app()
    r = client.post(
        "/extract-index/admin/preflight", headers={"X-API-Key": "nope"}
    )
    assert r.status_code == 401


def test_admin_valid_key_reaches_gates() -> None:
    client = _admin_app()
    r = client.post(
        "/extract-index/admin/preflight", headers={"X-API-Key": API_KEY}
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_bootstrap_disabled_rejects_preflight() -> None:
    client = _admin_app(_settings(bootstrap_enabled=False))
    r = client.post(
        "/extract-index/admin/preflight", headers={"X-API-Key": API_KEY}
    )
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "bootstrap_disabled"


def test_mode_not_off_rejects_preflight() -> None:
    client = _admin_app(_settings(mode=ExtractIndexMode.SHADOW))
    r = client.post(
        "/extract-index/admin/preflight", headers={"X-API-Key": API_KEY}
    )
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "extract_index_mode_must_be_off"


def test_production_environment_rejected_on_preflight() -> None:
    client = _admin_app(_settings(environment=ExtractIndexEnvironment.PRODUCTION))
    r = client.post(
        "/extract-index/admin/preflight", headers={"X-API-Key": API_KEY}
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "environment_not_sandbox"


def test_admin_not_under_graph_public_exception() -> None:
    from app.adapters.primary.http.api_key_auth import is_public_path

    assert is_public_path("/health") is True
    assert is_public_path("/extract-index/admin/preflight") is False
    assert is_public_path("/graph/diagnostics") is False


def test_chunks_disabled_blocks_start() -> None:
    client = _admin_app()
    r = client.post(
        "/extract-index/admin/campaigns/start",
        headers={"X-API-Key": API_KEY},
        json={
            "environment": "sandbox",
            "drive_id": "d1",
            "root_identity": "root",
        },
    )
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "bootstrap_chunks_disabled"


def test_app_factory_mounts_router() -> None:
    os.environ["API_HTTP_KEY"] = API_KEY
    app = create_app()
    paths = {getattr(r, "path", None) for r in app.routes}
    assert any(
        isinstance(p, str) and p.startswith("/extract-index/admin") for p in paths
    )


def test_remote_preflight_zero_writes_with_fake_graph(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GRAPH_CLIENTS_BASE_PATH", "INFORMACION CREDITOS-CLIENTES/03 COMWARE PRUEBAS- INFORMACION CREDITOS CLIENTES")
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "sandbox")
    monkeypatch.setenv("EXTRACT_INDEX_MODE", "off")
    monkeypatch.setenv("EXTRACT_INDEX_BOOTSTRAP_ENABLED", "true")

    fake = FakeMsGraph(
        lists_by_display={
            "INDICE_EXTRACTOS": "list-indice",
            "CONTROL_INDICE_EXTRACTOS": "list-control",
        },
        columns_by_list={
            "list-indice": _cols(INDICE_EXTRACTOS_COLUMNS),
            "list-control": _cols(CONTROL_INDICE_COLUMNS),
        },
    )

    # Stub resolve_sharepoint_from_env to avoid full site resolution
    async def fake_resolve(graph):
        return {"site_id": "site-1", "drive_id": "drive-1", "file_path": "x"}

    monkeypatch.setattr(
        "app.application.services.extract_index.remote_preflight.resolve_sharepoint_from_env",
        fake_resolve,
    )

    # children listing
    async def fake_get(endpoint, params=None):
        if "/lists?" in endpoint or endpoint.rstrip("/").endswith("/lists"):
            return await FakeMsGraph.get(fake, endpoint, params)
        if "/columns" in endpoint:
            return await FakeMsGraph.get(fake, endpoint, params)
        if "/children" in endpoint:
            return {"value": [{"id": "c1", "name": "Cliente A", "folder": {}}]}
        return await FakeMsGraph.get(fake, endpoint, params)

    fake.get = fake_get  # type: ignore[method-assign]

    report = asyncio.run(
        run_remote_sandbox_preflight(fake, settings=_settings())
    )
    assert report.mutation_counters["list_item_writes"] == 0
    assert report.mutation_counters["drive_mutations"] == 0
    assert report.mutation_counters["pdf_downloads"] == 0
    assert report.campaigns_created == 0 if hasattr(report, "campaigns_created") else True
    assert report.as_dict()["campaigns_created"] == 0
    assert report.as_dict()["checkpoints_written"] == 0
    # schema may fail if fake columns incomplete for indexed CREDIT_KEY — still zero writes
    assert fake.document_mutation_count() == 0


def test_readonly_probe_blocks_writes() -> None:
    counters = MutationCounters()
    probe = ReadOnlyGraphProbe(FakeMsGraph(), counters)

    async def _run() -> None:
        with pytest.raises(PermissionError):
            await probe.post_json("/sites/s/lists/l/items", {"fields": {}})
        with pytest.raises(PermissionError):
            await probe.patch_json("/drives/d/items/1", {})
        with pytest.raises(PermissionError):
            await probe.get_bytes("/drives/d/items/1/content")

    asyncio.run(_run())
    assert counters.list_item_writes >= 1
    assert counters.drive_mutations >= 1
    assert counters.pdf_downloads >= 1
