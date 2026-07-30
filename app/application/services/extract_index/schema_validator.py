"""Validación de esquema de listas existentes (sin create_list ni auto-fix)."""

from __future__ import annotations

from typing import Any, Iterable

from app.application.services.extract_index.column_specs import (
    graph_column_type_family,
    types_compatible,
)
from app.domain.exceptions import ExtractIndexSchemaError
from app.domain.models.extract_index import (
    SchemaColumnSpec,
    SchemaValidationIssue,
    SchemaValidationResult,
)
from app.domain.ports.graph import GraphApiPort


def _column_name(col: dict[str, Any]) -> str:
    return str(col.get("name") or "").strip()


def _column_display(col: dict[str, Any]) -> str:
    return str(col.get("displayName") or col.get("name") or "").strip()


def validate_columns_against_specs(
    *,
    list_display_name: str,
    list_id: str,
    columns: Iterable[dict[str, Any]],
    specs: tuple[SchemaColumnSpec, ...],
) -> SchemaValidationResult:
    """
    Compara columnas Graph (nombre interno) contra specs.
    Reporta diferencias; no corrige. ok=False si hay errores.
    """
    by_internal = {_column_name(c): c for c in columns if _column_name(c)}
    issues: list[SchemaValidationIssue] = []

    for spec in specs:
        col = by_internal.get(spec.internal_name)
        if col is None:
            # Aviso si solo existe por displayName distinto al interno
            by_display = {
                _column_display(c): c for c in columns if _column_display(c)
            }
            if spec.display_name in by_display and spec.internal_name not in by_internal:
                issues.append(
                    SchemaValidationIssue(
                        code="internal_name_mismatch",
                        message=(
                            f"Existe displayName={spec.display_name!r} pero falta "
                            f"nombre interno {spec.internal_name!r}"
                        ),
                        column_internal_name=spec.internal_name,
                        severity="error",
                    )
                )
            elif spec.required:
                issues.append(
                    SchemaValidationIssue(
                        code="missing_column",
                        message=f"Falta columna interna requerida {spec.internal_name!r}",
                        column_internal_name=spec.internal_name,
                        severity="error",
                    )
                )
            elif not spec.required:
                issues.append(
                    SchemaValidationIssue(
                        code="missing_optional_column",
                        message=f"Falta columna opcional {spec.internal_name!r}",
                        column_internal_name=spec.internal_name,
                        severity="warning",
                    )
                )
            continue

        actual_type = graph_column_type_family(col)
        if not types_compatible(spec.column_type, actual_type):
            issues.append(
                SchemaValidationIssue(
                    code="type_mismatch",
                    message=(
                        f"Columna {spec.internal_name}: esperado {spec.column_type}, "
                        f"actual {actual_type}"
                    ),
                    column_internal_name=spec.internal_name,
                    severity="error",
                )
            )

        if spec.must_be_indexed and not bool(col.get("indexed")):
            issues.append(
                SchemaValidationIssue(
                    code="not_indexed",
                    message=(
                        f"Columna {spec.internal_name} debe estar indexada "
                        f"(indexed=true en Graph)"
                    ),
                    column_internal_name=spec.internal_name,
                    severity="error",
                )
            )

    ok = not any(i.severity == "error" for i in issues)
    return SchemaValidationResult(
        list_display_name=list_display_name,
        list_id=list_id,
        ok=ok,
        issues=issues,
    )


def raise_if_schema_incompatible(result: SchemaValidationResult) -> None:
    if result.ok:
        return
    detail = "; ".join(f"{i.code}:{i.message}" for i in result.errors)
    raise ExtractIndexSchemaError(
        f"Esquema incompatible en {result.list_display_name} "
        f"(list_id={result.list_id}): {detail}"
    )


async def fetch_list_columns(
    graph: GraphApiPort, *, site_id: str, list_id: str
) -> list[dict[str, Any]]:
    """Lee columnas de una lista existente (paginado)."""
    endpoint: str | None = f"/sites/{site_id}/lists/{list_id}/columns?$top=100"
    columns: list[dict[str, Any]] = []
    while endpoint:
        page = await graph.get(endpoint)
        columns.extend(page.get("value") or [])
        next_link = page.get("@odata.nextLink")
        if not next_link or not isinstance(next_link, str):
            break
        marker = "/v1.0/"
        endpoint = (
            next_link.split(marker, 1)[1] if marker in next_link else next_link.lstrip("/")
        )
    return columns
