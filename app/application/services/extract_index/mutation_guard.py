"""Mutation guard fail-closed para Graph (documentos vs listas allowlisted)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from app.domain.exceptions import DocumentMutationForbidden, UnauthorizedListWriteError
from app.domain.ports.graph import GraphApiPort

logger = logging.getLogger(__name__)

_DRIVE_MUTATION_RE = re.compile(
    r"(^|/)?drives/[^/]+/(root:|items/)",
    re.IGNORECASE,
)
_LIST_ITEMS_RE = re.compile(
    r"(^|/)sites/[^/]+/lists/(?P<list_id>[^/]+)/items(?:/|\?|$)",
    re.IGNORECASE,
)


def is_drive_document_path(endpoint: str) -> bool:
    """True si el endpoint apunta a driveItems / contenido documental."""
    path = endpoint.split("?", 1)[0]
    if "/lists/" in path.lower():
        return False
    return bool(_DRIVE_MUTATION_RE.search(path))


def extract_list_id_from_items_endpoint(endpoint: str) -> str | None:
    match = _LIST_ITEMS_RE.search(endpoint.split("?", 1)[0])
    if not match:
        return None
    return match.group("list_id")


@dataclass
class MutationGuardStats:
    """Contadores de evidencia para tests y operación."""

    allowed_gets: int = 0
    blocked_document_mutations: int = 0
    blocked_unauthorized_list_writes: int = 0
    allowed_list_writes: int = 0
    violations: list[str] = field(default_factory=list)


class GraphMutationGuard:
    """
    Envuelve GraphApiPort.

    - GET / get_bytes: siempre permitidos (incl. descargas de contenido).
    - POST/PUT/PATCH/DELETE sobre /drives/...: abortan (violación).
    - Escrituras solo a ítems de list_ids allowlisted.
    """

    def __init__(
        self,
        inner: GraphApiPort,
        *,
        allowed_list_ids: frozenset[str] | set[str],
    ) -> None:
        self._inner = inner
        self._allowed_list_ids = frozenset(str(x) for x in allowed_list_ids)
        self.stats = MutationGuardStats()

    def _assert_mutation_allowed(self, method: str, endpoint: str) -> None:
        if is_drive_document_path(endpoint):
            msg = (
                f"DocumentMutationForbidden: {method} bloqueado sobre ruta "
                f"documental: {endpoint}"
            )
            self.stats.blocked_document_mutations += 1
            self.stats.violations.append(msg)
            logger.error("extract_index_security_violation %s", msg)
            raise DocumentMutationForbidden(msg)

        list_id = extract_list_id_from_items_endpoint(endpoint)
        if list_id is None:
            msg = (
                f"UnauthorizedListWriteError: {method} no apunta a ítems de lista "
                f"allowlisted: {endpoint}"
            )
            self.stats.blocked_unauthorized_list_writes += 1
            self.stats.violations.append(msg)
            logger.error("extract_index_security_violation %s", msg)
            raise UnauthorizedListWriteError(msg)

        if list_id not in self._allowed_list_ids:
            msg = (
                f"UnauthorizedListWriteError: list_id={list_id!r} fuera de allowlist "
                f"{sorted(self._allowed_list_ids)}; endpoint={endpoint}"
            )
            self.stats.blocked_unauthorized_list_writes += 1
            self.stats.violations.append(msg)
            logger.error("extract_index_security_violation %s", msg)
            raise UnauthorizedListWriteError(msg)

        self.stats.allowed_list_writes += 1

    async def get(
        self, endpoint: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        self.stats.allowed_gets += 1
        return await self._inner.get(endpoint, params)

    async def get_bytes(
        self, endpoint: str, params: dict[str, Any] | None = None
    ) -> bytes:
        self.stats.allowed_gets += 1
        return await self._inner.get_bytes(endpoint, params)

    async def put_bytes(
        self,
        endpoint: str,
        content: bytes,
        content_type: str = "application/octet-stream",
        if_match: str | None = None,
    ) -> dict[str, Any]:
        self._assert_mutation_allowed("PUT", endpoint)
        return await self._inner.put_bytes(
            endpoint, content, content_type=content_type, if_match=if_match
        )

    async def post_json(
        self, endpoint: str, body: dict[str, Any]
    ) -> tuple[dict[str, Any], int]:
        self._assert_mutation_allowed("POST", endpoint)
        return await self._inner.post_json(endpoint, body)

    async def patch_json(self, endpoint: str, body: dict[str, Any]) -> dict[str, Any]:
        self._assert_mutation_allowed("PATCH", endpoint)
        return await self._inner.patch_json(endpoint, body)

    async def delete(self, endpoint: str) -> None:
        self._assert_mutation_allowed("DELETE", endpoint)
        await self._inner.delete(endpoint)
