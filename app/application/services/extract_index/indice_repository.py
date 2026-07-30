"""Repositorio Graph de ítems INDICE_EXTRACTOS."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.application.services.extract_index.column_specs import INDICE_EXTRACTOS_COLUMNS
from app.application.services.extract_index.keys import (
    assert_same_environment_and_drive,
    build_credit_key,
    build_doc_key,
    parse_doc_key,
)
from app.application.services.extract_index.list_http import (
    environment_and_field_filter,
    find_list_id_by_display_name,
    paginate_list_items,
    with_graph_retries,
)
from app.application.services.extract_index.odata import eq_string
from app.application.services.extract_index.schema_validator import (
    fetch_list_columns,
    raise_if_schema_incompatible,
    validate_columns_against_specs,
)
from app.domain.exceptions import ExtractIndexDuplicateDocKeyError, ExtractIndexError
from app.domain.models.extract_index import (
    DocKey,
    ExtractIndexCandidate,
    ExtractIndexEnvironment,
    ParseStatus,
    SchemaValidationResult,
)
from app.domain.ports.graph import GraphApiPort


def _parse_environment_field(raw: Any) -> ExtractIndexEnvironment:
    text = str(raw or "").strip().lower()
    if text == "production":
        return ExtractIndexEnvironment.PRODUCTION
    return ExtractIndexEnvironment.SANDBOX


def _parse_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    text = str(value)[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _parse_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _fields_to_candidate(item: dict[str, Any]) -> ExtractIndexCandidate:
    fields = item.get("fields") or {}
    env = _parse_environment_field(fields.get("ENVIRONMENT"))
    drive_id = str(fields.get("DRIVE_ID") or "")
    item_id = str(fields.get("ITEM_ID") or "")
    credit_folder = str(fields.get("CREDIT_FOLDER_ITEM_ID") or "")
    credit_key = build_credit_key(
        environment=env, drive_id=drive_id, credit_folder_item_id=credit_folder
    )
    doc_key = build_doc_key(environment=env, drive_id=drive_id, item_id=item_id)
    parse_raw = str(fields.get("ESTADO_PARSEO") or ParseStatus.PENDING.value).lower()
    try:
        parse_status = ParseStatus(parse_raw)
    except ValueError:
        parse_status = ParseStatus.PENDING
    size_raw = fields.get("TAMANO")
    size = int(size_raw) if size_raw is not None and str(size_raw).strip() != "" else None
    return ExtractIndexCandidate(
        environment=env,
        credit_key=credit_key,
        doc_key=doc_key,
        drive_id=drive_id,
        item_id=item_id,
        credit_folder_item_id=credit_folder,
        name=str(fields.get("NOMBRE") or ""),
        path=str(fields.get("RUTA") or ""),
        ubicacion=str(fields.get("UBICACION") or ""),
        ctag=str(fields.get("CTAG") or ""),
        etag=str(fields.get("ETAG") or ""),
        size=size,
        parse_status=parse_status,
        parser_version=str(fields.get("VERSION_PARSER") or ""),
        fecha_limite=_parse_date(fields.get("FECHA_LIMITE")),
        content_hash=str(fields.get("HASH_CONTENIDO") or ""),
        eliminado=bool(fields.get("ELIMINADO")),
        parse_error=str(fields.get("PARSE_ERROR") or ""),
        ultima_revision=_parse_datetime(fields.get("ULTIMA_REVISION")),
        list_item_id=str(item.get("id") or "") or None,
    )


def _candidate_to_fields(candidate: ExtractIndexCandidate) -> dict[str, Any]:
    assert_same_environment_and_drive(
        environment=candidate.environment,
        drive_id=candidate.drive_id,
        credit_key=candidate.credit_key,
        doc_key=candidate.doc_key,
    )
    fields: dict[str, Any] = {
        "Title": candidate.doc_key.as_string()[:255],
        "ENVIRONMENT": candidate.environment.value,
        "CREDIT_KEY": candidate.credit_key.as_string(),
        "DOC_KEY": candidate.doc_key.as_string(),
        "DRIVE_ID": candidate.drive_id,
        "ITEM_ID": candidate.item_id,
        "CREDIT_FOLDER_ITEM_ID": candidate.credit_folder_item_id,
        "NOMBRE": candidate.name,
        "RUTA": candidate.path,
        "UBICACION": candidate.ubicacion,
        "CTAG": candidate.ctag,
        "ETAG": candidate.etag,
        "ESTADO_PARSEO": candidate.parse_status.value,
        "VERSION_PARSER": candidate.parser_version,
        "HASH_CONTENIDO": candidate.content_hash,
        "ELIMINADO": candidate.eliminado,
        "PARSE_ERROR": candidate.parse_error,
    }
    if candidate.size is not None:
        fields["TAMANO"] = candidate.size
    if candidate.fecha_limite is not None:
        fields["FECHA_LIMITE"] = candidate.fecha_limite.isoformat()
    if candidate.ultima_revision is not None:
        fields["ULTIMA_REVISION"] = candidate.ultima_revision.isoformat()
    return fields


class GraphExtractIndexRepository:
    """Implementa ExtractIndexRepository sobre INDICE_EXTRACTOS."""

    def __init__(
        self,
        graph: GraphApiPort,
        *,
        site_id: str,
        list_display_name: str = "INDICE_EXTRACTOS",
        list_id: str | None = None,
        max_retries: int = 4,
        retry_base_seconds: float = 0.5,
        require_schema: bool = True,
    ) -> None:
        self._graph = graph
        self._site_id = site_id
        self._list_display_name = list_display_name
        self._list_id = list_id
        self._max_retries = max_retries
        self._retry_base_seconds = retry_base_seconds
        self._require_schema = require_schema
        self._schema_validated = False

    async def _resolve_list_id(self) -> str:
        if self._list_id:
            return self._list_id
        self._list_id = await find_list_id_by_display_name(
            self._graph,
            site_id=self._site_id,
            display_name=self._list_display_name,
        )
        return self._list_id

    async def validate_schema(self) -> SchemaValidationResult:
        list_id = await self._resolve_list_id()

        async def _load() -> list[dict[str, Any]]:
            return await fetch_list_columns(
                self._graph, site_id=self._site_id, list_id=list_id
            )

        columns = await with_graph_retries(
            _load,
            max_retries=self._max_retries,
            base_seconds=self._retry_base_seconds,
            label="validate_schema_indice",
        )
        result = validate_columns_against_specs(
            list_display_name=self._list_display_name,
            list_id=list_id,
            columns=columns,
            specs=INDICE_EXTRACTOS_COLUMNS,
        )
        if self._require_schema:
            raise_if_schema_incompatible(result)
        self._schema_validated = result.ok
        return result

    async def _ensure_schema(self) -> None:
        if self._schema_validated or not self._require_schema:
            return
        await self.validate_schema()

    async def find_by_credit_key(
        self, *, environment: ExtractIndexEnvironment, credit_key: str
    ) -> list[ExtractIndexCandidate]:
        await self._ensure_schema()
        list_id = await self._resolve_list_id()
        filt = environment_and_field_filter(
            environment=environment.value,
            field_name="CREDIT_KEY",
            field_value=credit_key,
        )

        async def _load() -> list[dict[str, Any]]:
            return await paginate_list_items(
                self._graph,
                site_id=self._site_id,
                list_id=list_id,
                filter_expr=filt,
            )

        raw = await with_graph_retries(
            _load,
            max_retries=self._max_retries,
            base_seconds=self._retry_base_seconds,
            label="find_by_credit_key",
        )
        return [_fields_to_candidate(it) for it in raw]

    async def find_by_doc_key(
        self, *, environment: ExtractIndexEnvironment, doc_key: str
    ) -> list[ExtractIndexCandidate]:
        await self._ensure_schema()
        list_id = await self._resolve_list_id()
        filt = environment_and_field_filter(
            environment=environment.value,
            field_name="DOC_KEY",
            field_value=doc_key,
        )

        async def _load() -> list[dict[str, Any]]:
            return await paginate_list_items(
                self._graph,
                site_id=self._site_id,
                list_id=list_id,
                filter_expr=filt,
            )

        raw = await with_graph_retries(
            _load,
            max_retries=self._max_retries,
            base_seconds=self._retry_base_seconds,
            label="find_by_doc_key",
        )
        return [_fields_to_candidate(it) for it in raw]

    async def upsert_by_doc_key(
        self, candidate: ExtractIndexCandidate
    ) -> ExtractIndexCandidate:
        await self._ensure_schema()
        list_id = await self._resolve_list_id()
        existing = await self.find_by_doc_key(
            environment=candidate.environment,
            doc_key=candidate.doc_key.as_string(),
        )
        if len(existing) > 1:
            raise ExtractIndexDuplicateDocKeyError(
                f"DOC_KEY duplicado ({len(existing)} filas): "
                f"{candidate.doc_key.as_string()}"
            )
        fields = _candidate_to_fields(candidate)

        if len(existing) == 1 and existing[0].list_item_id:
            item_id = existing[0].list_item_id

            async def _patch() -> dict[str, Any]:
                return await self._graph.patch_json(
                    f"/sites/{self._site_id}/lists/{list_id}/items/{item_id}/fields",
                    fields,
                )

            await with_graph_retries(
                _patch,
                max_retries=self._max_retries,
                base_seconds=self._retry_base_seconds,
                label="upsert_patch_indice",
            )
            candidate.list_item_id = item_id
            return candidate

        async def _create() -> tuple[dict[str, Any], int]:
            return await self._graph.post_json(
                f"/sites/{self._site_id}/lists/{list_id}/items",
                {"fields": fields},
            )

        created, status = await with_graph_retries(
            _create,
            max_retries=self._max_retries,
            base_seconds=self._retry_base_seconds,
            label="upsert_create_indice",
        )
        if status >= 400:
            raise ExtractIndexError(
                f"No se pudo crear ítem INDICE_EXTRACTOS HTTP {status}"
            )
        candidate.list_item_id = str(created.get("id") or "") or None
        return candidate

    async def report_duplicate_doc_keys(
        self, *, environment: ExtractIndexEnvironment
    ) -> list[DocKey]:
        await self._ensure_schema()
        list_id = await self._resolve_list_id()
        filt = eq_string("ENVIRONMENT", environment.value)

        async def _load() -> list[dict[str, Any]]:
            return await paginate_list_items(
                self._graph,
                site_id=self._site_id,
                list_id=list_id,
                filter_expr=filt,
            )

        raw = await with_graph_retries(
            _load,
            max_retries=self._max_retries,
            base_seconds=self._retry_base_seconds,
            label="report_duplicate_doc_keys",
        )
        counts: dict[str, int] = {}
        for it in raw:
            fields = it.get("fields") or {}
            dk = str(fields.get("DOC_KEY") or "")
            if not dk:
                continue
            counts[dk] = counts.get(dk, 0) + 1
        return [parse_doc_key(k) for k, n in counts.items() if n > 1]
