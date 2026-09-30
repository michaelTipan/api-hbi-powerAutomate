"""Decisiones del operador en fase 3 (Consolidar).

Cada acción se valida contra la verificación recién calculada (``assess_merge_readiness``):
solo se decide sobre lo que la verificación muestra (un crédito que requiere atención,
una diferencia pendiente, un asiento listado, un tipo con opciones compatibles). Las
decisiones van al mismo registro del proceso que usa la fase 4 (``DecisionsRegistryPath``)
y se pueden deshacer hasta consolidar.
"""
from __future__ import annotations

import dataclasses
from decimal import Decimal
from typing import Any

from app.application.services.amortization_decisions import (
    FASE_CONSOLIDACION,
    MOTIVOS_NO_USADO,
    add_confirmation,
    add_exclusion,
    add_tipo_correction,
    add_unused_asiento,
    conciliation_key as _conciliation_key,
    credit_token,
    money,
    set_group_assignments,
    undo_confirmation,
    undo_exclusion,
    undo_group_assignments,
    undo_tipo_correction,
    undo_unused_asiento,
)
from app.application.services.merge_verification import find_group, find_group_by_key
from app.application.services.review_schema import normalize_tipo_aplicacion_confirmado
from app.application.ui.amortization_decisions_service import (
    DecisionContext,
    _context,
    _err,
    _mutate,
    _save_path_in_control,
)
from app.application.ui.merge_readiness import MergeReadiness, assess_merge_readiness, readiness_to_ui
from app.application.ui.schemas import UiMergeDecisionResponse
from app.domain.ports.graph import GraphApiPort

MERGE_DECISION_ALLOWED_STATES = frozenset({"PENDIENTE_ASIENTOS", "MERGE_PARCIAL", "ERROR_MERGE"})

_MSG_STALE = "La verificación cambió desde que abrió esta ventana. Verifique de nuevo."


async def _ctx(graph: GraphApiPort, bank_code: str, process_key: str) -> DecisionContext:
    return await _context(
        graph,
        bank_code=bank_code,
        process_key=process_key,
        allowed_states=MERGE_DECISION_ALLOWED_STATES,
    )


async def _verification(graph: GraphApiPort, ctx: DecisionContext) -> dict[str, Any]:
    readiness = await assess_merge_readiness(graph, ctx.snapshot, ctx.bank_code)
    if readiness.verification is None:
        raise _err(
            "merge_verification_unavailable",
            readiness.user_message
            or "No se pudo verificar los asientos contables. Actualice e intente nuevamente.",
            503,
        )
    return readiness.verification


async def _respond(graph: GraphApiPort, ctx: DecisionContext) -> UiMergeDecisionResponse:
    snap = ctx.snapshot
    if (snap.decisions_registry_path or "").strip() != ctx.registry_path:
        snap = dataclasses.replace(snap, decisions_registry_path=ctx.registry_path)
    readiness: MergeReadiness = await assess_merge_readiness(graph, snap, ctx.bank_code)
    return UiMergeDecisionResponse(ok=True, merge_readiness=readiness_to_ui(readiness))


def _group_or_error(verification: dict[str, Any], credit: str) -> dict[str, Any]:
    group = find_group(verification, credit)
    if group is None:
        raise _err("merge_credit_not_found", "Este crédito no está en el lote. Actualice la página.", 404)
    return group


async def exclude_credit(
    graph: GraphApiPort,
    *,
    bank_code: str,
    process_key: str,
    credit: str,
    motivo_codigo: str,
    nota: str,
    quien: str,
) -> UiMergeDecisionResponse:
    ctx = await _ctx(graph, bank_code, process_key)
    group = _group_or_error(await _verification(graph, ctx), credit)
    if group["status"] == "excluded":
        return await _respond(graph, ctx)
    if group["status"] != "attention":
        raise _err(
            "exclusion_not_available",
            "Solo se pueden excluir créditos que requieren atención. Actualice la página.",
        )
    credits = list(group["credits"])
    folders = {f["credito"]: f["path"] for f in group.get("folders") or []}

    def _fn(reg: dict[str, Any]):
        return add_exclusion(
            reg,
            credits=credits,
            clientes=dict(group.get("clientes") or {}),
            id_pagos=[c["id_pago"] for c in group.get("consignaciones") or []],
            tablas=dict(group.get("tablas") or {}),
            motivo_codigo=motivo_codigo,
            nota=nota,
            quien=quien,
            issue_codes=[m["code"] for m in group.get("motivos") or []],
            fase=FASE_CONSOLIDACION,
            asientos_dirs=folders,
        )

    await _mutate(graph, ctx, _fn)
    await _save_path_in_control(graph, ctx)
    return await _respond(graph, ctx)


async def undo_credit_exclusion(
    graph: GraphApiPort, *, bank_code: str, process_key: str, credit: str, quien: str
) -> UiMergeDecisionResponse:
    ctx = await _ctx(graph, bank_code, process_key)
    await _mutate(graph, ctx, lambda reg: undo_exclusion(reg, credit=credit, quien=quien))
    return await _respond(graph, ctx)


async def confirm_difference(
    graph: GraphApiPort,
    *,
    bank_code: str,
    process_key: str,
    conciliation_key: str,
    nota: str,
    quien: str,
) -> UiMergeDecisionResponse:
    ctx = await _ctx(graph, bank_code, process_key)
    key = (conciliation_key or "").strip()
    verification = await _verification(graph, ctx)
    match: tuple[dict[str, Any], dict[str, Any]] | None = None
    for group in verification.get("groups") or []:
        for fecha in group.get("fechas") or []:
            if fecha.get("conciliation_key") == key and fecha.get("status") in ("BANK_GREATER", "CONFIRMED"):
                match = (group, fecha)
    if match is None:
        raise _err(
            "confirmation_not_available",
            "Esta diferencia ya no está pendiente de confirmación. Verifique de nuevo.",
        )
    group, fecha = match

    def _fn(reg: dict[str, Any]):
        return add_confirmation(
            reg,
            key=key,
            credits=list(group["credits"]),
            clientes=dict(group.get("clientes") or {}),
            fecha_banco=str(fecha.get("fecha") or ""),
            monto_banco=fecha.get("monto_banco"),
            monto_asientos=fecha.get("monto_asientos"),
            nota=nota,
            quien=quien,
            fase=FASE_CONSOLIDACION,
            origen="consolidar",
        )

    await _mutate(graph, ctx, _fn)
    await _save_path_in_control(graph, ctx)
    return await _respond(graph, ctx)


async def undo_difference_confirmation(
    graph: GraphApiPort, *, bank_code: str, process_key: str, conciliation_key: str, quien: str
) -> UiMergeDecisionResponse:
    ctx = await _ctx(graph, bank_code, process_key)
    key = (conciliation_key or "").strip()
    await _mutate(graph, ctx, lambda reg: undo_confirmation(reg, key=key, quien=quien))
    return await _respond(graph, ctx)


def validate_assignment(group: dict[str, Any], items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Valida la asignación del usuario. Devuelve (asignaciones, faltantes por fecha).

    Todos los asientos usables asignados, cada uno a un pago elegible (fecha del pago ≤
    fecha del asiento) y ningún pago con más de lo que recibió el banco.
    """
    usable = {a["path"]: a for a in group.get("asientos") or [] if a.get("state") == "usable"}
    chosen: dict[str, str] = {}
    for item in items:
        path = str(item.get("asiento_path") or "").strip()
        pid = str(item.get("id_pago") or "").strip()
        if path not in usable:
            raise _err("assignment_stale", _MSG_STALE)
        if pid not in usable[path].get("eligible_id_pagos", []):
            raise _err(
                "assignment_not_eligible",
                "Un asiento no puede asignarse a un pago posterior a la fecha del asiento.",
                422,
            )
        chosen[path] = pid
    if set(chosen) != set(usable):
        raise _err("assignment_incomplete", "Asigne todos los asientos antes de confirmar.", 422)
    payments = {p["id_pago"]: p for p in (group.get("assignment") or {}).get("payments") or []}
    assigned: dict[str, Decimal] = {pid: Decimal("0.00") for pid in payments}
    for path, pid in chosen.items():
        assigned[pid] = assigned.get(pid, Decimal("0.00")) + (money(usable[path].get("cash")) or Decimal("0.00"))
    for pid, total in assigned.items():
        bank = money(payments.get(pid, {}).get("monto")) or Decimal("0.00")
        if total > bank:
            raise _err(
                "assignment_exceeds_payment",
                "Hay un pago con más asientos de lo que recibió el banco. Revise la asignación.",
                422,
            )
    rows = [
        {
            "credito": usable[path]["credito"],
            "asiento_pdf_path": path,
            "id_pago": pid,
            "fecha_banco": payments.get(pid, {}).get("fecha", ""),
        }
        for path, pid in chosen.items()
    ]
    by_date: dict[str, tuple[Decimal, Decimal]] = {}
    for pid, p in payments.items():
        fecha = str(p.get("fecha") or "")
        bank, cash = by_date.get(fecha, (Decimal("0.00"), Decimal("0.00")))
        by_date[fecha] = (
            bank + (money(p.get("monto")) or Decimal("0.00")),
            cash + assigned.get(pid, Decimal("0.00")),
        )
    shortfalls = [
        {"fecha": fecha, "monto_banco": bank, "monto_asientos": cash}
        for fecha, (bank, cash) in sorted(by_date.items())
        if cash < bank
    ]
    return rows, shortfalls


async def save_assignment(
    graph: GraphApiPort,
    *,
    bank_code: str,
    process_key: str,
    group_key: str,
    items: list[dict[str, Any]],
    quien: str,
) -> UiMergeDecisionResponse:
    ctx = await _ctx(graph, bank_code, process_key)
    verification = await _verification(graph, ctx)
    group = find_group_by_key(verification, group_key)
    if group is None or group["status"] == "excluded":
        raise _err("assignment_stale", _MSG_STALE)
    assignment = group.get("assignment") or {}
    if not (assignment.get("required") or assignment.get("explicit")):
        raise _err(
            "assignment_not_required",
            "Este crédito no necesita asignar asientos. Verifique de nuevo.",
        )
    rows, shortfalls = validate_assignment(group, items)

    def _fn(reg: dict[str, Any]):
        out, created = set_group_assignments(reg, group_key=group_key, items=rows, quien=quien)
        for s in shortfalls:
            out, _ = add_confirmation(
                out,
                key=_conciliation_key(group_key, s["fecha"]),
                credits=list(group["credits"]),
                clientes=dict(group.get("clientes") or {}),
                fecha_banco=s["fecha"],
                monto_banco=s["monto_banco"],
                monto_asientos=s["monto_asientos"],
                nota="Diferencia no aplicada",
                quien=quien,
                fase=FASE_CONSOLIDACION,
                origen="asignacion",
            )
        return out, created

    await _mutate(graph, ctx, _fn)
    await _save_path_in_control(graph, ctx)
    return await _respond(graph, ctx)


async def undo_assignment(
    graph: GraphApiPort, *, bank_code: str, process_key: str, group_key: str, quien: str
) -> UiMergeDecisionResponse:
    ctx = await _ctx(graph, bank_code, process_key)
    await _mutate(graph, ctx, lambda reg: undo_group_assignments(reg, group_key=group_key, quien=quien))
    return await _respond(graph, ctx)


async def mark_asiento_unused(
    graph: GraphApiPort,
    *,
    bank_code: str,
    process_key: str,
    asiento_path: str,
    motivo_codigo: str,
    quien: str,
) -> UiMergeDecisionResponse:
    ctx = await _ctx(graph, bank_code, process_key)
    verification = await _verification(graph, ctx)
    path = str(asiento_path or "").strip()
    found: dict[str, Any] | None = None
    for group in verification.get("groups") or []:
        if group["status"] == "excluded":
            continue
        for a in group.get("asientos") or []:
            if a.get("path") == path:
                found = a
    if found is None or not found.get("can_mark_unused"):
        raise _err("asiento_not_available", "Este asiento ya no está en la carpeta. Verifique de nuevo.")
    code = (motivo_codigo or "NO_CORRESPONDE").strip().upper()
    if code not in MOTIVOS_NO_USADO:
        raise _err("unused_reason_invalid", "Seleccione el motivo.", 422)
    await _mutate(
        graph,
        ctx,
        lambda reg: add_unused_asiento(
            reg,
            path=path,
            credito_carpeta=credit_token(found.get("credito")),
            nota="",
            quien=quien,
            motivo_codigo=code,
            fase=FASE_CONSOLIDACION,
        ),
    )
    await _save_path_in_control(graph, ctx)
    return await _respond(graph, ctx)


async def undo_asiento_unused(
    graph: GraphApiPort, *, bank_code: str, process_key: str, asiento_path: str, quien: str
) -> UiMergeDecisionResponse:
    ctx = await _ctx(graph, bank_code, process_key)
    path = str(asiento_path or "").strip()
    await _mutate(graph, ctx, lambda reg: undo_unused_asiento(reg, path=path, quien=quien))
    return await _respond(graph, ctx)


async def use_tipo(
    graph: GraphApiPort,
    *,
    bank_code: str,
    process_key: str,
    id_pago: str,
    tipo: str,
    nota: str,
    quien: str,
) -> UiMergeDecisionResponse:
    ctx = await _ctx(graph, bank_code, process_key)
    verification = await _verification(graph, ctx)
    pid = str(id_pago or "").strip()
    group = next(
        (
            g
            for g in verification.get("groups") or []
            if (g.get("tipo") or {}).get("id_pago") == pid and g["status"] != "excluded"
        ),
        None,
    )
    info = (group or {}).get("tipo") or {}
    if group is None or not info.get("needed"):
        raise _err("tipo_not_available", "El tipo de este pago ya no requiere confirmación. Verifique de nuevo.")
    nuevo = normalize_tipo_aplicacion_confirmado(tipo) or str(tipo or "").strip()
    if nuevo not in (info.get("opciones") or []):
        raise _err("tipo_not_compatible", "Elija uno de los tipos compatibles con los asientos.", 422)
    await _mutate(
        graph,
        ctx,
        lambda reg: add_tipo_correction(
            reg,
            group_key=str(group["group_key"]),
            id_pago=pid,
            credits=list(group["credits"]),
            tipo_anterior=str(info.get("declarado") or ""),
            tipo_nuevo=nuevo,
            nota=nota,
            quien=quien,
        ),
    )
    await _save_path_in_control(graph, ctx)
    return await _respond(graph, ctx)


async def undo_tipo(
    graph: GraphApiPort, *, bank_code: str, process_key: str, id_pago: str, quien: str
) -> UiMergeDecisionResponse:
    ctx = await _ctx(graph, bank_code, process_key)
    pid = str(id_pago or "").strip()
    await _mutate(graph, ctx, lambda reg: undo_tipo_correction(reg, id_pago=pid, quien=quien))
    return await _respond(graph, ctx)


__all__ = [
    "MERGE_DECISION_ALLOWED_STATES",
    "confirm_difference",
    "exclude_credit",
    "mark_asiento_unused",
    "save_assignment",
    "undo_asiento_unused",
    "undo_assignment",
    "undo_credit_exclusion",
    "undo_difference_confirmation",
    "undo_tipo",
    "use_tipo",
    "validate_assignment",
]
