"""Créditos que ya quedaron registrados en su tabla de amortización en un proceso.

La fuente de verdad es ``_AUTOMATION_LOG`` de cada tabla (filas APLICADO /
ADOPTADO_EXISTENTE con un ID Pago del proceso): sobrevive a varios intentos de
Apply y a que el crédito se excluya después. El resultado de un intento (dry-run
o Apply) aporta además los créditos aplicados en ese intento.
"""
from __future__ import annotations

import hashlib
import io
import logging
from collections.abc import Awaitable, Callable, Iterable
from typing import Any

import httpx
import openpyxl

from app.application.services.amortization_decisions import credit_token
from app.application.services.amortization_workbook import (
    ADOPTADO_EXISTENTE,
    APLICADO,
    load_automation_log_index,
)

logger = logging.getLogger(__name__)

APPLIED_LOG_STATES = frozenset({APLICADO, ADOPTADO_EXISTENTE})
_APPLIED_APPLY_STATUSES = frozenset({"APPLIED", "ADOPTED"})
_APPLIED_PLAN_STATUSES = frozenset({"ALREADY_APPLIED"})


def table_id(path: str | None) -> str:
    """Id corto y estable de una ruta de tabla (mismo criterio que el resumen del plan)."""
    norm = str(path or "").strip().strip("/").casefold()
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:10] if norm else ""


def applied_credits_in_workbook(
    workbook_bytes: bytes,
    *,
    credits: Iterable[str],
    id_pagos: Iterable[str],
) -> set[str]:
    """Créditos (de ``credits``) con filas aplicadas en el log para algún ID Pago dado.

    Sin ID Pago no se puede acotar al proceso (el log guarda meses de historia): no
    se marca nada.
    """
    wanted = {credit_token(c) for c in credits if credit_token(c)}
    pagos = {str(p).strip() for p in id_pagos if str(p or "").strip()}
    if not wanted or not pagos:
        return set()
    wb = openpyxl.load_workbook(io.BytesIO(workbook_bytes), data_only=True)
    try:
        index = load_automation_log_index(wb)
    finally:
        wb.close()
    found: set[str] = set()
    for rec in index.values():
        estado = str(rec.estado or rec.accion or "").strip().upper()
        if estado not in APPLIED_LOG_STATES:
            continue
        if str(rec.id_pago or "").strip() not in pagos:
            continue
        tok = credit_token(rec.credito)
        if tok in wanted:
            found.add(tok)
    return found


def _is_not_found(exc: BaseException) -> bool:
    if isinstance(exc, FileNotFoundError):
        return True
    if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
        return exc.response.status_code == 404
    return False


async def applied_credits_in_tables(
    download_fn: Callable[[str], Awaitable[bytes]],
    *,
    tablas: dict[str, str],
    id_pagos: Iterable[str],
) -> set[str]:
    """Revisa el log de la tabla de cada crédito. Una tabla inexistente no tiene escrituras.

    Otros errores de descarga se propagan: el llamador decide si bloquea o sigue.
    """
    pagos = [str(p).strip() for p in id_pagos if str(p or "").strip()]
    if not pagos:
        return set()
    by_path: dict[str, set[str]] = {}
    for tok, path in (tablas or {}).items():
        norm = str(path or "").strip().strip("/")
        if norm and credit_token(tok):
            by_path.setdefault(norm, set()).add(credit_token(tok))
    found: set[str] = set()
    for path, toks in by_path.items():
        try:
            raw = await download_fn(path)
        except Exception as exc:
            if _is_not_found(exc):
                continue
            raise
        found |= applied_credits_in_workbook(raw, credits=toks, id_pagos=pagos)
    return found


def _result_items(result: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for source in (result, result.get("preflight"), result.get("dry_run")):
        if isinstance(source, dict):
            items.extend(it for it in source.get("items") or [] if isinstance(it, dict))
    return items


def applied_tables_by_credit_from_result(result: dict[str, Any] | None) -> dict[str, list[str]]:
    """Créditos aplicados (escritos, adoptados o ya aplicados) en un intento → rutas de tabla."""
    out: dict[str, list[str]] = {}
    if not isinstance(result, dict):
        return out
    uploaded = {
        str(p or "").strip().strip("/").casefold() for p in result.get("tables_uploaded") or []
    }
    for it in _result_items(result):
        apply_status = str(it.get("apply_status") or "").strip().upper()
        plan_status = str(it.get("application_status") or "").strip().upper()
        tabla = str(it.get("tabla_amortizacion_path") or "").strip().strip("/")
        if apply_status == "APPLIED":
            # Escrito en memoria: solo cuenta si la tabla se subió en este intento.
            applied = tabla.casefold() in uploaded
        else:
            applied = apply_status in _APPLIED_APPLY_STATUSES or (
                plan_status in _APPLIED_PLAN_STATUSES and not it.get("error_code")
            )
        if not applied:
            continue
        tok = credit_token(it.get("credito"))
        if not tok:
            continue
        tables = out.setdefault(tok, [])
        if tabla and tabla not in tables:
            tables.append(tabla)
    return out


__all__ = [
    "APPLIED_LOG_STATES",
    "applied_credits_in_tables",
    "applied_credits_in_workbook",
    "applied_tables_by_credit_from_result",
    "table_id",
]
