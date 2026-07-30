"""Repositorio Graph de ítems CONTROL_INDICE_EXTRACTOS."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.application.services.extract_index.column_specs import CONTROL_INDICE_COLUMNS
from app.application.services.extract_index.list_http import (
    environment_and_field_filter,
    find_list_id_by_display_name,
    paginate_list_items,
    with_graph_retries,
)
from app.application.services.extract_index.schema_validator import (
    fetch_list_columns,
    raise_if_schema_incompatible,
    validate_columns_against_specs,
)
from app.domain.exceptions import ExtractIndexError
from app.domain.models.extract_index import (
    BootstrapControlRecord,
    CampaignStatus,
    ExtractIndexEnvironment,
    SchemaValidationResult,
)
from app.domain.ports.graph import GraphApiPort


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


def _fields_to_record(item: dict[str, Any]) -> BootstrapControlRecord:
    fields = item.get("fields") or {}
    env_raw = str(fields.get("ENVIRONMENT") or "sandbox").strip().lower()
    env = (
        ExtractIndexEnvironment.PRODUCTION
        if env_raw == "production"
        else ExtractIndexEnvironment.SANDBOX
    )
    status_raw = str(fields.get("STATUS") or CampaignStatus.IDLE.value).lower()
    try:
        status = CampaignStatus(status_raw)
    except ValueError:
        status = CampaignStatus.IDLE
    return BootstrapControlRecord(
        environment=env,
        campaign_id=str(fields.get("CAMPAIGN_ID") or ""),
        status=status,
        chunk_id=str(fields.get("CHUNK_ID") or ""),
        checkpoint=str(fields.get("CHECKPOINT") or ""),
        current_client=str(fields.get("CURRENT_CLIENT") or ""),
        current_credit=str(fields.get("CURRENT_CREDIT") or ""),
        heartbeat=_parse_datetime(fields.get("HEARTBEAT")),
        continuation_required=bool(fields.get("CONTINUATION_REQUIRED")),
        paused=bool(fields.get("PAUSED")),
        cancellation_requested=bool(fields.get("CANCELLATION_REQUESTED")),
        completed=bool(fields.get("COMPLETED")),
        error_summary=str(fields.get("ERROR_SUMMARY") or ""),
        totals_json=str(fields.get("TOTALS_JSON") or ""),
        list_item_id=str(item.get("id") or "") or None,
    )


def _record_to_fields(record: BootstrapControlRecord) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "Title": f"{record.environment.value}|{record.campaign_id}"[:255],
        "ENVIRONMENT": record.environment.value,
        "CAMPAIGN_ID": record.campaign_id,
        "STATUS": record.status.value,
        "CHUNK_ID": record.chunk_id,
        "CHECKPOINT": record.checkpoint,
        "CURRENT_CLIENT": record.current_client,
        "CURRENT_CREDIT": record.current_credit,
        "CONTINUATION_REQUIRED": record.continuation_required,
        "PAUSED": record.paused,
        "CANCELLATION_REQUESTED": record.cancellation_requested,
        "COMPLETED": record.completed,
        "ERROR_SUMMARY": record.error_summary,
        "TOTALS_JSON": record.totals_json,
    }
    if record.heartbeat is not None:
        fields["HEARTBEAT"] = record.heartbeat.isoformat()
    return fields


class GraphBootstrapControlRepository:
    """Implementa BootstrapControlRepository sobre CONTROL_INDICE_EXTRACTOS."""

    def __init__(
        self,
        graph: GraphApiPort,
        *,
        site_id: str,
        list_display_name: str = "CONTROL_INDICE_EXTRACTOS",
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
            label="validate_schema_control",
        )
        result = validate_columns_against_specs(
            list_display_name=self._list_display_name,
            list_id=list_id,
            columns=columns,
            specs=CONTROL_INDICE_COLUMNS,
        )
        if self._require_schema:
            raise_if_schema_incompatible(result)
        self._schema_validated = result.ok
        return result

    async def _ensure_schema(self) -> None:
        if self._schema_validated or not self._require_schema:
            return
        await self.validate_schema()

    async def get_by_campaign_id(
        self, *, environment: ExtractIndexEnvironment, campaign_id: str
    ) -> BootstrapControlRecord | None:
        await self._ensure_schema()
        list_id = await self._resolve_list_id()
        filt = environment_and_field_filter(
            environment=environment.value,
            field_name="CAMPAIGN_ID",
            field_value=campaign_id,
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
            label="get_by_campaign_id",
        )
        if not raw:
            return None
        if len(raw) > 1:
            raise ExtractIndexError(
                f"CAMPAIGN_ID duplicado en control ({len(raw)}): {campaign_id}"
            )
        return _fields_to_record(raw[0])

    async def upsert_by_campaign_id(
        self, record: BootstrapControlRecord
    ) -> BootstrapControlRecord:
        await self._ensure_schema()
        list_id = await self._resolve_list_id()
        existing = await self.get_by_campaign_id(
            environment=record.environment, campaign_id=record.campaign_id
        )
        fields = _record_to_fields(record)
        if existing and existing.list_item_id:
            item_id = existing.list_item_id

            async def _patch() -> dict[str, Any]:
                return await self._graph.patch_json(
                    f"/sites/{self._site_id}/lists/{list_id}/items/{item_id}/fields",
                    fields,
                )

            await with_graph_retries(
                _patch,
                max_retries=self._max_retries,
                base_seconds=self._retry_base_seconds,
                label="upsert_patch_control",
            )
            record.list_item_id = item_id
            return record

        async def _create() -> tuple[dict[str, Any], int]:
            return await self._graph.post_json(
                f"/sites/{self._site_id}/lists/{list_id}/items",
                {"fields": fields},
            )

        created, status = await with_graph_retries(
            _create,
            max_retries=self._max_retries,
            base_seconds=self._retry_base_seconds,
            label="upsert_create_control",
        )
        if status >= 400:
            raise ExtractIndexError(
                f"No se pudo crear ítem CONTROL_INDICE_EXTRACTOS HTTP {status}"
            )
        record.list_item_id = str(created.get("id") or "") or None
        return record
