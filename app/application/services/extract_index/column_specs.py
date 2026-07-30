"""Especificación de columnas esperadas (nombres internos Graph)."""

from __future__ import annotations

from app.domain.models.extract_index import SchemaColumnSpec

# Nombres internos acordados (admin debe crear columnas con estos internal names).
# SharePoint suele usar el mismo nombre si se crean sin espacios conflictivos.

INDICE_EXTRACTOS_COLUMNS: tuple[SchemaColumnSpec, ...] = (
    SchemaColumnSpec("ENVIRONMENT", "ENVIRONMENT", "text", True, False),
    SchemaColumnSpec("CREDIT_KEY", "CREDIT_KEY", "text", True, True),
    SchemaColumnSpec("DOC_KEY", "DOC_KEY", "text", True, False),
    SchemaColumnSpec("DRIVE_ID", "DRIVE_ID", "text", True, False),
    SchemaColumnSpec("ITEM_ID", "ITEM_ID", "text", True, False),
    SchemaColumnSpec("CREDIT_FOLDER_ITEM_ID", "CREDIT_FOLDER_ITEM_ID", "text", True, False),
    SchemaColumnSpec("NOMBRE", "NOMBRE", "text", False, False),
    SchemaColumnSpec("RUTA", "RUTA", "text", False, False),
    SchemaColumnSpec("UBICACION", "UBICACION", "text", False, False),
    SchemaColumnSpec("CTAG", "CTAG", "text", False, False),
    SchemaColumnSpec("ETAG", "ETAG", "text", False, False),
    SchemaColumnSpec("TAMANO", "TAMANO", "number", False, False),
    SchemaColumnSpec("ESTADO_PARSEO", "ESTADO_PARSEO", "text", False, False),
    SchemaColumnSpec("VERSION_PARSER", "VERSION_PARSER", "text", False, False),
    SchemaColumnSpec("FECHA_LIMITE", "FECHA_LIMITE", "dateTime", False, False),
    SchemaColumnSpec("HASH_CONTENIDO", "HASH_CONTENIDO", "text", False, False),
    SchemaColumnSpec("ELIMINADO", "ELIMINADO", "boolean", False, False),
    SchemaColumnSpec("PARSE_ERROR", "PARSE_ERROR", "text", False, False),
    SchemaColumnSpec("ULTIMA_REVISION", "ULTIMA_REVISION", "dateTime", False, False),
)

CONTROL_INDICE_COLUMNS: tuple[SchemaColumnSpec, ...] = (
    SchemaColumnSpec("ENVIRONMENT", "ENVIRONMENT", "text", True, False),
    SchemaColumnSpec("CAMPAIGN_ID", "CAMPAIGN_ID", "text", True, True),
    SchemaColumnSpec("STATUS", "STATUS", "text", True, False),
    SchemaColumnSpec("CHUNK_ID", "CHUNK_ID", "text", False, False),
    SchemaColumnSpec("CHECKPOINT", "CHECKPOINT", "text", False, False),
    SchemaColumnSpec("CURRENT_CLIENT", "CURRENT_CLIENT", "text", False, False),
    SchemaColumnSpec("CURRENT_CREDIT", "CURRENT_CREDIT", "text", False, False),
    SchemaColumnSpec("HEARTBEAT", "HEARTBEAT", "dateTime", False, False),
    SchemaColumnSpec("CONTINUATION_REQUIRED", "CONTINUATION_REQUIRED", "boolean", False, False),
    SchemaColumnSpec("PAUSED", "PAUSED", "boolean", False, False),
    SchemaColumnSpec("CANCELLATION_REQUESTED", "CANCELLATION_REQUESTED", "boolean", False, False),
    SchemaColumnSpec("COMPLETED", "COMPLETED", "boolean", False, False),
    SchemaColumnSpec("ERROR_SUMMARY", "ERROR_SUMMARY", "text", False, False),
    SchemaColumnSpec("TOTALS_JSON", "TOTALS_JSON", "text", False, False),
)

# Mapeo tipo Graph column → familia esperada
_GRAPH_TYPE_ALIASES: dict[str, frozenset[str]] = {
    "text": frozenset({"text", "string"}),
    "number": frozenset({"number", "integer", "currency"}),
    "boolean": frozenset({"boolean"}),
    "dateTime": frozenset({"dateTime", "dateTimeOffset"}),
}


def graph_column_type_family(column: dict) -> str:
    """Infiere familia de tipo desde el objeto columna de Graph."""
    for key in ("text", "number", "boolean", "dateTime", "choice", "currency"):
        if key in column and column.get(key) is not None:
            if key == "currency":
                return "number"
            return key
    return str(column.get("type") or "unknown")


def types_compatible(expected: str, actual_family: str) -> bool:
    allowed = _GRAPH_TYPE_ALIASES.get(expected, frozenset({expected}))
    return actual_family in allowed
