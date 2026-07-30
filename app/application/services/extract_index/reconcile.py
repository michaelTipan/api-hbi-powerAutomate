"""
Motor puro de detección de cambios / reconciliación del índice (Fase 2A).

No llama Graph, no escribe listas, no decide el resultado oficial de Generate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Any

from app.domain.models.extract_index import ParseStatus


class ReconcileActionKind(str, Enum):
    UNCHANGED = "unchanged"
    METADATA_ONLY_UPDATE = "metadata_only_update"
    DOWNLOAD_AND_PARSE = "download_and_parse"
    RETRY_PARSE = "retry_parse"
    MARK_DELETED = "mark_deleted"
    FALLBACK_REQUIRED = "fallback_required"


@dataclass(frozen=True, slots=True)
class IndexedCandidateView:
    """Vista mínima de una fila del índice."""

    item_id: str
    doc_key: str
    ctag: str = ""
    etag: str = ""
    size: int | None = None
    name: str = ""
    path: str = ""
    parse_status: ParseStatus = ParseStatus.PENDING
    parser_version: str = ""
    fecha_limite: date | None = None
    eliminado: bool = False


@dataclass(frozen=True, slots=True)
class LiveFileMetadata:
    """Metadata actual de un PDF candidato en el drive (ya listada)."""

    item_id: str
    name: str = ""
    path: str = ""
    ctag: str = ""
    etag: str = ""
    size: int | None = None
    source_location: str = ""


@dataclass(frozen=True, slots=True)
class ReconcileAction:
    kind: ReconcileActionKind
    item_id: str = ""
    doc_key: str = ""
    reason: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ReconcileResult:
    environment: str
    drive_id: str
    actions: tuple[ReconcileAction, ...]
    fallback_required: bool
    fallback_reason: str = ""


def _metadata_differs(indexed: IndexedCandidateView, live: LiveFileMetadata) -> bool:
    if indexed.name and live.name and indexed.name != live.name:
        return True
    if indexed.path and live.path and indexed.path != live.path:
        return True
    if indexed.etag and live.etag and indexed.etag != live.etag:
        # etag puede cambiar con metadata; si ctag igual priorizamos metadata_only
        return True
    if indexed.size is not None and live.size is not None and indexed.size != live.size:
        return True
    return False


def decide_item_action(
    indexed: IndexedCandidateView | None,
    live: LiveFileMetadata | None,
    *,
    current_parser_version: str,
) -> ReconcileAction:
    """Decisión pura para un par índice/live (mismo item_id)."""
    if indexed is None and live is None:
        return ReconcileAction(
            ReconcileActionKind.FALLBACK_REQUIRED,
            reason="empty_pair",
        )
    if live is None and indexed is not None:
        return ReconcileAction(
            ReconcileActionKind.MARK_DELETED,
            item_id=indexed.item_id,
            doc_key=indexed.doc_key,
            reason="missing_on_drive",
        )
    assert live is not None
    if indexed is None:
        return ReconcileAction(
            ReconcileActionKind.DOWNLOAD_AND_PARSE,
            item_id=live.item_id,
            reason="new_item",
        )

    # Parse error previo con misma identidad de contenido → reintento
    if indexed.parse_status == ParseStatus.ERROR:
        same_ctag = bool(indexed.ctag) and indexed.ctag == live.ctag
        if same_ctag or (not indexed.ctag and indexed.etag and indexed.etag == live.etag):
            return ReconcileAction(
                ReconcileActionKind.RETRY_PARSE,
                item_id=live.item_id,
                doc_key=indexed.doc_key,
                reason="previous_parse_error",
            )
        return ReconcileAction(
            ReconcileActionKind.DOWNLOAD_AND_PARSE,
            item_id=live.item_id,
            doc_key=indexed.doc_key,
            reason="parse_error_and_content_changed",
        )

    # Parser version distinta → re-parse (descarga si ctag cambió; si no, retry)
    if (
        current_parser_version
        and indexed.parser_version
        and current_parser_version != indexed.parser_version
    ):
        if indexed.ctag and live.ctag and indexed.ctag == live.ctag:
            return ReconcileAction(
                ReconcileActionKind.RETRY_PARSE,
                item_id=live.item_id,
                doc_key=indexed.doc_key,
                reason="parser_version_changed",
            )
        return ReconcileAction(
            ReconcileActionKind.DOWNLOAD_AND_PARSE,
            item_id=live.item_id,
            doc_key=indexed.doc_key,
            reason="parser_version_changed_unknown_content",
        )

    if indexed.ctag and live.ctag:
        if indexed.ctag == live.ctag:
            if _metadata_differs(indexed, live):
                return ReconcileAction(
                    ReconcileActionKind.METADATA_ONLY_UPDATE,
                    item_id=live.item_id,
                    doc_key=indexed.doc_key,
                    reason="same_ctag_metadata_changed",
                )
            return ReconcileAction(
                ReconcileActionKind.UNCHANGED,
                item_id=live.item_id,
                doc_key=indexed.doc_key,
                reason="same_ctag",
            )
        return ReconcileAction(
            ReconcileActionKind.DOWNLOAD_AND_PARSE,
            item_id=live.item_id,
            doc_key=indexed.doc_key,
            reason="ctag_changed",
        )

    # cTag ausente: etag + size; ante duda descargar
    if indexed.etag and live.etag and indexed.etag == live.etag:
        if indexed.size is not None and live.size is not None and indexed.size != live.size:
            return ReconcileAction(
                ReconcileActionKind.DOWNLOAD_AND_PARSE,
                item_id=live.item_id,
                doc_key=indexed.doc_key,
                reason="etag_same_size_diff",
            )
        if _metadata_differs(indexed, live):
            return ReconcileAction(
                ReconcileActionKind.METADATA_ONLY_UPDATE,
                item_id=live.item_id,
                doc_key=indexed.doc_key,
                reason="no_ctag_etag_same_metadata_changed",
            )
        return ReconcileAction(
            ReconcileActionKind.UNCHANGED,
            item_id=live.item_id,
            doc_key=indexed.doc_key,
            reason="no_ctag_etag_same",
        )

    return ReconcileAction(
        ReconcileActionKind.DOWNLOAD_AND_PARSE,
        item_id=live.item_id,
        doc_key=indexed.doc_key,
        reason="insufficient_change_signals",
    )


def reconcile_credit_candidates(
    *,
    environment: str,
    drive_id: str,
    indexed: list[IndexedCandidateView],
    live: list[LiveFileMetadata],
    current_parser_version: str = "",
) -> ReconcileResult:
    """
    Reconcilia candidatos indexados vs metadata live del crédito.

    ``fallback_required`` si no hay live ni index utilizable, o si el índice
    no aporta ningún candidato con parse OK / pending recuperable.
    """
    indexed_active = [i for i in indexed if not i.eliminado]
    by_id_indexed = {i.item_id: i for i in indexed_active}
    by_id_live = {l.item_id: l for l in live}

    actions: list[ReconcileAction] = []
    all_ids = set(by_id_indexed) | set(by_id_live)
    for item_id in sorted(all_ids):
        actions.append(
            decide_item_action(
                by_id_indexed.get(item_id),
                by_id_live.get(item_id),
                current_parser_version=current_parser_version,
            )
        )

    fallback = False
    fallback_reason = ""
    if not live and not indexed_active:
        fallback = True
        fallback_reason = "no_candidates"
        actions.append(
            ReconcileAction(
                ReconcileActionKind.FALLBACK_REQUIRED,
                reason=fallback_reason,
            )
        )
    elif not live and indexed_active:
        # Todo marcado eliminado → índice insuficiente para selección
        fallback = True
        fallback_reason = "all_indexed_missing_on_drive"
        actions.append(
            ReconcileAction(
                ReconcileActionKind.FALLBACK_REQUIRED,
                reason=fallback_reason,
            )
        )
    else:
        usable = [
            a
            for a in actions
            if a.kind
            in (
                ReconcileActionKind.UNCHANGED,
                ReconcileActionKind.METADATA_ONLY_UPDATE,
                ReconcileActionKind.DOWNLOAD_AND_PARSE,
                ReconcileActionKind.RETRY_PARSE,
            )
        ]
        if not usable:
            fallback = True
            fallback_reason = "no_usable_actions"
            actions.append(
                ReconcileAction(
                    ReconcileActionKind.FALLBACK_REQUIRED,
                    reason=fallback_reason,
                )
            )

    return ReconcileResult(
        environment=environment,
        drive_id=drive_id,
        actions=tuple(actions),
        fallback_required=fallback,
        fallback_reason=fallback_reason,
    )


def classify_index_sufficiency(
    *,
    actions: tuple[ReconcileAction, ...] | list[ReconcileAction],
    has_fecha_limite_cached: bool,
) -> ReconcileActionKind:
    """
    Decisión pura de alto nivel: hit / refresh / fallback.

    - hit: solo unchanged (+ metadata_only opcional) y hay fecha cacheada
    - refresh: hay download/retry
    - fallback: fallback_required presente o sin señales útiles
    """
    kinds = {a.kind for a in actions}
    if ReconcileActionKind.FALLBACK_REQUIRED in kinds:
        return ReconcileActionKind.FALLBACK_REQUIRED
    if (
        ReconcileActionKind.DOWNLOAD_AND_PARSE in kinds
        or ReconcileActionKind.RETRY_PARSE in kinds
    ):
        return ReconcileActionKind.DOWNLOAD_AND_PARSE
    if has_fecha_limite_cached and kinds.issubset(
        {
            ReconcileActionKind.UNCHANGED,
            ReconcileActionKind.METADATA_ONLY_UPDATE,
            ReconcileActionKind.MARK_DELETED,
        }
    ):
        return ReconcileActionKind.UNCHANGED
    if not has_fecha_limite_cached:
        return ReconcileActionKind.FALLBACK_REQUIRED
    return ReconcileActionKind.DOWNLOAD_AND_PARSE
