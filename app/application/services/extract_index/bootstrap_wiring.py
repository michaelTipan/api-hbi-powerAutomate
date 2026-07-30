"""Composición de dependencias del bootstrap (sin app_factory)."""

from __future__ import annotations

from dataclasses import dataclass

from app.adapters.secondary.extract_index_list_adapters import (
    AllowlistedExtractIndexLists,
    build_allowlisted_extract_index_lists,
)
from app.adapters.secondary.graph_document_tree_readonly import (
    GraphDocumentTreeReadOnlyAdapter,
)
from app.application.config.extract_index_settings import (
    ExtractIndexSettings,
    get_extract_index_settings,
)
from app.application.services.extract_index.bootstrap_campaign import (
    BootstrapCampaignService,
)
from app.application.services.extract_index.bootstrap_clock import SystemClock
from app.application.services.extract_index.credit_lock import InMemoryCreditLock
from app.domain.ports.bootstrap_scope import BootstrapScopePort
from app.domain.ports.clock import ClockPort
from app.domain.ports.credit_lock import CreditLockPort
from app.domain.ports.document_tree_readonly import DocumentTreeReadOnlyPort
from app.domain.ports.extract_index import (
    BootstrapControlRepository,
    ExtractIndexRepository,
)
from app.domain.ports.graph import GraphApiPort


@dataclass(slots=True)
class BootstrapWiring:
    """Dependencias listas para el motor / router admin (inyección explícita)."""

    settings: ExtractIndexSettings
    service: BootstrapCampaignService
    document_tree: DocumentTreeReadOnlyPort
    lists: AllowlistedExtractIndexLists | None
    lock: CreditLockPort
    scope: BootstrapScopePort
    clock: ClockPort


def compose_bootstrap_wiring(
    *,
    scope: BootstrapScopePort,
    index_repo: ExtractIndexRepository,
    control_repo: BootstrapControlRepository,
    document_tree: DocumentTreeReadOnlyPort,
    lock: CreditLockPort | None = None,
    clock: ClockPort | None = None,
    settings: ExtractIndexSettings | None = None,
    lists: AllowlistedExtractIndexLists | None = None,
    max_credits_per_chunk: int | None = None,
    max_seconds_per_chunk: float | None = None,
) -> BootstrapWiring:
    """Composición pura (fakes o adapters reales) sin tocar FastAPI."""
    cfg = settings or get_extract_index_settings()
    lock_port = lock or InMemoryCreditLock()
    clock_port = clock or SystemClock()
    service = BootstrapCampaignService(
        control_repo=control_repo,
        index_repo=index_repo,
        lock=lock_port,
        scope=scope,
        clock=clock_port,
        document_tree=document_tree,
        max_credits_per_chunk=max_credits_per_chunk or cfg.max_clients_per_chunk,
        max_seconds_per_chunk=float(
            max_seconds_per_chunk
            if max_seconds_per_chunk is not None
            else cfg.max_seconds_per_chunk
        ),
    )
    return BootstrapWiring(
        settings=cfg,
        service=service,
        document_tree=document_tree,
        lists=lists,
        lock=lock_port,
        scope=scope,
        clock=clock_port,
    )


def compose_bootstrap_wiring_from_graph(
    graph: GraphApiPort,
    *,
    site_id: str,
    indice_list_id: str,
    control_list_id: str,
    scope: BootstrapScopePort,
    settings: ExtractIndexSettings | None = None,
    require_schema: bool = True,
    lock: CreditLockPort | None = None,
    clock: ClockPort | None = None,
) -> BootstrapWiring:
    """
    Wiring Graph: tree RO + listas allowlisted + motor.

    En 3A2 se prueba con FakeMsGraph; el montaje en app_factory queda diferido.
    """
    cfg = settings or get_extract_index_settings()
    lists = build_allowlisted_extract_index_lists(
        graph,
        site_id=site_id,
        indice_list_id=indice_list_id,
        control_list_id=control_list_id,
        indice_list_display_name=cfg.indice_list_display_name,
        control_list_display_name=cfg.control_list_display_name,
        max_retries=cfg.graph_retry_max,
        retry_base_seconds=cfg.graph_retry_base_seconds,
        require_schema=require_schema,
    )
    # Árbol documental: adapter RO sobre el Graph crudo (sin métodos de escritura).
    tree = GraphDocumentTreeReadOnlyAdapter(graph)
    return compose_bootstrap_wiring(
        scope=scope,
        index_repo=lists.indice,
        control_repo=lists.control,
        document_tree=tree,
        lock=lock,
        clock=clock,
        settings=cfg,
        lists=lists,
    )
