"""Decisiones del operador en fase 4: excluir crédito(s) y "Continuar con los asientos".

Cada acción se valida contra el último intento de amortización persistido en
Control (``LastAmortizationAttemptJson``): solo se puede excluir un crédito que
aparece en un problema excluible y solo se confirma una conciliación marcada
como confirmable. El registro vive en SharePoint (JSON por proceso) y el Control
solo guarda su ruta (``DecisionsRegistryPath``).
"""
from __future__ import annotations

import dataclasses
import logging
import posixpath
from dataclasses import dataclass
from typing import Any

from app.application.config.payment_validation_settings import validate_bank_code
from app.application.services.amortization_decisions import (
    CONTROL_COLUMN,
    DecisionsRegistryError,
    DecisionsRegistryUnavailableError,
    active_confirmations,
    active_exclusions,
    add_confirmation,
    add_exclusion,
    credit_token,
    load_registry_for_process,
    money,
    mutate_registry,
    registry_filename,
    resolve_registry_path,
    undo_confirmation,
    undo_exclusion,
)
from app.application.ui.amortization_attempt import parse_last_amortization_attempt_json
from app.application.ui.schemas import (
    UiAmortizationDecisions,
    UiConfirmedConciliation,
    UiExcludedCredit,
    UiLastAmortizationAttempt,
    UiLink,
    UiOperationalIssue,
)
from app.application.use_cases.payment_validation_process_control import (
    ProcessControlSnapshot,
    read_process_control_snapshot,
    update_process_control_row2,
    utc_now_iso,
)
from app.application.use_cases.setup_merge_control_workbook import (
    process_date_from_process_key,
)
from app.domain.ports.graph import GraphApiPort

logger = logging.getLogger(__name__)

# Fase 4 activa: se puede decidir antes de (re)procesar la amortización.
DECISION_ALLOWED_STATES = frozenset({"CONSOLIDADO", "ERROR_APPLY", "AMORTIZACION_PARCIAL"})


@dataclass
class DecisionContext:
    site_id: str
    drive_id: str
    bank_code: str
    process_key: str
    report_date_iso: str
    snapshot: ProcessControlSnapshot
    attempt: UiLastAmortizationAttempt | None
    registry_path: str


def _err(code: str, message: str, status: int = 409) -> DecisionsRegistryError:
    return DecisionsRegistryError(code, message, status_code=status)


async def _context(
    graph: GraphApiPort,
    *,
    bank_code: str,
    process_key: str,
    allowed_states: frozenset[str] = DECISION_ALLOWED_STATES,
) -> DecisionContext:
    from app.application.use_cases.amortization_fill_dry_run import _drive_context

    bank = (bank_code or "").strip()
    validate_bank_code(bank)
    key = (process_key or "").strip()
    site_id, drive_id = await _drive_context(graph)
    snap = await read_process_control_snapshot(graph, site_id, drive_id, bank_code=bank)
    if not key or (snap.process_key or "").strip() != key:
        raise _err(
            "process_key_mismatch",
            "El proceso cambió desde que abrió esta página. Actualice e intente de nuevo.",
        )
    estado = (snap.estado_proceso or "").strip().upper()
    if estado not in allowed_states or not snap.is_active:
        raise _err(
            "decisions_not_allowed",
            "En la etapa actual del proceso ya no se pueden excluir créditos ni confirmar diferencias.",
        )
    report_date = process_date_from_process_key(key)
    report_date_iso = report_date.isoformat() if report_date else ""
    path = (snap.decisions_registry_path or "").strip().strip("/")
    if path and posixpath.basename(path) != registry_filename(bank, report_date_iso, key):
        # Ruta heredada de un proceso anterior del banco: este proceso usa la suya.
        path = ""
        snap = dataclasses.replace(snap, decisions_registry_path="")
    if not path:
        path = resolve_registry_path(
            bank_code=bank,
            report_date_iso=report_date_iso,
            process_key=key,
            merge_manifest_path=snap.merge_manifest_path,
        )
    return DecisionContext(
        site_id=site_id,
        drive_id=drive_id,
        bank_code=bank,
        process_key=key,
        report_date_iso=report_date_iso,
        snapshot=snap,
        attempt=parse_last_amortization_attempt_json(snap.last_amortization_attempt_json),
        registry_path=path,
    )


def _issues(ctx: DecisionContext) -> list[UiOperationalIssue]:
    return list(ctx.attempt.operational_issues) if ctx.attempt else []


def _excludable_group(ctx: DecisionContext, credit: str) -> tuple[list[str], list[UiOperationalIssue]]:
    tok = credit_token(credit)
    group: list[str] = []
    related: list[UiOperationalIssue] = []
    for issue in _issues(ctx):
        dec = issue.decision
        if dec is None or not dec.excludable:
            continue
        credits = [credit_token(c) for c in dec.group_credits]
        if tok in credits:
            group = sorted(set(group) | set(credits), key=_sort_key)
    if group:
        for issue in _issues(ctx):
            dec = issue.decision
            if dec and dec.excludable and set(map(credit_token, dec.group_credits)) & set(group):
                related.append(issue)
    return group, related


def _sort_key(tok: str) -> tuple[int, int | str]:
    return (0, int(tok)) if tok.isdigit() else (1, tok)


async def _save_path_in_control(graph: GraphApiPort, ctx: DecisionContext) -> None:
    if (ctx.snapshot.decisions_registry_path or "").strip():
        return
    try:
        await update_process_control_row2(
            graph,
            ctx.site_id,
            ctx.drive_id,
            bank_code=ctx.bank_code,
            updates={CONTROL_COLUMN: ctx.registry_path, "LastUpdatedAtProceso": utc_now_iso()},
        )
    except Exception as exc:
        # Sin la ruta en Control la próxima validación no vería la decisión: fallar visible.
        logger.warning("decisions: no se pudo guardar la ruta en Control: %s", exc)
        raise _err(
            "decisions_control_update_failed",
            "No se pudo guardar la decisión en el control del proceso. Intente de nuevo.",
            503,
        ) from exc


async def _mutate(graph: GraphApiPort, ctx: DecisionContext, fn) -> tuple[dict[str, Any], Any]:
    loaded, result = await mutate_registry(
        graph,
        ctx.site_id,
        ctx.drive_id,
        path=ctx.registry_path,
        process_key=ctx.process_key,
        bank_code=ctx.bank_code,
        report_date_iso=ctx.report_date_iso,
        mutate=fn,
    )
    return loaded.data or {}, result


async def exclude_credit(
    graph: GraphApiPort,
    *,
    bank_code: str,
    process_key: str,
    credit: str,
    motivo_codigo: str,
    nota: str,
    quien: str,
) -> UiAmortizationDecisions:
    ctx = await _context(graph, bank_code=bank_code, process_key=process_key)
    group, related = _excludable_group(ctx, credit)
    if not group:
        raise _err(
            "exclusion_not_available",
            "Este crédito no tiene un problema de amortización que permita excluirlo. "
            "Actualice la página.",
        )
    info = ctx.attempt.plan_summary.credit_info if ctx.attempt and ctx.attempt.plan_summary else {}
    clientes: dict[str, str] = {}
    tablas: dict[str, str] = {}
    id_pagos: set[str] = set()
    for tok in group:
        ci = info.get(tok)
        if ci is not None:
            clientes[tok] = ci.client_name or ""
            tablas[tok] = ci.table_path or ""
            id_pagos.update(ci.payment_ids)
    for issue in related:
        loc = issue.location
        tok = credit_token(loc.credit) if loc and loc.credit else ""
        if tok and not clientes.get(tok) and loc and loc.client_name:
            clientes[tok] = loc.client_name
        if loc and loc.payment_id:
            id_pagos.add(loc.payment_id)
        if tok and not tablas.get(tok):
            for link in issue.links:
                if link.rel == "amortization_table" and link.path:
                    tablas[tok] = link.path
                    break

    def _fn(reg: dict[str, Any]):
        return add_exclusion(
            reg,
            credits=group,
            clientes=clientes,
            id_pagos=sorted(id_pagos),
            tablas=tablas,
            motivo_codigo=motivo_codigo,
            nota=nota,
            quien=quien,
            issue_codes=[i.technical_reference or "" for i in related],
        )

    registry, _entry = await _mutate(graph, ctx, _fn)
    await _save_path_in_control(graph, ctx)
    return build_decisions_view(registry, ctx.attempt)


async def undo_credit_exclusion(
    graph: GraphApiPort, *, bank_code: str, process_key: str, credit: str, quien: str
) -> UiAmortizationDecisions:
    ctx = await _context(graph, bank_code=bank_code, process_key=process_key)
    registry, _entry = await _mutate(
        graph, ctx, lambda reg: undo_exclusion(reg, credit=credit, quien=quien)
    )
    return build_decisions_view(registry, ctx.attempt)


async def confirm_conciliation(
    graph: GraphApiPort,
    *,
    bank_code: str,
    process_key: str,
    conciliation_key: str,
    nota: str,
    quien: str,
) -> UiAmortizationDecisions:
    ctx = await _context(graph, bank_code=bank_code, process_key=process_key)
    key = (conciliation_key or "").strip()
    match = next(
        (
            i
            for i in _issues(ctx)
            if i.decision
            and i.decision.confirmable
            and (i.decision.conciliation_key or "") == key
        ),
        None,
    )
    if match is None or match.decision is None:
        raise _err(
            "confirmation_not_available",
            "Esta diferencia ya no está pendiente de confirmación. Actualice la página.",
        )
    dec = match.decision
    clientes: dict[str, str] = {}
    if match.location and match.location.credit and match.location.client_name:
        clientes[credit_token(match.location.credit)] = match.location.client_name

    def _fn(reg: dict[str, Any]):
        return add_confirmation(
            reg,
            key=key,
            credits=list(dec.group_credits),
            clientes=clientes,
            fecha_banco=dec.fecha_banco or "",
            monto_banco=dec.bank_amount,
            monto_asientos=dec.asientos_amount,
            nota=nota,
            quien=quien,
        )

    registry, _entry = await _mutate(graph, ctx, _fn)
    await _save_path_in_control(graph, ctx)
    return build_decisions_view(registry, ctx.attempt)


async def undo_conciliation_confirmation(
    graph: GraphApiPort, *, bank_code: str, process_key: str, conciliation_key: str, quien: str
) -> UiAmortizationDecisions:
    ctx = await _context(graph, bank_code=bank_code, process_key=process_key)
    registry, _entry = await _mutate(
        graph,
        ctx,
        lambda reg: undo_confirmation(reg, key=(conciliation_key or "").strip(), quien=quien),
    )
    return build_decisions_view(registry, ctx.attempt)


# --- proyección para el detalle del proceso ----------------------------------------


def _table_link(path: str | None, web_urls: dict[str, str] | None) -> UiLink | None:
    norm = str(path or "").strip().strip("/")
    if not norm:
        return None
    return UiLink(
        rel="amortization_table",
        label="Abrir tabla",
        path=norm,
        web_url=(web_urls or {}).get(norm),
        open_mode="sharepoint",
    )


def _excluded_rows(
    entries: list[dict[str, Any]], web_urls: dict[str, str] | None, *, closed: bool
) -> list[UiExcludedCredit]:
    rows: list[UiExcludedCredit] = []
    for entry in entries:
        credits = [str(c) for c in entry.get("credits") or []]
        clientes = entry.get("clientes") or {}
        tablas = entry.get("tablas") or {}
        for tok in credits:
            rows.append(
                UiExcludedCredit(
                    credit=tok,
                    client_name=str(clientes.get(tok) or "").strip() or None,
                    motivo=str(entry.get("motivo") or ""),
                    motivo_codigo=str(entry.get("motivo_codigo") or ""),
                    nota=str(entry.get("nota") or "").strip() or None,
                    group_credits=credits,
                    exclusion_id=str(entry.get("exclusion_id") or "") or None,
                    can_undo=not closed and not entry.get("locked_at"),
                    table_link=_table_link(tablas.get(tok), web_urls),
                )
            )
    return rows


def _as_float(value: Any) -> float | None:
    dec = money(value)
    return float(dec) if dec is not None else None


def build_decisions_view(
    registry: dict[str, Any] | None,
    attempt: UiLastAmortizationAttempt | None,
    *,
    web_urls: dict[str, str] | None = None,
    closed: bool = False,
) -> UiAmortizationDecisions:
    exclusions = active_exclusions(registry)
    excluded = _excluded_rows(exclusions, web_urls, closed=closed)
    confirmations = [
        UiConfirmedConciliation(
            conciliation_key=str(c.get("conciliation_key") or ""),
            credits=[str(t) for t in c.get("credits") or []],
            fecha_banco=str(c.get("fecha_banco") or "") or None,
            bank_amount=_as_float(c.get("monto_banco")),
            asientos_amount=_as_float(c.get("monto_asientos")),
            unapplied_amount=_as_float(c.get("monto_sin_aplicar")),
            nota=str(c.get("nota") or "").strip() or None,
            can_undo=not closed and not c.get("locked_at"),
        )
        for c in active_confirmations(registry)
    ]
    planned_lines: int | None = None
    planned_tables: int | None = None
    plan = attempt.plan_summary if attempt else None
    if plan is not None and excluded:
        excluded_toks = {row.credit for row in excluded}
        planned_lines = sum(
            n for tok, n in plan.lines_by_credit.items() if tok not in excluded_toks
        )
        planned_tables = len(
            {
                t
                for tok, ids in plan.tables_by_credit.items()
                if tok not in excluded_toks
                for t in ids
            }
        )
    closure = (registry or {}).get("closure") if isinstance(registry, dict) else None
    not_amortized: list[UiExcludedCredit] = []
    if closed:
        not_amortized = excluded
        if isinstance(closure, dict) and closure.get("creditos_sin_amortizar"):
            not_amortized = [
                UiExcludedCredit(
                    credit=str(c.get("credito") or ""),
                    client_name=str(c.get("cliente") or "").strip() or None,
                    motivo=str(c.get("motivo") or ""),
                    motivo_codigo=str(c.get("motivo_codigo") or ""),
                    nota=str(c.get("nota") or "").strip() or None,
                    table_link=_table_link(c.get("tabla_amortizacion_path"), web_urls),
                )
                for c in closure["creditos_sin_amortizar"]
                if isinstance(c, dict) and str(c.get("credito") or "").strip()
            ]
    return UiAmortizationDecisions(
        excluded=[] if closed else excluded,
        confirmations=[] if closed else confirmations,
        planned_lines=planned_lines,
        planned_tables=planned_tables,
        credits_not_amortized=not_amortized,
    )


async def load_decisions_for_detail(
    graph: GraphApiPort,
    *,
    site_id: str,
    drive_id: str,
    snapshot: ProcessControlSnapshot,
    attempt: UiLastAmortizationAttempt | None,
    closed: bool,
) -> UiAmortizationDecisions | None:
    """Vista de decisiones para el detalle; None si el proceso no tiene registro."""
    path = (snapshot.decisions_registry_path or "").strip()
    if not path:
        return None
    try:
        registry = await load_registry_for_process(
            graph,
            site_id,
            drive_id,
            registry_path=path,
            process_key=(snapshot.process_key or "").strip(),
        )
    except DecisionsRegistryUnavailableError:
        return UiAmortizationDecisions(
            available=False,
            user_message=(
                "No se pudo leer el registro de créditos excluidos de este proceso."
            ),
        )
    if registry is None:
        return None
    return build_decisions_view(registry, attempt, closed=closed)


__all__ = [
    "DECISION_ALLOWED_STATES",
    "build_decisions_view",
    "confirm_conciliation",
    "exclude_credit",
    "load_decisions_for_detail",
    "undo_conciliation_confirmation",
    "undo_credit_exclusion",
]
