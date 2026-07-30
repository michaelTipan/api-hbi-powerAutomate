"""Fase 2B1: shadow evaluator aislado (fakes, sin Graph real, sin Generate)."""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any

import httpx
import pytest

from app.adapters.secondary.graph_document_tree_readonly import (
    GraphDocumentTreeReadOnlyAdapter,
    assert_readonly_port_has_no_write_attrs,
)
from app.application.config.extract_index_settings import (
    ExtractIndexMode,
    ExtractIndexSettings,
)
from app.application.services.extract_index.index_select_adapter import (
    IndexSelectAdapter,
    IndexSelectRequest,
)
from app.application.services.extract_index.keys import build_credit_key, build_doc_key
from app.application.services.extract_index.mutation_guard import GraphMutationGuard
from app.application.services.extract_index.reconcile import LiveFileMetadata
from app.application.services.extract_index.shadow_evaluator import (
    ShadowIndexEvaluator,
    ShadowJobBudget,
)
from app.application.services.extract_index.shadow_models import (
    DivergenceType,
    OfficialV2Snapshot,
    ShadowOutcomeKind,
    ShadowSkipReason,
)
from app.application.services.extract_index.shadow_sampling import (
    ShadowSampleContext,
    is_credit_in_shadow_sample,
    stable_sample_bucket,
)
from app.domain.exceptions import (
    DocumentMutationForbidden,
    ExtractIndexSchemaError,
    UnauthorizedListWriteError,
)
from app.domain.models.extract_index import (
    ExtractIndexCandidate,
    ExtractIndexEnvironment,
    ParseStatus,
)
from tests.fakes.fake_extract_index_graph import FakeMsGraph


def _settings(**overrides: Any) -> ExtractIndexSettings:
    base = dict(
        mode=ExtractIndexMode.SHADOW,
        environment=ExtractIndexEnvironment.SANDBOX,
        bootstrap_enabled=False,
        max_clients_per_chunk=3,
        max_seconds_per_chunk=180,
        shadow_max_credits=None,
        shadow_sample_pct=100.0,
        shadow_allowed_banks=frozenset(),
        shadow_allowed_dates=frozenset(),
        shadow_timeout_seconds=2.0,
        shadow_total_budget_seconds=45.0,
        indice_list_display_name="INDICE_EXTRACTOS",
        control_list_display_name="CONTROL_INDICE_EXTRACTOS",
        graph_retry_max=2,
        graph_retry_base_seconds=0.01,
    )
    base.update(overrides)
    return ExtractIndexSettings(**base)


def _cand(
    *,
    item_id: str = "pdf1",
    fecha: date | None = date(2026, 6, 1),
    ctag: str = "c1",
    parse: ParseStatus = ParseStatus.OK,
    drive: str = "driveA",
    env: ExtractIndexEnvironment = ExtractIndexEnvironment.SANDBOX,
    ubicacion: str = "extractos_folder",
) -> ExtractIndexCandidate:
    ck = build_credit_key(
        environment=env, drive_id=drive, credit_folder_item_id="cred1"
    )
    dk = build_doc_key(environment=env, drive_id=drive, item_id=item_id)
    return ExtractIndexCandidate(
        environment=env,
        credit_key=ck,
        doc_key=dk,
        drive_id=drive,
        item_id=item_id,
        credit_folder_item_id="cred1",
        name=f"Extracto {item_id}.pdf",
        path=f"cli/cred/EXTRACTOS/Extracto {item_id}.pdf",
        ubicacion=ubicacion,
        ctag=ctag,
        etag="e1",
        parse_status=parse,
        fecha_limite=fecha,
        parser_version="v1",
    )


class _MemLoader:
    def __init__(self, rows: list[ExtractIndexCandidate] | Exception) -> None:
        self.rows = rows

    async def load_by_credit_key(
        self, *, environment: ExtractIndexEnvironment, credit_key: str
    ) -> list[ExtractIndexCandidate]:
        if isinstance(self.rows, Exception):
            raise self.rows
        return [
            r
            for r in self.rows
            if r.environment == environment and r.credit_key.as_string() == credit_key
        ]


class _SlowDocs:
    async def get_json(self, endpoint: str, params=None) -> dict:
        return {}

    async def get_bytes(self, endpoint: str, params=None) -> bytes:
        await asyncio.sleep(5.0)
        return b"x"


class _MemDocs:
    def __init__(self, files: dict[str, bytes] | None = None) -> None:
        self.files = files or {}
        self.calls: list[str] = []

    async def get_json(self, endpoint: str, params=None) -> dict:
        return {}

    async def get_bytes(self, endpoint: str, params=None) -> bytes:
        self.calls.append(endpoint)
        # endpoint is relative path in tests
        key = endpoint
        if key not in self.files:
            raise FileNotFoundError(key)
        return self.files[key]


def _fecha_fn(pdf_bytes: bytes) -> date | None:
    text = pdf_bytes.decode("utf-8", errors="ignore")
    if "FECHA_LIMITE=" not in text:
        return None
    return date.fromisoformat(text.split("FECHA_LIMITE=", 1)[1].split(";", 1)[0])


def _pdf(fecha: date, tag: str) -> bytes:
    return f"FECHA_LIMITE={fecha.isoformat()};{tag}".encode()


def _v2(
    *,
    item_id: str | None = "pdf1",
    fecha: date | None = date(2026, 6, 1),
    err: str | None = None,
    credit_key: str = "sandbox|driveA|cred1",
) -> OfficialV2Snapshot:
    return OfficialV2Snapshot(
        credit_key=credit_key,
        item_id=item_id,
        fecha_limite=fecha,
        source_location="extractos_folder",
        selection_reason="max_fecha_limite",
        error_code=err,
        relative_path=f"cli/cred/EXTRACTOS/Extracto {item_id}.pdf" if item_id else None,
    )


def _request(
    *,
    live_ctag: str = "c1",
    item_id: str = "pdf1",
) -> IndexSelectRequest:
    folder_items = [
        {"name": "EXTRACTOS", "folder": {}, "id": "exfold"},
    ]
    children = [
        {
            "name": f"Extracto {item_id}.pdf",
            "id": item_id,
            "file": {},
            "cTag": live_ctag,
            "eTag": "e1",
        }
    ]
    return IndexSelectRequest(
        environment=ExtractIndexEnvironment.SANDBOX,
        drive_id="driveA",
        credit_key="sandbox|driveA|cred1",
        credit_path="cli/cred",
        credit_folder_items=folder_items,
        extractos_children=children,
        live_files=[
            LiveFileMetadata(
                item_id=item_id,
                name=f"Extracto {item_id}.pdf",
                path=f"cli/cred/EXTRACTOS/Extracto {item_id}.pdf",
                ctag=live_ctag,
                etag="e1",
                source_location="extractos_folder",
            )
        ],
        content_endpoint_builder=lambda rel: rel,
        parser_version="v1",
        fecha_limite_fn=_fecha_fn,
    )


def _run(coro):
    return asyncio.run(coro)


# --- Sampling ---


def test_sampling_deterministic() -> None:
    ctx = ShadowSampleContext(
        environment="sandbox",
        bank_code="banco_bogota",
        process_date=date(2026, 7, 29),
        credit_key="sandbox|d|c1",
    )
    a = stable_sample_bucket(ctx)
    b = stable_sample_bucket(ctx)
    assert a == b
    assert is_credit_in_shadow_sample(ctx, sample_pct=0.0) is False
    assert is_credit_in_shadow_sample(ctx, sample_pct=100.0) is True


# --- Happy / divergence ---


def test_shadow_v2_and_index_match() -> None:
    loader = _MemLoader([_cand()])
    adapter = IndexSelectAdapter(
        loader=loader, document_tree=_MemDocs(), default_fecha_limite_fn=_fecha_fn
    )
    ev = ShadowIndexEvaluator(settings=_settings(), adapter=adapter)
    v2 = _v2()
    res = _run(
        ev.evaluate(
            official_v2=v2,
            request=_request(),
            bank_code="banco_bogota",
            process_date=date(2026, 7, 29),
        )
    )
    assert res.outcome == ShadowOutcomeKind.INDEX_SELECTED
    assert res.comparison is not None
    assert res.comparison.divergence_type == DivergenceType.NONE
    assert res.comparison.item_id_index == "pdf1"
    assert v2.item_id == "pdf1"  # V2 intacto


def test_shadow_item_id_divergence() -> None:
    loader = _MemLoader([_cand(item_id="pdfINDEX")])
    adapter = IndexSelectAdapter(
        loader=loader, document_tree=_MemDocs(), default_fecha_limite_fn=_fecha_fn
    )
    ev = ShadowIndexEvaluator(settings=_settings(), adapter=adapter)
    req = _request(item_id="pdfINDEX")
    res = _run(
        ev.evaluate(
            official_v2=_v2(item_id="pdfV2"),
            request=req,
            bank_code="banco_bogota",
            process_date=date(2026, 7, 29),
        )
    )
    assert res.outcome == ShadowOutcomeKind.INDEX_DIVERGENCE
    assert res.comparison is not None
    assert res.comparison.divergence_type == DivergenceType.ITEM_ID


def test_shadow_fecha_divergence() -> None:
    loader = _MemLoader([_cand(fecha=date(2026, 1, 1))])
    adapter = IndexSelectAdapter(
        loader=loader, document_tree=_MemDocs(), default_fecha_limite_fn=_fecha_fn
    )
    ev = ShadowIndexEvaluator(settings=_settings(), adapter=adapter)
    res = _run(
        ev.evaluate(
            official_v2=_v2(fecha=date(2026, 8, 1)),
            request=_request(),
            bank_code="banco_bogota",
            process_date=date(2026, 7, 29),
        )
    )
    assert res.outcome == ShadowOutcomeKind.INDEX_DIVERGENCE
    assert res.comparison is not None
    assert res.comparison.divergence_type == DivergenceType.FECHA_LIMITE


def test_shadow_index_empty() -> None:
    adapter = IndexSelectAdapter(
        loader=_MemLoader([]),
        document_tree=_MemDocs(),
        default_fecha_limite_fn=_fecha_fn,
    )
    ev = ShadowIndexEvaluator(settings=_settings(), adapter=adapter)
    res = _run(
        ev.evaluate(
            official_v2=_v2(),
            request=_request(),
            bank_code="banco_bogota",
            process_date=date(2026, 7, 29),
        )
    )
    assert res.outcome == ShadowOutcomeKind.INDEX_UNAVAILABLE


def test_shadow_index_insufficient_deleted() -> None:
    # Indexado pero no en live → fallback
    loader = _MemLoader([_cand(item_id="gone")])
    adapter = IndexSelectAdapter(
        loader=loader, document_tree=_MemDocs(), default_fecha_limite_fn=_fecha_fn
    )
    ev = ShadowIndexEvaluator(settings=_settings(), adapter=adapter)
    req = _request(item_id="other")
    res = _run(
        ev.evaluate(
            official_v2=_v2(),
            request=req,
            bank_code="banco_bogota",
            process_date=date(2026, 7, 29),
        )
    )
    assert res.outcome in (
        ShadowOutcomeKind.INDEX_INSUFFICIENT,
        ShadowOutcomeKind.FALLBACK_REQUIRED,
    )


def test_shadow_duplicates() -> None:
    dup = _cand(item_id="pdf1")
    loader = _MemLoader([dup, _cand(item_id="pdf1")])  # same doc_key
    # Same item_id → same doc_key; need two with same DOC_KEY different list rows
    c2 = _cand(item_id="pdf1")
    loader = _MemLoader([dup, c2])
    adapter = IndexSelectAdapter(
        loader=loader, document_tree=_MemDocs(), default_fecha_limite_fn=_fecha_fn
    )
    ev = ShadowIndexEvaluator(settings=_settings(), adapter=adapter)
    res = _run(
        ev.evaluate(
            official_v2=_v2(),
            request=_request(),
            bank_code="banco_bogota",
            process_date=date(2026, 7, 29),
        )
    )
    assert res.outcome in (
        ShadowOutcomeKind.FALLBACK_REQUIRED,
        ShadowOutcomeKind.INDEX_INSUFFICIENT,
        ShadowOutcomeKind.INDEX_UNAVAILABLE,
    )


def test_shadow_parse_error_status() -> None:
    loader = _MemLoader(
        [_cand(parse=ParseStatus.ERROR, fecha=None)]
    )
    adapter = IndexSelectAdapter(
        loader=loader, document_tree=_MemDocs(), default_fecha_limite_fn=_fecha_fn
    )
    # same ctag → retry path needs download; provide docs that raise PdfStreamError-like
    class BoomDocs(_MemDocs):
        async def get_bytes(self, endpoint: str, params=None) -> bytes:
            raise RuntimeError("PdfStreamError: truncated")

    adapter = IndexSelectAdapter(
        loader=loader, document_tree=BoomDocs(), default_fecha_limite_fn=_fecha_fn
    )
    ev = ShadowIndexEvaluator(settings=_settings(), adapter=adapter)
    res = _run(
        ev.evaluate(
            official_v2=_v2(),
            request=_request(),
            bank_code="banco_bogota",
            process_date=date(2026, 7, 29),
        )
    )
    # parse error + failed downloads → insufficient/fallback, never raises
    assert res.outcome != ShadowOutcomeKind.INDEX_SELECTED
    assert res.official_v2_untouched is True


def test_shadow_pdf_stream_error_isolated() -> None:
    loader = _MemLoader([_cand(ctag="old")])
    docs = _MemDocs(
        {
            "cli/cred/EXTRACTOS/Extracto pdf1.pdf": _pdf(date(2026, 6, 1), "x"),
        }
    )

    def boom(_b: bytes) -> date | None:
        raise RuntimeError("PdfStreamError")

    adapter = IndexSelectAdapter(
        loader=loader, document_tree=docs, default_fecha_limite_fn=_fecha_fn
    )
    ev = ShadowIndexEvaluator(settings=_settings(), adapter=adapter)
    req = _request(live_ctag="new")
    # Forzar fecha_fn que lanza (no usar la del request por defecto)
    req = IndexSelectRequest(
        environment=req.environment,
        drive_id=req.drive_id,
        credit_key=req.credit_key,
        credit_path=req.credit_path,
        credit_folder_items=req.credit_folder_items,
        extractos_children=req.extractos_children,
        live_files=req.live_files,
        content_endpoint_builder=req.content_endpoint_builder,
        parser_version=req.parser_version,
        fecha_limite_fn=boom,
    )
    res = _run(
        ev.evaluate(
            official_v2=_v2(),
            request=req,
            bank_code="banco_bogota",
            process_date=date(2026, 7, 29),
        )
    )
    assert res.isolated_error_type == "RuntimeError"
    assert res.outcome == ShadowOutcomeKind.INDEX_ERROR
    assert res.official_v2_untouched is True


def test_shadow_environment_mismatch() -> None:
    class RawLoader:
        async def load_by_credit_key(self, **kwargs):
            return [_cand(env=ExtractIndexEnvironment.PRODUCTION)]

    adapter = IndexSelectAdapter(
        loader=RawLoader(),
        document_tree=_MemDocs(),
        default_fecha_limite_fn=_fecha_fn,
    )
    ev = ShadowIndexEvaluator(settings=_settings(), adapter=adapter)
    res = _run(
        ev.evaluate(
            official_v2=_v2(),
            request=_request(),
            bank_code="banco_bogota",
            process_date=date(2026, 7, 29),
        )
    )
    assert res.outcome == ShadowOutcomeKind.INDEX_INSUFFICIENT


def test_shadow_drive_mismatch() -> None:
    class RawLoader:
        async def load_by_credit_key(self, **kwargs):
            return [_cand(drive="OTHER")]

    adapter = IndexSelectAdapter(
        loader=RawLoader(),
        document_tree=_MemDocs(),
        default_fecha_limite_fn=_fecha_fn,
    )
    ev = ShadowIndexEvaluator(settings=_settings(), adapter=adapter)
    res = _run(
        ev.evaluate(
            official_v2=_v2(),
            request=_request(),
            bank_code="banco_bogota",
            process_date=date(2026, 7, 29),
        )
    )
    assert res.outcome == ShadowOutcomeKind.INDEX_INSUFFICIENT

    loader = _MemLoader([_cand(ctag="old")])
    adapter = IndexSelectAdapter(
        loader=loader,
        document_tree=_SlowDocs(),
        default_fecha_limite_fn=_fecha_fn,
    )
    ev = ShadowIndexEvaluator(
        settings=_settings(shadow_timeout_seconds=0.05),
        adapter=adapter,
    )
    res = _run(
        ev.evaluate(
            official_v2=_v2(),
            request=_request(live_ctag="new"),
            bank_code="banco_bogota",
            process_date=date(2026, 7, 29),
        )
    )
    assert res.outcome == ShadowOutcomeKind.INDEX_TIMEOUT
    assert res.isolated_error_type == "TimeoutError"


def test_shadow_429_isolated() -> None:
    err = httpx.HTTPStatusError(
        "429",
        request=httpx.Request("GET", "https://graph.microsoft.com"),
        response=httpx.Response(429, request=httpx.Request("GET", "https://x")),
    )
    adapter = IndexSelectAdapter(
        loader=_MemLoader(err),
        document_tree=_MemDocs(),
        default_fecha_limite_fn=_fecha_fn,
    )
    ev = ShadowIndexEvaluator(settings=_settings(), adapter=adapter)
    res = _run(
        ev.evaluate(
            official_v2=_v2(),
            request=_request(),
            bank_code="banco_bogota",
            process_date=date(2026, 7, 29),
        )
    )
    assert res.isolated_error_type is not None
    assert res.outcome == ShadowOutcomeKind.INDEX_ERROR


def test_shadow_403_isolated() -> None:
    from app.domain.exceptions import ExtractIndexError

    adapter = IndexSelectAdapter(
        loader=_MemLoader(ExtractIndexError("permiso denegado HTTP 403")),
        document_tree=_MemDocs(),
        default_fecha_limite_fn=_fecha_fn,
    )
    ev = ShadowIndexEvaluator(settings=_settings(), adapter=adapter)
    res = _run(
        ev.evaluate(
            official_v2=_v2(),
            request=_request(),
            bank_code="banco_bogota",
            process_date=date(2026, 7, 29),
        )
    )
    assert res.outcome == ShadowOutcomeKind.INDEX_UNAVAILABLE
    assert "403" in (res.isolated_error_message or "")


def test_shadow_schema_incompatible() -> None:
    adapter = IndexSelectAdapter(
        loader=_MemLoader(ExtractIndexSchemaError("schema bad")),
        document_tree=_MemDocs(),
        default_fecha_limite_fn=_fecha_fn,
    )
    ev = ShadowIndexEvaluator(settings=_settings(), adapter=adapter)
    res = _run(
        ev.evaluate(
            official_v2=_v2(),
            request=_request(),
            bank_code="banco_bogota",
            process_date=date(2026, 7, 29),
        )
    )
    assert res.outcome == ShadowOutcomeKind.INDEX_UNAVAILABLE
    assert res.isolated_error_type == "ExtractIndexSchemaError"


def test_shadow_credit_out_of_sample() -> None:
    adapter = IndexSelectAdapter(
        loader=_MemLoader([_cand()]),
        document_tree=_MemDocs(),
        default_fecha_limite_fn=_fecha_fn,
    )
    ev = ShadowIndexEvaluator(
        settings=_settings(shadow_sample_pct=0.0), adapter=adapter
    )
    res = _run(
        ev.evaluate(
            official_v2=_v2(),
            request=_request(),
            bank_code="banco_bogota",
            process_date=date(2026, 7, 29),
        )
    )
    assert res.skip_reason == ShadowSkipReason.CREDIT_OUT_OF_SAMPLE


def test_shadow_bank_not_allowed() -> None:
    adapter = IndexSelectAdapter(
        loader=_MemLoader([_cand()]),
        document_tree=_MemDocs(),
        default_fecha_limite_fn=_fecha_fn,
    )
    ev = ShadowIndexEvaluator(
        settings=_settings(shadow_allowed_banks=frozenset({"banco_bogota"})),
        adapter=adapter,
    )
    res = _run(
        ev.evaluate(
            official_v2=_v2(),
            request=_request(),
            bank_code="banco_bancolombia",
            process_date=date(2026, 7, 29),
        )
    )
    assert res.skip_reason == ShadowSkipReason.BANK_NOT_ALLOWED


def test_shadow_max_credits() -> None:
    adapter = IndexSelectAdapter(
        loader=_MemLoader([_cand()]),
        document_tree=_MemDocs(),
        default_fecha_limite_fn=_fecha_fn,
    )
    budget = ShadowJobBudget(evaluated=1)
    ev = ShadowIndexEvaluator(
        settings=_settings(shadow_max_credits=1),
        adapter=adapter,
        budget=budget,
    )
    res = _run(
        ev.evaluate(
            official_v2=_v2(),
            request=_request(),
            bank_code="banco_bogota",
            process_date=date(2026, 7, 29),
        )
    )
    assert res.skip_reason == ShadowSkipReason.MAX_CREDITS_REACHED


def test_shadow_unexpected_exception_isolated_v2_preserved() -> None:
    class BoomLoader(_MemLoader):
        async def load_by_credit_key(self, **kwargs):
            raise RuntimeError("unexpected boom")

    adapter = IndexSelectAdapter(
        loader=BoomLoader([]),
        document_tree=_MemDocs(),
        default_fecha_limite_fn=_fecha_fn,
    )
    ev = ShadowIndexEvaluator(settings=_settings(), adapter=adapter)
    v2 = _v2(item_id="KEEP", fecha=date(2026, 6, 1), err=None)
    res = _run(
        ev.evaluate(
            official_v2=v2,
            request=_request(),
            bank_code="banco_bogota",
            process_date=date(2026, 7, 29),
        )
    )
    assert res.isolated_error_type == "RuntimeError"
    assert v2.item_id == "KEEP"
    assert v2.fecha_limite == date(2026, 6, 1)
    assert v2.error_code is None
    assert res.official_v2_untouched is True


def test_zero_document_mutations_and_unauthorized_lists() -> None:
    fake = FakeMsGraph()
    guard = GraphMutationGuard(fake, allowed_list_ids={"list-indice"})
    port = GraphDocumentTreeReadOnlyAdapter(guard)
    assert_readonly_port_has_no_write_attrs(port)
    with pytest.raises(DocumentMutationForbidden):
        _run(guard.put_bytes("/drives/d1/items/1/content", b"x"))
    with pytest.raises(UnauthorizedListWriteError):
        _run(guard.post_json("/sites/s/lists/other/items", {"fields": {}}))
    assert fake.document_mutation_count() == 0


def test_mode_off_skips() -> None:
    adapter = IndexSelectAdapter(
        loader=_MemLoader([_cand()]),
        document_tree=_MemDocs(),
        default_fecha_limite_fn=_fecha_fn,
    )
    ev = ShadowIndexEvaluator(
        settings=_settings(mode=ExtractIndexMode.OFF), adapter=adapter
    )
    res = _run(
        ev.evaluate(
            official_v2=_v2(),
            request=_request(),
            bank_code="banco_bogota",
            process_date=date(2026, 7, 29),
        )
    )
    assert res.skip_reason == ShadowSkipReason.MODE_OFF
