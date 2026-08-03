"""Catálogo de documentos del proceso (grupos N) para UI sin saturar la página.

Los enlaces 1:1 del lote (revisión, histórico, correo) siguen en `links`.
Los conjuntos grandes (PDFs consolidados, tablas de amortización) van en
`document_groups` con conteo + lista para drawer en el frontend.
"""
from __future__ import annotations

from typing import Any, Mapping, Protocol, Sequence

from app.application.ui.schemas import UiDocumentGroup, UiLink


class _JobPayloadSource(Protocol):
    """Mínimo para leer ``result`` del job Apply/amortization (JobReadResult)."""

    @property
    def payload(self) -> Mapping[str, Any]: ...


def _nz(value: str | None) -> str:
    return (value or "").strip()


def is_merge_pdf_rel(rel: str) -> bool:
    r = _nz(rel)
    return r == "merge_pdf" or r.startswith("merge_pdf:")


def apply_result_from_staged_jobs(
    staged_jobs: Mapping[str, _JobPayloadSource],
) -> dict[str, Any] | None:
    """Lee el resultado Apply para ``document_groups`` / tablas de amortización.

    La UI normaliza el job bajo ``\"amortization\"``; ``\"apply\"`` queda como
    fallback legacy/PA. Sin esto, ``tables_updated_links`` no llega al catálogo.
    """
    for key in ("amortization", "apply"):
        job = staged_jobs.get(key)
        if job is None:
            continue
        raw = job.payload.get("result")
        if isinstance(raw, dict):
            return raw
    return None


def links_to_group(
    *,
    group_id: str,
    title: str,
    links: Sequence[UiLink],
) -> UiDocumentGroup | None:
    items = [l for l in links if l is not None]
    if not items:
        return None
    return UiDocumentGroup(
        id=group_id,
        title=title,
        count=len(items),
        links=list(items),
    )


def merge_pdf_group_from_links(links: Sequence[UiLink]) -> UiDocumentGroup | None:
    merge_links = [l for l in links if is_merge_pdf_rel(l.rel)]
    return links_to_group(
        group_id="merge_pdfs",
        title="PDFs consolidados",
        links=merge_links,
    )


def amortization_links_from_apply_result(result: dict[str, Any] | None) -> list[UiLink]:
    """Convierte tables_updated_links del job Apply a UiLink seguros."""
    if not isinstance(result, dict):
        return []
    raw = result.get("tables_updated_links")
    if not isinstance(raw, list):
        return []
    out: list[UiLink] = []
    for idx, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        label = _nz(str(item.get("label") or "")) or f"Tabla de amortización {idx + 1}"
        url = _nz(str(item.get("file_url") or item.get("web_url") or ""))
        path = _nz(str(item.get("path") or item.get("tabla_amortizacion_path") or ""))
        if not url and not path:
            continue
        out.append(
            UiLink(
                rel=f"amort_table:{idx}",
                label=label,
                path=path or None,
                web_url=url or None,
                open_mode="sharepoint",
            )
        )
    return out


def amortization_group_from_apply_result(
    result: dict[str, Any] | None,
) -> UiDocumentGroup | None:
    return links_to_group(
        group_id="amortization_tables",
        title="Tablas de amortización",
        links=amortization_links_from_apply_result(result),
    )


def document_groups_from_archive_payload(
    raw_groups: Any,
) -> list[UiDocumentGroup]:
    """Rehidrata grupos desde JSON de archivo (compat: ausente → [])."""
    if not isinstance(raw_groups, list):
        return []
    out: list[UiDocumentGroup] = []
    for raw in raw_groups:
        if not isinstance(raw, dict):
            continue
        gid = _nz(str(raw.get("id") or ""))
        title = _nz(str(raw.get("title") or ""))
        if not gid or not title:
            continue
        links_raw = raw.get("links") if isinstance(raw.get("links"), list) else []
        links: list[UiLink] = []
        for idx, item in enumerate(links_raw):
            if not isinstance(item, dict):
                continue
            rel = _nz(str(item.get("rel") or f"{gid}:{idx}"))
            label = _nz(str(item.get("label") or "")) or rel
            path = _nz(str(item.get("path") or "")) or None
            web_url = _nz(str(item.get("web_url") or item.get("file_url") or "")) or None
            if not path and not web_url:
                continue
            links.append(
                UiLink(
                    rel=rel,
                    label=label,
                    path=path,
                    web_url=web_url,
                    open_mode="sharepoint",
                )
            )
        if not links:
            continue
        out.append(
            UiDocumentGroup(
                id=gid,
                title=title,
                count=len(links),
                links=links,
            )
        )
    return out


def serialize_document_groups(groups: Sequence[UiDocumentGroup]) -> list[dict[str, Any]]:
    return [
        {
            "id": g.id,
            "title": g.title,
            "count": g.count,
            "links": [
                {
                    "rel": l.rel,
                    "label": l.label,
                    "path": l.path,
                    "web_url": l.web_url,
                    "open_mode": l.open_mode,
                }
                for l in g.links
            ],
        }
        for g in groups
    ]


def build_live_document_groups(
    *,
    links: Sequence[UiLink],
    apply_result: dict[str, Any] | None,
) -> list[UiDocumentGroup]:
    """Grupos para proceso activo: merge desde links + amort desde job Apply."""
    groups: list[UiDocumentGroup] = []
    merge = merge_pdf_group_from_links(links)
    if merge is not None:
        groups.append(merge)
    amort = amortization_group_from_apply_result(apply_result)
    if amort is not None:
        groups.append(amort)
    return groups
