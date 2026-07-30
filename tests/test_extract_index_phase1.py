"""Tests Fase 1: keys, settings, schema, repos, mutation guard, read-only."""

from __future__ import annotations

import asyncio
from datetime import date

import pytest

from app.adapters.secondary.graph_document_tree_readonly import (
    GraphDocumentTreeReadOnlyAdapter,
    assert_readonly_port_has_no_write_attrs,
)
from app.application.config.extract_index_settings import (
    ExtractIndexMode,
    get_extract_index_settings,
)
from app.application.services.extract_index.column_specs import (
    CONTROL_INDICE_COLUMNS,
    INDICE_EXTRACTOS_COLUMNS,
)
from app.application.services.extract_index.control_repository import (
    GraphBootstrapControlRepository,
)
from app.application.services.extract_index.indice_repository import (
    GraphExtractIndexRepository,
)
from app.application.services.extract_index.keys import (
    assert_same_environment_and_drive,
    build_credit_key,
    build_doc_key,
    parse_credit_key,
    parse_doc_key,
)
from app.application.services.extract_index.mutation_guard import GraphMutationGuard
from app.application.services.extract_index.odata import escape_odata_string, eq_string
from app.application.services.extract_index.schema_validator import (
    raise_if_schema_incompatible,
    validate_columns_against_specs,
)
from app.domain.exceptions import (
    DocumentMutationForbidden,
    ExtractIndexDuplicateDocKeyError,
    ExtractIndexError,
    ExtractIndexSchemaError,
    UnauthorizedListWriteError,
)
from app.domain.models.extract_index import (
    BootstrapControlRecord,
    CampaignStatus,
    ExtractIndexCandidate,
    ExtractIndexEnvironment,
    ParseStatus,
)
from tests.fakes.fake_extract_index_graph import FakeMsGraph


def _full_indice_columns(*, credit_key_indexed: bool = True) -> list[dict]:
    cols: list[dict] = []
    for spec in INDICE_EXTRACTOS_COLUMNS:
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
            entry["indexed"] = credit_key_indexed
        cols.append(entry)
    return cols


def _full_control_columns() -> list[dict]:
    cols: list[dict] = []
    for spec in CONTROL_INDICE_COLUMNS:
        entry: dict = {"name": spec.internal_name, "displayName": spec.display_name}
        if spec.column_type == "text":
            entry["text"] = {}
        elif spec.column_type == "boolean":
            entry["boolean"] = {}
        elif spec.column_type == "dateTime":
            entry["dateTime"] = {}
        if spec.must_be_indexed:
            entry["indexed"] = True
        cols.append(entry)
    return cols


def _candidate(
    *,
    env: ExtractIndexEnvironment = ExtractIndexEnvironment.SANDBOX,
    drive: str = "driveA",
    credit_folder: str = "cred1",
    item: str = "pdf1",
) -> ExtractIndexCandidate:
    ck = build_credit_key(
        environment=env, drive_id=drive, credit_folder_item_id=credit_folder
    )
    dk = build_doc_key(environment=env, drive_id=drive, item_id=item)
    return ExtractIndexCandidate(
        environment=env,
        credit_key=ck,
        doc_key=dk,
        drive_id=drive,
        item_id=item,
        credit_folder_item_id=credit_folder,
        name="Extracto.pdf",
        path="/cli/cred/Extracto.pdf",
        ctag="c1",
        etag="e1",
        parse_status=ParseStatus.OK,
        fecha_limite=date(2026, 7, 1),
    )


# --- Keys / settings ---


def test_credit_and_doc_key_deterministic() -> None:
    ck = build_credit_key(
        environment="sandbox", drive_id="d1", credit_folder_item_id="c1"
    )
    dk = build_doc_key(environment="sandbox", drive_id="d1", item_id="i1")
    assert ck.as_string() == "sandbox|d1|c1"
    assert dk.as_string() == "sandbox|d1|i1"
    assert parse_credit_key(ck.as_string()) == ck
    assert parse_doc_key(dk.as_string()) == dk


def test_keys_reject_pipe_and_empty() -> None:
    with pytest.raises(ExtractIndexError):
        build_doc_key(environment="sandbox", drive_id="d|x", item_id="i1")
    with pytest.raises(ExtractIndexError):
        build_credit_key(environment="sandbox", drive_id="", credit_folder_item_id="c")


def test_sandbox_production_isolation_assert() -> None:
    ck = build_credit_key(
        environment="sandbox", drive_id="d1", credit_folder_item_id="c1"
    )
    dk = build_doc_key(environment="production", drive_id="d1", item_id="i1")
    with pytest.raises(ExtractIndexError):
        assert_same_environment_and_drive(
            environment=ExtractIndexEnvironment.SANDBOX,
            drive_id="d1",
            credit_key=ck,
            doc_key=dk,
        )


def test_no_mix_drives() -> None:
    ck = build_credit_key(
        environment="sandbox", drive_id="d1", credit_folder_item_id="c1"
    )
    dk = build_doc_key(environment="sandbox", drive_id="d2", item_id="i1")
    with pytest.raises(ExtractIndexError):
        assert_same_environment_and_drive(
            environment=ExtractIndexEnvironment.SANDBOX,
            drive_id="d1",
            credit_key=ck,
            doc_key=dk,
        )


def test_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EXTRACT_INDEX_MODE", raising=False)
    monkeypatch.delenv("EXTRACT_INDEX_BOOTSTRAP_ENABLED", raising=False)
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "sandbox")
    s = get_extract_index_settings()
    assert s.mode == ExtractIndexMode.OFF
    assert s.bootstrap_enabled is False
    assert s.environment == ExtractIndexEnvironment.SANDBOX
    assert s.max_clients_per_chunk == 3


# --- OData / schema ---


def test_odata_escape_special_chars() -> None:
    assert escape_odata_string("O'Brien") == "O''Brien"
    assert "O''Brien" in eq_string("DOC_KEY", "sandbox|d|O'Brien")


def test_schema_valid() -> None:
    result = validate_columns_against_specs(
        list_display_name="INDICE_EXTRACTOS",
        list_id="L1",
        columns=_full_indice_columns(),
        specs=INDICE_EXTRACTOS_COLUMNS,
    )
    assert result.ok


def test_schema_invalid_missing_and_not_indexed() -> None:
    cols = [c for c in _full_indice_columns(credit_key_indexed=False) if c["name"] != "DOC_KEY"]
    result = validate_columns_against_specs(
        list_display_name="INDICE_EXTRACTOS",
        list_id="L1",
        columns=cols,
        specs=INDICE_EXTRACTOS_COLUMNS,
    )
    assert not result.ok
    codes = {i.code for i in result.errors}
    assert "missing_column" in codes
    assert "not_indexed" in codes
    with pytest.raises(ExtractIndexSchemaError):
        raise_if_schema_incompatible(result)


def test_schema_internal_vs_display_mismatch() -> None:
    cols = [
        {
            "name": "CreditKeyWrong",
            "displayName": "CREDIT_KEY",
            "text": {},
            "indexed": True,
        }
    ]
    result = validate_columns_against_specs(
        list_display_name="INDICE_EXTRACTOS",
        list_id="L1",
        columns=cols,
        specs=INDICE_EXTRACTOS_COLUMNS,
    )
    assert any(i.code == "internal_name_mismatch" for i in result.errors)


# --- Mutation guard / readonly ---


def test_readonly_get_allowed_and_no_write_attrs() -> None:
    async def _run() -> None:
        fake = FakeMsGraph()
        port = GraphDocumentTreeReadOnlyAdapter(fake)
        assert_readonly_port_has_no_write_attrs(port)
        data = await port.get_json("/drives/d1/root:/folder:/children")
        assert data["id"] == "drive-item"
        content = await port.get_bytes("/drives/d1/items/x/content")
        assert content.startswith(b"%PDF")
        assert fake.document_mutation_count() == 0

    asyncio.run(_run())


def test_mutation_guard_blocks_drive_mutations() -> None:
    async def _run() -> None:
        fake = FakeMsGraph()
        guard = GraphMutationGuard(fake, allowed_list_ids={"list-indice"})
        await guard.get("/drives/d1/root:/a")
        with pytest.raises(DocumentMutationForbidden):
            await guard.post_json("/drives/d1/root:/a:/content", {"x": 1})
        with pytest.raises(DocumentMutationForbidden):
            await guard.put_bytes("/drives/d1/items/1/content", b"x")
        with pytest.raises(DocumentMutationForbidden):
            await guard.patch_json("/drives/d1/items/1", {"name": "y"})
        with pytest.raises(DocumentMutationForbidden):
            await guard.delete("/drives/d1/items/1")
        assert guard.stats.blocked_document_mutations == 4
        assert fake.document_mutation_count() == 0

    asyncio.run(_run())


def test_mutation_guard_blocks_unauthorized_list() -> None:
    async def _run() -> None:
        fake = FakeMsGraph()
        guard = GraphMutationGuard(fake, allowed_list_ids={"list-indice"})
        with pytest.raises(UnauthorizedListWriteError):
            await guard.post_json("/sites/s1/lists/other-list/items", {"fields": {}})
        assert guard.stats.blocked_unauthorized_list_writes == 1

    asyncio.run(_run())


def test_mutation_guard_allows_allowlisted_list_write() -> None:
    async def _run() -> None:
        fake = FakeMsGraph(lists_by_display={"INDICE_EXTRACTOS": "list-indice"})
        guard = GraphMutationGuard(fake, allowed_list_ids={"list-indice"})
        created, status = await guard.post_json(
            "/sites/s1/lists/list-indice/items",
            {"fields": {"Title": "t"}},
        )
        assert status == 201
        assert created["id"]
        assert guard.stats.allowed_list_writes == 1

    asyncio.run(_run())


# --- Repositories ---


def _indice_repo(fake: FakeMsGraph) -> GraphExtractIndexRepository:
    fake.lists_by_display["INDICE_EXTRACTOS"] = "list-indice"
    fake.columns_by_list["list-indice"] = _full_indice_columns()
    return GraphExtractIndexRepository(
        fake,
        site_id="site1",
        list_id="list-indice",
        max_retries=3,
        retry_base_seconds=0.01,
        require_schema=True,
    )


def test_upsert_idempotent_and_env_filter() -> None:
    async def _run() -> None:
        fake = FakeMsGraph()
        repo = _indice_repo(fake)
        c1 = _candidate(item="pdf1")
        saved = await repo.upsert_by_doc_key(c1)
        assert saved.list_item_id == "1"
        c1b = _candidate(item="pdf1")
        c1b.name = "Extracto-v2.pdf"
        saved2 = await repo.upsert_by_doc_key(c1b)
        assert saved2.list_item_id == "1"
        assert len(fake.items_by_list["list-indice"]) == 1
        assert fake.items_by_list["list-indice"][0]["fields"]["NOMBRE"] == "Extracto-v2.pdf"

        c_prod = _candidate(env=ExtractIndexEnvironment.PRODUCTION, item="pdf1")
        await repo.upsert_by_doc_key(c_prod)
        found = await repo.find_by_doc_key(
            environment=ExtractIndexEnvironment.SANDBOX,
            doc_key=c1.doc_key.as_string(),
        )
        assert len(found) == 1
        assert found[0].environment == ExtractIndexEnvironment.SANDBOX

    asyncio.run(_run())


def test_duplicate_doc_key_detection() -> None:
    async def _run() -> None:
        fake = FakeMsGraph()
        repo = _indice_repo(fake)
        fields = {
            "ENVIRONMENT": "sandbox",
            "CREDIT_KEY": "sandbox|driveA|cred1",
            "DOC_KEY": "sandbox|driveA|pdfX",
            "DRIVE_ID": "driveA",
            "ITEM_ID": "pdfX",
            "CREDIT_FOLDER_ITEM_ID": "cred1",
        }
        fake.items_by_list["list-indice"] = [
            {"id": "10", "fields": dict(fields)},
            {"id": "11", "fields": dict(fields)},
        ]
        dupes = await repo.report_duplicate_doc_keys(
            environment=ExtractIndexEnvironment.SANDBOX
        )
        assert len(dupes) == 1
        with pytest.raises(ExtractIndexDuplicateDocKeyError):
            await repo.upsert_by_doc_key(_candidate(item="pdfX"))

    asyncio.run(_run())


def test_pagination_across_pages() -> None:
    async def _run() -> None:
        fake = FakeMsGraph()
        _indice_repo(fake)
        items = []
        for i in range(5):
            items.append(
                {
                    "id": str(i + 1),
                    "fields": {
                        "ENVIRONMENT": "sandbox",
                        "CREDIT_KEY": "sandbox|driveA|cred1",
                        "DOC_KEY": f"sandbox|driveA|pdf{i}",
                        "DRIVE_ID": "driveA",
                        "ITEM_ID": f"pdf{i}",
                        "CREDIT_FOLDER_ITEM_ID": "cred1",
                    },
                }
            )
        fake.items_by_list["list-indice"] = items
        from app.application.services.extract_index.list_http import paginate_list_items
        from app.application.services.extract_index.odata import and_filters, eq_string

        filt = and_filters(
            eq_string("ENVIRONMENT", "sandbox"),
            eq_string("CREDIT_KEY", "sandbox|driveA|cred1"),
        )
        all_items = await paginate_list_items(
            fake,
            site_id="site1",
            list_id="list-indice",
            filter_expr=filt,
            page_size=2,
        )
        assert len(all_items) == 5
        assert any(
            "@odata.nextLink" in str(c.endpoint) or "skiptoken" in c.endpoint
            for c in fake.calls
        )

    asyncio.run(_run())


def test_filter_with_special_chars() -> None:
    async def _run() -> None:
        fake = FakeMsGraph()
        repo = _indice_repo(fake)
        weird = _candidate(item="id'with'quote")
        await repo.upsert_by_doc_key(weird)
        found = await repo.find_by_doc_key(
            environment=ExtractIndexEnvironment.SANDBOX,
            doc_key=weird.doc_key.as_string(),
        )
        assert len(found) == 1

    asyncio.run(_run())


def test_429_retries_then_success() -> None:
    async def _run() -> None:
        fake = FakeMsGraph()
        repo = _indice_repo(fake)
        fake.fail_statuses = [429, 429]
        saved = await repo.upsert_by_doc_key(_candidate())
        assert saved.list_item_id is not None

    asyncio.run(_run())


def test_403_not_hidden() -> None:
    async def _run() -> None:
        fake = FakeMsGraph()
        repo = _indice_repo(fake)
        fake.fail_statuses = [403]
        with pytest.raises(ExtractIndexError, match="permiso denegado"):
            await repo.upsert_by_doc_key(_candidate())

    asyncio.run(_run())


def test_control_repo_upsert() -> None:
    async def _run() -> None:
        fake = FakeMsGraph()
        fake.lists_by_display["CONTROL_INDICE_EXTRACTOS"] = "list-control"
        fake.columns_by_list["list-control"] = _full_control_columns()
        repo = GraphBootstrapControlRepository(
            fake,
            site_id="site1",
            list_id="list-control",
            max_retries=2,
            retry_base_seconds=0.01,
        )
        rec = BootstrapControlRecord(
            environment=ExtractIndexEnvironment.SANDBOX,
            campaign_id="camp-1",
            status=CampaignStatus.RUNNING,
            chunk_id="chunk-1",
            continuation_required=True,
        )
        saved = await repo.upsert_by_campaign_id(rec)
        assert saved.list_item_id == "1"
        again = await repo.get_by_campaign_id(
            environment=ExtractIndexEnvironment.SANDBOX, campaign_id="camp-1"
        )
        assert again is not None
        assert again.continuation_required is True

    asyncio.run(_run())


def test_zero_document_mutations_in_list_ops() -> None:
    async def _run() -> None:
        fake = FakeMsGraph()
        guard = GraphMutationGuard(fake, allowed_list_ids={"list-indice", "list-control"})
        fake.lists_by_display["INDICE_EXTRACTOS"] = "list-indice"
        fake.columns_by_list["list-indice"] = _full_indice_columns()
        repo = GraphExtractIndexRepository(
            guard,
            site_id="site1",
            list_id="list-indice",
            max_retries=2,
            retry_base_seconds=0.01,
        )
        await repo.upsert_by_doc_key(_candidate())
        assert fake.document_mutation_count() == 0
        assert guard.stats.blocked_document_mutations == 0

    asyncio.run(_run())
