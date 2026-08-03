"""Catálogo de documentos UI (grupos N) — sin Graph."""
from __future__ import annotations

from app.application.ui.document_catalog import (
    amortization_group_from_apply_result,
    apply_result_from_staged_jobs,
    build_live_document_groups,
    document_groups_from_archive_payload,
    merge_pdf_group_from_links,
    serialize_document_groups,
)
from app.application.ui.schemas import UiLink


def test_merge_pdf_group_counts_indexed_rels() -> None:
    links = [
        UiLink(rel="review_excel", label="Rev", path="a.xlsx", web_url="https://x/a"),
        UiLink(rel="merge_pdf:0", label="PDF 1", path="p1.pdf", web_url="https://x/1"),
        UiLink(rel="merge_pdf:1", label="PDF 2", path="p2.pdf", web_url="https://x/2"),
    ]
    group = merge_pdf_group_from_links(links)
    assert group is not None
    assert group.id == "merge_pdfs"
    assert group.count == 2


def test_amortization_group_from_apply_result() -> None:
    group = amortization_group_from_apply_result(
        {
            "tables_updated_links": [
                {
                    "label": "Cliente A",
                    "path": "clientes/a.xlsx",
                    "file_url": "https://sp/a",
                },
                {"label": "Cliente B", "file_url": "https://sp/b"},
            ]
        }
    )
    assert group is not None
    assert group.count == 2
    assert group.links[0].web_url == "https://sp/a"
    assert group.links[0].path == "clientes/a.xlsx"


def test_build_live_document_groups_combines_merge_and_amort() -> None:
    links = [
        UiLink(rel="merge_pdf", label="PDF", path="m.pdf", web_url="https://x/m"),
        UiLink(rel="email_pdf", label="Correo", path="e.pdf", web_url="https://x/e"),
    ]
    groups = build_live_document_groups(
        links=links,
        apply_result={
            "tables_updated_links": [
                {"label": "T1", "file_url": "https://sp/t1"},
            ]
        },
    )
    ids = [g.id for g in groups]
    assert ids == ["merge_pdfs", "amortization_tables"]


def test_archive_roundtrip_document_groups() -> None:
    links = [
        UiLink(
            rel="amort_table:0",
            label="Tabla",
            path="t.xlsx",
            web_url="https://sp/t",
        )
    ]
    group = amortization_group_from_apply_result(
        {"tables_updated_links": [{"label": "Tabla", "path": "t.xlsx", "file_url": "https://sp/t"}]}
    )
    assert group is not None
    raw = serialize_document_groups([group])
    restored = document_groups_from_archive_payload(raw)
    assert len(restored) == 1
    assert restored[0].links[0].label == "Tabla"
    assert len(links) == 1  # sanity


class _FakeJob:
    def __init__(self, payload: dict) -> None:
        self.payload = payload


def test_apply_result_prefers_amortization_stage_over_apply() -> None:
    amort_job = _FakeJob(
        payload={
            "type": "amortization_process",
            "result": {
                "tables_updated_links": [
                    {"label": "Tabla UI", "file_url": "https://sp/ui"},
                ]
            },
        }
    )
    legacy_apply = _FakeJob(
        payload={
            "type": "amortization_apply",
            "result": {
                "tables_updated_links": [
                    {"label": "Tabla legacy", "file_url": "https://sp/legacy"},
                ]
            },
        }
    )
    result = apply_result_from_staged_jobs(
        {"amortization": amort_job, "apply": legacy_apply}
    )
    assert result is not None
    assert result["tables_updated_links"][0]["label"] == "Tabla UI"

