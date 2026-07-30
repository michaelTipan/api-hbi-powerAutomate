"""Fase 3A2: wiring admin, adapters allowlist, contratos HTTP (fakes; sin Graph real)."""

from __future__ import annotations

import os
from datetime import date
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.adapters.primary.http.api_key_auth import install_api_key_auth
from app.adapters.primary.http.extract_index_admin_deps import ExtractIndexAdminState
from app.adapters.primary.http.routers import extract_index_admin
from app.adapters.secondary.extract_index_list_adapters import (
    build_allowlisted_extract_index_lists,
)
from app.adapters.secondary.graph_document_tree_readonly import (
    GraphDocumentTreeReadOnlyAdapter,
    assert_readonly_port_has_no_write_attrs,
)
from app.application.config.extract_index_settings import (
    ExtractIndexMode,
    ExtractIndexSettings,
)
from app.application.services.extract_index.bootstrap_models import (
    BOOTSTRAP_PARSER_VERSION,
    BOOTSTRAP_SCHEMA_VERSION,
    CampaignScopeKey,
)
from app.application.services.extract_index.bootstrap_wiring import (
    compose_bootstrap_wiring,
    compose_bootstrap_wiring_from_graph,
)
from app.application.services.extract_index.column_specs import (
    CONTROL_INDICE_COLUMNS,
    INDICE_EXTRACTOS_COLUMNS,
)
from app.application.services.extract_index.mutation_guard import GraphMutationGuard
from app.domain.exceptions import DocumentMutationForbidden, UnauthorizedListWriteError
from app.domain.models.extract_index import (
    CreditKey,
    DocKey,
    ExtractIndexCandidate,
    ExtractIndexEnvironment,
    ParseStatus,
)
from app.domain.ports.bootstrap_scope import BootstrapCreditUnit
from tests.fakes.fake_bootstrap import (
    FakeBootstrapScope,
    FakeReadonlyDocumentTree,
    InMemoryBootstrapControlRepository,
    InMemoryExtractIndexRepository,
)
from tests.fakes.fake_extract_index_graph import FakeMsGraph


def _settings(
    *,
    bootstrap_enabled: bool = True,
    mode: ExtractIndexMode = ExtractIndexMode.OFF,
    environment: ExtractIndexEnvironment = ExtractIndexEnvironment.SANDBOX,
) -> ExtractIndexSettings:
    return ExtractIndexSettings(
        mode=mode,
        environment=environment,
        bootstrap_enabled=bootstrap_enabled,
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


def _cand(folder: str = "c1") -> ExtractIndexCandidate:
    env = ExtractIndexEnvironment.SANDBOX
    drive = "drive-1"
    ck = CreditKey(environment=env, drive_id=drive, credit_folder_item_id=folder)
    dk = DocKey(environment=env, drive_id=drive, item_id=f"pdf-{folder}")
    return ExtractIndexCandidate(
        environment=env,
        credit_key=ck,
        doc_key=dk,
        drive_id=drive,
        item_id=f"pdf-{folder}",
        credit_folder_item_id=folder,
        name=f"{folder}.pdf",
        parse_status=ParseStatus.OK,
        parser_version=BOOTSTRAP_PARSER_VERSION,
        fecha_limite=date(2026, 6, 1),
    )


def _unit(folder: str) -> BootstrapCreditUnit:
    return BootstrapCreditUnit(
        client_identity="cli",
        credit_identity=folder,
        credit_folder_item_id=folder,
        credit_path=f"cli/{folder}",
        candidates=[_cand(folder)],
        opaque_cursor=folder,
    )


def _wiring(units: list[BootstrapCreditUnit] | None = None, **settings_kw: Any):
    scope = FakeBootstrapScope(units=units or [_unit("c1"), _unit("c2")])
    index = InMemoryExtractIndexRepository()
    control = InMemoryBootstrapControlRepository()
    tree = FakeReadonlyDocumentTree()
    wiring = compose_bootstrap_wiring(
        scope=scope,
        index_repo=index,
        control_repo=control,
        document_tree=tree,
        settings=_settings(**settings_kw),
        max_credits_per_chunk=2,
    )
    return wiring, index, control


_TEST_API_KEY = "test-extract-index-admin-key"


def _app_with_admin(
    wiring,
    *,
    api_key: str | None = _TEST_API_KEY,
) -> FastAPI:
    app = FastAPI()
    os.environ["EXTRACT_INDEX_REMOTE_PREFLIGHT"] = "false"
    os.environ["EXTRACT_INDEX_BOOTSTRAP_CHUNKS_ENABLED"] = "true"
    if api_key is not None:
        os.environ["API_HTTP_KEY"] = api_key
    else:
        os.environ.pop("API_HTTP_KEY", None)
    install_api_key_auth(app)
    app.include_router(extract_index_admin.router)
    app.state.extract_index_admin = ExtractIndexAdminState(wiring=wiring)
    return app


def _headers(api_key: str = _TEST_API_KEY) -> dict[str, str]:
    return {"X-API-Key": api_key}


def _full_columns(specs) -> list[dict]:
    cols: list[dict] = []
    for spec in specs:
        entry: dict = {"name": spec.internal_name, "displayName": spec.display_name}
        if spec.column_type == "text":
            entry["text"] = {}
        elif spec.column_type == "number":
            entry["number"] = {}
        elif spec.column_type == "boolean":
            entry["boolean"] = {}
        elif spec.column_type == "dateTime":
            entry["dateTime"] = {}
        if spec.must_be_indexed:
            entry["indexed"] = True
        cols.append(entry)
    return cols


# --- adapters / wiring ---


def test_document_tree_readonly_has_no_write_attrs() -> None:
    fake = FakeMsGraph()
    tree = GraphDocumentTreeReadOnlyAdapter(fake)
    assert_readonly_port_has_no_write_attrs(tree)


def test_allowlisted_lists_block_document_mutation_and_foreign_list() -> None:
    fake = FakeMsGraph(
        lists_by_display={
            "INDICE_EXTRACTOS": "list-indice",
            "CONTROL_INDICE_EXTRACTOS": "list-control",
        },
        columns_by_list={
            "list-indice": _full_columns(INDICE_EXTRACTOS_COLUMNS),
            "list-control": _full_columns(CONTROL_INDICE_COLUMNS),
        },
    )
    lists = build_allowlisted_extract_index_lists(
        fake,
        site_id="site-1",
        indice_list_id="list-indice",
        control_list_id="list-control",
        require_schema=False,
    )
    import asyncio

    async def _run() -> None:
        with pytest.raises(DocumentMutationForbidden):
            await lists.mutation_guard.post_json(
                "/drives/d1/items/x/children", {"name": "nope"}
            )
        with pytest.raises(UnauthorizedListWriteError):
            await lists.mutation_guard.post_json(
                "/sites/site-1/lists/other-list/items", {"fields": {"Title": "x"}}
            )

    asyncio.run(_run())
    assert lists.mutation_guard.stats.blocked_document_mutations >= 1
    assert lists.mutation_guard.stats.blocked_unauthorized_list_writes >= 1


def test_compose_wiring_from_graph_uses_fake_only() -> None:
    fake = FakeMsGraph(
        lists_by_display={
            "INDICE_EXTRACTOS": "list-indice",
            "CONTROL_INDICE_EXTRACTOS": "list-control",
        },
        columns_by_list={
            "list-indice": _full_columns(INDICE_EXTRACTOS_COLUMNS),
            "list-control": _full_columns(CONTROL_INDICE_COLUMNS),
        },
    )
    wiring = compose_bootstrap_wiring_from_graph(
        fake,
        site_id="site-1",
        indice_list_id="list-indice",
        control_list_id="list-control",
        scope=FakeBootstrapScope(units=[_unit("c1")]),
        settings=_settings(),
        require_schema=False,
    )
    assert wiring.lists is not None
    assert isinstance(wiring.lists.mutation_guard, GraphMutationGuard)
    assert isinstance(wiring.document_tree, GraphDocumentTreeReadOnlyAdapter)
    assert fake.document_mutation_count() == 0


# --- HTTP contracts ---


def test_preflight_ok() -> None:
    wiring, *_ = _wiring()
    client = TestClient(_app_with_admin(wiring))
    r = client.post("/extract-index/admin/preflight", headers=_headers())
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["capabilities"]["graph_real"] is False
    assert body["capabilities"]["active_mode"] is False


def test_bootstrap_disabled_rejects() -> None:
    wiring, *_ = _wiring(bootstrap_enabled=False)
    client = TestClient(_app_with_admin(wiring))
    r = client.post("/extract-index/admin/preflight", headers=_headers())
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "bootstrap_disabled"


def test_mode_shadow_rejects_bootstrap_admin() -> None:
    wiring, *_ = _wiring(mode=ExtractIndexMode.SHADOW)
    client = TestClient(_app_with_admin(wiring))
    r = client.post("/extract-index/admin/preflight", headers=_headers())
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "extract_index_mode_must_be_off"


def test_environment_mismatch_on_start() -> None:
    wiring, *_ = _wiring(environment=ExtractIndexEnvironment.SANDBOX)
    client = TestClient(_app_with_admin(wiring))
    r = client.post(
        "/extract-index/admin/campaigns/start",
        headers=_headers(),
        json={
            "environment": "production",
            "drive_id": "drive-1",
            "root_identity": "root",
        },
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "environment_mismatch"


def test_start_chunk_status_pause_resume_cancel_flow() -> None:
    wiring, index, _ = _wiring()
    client = TestClient(_app_with_admin(wiring))
    start = client.post(
        "/extract-index/admin/campaigns/start",
        headers=_headers(),
        json={
            "environment": "sandbox",
            "drive_id": "drive-1",
            "root_identity": "root-clients",
        },
    )
    assert start.status_code == 200
    campaign_id = start.json()["campaign_id"]
    assert campaign_id == CampaignScopeKey(
        environment=ExtractIndexEnvironment.SANDBOX,
        drive_id="drive-1",
        root_identity="root-clients",
        parser_version=BOOTSTRAP_PARSER_VERSION,
        schema_version=BOOTSTRAP_SCHEMA_VERSION,
    ).as_campaign_id()

    chunk = client.post(
        f"/extract-index/admin/campaigns/{campaign_id}/chunks",
        headers=_headers(),
        json={"environment": "sandbox", "expected_drive_id": "drive-1"},
    )
    assert chunk.status_code == 200
    body = chunk.json()
    assert "campaign_id" in body and "chunk_id" in body
    assert "continuation_required" in body
    assert "status" in body
    assert "checkpoint" in body
    assert body["credits_confirmed"] == 2
    assert body["continuation_required"] is False
    assert len(index.items) == 2

    # Segundo POST chunks no autoencadena trabajo extra (ya completed)
    chunk2 = client.post(
        f"/extract-index/admin/campaigns/{campaign_id}/chunks",
        headers=_headers(),
        json={"environment": "sandbox"},
    )
    assert chunk2.status_code == 200
    assert chunk2.json()["credits_confirmed"] == 0

    status = client.get(
        f"/extract-index/admin/campaigns/{campaign_id}",
        headers=_headers(),
        params={"environment": "sandbox"},
    )
    assert status.status_code == 200
    assert status.json()["status"] == "completed"

    # Nueva campaña para pause/resume/cancel
    wiring2, *_ = _wiring([_unit("a"), _unit("b"), _unit("c")])
    client2 = TestClient(_app_with_admin(wiring2))
    start2 = client2.post(
        "/extract-index/admin/campaigns/start",
        headers=_headers(),
        json={
            "environment": "sandbox",
            "drive_id": "drive-1",
            "root_identity": "root-2",
        },
    ).json()
    cid = start2["campaign_id"]
    client2.post(
        f"/extract-index/admin/campaigns/{cid}/chunks",
        headers=_headers(),
        json={"environment": "sandbox"},
    )
    paused = client2.post(
        f"/extract-index/admin/campaigns/{cid}/pause",
        headers=_headers(),
        json={"environment": "sandbox"},
    )
    assert paused.status_code == 200
    assert paused.json()["paused"] is True
    assert paused.json()["continuation_required"] is False

    resumed = client2.post(
        f"/extract-index/admin/campaigns/{cid}/resume",
        headers=_headers(),
        json={"environment": "sandbox"},
    )
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "running"

    cancelled = client2.post(
        f"/extract-index/admin/campaigns/{cid}/cancel",
        headers=_headers(),
        json={"environment": "sandbox"},
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["continuation_required"] is False


def test_api_key_required_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    wiring, *_ = _wiring()
    monkeypatch.setenv("API_HTTP_KEY", "secret-test-key")
    monkeypatch.setenv("EXTRACT_INDEX_REMOTE_PREFLIGHT", "false")
    monkeypatch.setenv("EXTRACT_INDEX_BOOTSTRAP_CHUNKS_ENABLED", "true")
    app = FastAPI()
    install_api_key_auth(app)
    app.include_router(extract_index_admin.router)
    app.state.extract_index_admin = ExtractIndexAdminState(wiring=wiring)
    client = TestClient(app, raise_server_exceptions=False)

    missing = client.post("/extract-index/admin/preflight")
    assert missing.status_code == 401

    bad = client.post(
        "/extract-index/admin/preflight", headers={"X-API-Key": "wrong"}
    )
    assert bad.status_code == 401

    ok = client.post(
        "/extract-index/admin/preflight", headers={"X-API-Key": "secret-test-key"}
    )
    assert ok.status_code == 200
    monkeypatch.delenv("API_HTTP_KEY", raising=False)


def test_responses_do_not_expose_secrets() -> None:
    wiring, *_ = _wiring()
    client = TestClient(_app_with_admin(wiring))
    start = client.post(
        "/extract-index/admin/campaigns/start",
        headers=_headers(),
        json={
            "environment": "sandbox",
            "drive_id": "drive-1",
            "root_identity": "root",
        },
    ).json()
    blob = str(start)
    assert "client_secret" not in blob.lower()
    assert "bearer " not in blob.lower()
    assert "API_HTTP_KEY" not in blob


def test_app_factory_mounts_admin_router_in_integration() -> None:
    from pathlib import Path

    src = Path("app/adapters/primary/http/app_factory.py").read_text(encoding="utf-8")
    assert "extract_index_admin" in src
    assert "attach_extract_index_admin_router_state" in src


def test_generate_unchanged_vs_2b2() -> None:
    """Generate puede recibir fixes operativos; 3A2 no debe acoplarlo a admin."""
    from pathlib import Path

    src = Path(
        "app/application/use_cases/payment_validation_generate.py"
    ).read_text(encoding="utf-8")
    assert "extract_index_admin" not in src
    assert "bootstrap_campaign" not in src


def test_admin_not_wired_returns_503() -> None:
    app = FastAPI()
    os.environ["API_HTTP_KEY"] = _TEST_API_KEY
    os.environ["EXTRACT_INDEX_REMOTE_PREFLIGHT"] = "false"
    install_api_key_auth(app)
    app.include_router(extract_index_admin.router)
    # sin app.state.extract_index_admin y sin attach lazy init lock
    client = TestClient(app, raise_server_exceptions=False)
    r = client.post("/extract-index/admin/preflight", headers=_headers())
    assert r.status_code == 503
    assert r.json()["detail"]["code"] in (
        "extract_index_admin_not_wired",
        "extract_index_admin_init_failed",
    )


def test_error_sanitizer_redacts_token_like_text() -> None:
    from app.adapters.primary.http.extract_index_admin_deps import sanitize_error_text

    assert sanitize_error_text("Bearer abc.def.ghi") == "error_sanitized"
    assert sanitize_error_text("ok message") == "ok message"
