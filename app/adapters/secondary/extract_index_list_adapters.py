"""Adapters de listas técnicas del índice con allowlist (MutationGuard)."""

from __future__ import annotations

from dataclasses import dataclass

from app.application.services.extract_index.control_repository import (
    GraphBootstrapControlRepository,
)
from app.application.services.extract_index.indice_repository import (
    GraphExtractIndexRepository,
)
from app.application.services.extract_index.mutation_guard import GraphMutationGuard
from app.domain.ports.graph import GraphApiPort


@dataclass(frozen=True, slots=True)
class AllowlistedExtractIndexLists:
    """
    Par de repositorios allowlisted.

    Toda escritura pasa por GraphMutationGuard; solo las dos list_ids técnicas.
    No expone un GraphApiPort general con escritura documental.
    """

    mutation_guard: GraphMutationGuard
    indice: GraphExtractIndexRepository
    control: GraphBootstrapControlRepository
    indice_list_id: str
    control_list_id: str


def build_allowlisted_extract_index_lists(
    graph: GraphApiPort,
    *,
    site_id: str,
    indice_list_id: str,
    control_list_id: str,
    indice_list_display_name: str = "INDICE_EXTRACTOS",
    control_list_display_name: str = "CONTROL_INDICE_EXTRACTOS",
    max_retries: int = 4,
    retry_base_seconds: float = 0.5,
    require_schema: bool = True,
) -> AllowlistedExtractIndexLists:
    """
    Compone guard + repos.

    ``graph`` puede ser FakeMsGraph en tests; en integración será MsGraphClient.
    """
    allowed = {str(indice_list_id), str(control_list_id)}
    if len(allowed) < 2:
        raise ValueError("indice_list_id y control_list_id deben ser distintos y no vacíos")
    guard = GraphMutationGuard(graph, allowed_list_ids=allowed)
    indice = GraphExtractIndexRepository(
        guard,
        site_id=site_id,
        list_display_name=indice_list_display_name,
        list_id=indice_list_id,
        max_retries=max_retries,
        retry_base_seconds=retry_base_seconds,
        require_schema=require_schema,
    )
    control = GraphBootstrapControlRepository(
        guard,
        site_id=site_id,
        list_display_name=control_list_display_name,
        list_id=control_list_id,
        max_retries=max_retries,
        retry_base_seconds=retry_base_seconds,
        require_schema=require_schema,
    )
    return AllowlistedExtractIndexLists(
        mutation_guard=guard,
        indice=indice,
        control=control,
        indice_list_id=indice_list_id,
        control_list_id=control_list_id,
    )
