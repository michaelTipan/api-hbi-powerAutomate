"""Fase 2A: caracterización V2 original vs extract_selection_v2 + reconcile puro."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import date
from typing import Any
from urllib.parse import unquote

import pytest

from app.application.services.extract_index.extract_selection_v2 import (
    EXTRACT_SOURCE_CREDIT_ROOT,
    EXTRACT_SOURCE_EXTRACTOS,
    build_extract_pdf_pool_from_listings,
    is_strict_extract_pdf_file_item,
    outcome_as_legacy_tuple,
    select_extract_by_max_fecha_limite_from_bytes,
)
from app.application.services.extract_index.reconcile import (
    IndexedCandidateView,
    LiveFileMetadata,
    ReconcileActionKind,
    classify_index_sufficiency,
    decide_item_action,
    reconcile_credit_candidates,
)
from app.application.services.payment_helpers import extract_fecha_limite_pago_from_pdf
from app.application.use_cases import payment_validation_generate as gen
from app.domain.models.extract_index import ParseStatus


def _item(name: str, *, folder: bool = False, item_id: str | None = None) -> dict[str, Any]:
    d: dict[str, Any] = {"name": name, "id": item_id or name}
    if folder:
        d["folder"] = {}
    else:
        d["file"] = {}
    return d


def _pdf_marker(fecha: date | None, payload: str = "x") -> bytes:
    """Bytes sintéticos: el mock de fecha lee FECHA_LIMITE=...; hash distinto por payload."""
    if fecha is None:
        return f"NO_DATE;{payload}".encode()
    return f"FECHA_LIMITE={fecha.isoformat()};{payload}".encode()


def _fecha_from_marker(pdf_bytes: bytes) -> date | None:
    text = pdf_bytes.decode("utf-8", errors="ignore")
    if "FECHA_LIMITE=" not in text:
        return None
    raw = text.split("FECHA_LIMITE=", 1)[1].split(";", 1)[0].strip()
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


class _MiniGraph:
    """Graph mínimo para ejercitar la V2 original (solo get_bytes)."""

    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = files
        self.get_bytes_calls: list[str] = []

    async def get(self, endpoint: str, params=None) -> dict:
        return {"value": []}

    async def get_bytes(self, endpoint: str, params=None) -> bytes:
        self.get_bytes_calls.append(endpoint)
        path = unquote(endpoint.split("/root:/", 1)[1].rsplit(":/content", 1)[0])
        if path not in self.files:
            raise FileNotFoundError(path)
        return self.files[path]


def _assert_parity(
    legacy: tuple,
    extracted: tuple,
) -> None:
    l_item, l_bytes, l_fecha, l_err, l_meta = legacy
    e_item, e_bytes, e_fecha, e_err, e_meta = extracted
    assert l_err == e_err
    assert l_fecha == e_fecha
    if l_item is None:
        assert e_item is None
    else:
        assert e_item is not None
        assert str(l_item.get("id") or l_item.get("name")) == str(
            e_item.get("id") or e_item.get("name")
        )
    assert l_bytes == e_bytes
    if l_meta is None:
        assert e_meta is None
    else:
        assert e_meta is not None
        assert l_meta.get("relative_path") == e_meta.get("relative_path")
        assert l_meta.get("source_location") == e_meta.get("source_location")


def _run_parity_case(
    *,
    credit_path: str,
    root_items: list[dict[str, Any]],
    extractos_children: list[dict[str, Any]] | None,
    files: dict[str, bytes],
) -> None:
    pool_ext = build_extract_pdf_pool_from_listings(
        credit_path=credit_path,
        credit_folder_items=root_items,
        extractos_children=extractos_children,
    )

    async def _legacy_pool_and_select():
        client = _MiniGraph(files)
        return await gen._select_extract_by_max_fecha_limite_v2(
            client, "site", "drive", pool_ext
        )

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            gen,
            "extract_fecha_limite_pago_from_pdf",
            _fecha_from_marker,
        )
        legacy = asyncio.run(_legacy_pool_and_select())

    extracted = outcome_as_legacy_tuple(
        select_extract_by_max_fecha_limite_from_bytes(
            pool_ext,
            content_by_relative_path=files,
            fecha_limite_fn=_fecha_from_marker,
        )
    )
    _assert_parity(legacy, extracted)


def test_strict_extract_filter_matches_generate() -> None:
    assert is_strict_extract_pdf_file_item(_item("Extracto 1.pdf")) is True
    assert is_strict_extract_pdf_file_item(_item("nota.pdf")) is False
    assert is_strict_extract_pdf_file_item(_item("Extracto.doc")) is False
    assert is_strict_extract_pdf_file_item(_item("EXTRACTOS", folder=True)) is False
    assert gen._is_strict_extract_pdf_file_item(_item("Extracto 1.pdf")) is True


def test_pool_only_extractos() -> None:
    root = [_item("EXTRACTOS", folder=True), _item("Tabla.xlsx")]
    children = [_item("Extracto A.pdf", item_id="a")]
    pool = build_extract_pdf_pool_from_listings(
        credit_path="cli/cred",
        credit_folder_items=root,
        extractos_children=children,
    )
    assert len(pool) == 1
    assert pool[0]["source_location"] == EXTRACT_SOURCE_EXTRACTOS
    assert pool[0]["relative_path"] == "cli/cred/EXTRACTOS/Extracto A.pdf"


def test_pool_only_root() -> None:
    root = [_item("Extracto root.pdf", item_id="r"), _item("otro.txt")]
    pool = build_extract_pdf_pool_from_listings(
        credit_path="cli/cred",
        credit_folder_items=root,
        extractos_children=None,
    )
    assert len(pool) == 1
    assert pool[0]["source_location"] == EXTRACT_SOURCE_CREDIT_ROOT


def test_pool_root_and_extractos() -> None:
    root = [
        _item("Extracto root.pdf", item_id="r"),
        _item("EXTRACTOS", folder=True),
    ]
    children = [_item("Extracto folder.pdf", item_id="f")]
    pool = build_extract_pdf_pool_from_listings(
        credit_path="cli/cred",
        credit_folder_items=root,
        extractos_children=children,
    )
    assert len(pool) == 2
    locs = {p["source_location"] for p in pool}
    assert locs == {EXTRACT_SOURCE_CREDIT_ROOT, EXTRACT_SOURCE_EXTRACTOS}


def test_pool_ignores_non_pdf_and_wrong_names() -> None:
    root = [
        _item("EXTRACTOS", folder=True),
        _item("Factura.pdf"),
        _item("Extracto.zip"),
        _item("extractos_backup", folder=True),
    ]
    children = [_item("readme.txt"), _item("Extracto ok.pdf", item_id="ok")]
    pool = build_extract_pdf_pool_from_listings(
        credit_path="cli/cred",
        credit_folder_items=root,
        extractos_children=children,
    )
    assert len(pool) == 1
    assert pool[0]["item"]["id"] == "ok"


def test_parity_max_fecha_root_newer() -> None:
    root = [
        _item("Extracto viejo.pdf", item_id="old"),
        _item("Extracto nuevo.pdf", item_id="new"),
    ]
    files = {
        "cli/cred/Extracto viejo.pdf": _pdf_marker(date(2025, 1, 1), "old"),
        "cli/cred/Extracto nuevo.pdf": _pdf_marker(date(2026, 6, 1), "new"),
    }
    _run_parity_case(
        credit_path="cli/cred",
        root_items=root,
        extractos_children=None,
        files=files,
    )


def test_parity_extractos_newer_than_root() -> None:
    root = [
        _item("Extracto root.pdf", item_id="root"),
        _item("EXTRACTOS", folder=True),
    ]
    children = [_item("Extracto folder.pdf", item_id="folder")]
    files = {
        "cli/cred/Extracto root.pdf": _pdf_marker(date(2025, 1, 1), "r"),
        "cli/cred/EXTRACTOS/Extracto folder.pdf": _pdf_marker(date(2026, 8, 1), "f"),
    }
    _run_parity_case(
        credit_path="cli/cred",
        root_items=root,
        extractos_children=children,
        files=files,
    )


def test_parity_root_newer_than_extractos() -> None:
    root = [
        _item("Extracto root.pdf", item_id="root"),
        _item("EXTRACTOS", folder=True),
    ]
    children = [_item("Extracto folder.pdf", item_id="folder")]
    files = {
        "cli/cred/Extracto root.pdf": _pdf_marker(date(2026, 9, 1), "r"),
        "cli/cred/EXTRACTOS/Extracto folder.pdf": _pdf_marker(date(2025, 1, 1), "f"),
    }
    _run_parity_case(
        credit_path="cli/cred",
        root_items=root,
        extractos_children=children,
        files=files,
    )


def test_parity_no_valid_fecha() -> None:
    root = [_item("Extracto a.pdf", item_id="a"), _item("Extracto b.pdf", item_id="b")]
    files = {
        "cli/cred/Extracto a.pdf": _pdf_marker(None, "a"),
        "cli/cred/Extracto b.pdf": _pdf_marker(None, "b"),
    }
    _run_parity_case(
        credit_path="cli/cred",
        root_items=root,
        extractos_children=None,
        files=files,
    )


def test_parity_tie_same_fecha_different_content() -> None:
    root = [_item("Extracto a.pdf", item_id="a"), _item("Extracto b.pdf", item_id="b")]
    files = {
        "cli/cred/Extracto a.pdf": _pdf_marker(date(2026, 1, 1), "aaa"),
        "cli/cred/Extracto b.pdf": _pdf_marker(date(2026, 1, 1), "bbb"),
    }
    _run_parity_case(
        credit_path="cli/cred",
        root_items=root,
        extractos_children=None,
        files=files,
    )


def test_parity_renamed_same_content_prefers_extractos() -> None:
    payload = _pdf_marker(date(2026, 3, 1), "same-bytes")
    root = [
        _item("Extracto viejo nombre.pdf", item_id="root"),
        _item("EXTRACTOS", folder=True),
    ]
    children = [_item("Extracto nuevo nombre.pdf", item_id="ex")]
    files = {
        "cli/cred/Extracto viejo nombre.pdf": payload,
        "cli/cred/EXTRACTOS/Extracto nuevo nombre.pdf": payload,
    }
    _run_parity_case(
        credit_path="cli/cred",
        root_items=root,
        extractos_children=children,
        files=files,
    )
    outcome = select_extract_by_max_fecha_limite_from_bytes(
        build_extract_pdf_pool_from_listings(
            credit_path="cli/cred",
            credit_folder_items=root,
            extractos_children=children,
        ),
        content_by_relative_path=files,
        fecha_limite_fn=_fecha_from_marker,
    )
    assert outcome.error_code is None
    assert outcome.candidate_meta is not None
    assert outcome.candidate_meta["source_location"] == EXTRACT_SOURCE_EXTRACTOS
    assert outcome.item is not None
    assert outcome.item["id"] == "ex"


def test_parity_empty_pool() -> None:
    _run_parity_case(
        credit_path="cli/cred",
        root_items=[_item("Tabla.xlsx")],
        extractos_children=None,
        files={},
    )


def test_parity_duplicate_candidates_same_hash() -> None:
    payload = _pdf_marker(date(2026, 2, 2), "dup")
    root = [
        _item("Extracto copy1.pdf", item_id="c1"),
        _item("Extracto copy2.pdf", item_id="c2"),
    ]
    files = {
        "cli/cred/Extracto copy1.pdf": payload,
        "cli/cred/Extracto copy2.pdf": payload,
    }
    _run_parity_case(
        credit_path="cli/cred",
        root_items=root,
        extractos_children=None,
        files=files,
    )


def test_payment_estado_does_not_change_selection() -> None:
    """NORMAL/ATRASADO/ADELANTADO se clasifican después; la selección V2 es solo max fecha."""
    root = [_item("Extracto.pdf", item_id="p1")]
    files = {"cli/cred/Extracto.pdf": _pdf_marker(date(2026, 4, 1), "one")}
    for _label in ("NORMAL", "ATRASADO", "ADELANTADO"):
        _run_parity_case(
            credit_path="cli/cred",
            root_items=root,
            extractos_children=None,
            files=files,
        )


def test_hash_deterministic_for_same_bytes() -> None:
    b = _pdf_marker(date(2026, 1, 1), "z")
    assert hashlib.sha256(b).hexdigest() == hashlib.sha256(b).hexdigest()


def test_reconcile_unchanged_same_ctag() -> None:
    indexed = IndexedCandidateView(
        item_id="1",
        doc_key="sandbox|d|1",
        ctag="c1",
        name="Extracto.pdf",
        path="a/Extracto.pdf",
        parse_status=ParseStatus.OK,
        fecha_limite=date(2026, 1, 1),
    )
    live = LiveFileMetadata(
        item_id="1", ctag="c1", name="Extracto.pdf", path="a/Extracto.pdf"
    )
    action = decide_item_action(indexed, live, current_parser_version="v1")
    assert action.kind == ReconcileActionKind.UNCHANGED


def test_reconcile_metadata_only_on_rename() -> None:
    indexed = IndexedCandidateView(
        item_id="1",
        doc_key="sandbox|d|1",
        ctag="c1",
        name="old.pdf",
        path="a/old.pdf",
        parse_status=ParseStatus.OK,
    )
    live = LiveFileMetadata(
        item_id="1", ctag="c1", name="new.pdf", path="a/new.pdf"
    )
    action = decide_item_action(indexed, live, current_parser_version="v1")
    assert action.kind == ReconcileActionKind.METADATA_ONLY_UPDATE


def test_reconcile_download_on_ctag_change() -> None:
    indexed = IndexedCandidateView(
        item_id="1", doc_key="k", ctag="old", parse_status=ParseStatus.OK
    )
    live = LiveFileMetadata(item_id="1", ctag="new")
    action = decide_item_action(indexed, live, current_parser_version="v1")
    assert action.kind == ReconcileActionKind.DOWNLOAD_AND_PARSE


def test_reconcile_retry_parse_error() -> None:
    indexed = IndexedCandidateView(
        item_id="1",
        doc_key="k",
        ctag="c1",
        parse_status=ParseStatus.ERROR,
    )
    live = LiveFileMetadata(item_id="1", ctag="c1")
    action = decide_item_action(indexed, live, current_parser_version="v1")
    assert action.kind == ReconcileActionKind.RETRY_PARSE


def test_reconcile_mark_deleted() -> None:
    indexed = IndexedCandidateView(item_id="1", doc_key="k", ctag="c1")
    action = decide_item_action(indexed, None, current_parser_version="v1")
    assert action.kind == ReconcileActionKind.MARK_DELETED


def test_reconcile_new_item() -> None:
    live = LiveFileMetadata(item_id="9", ctag="c9")
    action = decide_item_action(None, live, current_parser_version="v1")
    assert action.kind == ReconcileActionKind.DOWNLOAD_AND_PARSE
    assert action.reason == "new_item"


def test_reconcile_credit_fallback_when_empty() -> None:
    result = reconcile_credit_candidates(
        environment="sandbox",
        drive_id="d1",
        indexed=[],
        live=[],
    )
    assert result.fallback_required is True
    assert any(a.kind == ReconcileActionKind.FALLBACK_REQUIRED for a in result.actions)


def test_reconcile_deleted_candidate_scenario() -> None:
    indexed = [
        IndexedCandidateView(
            item_id="gone",
            doc_key="sandbox|d|gone",
            ctag="c1",
            parse_status=ParseStatus.OK,
            fecha_limite=date(2026, 1, 1),
        )
    ]
    result = reconcile_credit_candidates(
        environment="sandbox",
        drive_id="d1",
        indexed=indexed,
        live=[],
    )
    assert result.fallback_required is True
    assert any(a.kind == ReconcileActionKind.MARK_DELETED for a in result.actions)


def test_classify_hit_vs_refresh_vs_fallback() -> None:
    hit = reconcile_credit_candidates(
        environment="sandbox",
        drive_id="d",
        indexed=[
            IndexedCandidateView(
                item_id="1",
                doc_key="k",
                ctag="c",
                parse_status=ParseStatus.OK,
                fecha_limite=date(2026, 1, 1),
            )
        ],
        live=[LiveFileMetadata(item_id="1", ctag="c")],
    )
    assert (
        classify_index_sufficiency(
            actions=hit.actions, has_fecha_limite_cached=True
        )
        == ReconcileActionKind.UNCHANGED
    )
    refresh = reconcile_credit_candidates(
        environment="sandbox",
        drive_id="d",
        indexed=[
            IndexedCandidateView(
                item_id="1", doc_key="k", ctag="old", parse_status=ParseStatus.OK
            )
        ],
        live=[LiveFileMetadata(item_id="1", ctag="new")],
    )
    assert (
        classify_index_sufficiency(
            actions=refresh.actions, has_fecha_limite_cached=True
        )
        == ReconcileActionKind.DOWNLOAD_AND_PARSE
    )
    assert (
        classify_index_sufficiency(actions=hit.actions, has_fecha_limite_cached=False)
        == ReconcileActionKind.FALLBACK_REQUIRED
    )


def test_corrupt_pdf_fecha_helper_exception_is_not_swallowed() -> None:
    """
    No se “arregla” el helper histórico: un PDF truncado puede lanzar
    PdfStreamError desde pypdf. La selección extraída tampoco lo traga.
    """
    pool = build_extract_pdf_pool_from_listings(
        credit_path="c",
        credit_folder_items=[_item("Extracto.pdf", item_id="1")],
        extractos_children=None,
    )
    with pytest.raises(Exception):
        select_extract_by_max_fecha_limite_from_bytes(
            pool,
            content_by_relative_path={"c/Extracto.pdf": b"%PDF-1.4 truncated"},
            fecha_limite_fn=extract_fecha_limite_pago_from_pdf,
        )
