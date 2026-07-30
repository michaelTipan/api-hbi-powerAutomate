"""Escritura y lectura OData segura para filtros de listas SharePoint."""

from __future__ import annotations


def escape_odata_string(value: str) -> str:
    """Escapa comillas simples para literales OData (duplicar ')."""
    return str(value).replace("'", "''")


def eq_string(field: str, value: str) -> str:
    """fields/FieldName eq 'valor' con escape."""
    return f"fields/{field} eq '{escape_odata_string(value)}'"


def and_filters(*parts: str) -> str:
    cleaned = [p for p in parts if p and p.strip()]
    if not cleaned:
        raise ValueError("and_filters requiere al menos un predicado")
    return " and ".join(f"({p})" for p in cleaned)
