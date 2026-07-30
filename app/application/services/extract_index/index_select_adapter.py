"""Adaptador async: selección vía índice (read-only + reconcile + select pura)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable, Protocol

from app.application.services.extract_index.extract_selection_v2 import (
    build_extract_pdf_pool_from_listings,
    select_extract_by_max_fecha_limite_from_bytes,
)
from app.application.services.extract_index.reconcile import (
    IndexedCandidateView,
    LiveFileMetadata,
    ReconcileActionKind,
    classify_index_sufficiency,
    reconcile_credit_candidates,
)
from app.application.services.extract_index.shadow_models import IndexSelectionSnapshot
from app.domain.models.extract_index import (
    ExtractIndexCandidate,
    ExtractIndexEnvironment,
    ParseStatus,
)
from app.domain.ports.document_tree_readonly import DocumentTreeReadOnlyPort


FechaLimiteFn = Callable[[bytes], date | None]


class IndexCandidateLoader(Protocol):
    """Carga candidatos del índice (fake o ExtractIndexRepository)."""

    async def load_by_credit_key(
        self, *, environment: ExtractIndexEnvironment, credit_key: str
    ) -> list[ExtractIndexCandidate]: ...


@dataclass
class IndexSelectMetrics:
    graph_list_calls: int = 0
    pdf_downloads: int = 0
    pdf_parses: int = 0
    index_hits: int = 0
    index_misses: int = 0
    fallback_required: int = 0
    elapsed_ms: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class IndexSelectRequest:
    environment: ExtractIndexEnvironment
    drive_id: str
    credit_key: str
    credit_path: str
    credit_folder_items: list[dict[str, Any]]
    extractos_children: list[dict[str, Any]] | None
    live_files: list[LiveFileMetadata]
    content_endpoint_builder: Callable[[str], str]
    """relative_path → endpoint GET content vía DocumentTreeReadOnlyPort."""
    parser_version: str = "v1"
    fecha_limite_fn: FechaLimiteFn | None = None


@dataclass(frozen=True, slots=True)
class IndexSelectResult:
    snapshot: IndexSelectionSnapshot
    metrics: IndexSelectMetrics
    sufficiency: ReconcileActionKind
    reconcile_fallback: bool


def _candidate_to_view(c: ExtractIndexCandidate) -> IndexedCandidateView:
    return IndexedCandidateView(
        item_id=c.item_id,
        doc_key=c.doc_key.as_string(),
        ctag=c.ctag,
        etag=c.etag,
        size=c.size,
        name=c.name,
        path=c.path,
        parse_status=c.parse_status,
        parser_version=c.parser_version,
        fecha_limite=c.fecha_limite,
        eliminado=c.eliminado,
    )


class IndexSelectAdapter:
    """
    Evalúa candidatos del índice + metadata live.

    Usa únicamente DocumentTreeReadOnlyPort para descargas.
    No escribe listas ni muta documentos.
    """

    def __init__(
        self,
        *,
        loader: IndexCandidateLoader,
        document_tree: DocumentTreeReadOnlyPort,
        default_fecha_limite_fn: FechaLimiteFn,
    ) -> None:
        self._loader = loader
        self._docs = document_tree
        self._default_fecha_fn = default_fecha_limite_fn

    async def select(self, request: IndexSelectRequest) -> IndexSelectResult:
        started = time.perf_counter()
        metrics = IndexSelectMetrics()
        fecha_fn = request.fecha_limite_fn or self._default_fecha_fn

        indexed = await self._loader.load_by_credit_key(
            environment=request.environment, credit_key=request.credit_key
        )
        metrics.graph_list_calls += 1

        if not indexed:
            metrics.index_misses += 1
            metrics.fallback_required += 1
            metrics.elapsed_ms = (time.perf_counter() - started) * 1000.0
            return IndexSelectResult(
                snapshot=IndexSelectionSnapshot(
                    error_code="index_empty",
                    fallback_required=True,
                ),
                metrics=metrics,
                sufficiency=ReconcileActionKind.FALLBACK_REQUIRED,
                reconcile_fallback=True,
            )

        # Duplicados DOC_KEY
        doc_keys = [c.doc_key.as_string() for c in indexed]
        if len(doc_keys) != len(set(doc_keys)):
            metrics.fallback_required += 1
            metrics.elapsed_ms = (time.perf_counter() - started) * 1000.0
            return IndexSelectResult(
                snapshot=IndexSelectionSnapshot(
                    error_code="index_duplicate_doc_key",
                    fallback_required=True,
                ),
                metrics=metrics,
                sufficiency=ReconcileActionKind.FALLBACK_REQUIRED,
                reconcile_fallback=True,
            )

        # Validar environment/drive
        for c in indexed:
            if c.environment != request.environment:
                metrics.fallback_required += 1
                metrics.elapsed_ms = (time.perf_counter() - started) * 1000.0
                return IndexSelectResult(
                    snapshot=IndexSelectionSnapshot(
                        error_code="index_environment_mismatch",
                        fallback_required=True,
                    ),
                    metrics=metrics,
                    sufficiency=ReconcileActionKind.FALLBACK_REQUIRED,
                    reconcile_fallback=True,
                )
            if c.drive_id != request.drive_id:
                metrics.fallback_required += 1
                metrics.elapsed_ms = (time.perf_counter() - started) * 1000.0
                return IndexSelectResult(
                    snapshot=IndexSelectionSnapshot(
                        error_code="index_drive_mismatch",
                        fallback_required=True,
                    ),
                    metrics=metrics,
                    sufficiency=ReconcileActionKind.FALLBACK_REQUIRED,
                    reconcile_fallback=True,
                )

        views = [_candidate_to_view(c) for c in indexed]
        reconcile = reconcile_credit_candidates(
            environment=request.environment.value,
            drive_id=request.drive_id,
            indexed=views,
            live=request.live_files,
            current_parser_version=request.parser_version,
        )
        has_fecha = any(c.fecha_limite is not None and not c.eliminado for c in indexed)
        sufficiency = classify_index_sufficiency(
            actions=reconcile.actions, has_fecha_limite_cached=has_fecha
        )

        if reconcile.fallback_required or sufficiency == ReconcileActionKind.FALLBACK_REQUIRED:
            metrics.fallback_required += 1
            metrics.index_misses += 1
            metrics.elapsed_ms = (time.perf_counter() - started) * 1000.0
            return IndexSelectResult(
                snapshot=IndexSelectionSnapshot(
                    error_code="index_insufficient",
                    fallback_required=True,
                ),
                metrics=metrics,
                sufficiency=ReconcileActionKind.FALLBACK_REQUIRED,
                reconcile_fallback=True,
            )

        need_download_ids = {
            a.item_id
            for a in reconcile.actions
            if a.kind
            in (
                ReconcileActionKind.DOWNLOAD_AND_PARSE,
                ReconcileActionKind.RETRY_PARSE,
            )
            and a.item_id
        }

        # Hit: mismo cTag → reutilizar fecha_limite del índice sin descargar.
        if sufficiency == ReconcileActionKind.UNCHANGED and not need_download_ids:
            usable = [
                c
                for c in indexed
                if not c.eliminado
                and c.fecha_limite is not None
                and c.parse_status == ParseStatus.OK
            ]
            if not usable:
                metrics.fallback_required += 1
                metrics.elapsed_ms = (time.perf_counter() - started) * 1000.0
                return IndexSelectResult(
                    snapshot=IndexSelectionSnapshot(
                        error_code="index_parse_error",
                        fallback_required=True,
                    ),
                    metrics=metrics,
                    sufficiency=ReconcileActionKind.FALLBACK_REQUIRED,
                    reconcile_fallback=True,
                )
            max_d = max(c.fecha_limite for c in usable if c.fecha_limite is not None)
            winners = [c for c in usable if c.fecha_limite == max_d]
            if len(winners) > 1:
                metrics.elapsed_ms = (time.perf_counter() - started) * 1000.0
                return IndexSelectResult(
                    snapshot=IndexSelectionSnapshot(
                        error_code="extract_tie_max_fecha_limite",
                        fallback_required=True,
                    ),
                    metrics=metrics,
                    sufficiency=ReconcileActionKind.FALLBACK_REQUIRED,
                    reconcile_fallback=True,
                )
            w = winners[0]
            metrics.index_hits += 1
            metrics.elapsed_ms = (time.perf_counter() - started) * 1000.0
            return IndexSelectResult(
                snapshot=IndexSelectionSnapshot(
                    item_id=w.item_id,
                    fecha_limite=w.fecha_limite,
                    source_location=w.ubicacion or None,
                    selection_reason="index_hit_max_fecha_limite",
                    relative_path=w.path or None,
                ),
                metrics=metrics,
                sufficiency=ReconcileActionKind.UNCHANGED,
                reconcile_fallback=False,
            )

        pool = build_extract_pdf_pool_from_listings(
            credit_path=request.credit_path,
            credit_folder_items=request.credit_folder_items,
            extractos_children=request.extractos_children,
        )

        content_by_path: dict[str, bytes] = {}
        for cand in pool:
            rel = str(cand.get("relative_path") or "")
            if not rel:
                continue
            endpoint = request.content_endpoint_builder(rel)
            try:
                content_by_path[rel] = await self._docs.get_bytes(endpoint)
                metrics.pdf_downloads += 1
            except Exception:
                continue

        if not content_by_path:
            metrics.fallback_required += 1
            metrics.elapsed_ms = (time.perf_counter() - started) * 1000.0
            return IndexSelectResult(
                snapshot=IndexSelectionSnapshot(
                    error_code="index_insufficient",
                    fallback_required=True,
                ),
                metrics=metrics,
                sufficiency=ReconcileActionKind.FALLBACK_REQUIRED,
                reconcile_fallback=True,
            )

        outcome = select_extract_by_max_fecha_limite_from_bytes(
            pool,
            content_by_relative_path=content_by_path,
            fecha_limite_fn=fecha_fn,
        )
        metrics.pdf_parses += len(content_by_path)
        metrics.elapsed_ms = (time.perf_counter() - started) * 1000.0

        if outcome.error_code:
            metrics.fallback_required += 1
            return IndexSelectResult(
                snapshot=IndexSelectionSnapshot(
                    error_code=outcome.error_code,
                    fallback_required=True,
                    selection_reason=outcome.selection_reason,
                ),
                metrics=metrics,
                sufficiency=ReconcileActionKind.FALLBACK_REQUIRED,
                reconcile_fallback=True,
            )

        item = outcome.item or {}
        meta = outcome.candidate_meta or {}
        metrics.index_hits += 1
        return IndexSelectResult(
            snapshot=IndexSelectionSnapshot(
                item_id=str(item.get("id") or "") or None,
                fecha_limite=outcome.fecha_limite,
                source_location=str(meta.get("source_location") or "") or None,
                selection_reason=outcome.selection_reason,
                relative_path=str(meta.get("relative_path") or "") or None,
            ),
            metrics=metrics,
            sufficiency=sufficiency,
            reconcile_fallback=False,
        )
