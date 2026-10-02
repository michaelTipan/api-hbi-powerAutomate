"""Conciliación del lote en fase 4: grupos de pagos, asientos compartidos y cuadre banco↔asientos.

Reglas (misma lógica para PAGO y ABONO):

* Grupo = componente conexa de pagos (ID Pago del manifest) que comparten crédito.
* Un asiento genera una sola línea: si el mismo PDF aparece en varios pagos del mismo
  crédito, se asigna a uno solo. Con una sola fecha de pago en los candidatos se asigna
  al primero (PAGO antes que ABONO, luego orden del manifest). Con varias fechas se
  asigna solo si la fecha del asiento coincide con exactamente una fecha de pago;
  si no, el grupo queda con el problema «Requiere asignar asientos a sus pagos».
  El monto nunca decide la asignación.
* Efectivo del asiento = línea de banco (544111100505) solo si el asiento la trae;
  si no (saldos menores, retención sin recaudo) aporta 0. Los valores escritos no cambian.
* Cuadre por (grupo, fecha de pago) en pesos exactos (Decimal redondeado a centavos,
  sin otras tolerancias): igual → OK; asientos < banco → requiere «Continuar con los
  asientos» (queda registrado el monto sin aplicar); asientos > banco → problema.
* Los créditos excluidos en el registro de decisiones salen del lote junto con todo su grupo.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Awaitable, Callable

from app.application.services.accounting_pdf_parser import ACCOUNT_VALOR_PAGADO_CLIENTE
from app.application.services.amortization_decisions import (
    active_exclusions,
    conciliation_key,
    credit_token,
    exclusion_for_credit,
    explicit_assignments,
    find_confirmation,
    group_key_for_credits,
)
from app.application.services.review_schema import TipoAplicacion
from app.application.use_cases.merge_composite_validado_pdfs import normalize_sharepoint_path

CONCILIACION_ASIENTOS_MAYOR_BANCO = "CONCILIACION_ASIENTOS_MAYOR_BANCO"
CONCILIACION_BANCO_MAYOR_ASIENTOS = "CONCILIACION_BANCO_MAYOR_ASIENTOS"
ASIENTOS_REQUIEREN_ASIGNACION = "ASIENTOS_REQUIEREN_ASIGNACION"
DECISIONS_REGISTRY_UNAVAILABLE = "DECISIONS_REGISTRY_UNAVAILABLE"

CONCILIATION_CODES = frozenset(
    {
        CONCILIACION_ASIENTOS_MAYOR_BANCO,
        CONCILIACION_BANCO_MAYOR_ASIENTOS,
        ASIENTOS_REQUIEREN_ASIGNACION,
    }
)

_CENT = Decimal("0.01")
_OK_STATUSES = frozenset({"WOULD_APPLY", "WOULD_ADOPT_EXISTING", "ALREADY_APPLIED"})
_ADVISORY_SUPERSEDED = "BANK_ASIENTOS_NO_CUADRAN"
_SUPERSEDED_WARNING_MARKER = "no cuadra con Σ valor_pagado_cliente de asientos"


def bank_vs_asientos_warning(monto: Any, total: Any) -> str:
    """Aviso del cuadre por un solo ID Pago; el cuadre del grupo lo reemplaza."""
    return f"Monto banco ({monto}) {_SUPERSEDED_WARNING_MARKER} ({total})."


def cents(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value)).quantize(_CENT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return None


def cash_from_parsed(detected_codes: Any, valor_pagado_cliente: Any) -> Decimal:
    """Dinero real del asiento: la línea de banco solo si el asiento la trae."""
    codes = {str(c) for c in detected_codes or []}
    if ACCOUNT_VALOR_PAGADO_CLIENTE not in codes:
        return Decimal("0.00")
    return cents(valor_pagado_cliente) or Decimal("0.00")


@dataclass
class LotPayment:
    index: int
    output: dict[str, Any]
    id_pago: str
    cliente: str
    tipo: str
    fecha_banco: str
    monto_banco: Decimal | None
    legacy: bool
    credit_paths: dict[str, list[str]] = field(default_factory=dict)
    credit_labels: dict[str, str] = field(default_factory=dict)
    tables: dict[str, str] = field(default_factory=dict)


@dataclass
class LotGroup:
    key: str
    credits: list[str]
    payments: list[int]
    exclusion: dict[str, Any] | None = None
    date_assigned: bool = False
    assignment_problem_credits: list[str] = field(default_factory=list)

    @property
    def excluded(self) -> bool:
        return self.exclusion is not None


@dataclass
class LotModel:
    payments: list[LotPayment]
    groups: list[LotGroup]
    group_of_payment: dict[int, str]
    group_of_credit: dict[str, str]
    assignment: dict[tuple[str, str], int] = field(default_factory=dict)
    shared_asientos: int = 0
    covered_pairs: set[tuple[str, str]] = field(default_factory=set)

    def group(self, key: str) -> LotGroup:
        for g in self.groups:
            if g.key == key:
                return g
        raise KeyError(key)

    @property
    def lot_id_pagos(self) -> set[str]:
        return {p.id_pago for p in self.payments if p.id_pago}


def _norm_path(path: str) -> str:
    return normalize_sharepoint_path(path) or str(path or "").strip().strip("/").casefold()


def _payment_credit_paths(
    output: dict[str, Any],
    *,
    legacy_paths_fn: Callable[[dict[str, Any]], list[str]],
    legacy_credit_fn: Callable[[str], str],
) -> tuple[bool, dict[str, list[str]], dict[str, str], dict[str, str]]:
    credit_paths: dict[str, list[str]] = {}
    labels: dict[str, str] = {}
    tables: dict[str, str] = {}
    items = output.get("credit_items")
    if isinstance(items, list) and items:
        for ci in items:
            if not isinstance(ci, dict):
                continue
            label = str(ci.get("credito") or "").strip()
            tok = credit_token(label)
            if not tok:
                continue
            labels.setdefault(tok, label)
            tabla = str(ci.get("ruta_tabla_amortizacion") or "").strip().strip("/")
            if tabla:
                tables.setdefault(tok, tabla)
            paths = [str(p).strip().strip("/") for p in ci.get("asiento_pdf_paths") or [] if str(p).strip()]
            if not paths:
                single = str(ci.get("asiento_pdf_path") or "").strip().strip("/")
                if single:
                    paths = [single]
            credit_paths.setdefault(tok, []).extend(paths)
        return False, credit_paths, labels, tables
    legacy_credito = str(output.get("credito") or "").strip()
    for path in legacy_paths_fn(output):
        label = legacy_credit_fn(path) or legacy_credito
        tok = credit_token(label)
        if not tok:
            continue
        labels.setdefault(tok, label)
        credit_paths.setdefault(tok, []).append(path)
    return True, credit_paths, labels, tables


def build_lot_model(
    outputs: list[dict[str, Any]],
    *,
    tipo_fn: Callable[[dict[str, Any]], str],
    payment_date_fn: Callable[[dict[str, Any], str, list[str]], str],
    legacy_paths_fn: Callable[[dict[str, Any]], list[str]],
    legacy_credit_fn: Callable[[str], str],
) -> LotModel:
    payments: list[LotPayment] = []
    for idx, out in enumerate(outputs):
        if not isinstance(out, dict):
            continue
        tipo = tipo_fn(out)
        legacy, credit_paths, labels, tables = _payment_credit_paths(
            out, legacy_paths_fn=legacy_paths_fn, legacy_credit_fn=legacy_credit_fn
        )
        credits = list(credit_paths.keys())
        payments.append(
            LotPayment(
                index=idx,
                output=out,
                id_pago=str(out.get("id_pago") or "").strip(),
                cliente=str(out.get("cliente") or "").strip(),
                tipo=tipo,
                fecha_banco=payment_date_fn(out, tipo, credits) or "",
                monto_banco=cents(out.get("monto_banco")),
                legacy=legacy,
                credit_paths=credit_paths,
                credit_labels=labels,
                tables=tables,
            )
        )

    parent: dict[int, int] = {p.index: p.index for p in payments}

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    first_payment_of_credit: dict[str, int] = {}
    for p in payments:
        for tok in p.credit_paths:
            if tok in first_payment_of_credit:
                a, b = find(first_payment_of_credit[tok]), find(p.index)
                if a != b:
                    parent[max(a, b)] = min(a, b)
            else:
                first_payment_of_credit[tok] = p.index

    members: dict[int, list[LotPayment]] = {}
    for p in payments:
        members.setdefault(find(p.index), []).append(p)

    groups: list[LotGroup] = []
    group_of_payment: dict[int, str] = {}
    group_of_credit: dict[str, str] = {}
    for root in sorted(members):
        ps = members[root]
        credits: list[str] = []
        for p in ps:
            for tok in p.credit_paths:
                if tok not in credits:
                    credits.append(tok)
        key = group_key_for_credits(credits) or f"pago:{ps[0].id_pago or ps[0].index}"
        groups.append(LotGroup(key=key, credits=credits, payments=[p.index for p in ps]))
        for p in ps:
            group_of_payment[p.index] = key
        for tok in credits:
            group_of_credit[tok] = key
    return LotModel(
        payments=payments,
        groups=groups,
        group_of_payment=group_of_payment,
        group_of_credit=group_of_credit,
    )


def apply_exclusions(model: LotModel, registry: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Marca como excluidos los grupos con algún crédito excluido. Devuelve el detalle."""
    excluded: list[dict[str, Any]] = []
    if not registry:
        return excluded
    for group in model.groups:
        for tok in group.credits:
            entry = exclusion_for_credit(registry, tok)
            if entry is not None:
                group.exclusion = entry
                break
        if group.exclusion is None:
            continue
        payments = [model.payments[_pos(model, i)] for i in group.payments]
        for tok in group.credits:
            cliente = next((p.cliente for p in payments if tok in p.credit_paths), "")
            tabla = next((p.tables.get(tok, "") for p in payments if p.tables.get(tok)), "")
            excluded.append(
                {
                    "credito": tok,
                    "cliente": cliente
                    or str((group.exclusion.get("clientes") or {}).get(tok) or ""),
                    "motivo": str(group.exclusion.get("motivo") or ""),
                    "motivo_codigo": str(group.exclusion.get("motivo_codigo") or ""),
                    "nota": str(group.exclusion.get("nota") or ""),
                    "tabla_amortizacion_path": tabla
                    or str((group.exclusion.get("tablas") or {}).get(tok) or ""),
                    "group_key": group.key,
                    "group_credits": list(group.credits),
                    "id_pagos": sorted({p.id_pago for p in payments if p.id_pago}),
                    "exclusion_id": str(group.exclusion.get("exclusion_id") or ""),
                    "locked": bool(group.exclusion.get("locked_at")),
                }
            )
    return excluded


def exclusions_outside_lot(
    model: LotModel, registry: dict[str, Any] | None, excluded: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Exclusiones vigentes de créditos que no llegaron al manifest (excluidos al consolidar).

    Mismo formato que ``apply_exclusions``: la amortización no queda completa y el cierre
    los lista, aunque no haya consolidado para ellos.
    """
    if not registry:
        return []
    in_lot = {tok for group in model.groups for tok in group.credits}
    seen = {credit_token(e.get("credito")) for e in excluded}
    out: list[dict[str, Any]] = []
    for entry in active_exclusions(registry):
        tokens = [credit_token(c) for c in entry.get("credits") or [] if credit_token(c)]
        if not tokens or any(tok in in_lot for tok in tokens):
            continue
        for tok in tokens:
            if tok in seen:
                continue
            seen.add(tok)
            out.append(
                {
                    "credito": tok,
                    "cliente": str((entry.get("clientes") or {}).get(tok) or ""),
                    "motivo": str(entry.get("motivo") or ""),
                    "motivo_codigo": str(entry.get("motivo_codigo") or ""),
                    "nota": str(entry.get("nota") or ""),
                    "tabla_amortizacion_path": str((entry.get("tablas") or {}).get(tok) or ""),
                    "group_key": group_key_for_credits(tokens),
                    "group_credits": sorted(tokens, key=_sort_token),
                    "id_pagos": sorted({str(p) for p in entry.get("id_pagos") or [] if p}),
                    "exclusion_id": str(entry.get("exclusion_id") or ""),
                    "locked": bool(entry.get("locked_at")),
                }
            )
    return out


def _pos(model: LotModel, payment_index: int) -> int:
    for pos, p in enumerate(model.payments):
        if p.index == payment_index:
            return pos
    raise KeyError(payment_index)


def _payment(model: LotModel, payment_index: int) -> LotPayment:
    return model.payments[_pos(model, payment_index)]


def _preferred(model: LotModel, candidates: list[int]) -> int:
    for idx in candidates:
        if _payment(model, idx).tipo != TipoAplicacion.ABONO.value:
            return idx
    return candidates[0]


async def assign_shared_asientos(
    model: LotModel,
    *,
    registry: dict[str, Any] | None,
    asiento_date_fn: Callable[[str, str], Awaitable[str | None]],
) -> None:
    """Asigna cada asiento (crédito + PDF) a un único pago del grupo."""
    explicit: dict[tuple[str, str], str] = {}
    for a in explicit_assignments(registry):
        tok = credit_token(a.get("credito"))
        path = _norm_path(str(a.get("asiento_pdf_path") or ""))
        pago = str(a.get("id_pago") or "").strip()
        if tok and path and pago:
            explicit[(tok, path)] = pago

    for group in model.groups:
        if group.excluded:
            continue
        occurrences: dict[tuple[str, str], list[int]] = {}
        raw_path: dict[tuple[str, str], str] = {}
        for idx in group.payments:
            p = _payment(model, idx)
            for tok, paths in p.credit_paths.items():
                for path in paths:
                    key = (tok, _norm_path(path))
                    raw_path.setdefault(key, path)
                    lst = occurrences.setdefault(key, [])
                    if idx not in lst:
                        lst.append(idx)
        problem_credits: list[str] = []
        for key, cands in occurrences.items():
            if len(cands) == 1:
                model.assignment[key] = cands[0]
                continue
            model.shared_asientos += 1
            wanted = explicit.get(key)
            chosen = next((c for c in cands if _payment(model, c).id_pago == wanted), None)
            if chosen is not None:
                model.assignment[key] = chosen
                continue
            dates = {_payment(model, c).fecha_banco for c in cands}
            if len(dates) == 1:
                model.assignment[key] = _preferred(model, cands)
                continue
            fecha = (await asiento_date_fn(key[0], raw_path[key])) or ""
            matches = [c for c in cands if fecha and _payment(model, c).fecha_banco == fecha]
            if matches:
                model.assignment[key] = _preferred(model, matches)
                group.date_assigned = True
                continue
            model.assignment[key] = _preferred(model, cands)
            if key[0] not in problem_credits:
                problem_credits.append(key[0])
        group.assignment_problem_credits = problem_credits


def planner_outputs(model: LotModel) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Outputs para los planificadores: sin excluidos ni pagos cubiertos por otro pago del grupo.

    Devuelve (outputs_planificables, outputs_cubiertos). Un output sin cambios se
    entrega tal cual (mismo objeto) para no alterar el comportamiento previo.
    """
    planned: list[dict[str, Any]] = []
    covered: list[dict[str, Any]] = []
    for p in model.payments:
        group = model.group(model.group_of_payment[p.index])
        if group.excluded:
            continue
        kept: dict[str, list[str]] = {}
        changed = False
        for tok, paths in p.credit_paths.items():
            seen: set[str] = set()
            keep: list[str] = []
            for path in paths:
                norm = _norm_path(path)
                if norm in seen:
                    changed = True
                    continue
                seen.add(norm)
                if model.assignment.get((tok, norm), p.index) == p.index:
                    keep.append(path)
                else:
                    changed = True
            kept[tok] = keep
            if not paths and _covered_elsewhere(model, group, p, tok):
                changed = True
        if not changed:
            planned.append(p.output)
            continue
        dropped = [
            tok
            for tok, paths in p.credit_paths.items()
            if not kept.get(tok) and (paths or _covered_elsewhere(model, group, p, tok))
        ]
        for tok in dropped:
            model.covered_pairs.add((p.id_pago, tok))
        remaining = [tok for tok in p.credit_paths if tok not in dropped]
        if not remaining:
            covered.append(p.output)
            continue
        planned.append(_rewrite_output(p, kept, set(dropped)))
    return planned, covered


def _covered_elsewhere(model: LotModel, group: LotGroup, p: LotPayment, tok: str) -> bool:
    """Consolidado nuevo: el crédito no trae asientos en este pago porque se asignaron a
    otro pago del grupo. En el manifest viejo un crédito sin asientos es un faltante."""
    if not str(p.output.get("consolidado_key") or "").strip():
        return False
    return any(idx != p.index and _payment(model, idx).credit_paths.get(tok) for idx in group.payments)


def _rewrite_output(p: LotPayment, kept: dict[str, list[str]], dropped: set[str]) -> dict[str, Any]:
    out = copy.deepcopy(p.output)
    if not p.legacy:
        new_items = []
        for ci in out.get("credit_items") or []:
            if not isinstance(ci, dict):
                continue
            tok = credit_token(ci.get("credito"))
            if tok in dropped:
                continue
            if tok in kept:
                ci["asiento_pdf_paths"] = list(kept[tok])
                ci.pop("asiento_pdf_path", None)
            new_items.append(ci)
        out["credit_items"] = new_items
        sel = out.get("creditos_seleccionados")
        if isinstance(sel, list) and dropped:
            out["creditos_seleccionados"] = [c for c in sel if credit_token(c) not in dropped]
        return out
    paths: list[str] = []
    for tok, lst in kept.items():
        if tok in dropped:
            continue
        paths.extend(lst)
    out["asiento_pdf_paths"] = paths
    out.pop("asiento_pdf_path", None)
    return out


def _payment_for_item(model: LotModel, item: dict[str, Any]) -> LotPayment | None:
    id_pago = str(item.get("id_pago") or "").strip()
    tok = credit_token(item.get("credito"))
    fallback: LotPayment | None = None
    for p in model.payments:
        if p.id_pago != id_pago:
            continue
        if tok in p.credit_paths:
            return p
        fallback = fallback or p
    return fallback


def _mark_item_blocked(item: dict[str, Any], code: str, problem_id: str) -> None:
    if item.get("error_code"):
        return
    item["pre_conciliation_status"] = item.get("application_status")
    item["application_status"] = "ERROR"
    item["error_code"] = code
    item["conciliation_problem_id"] = problem_id


def add_advisory_code(item: dict[str, Any], code: str) -> None:
    """Marca un aviso no bloqueante sin perder los que el ítem ya traía."""
    codes = [str(c) for c in item.get("advisory_codes") or [] if str(c or "").strip()]
    prev = str(item.get("advisory_code") or "").strip()
    for c in (prev, code):
        if c and c not in codes:
            codes.append(c)
    item["advisory_codes"] = codes
    item["advisory_code"] = code


def _clear_superseded_advisory(item: dict[str, Any]) -> None:
    remaining = [
        str(c)
        for c in item.get("advisory_codes") or []
        if str(c or "").strip() and c != _ADVISORY_SUPERSEDED
    ]
    if "advisory_codes" in item:
        item["advisory_codes"] = remaining
    if item.get("advisory_code") != _ADVISORY_SUPERSEDED:
        return
    item.pop("advisory_code", None)
    # El aviso previo (p. ej. pago total sin saldo cero) sigue vigente: se restaura.
    if remaining:
        item["advisory_code"] = remaining[-1]
    # Sin el código, el aviso quedaría como advertencia desconocida y bloquearía Apply.
    item["warnings"] = [
        w for w in item.get("warnings") or [] if _SUPERSEDED_WARNING_MARKER not in str(w)
    ]


def _fmt_money(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


async def evaluate_lot_conciliation(
    model: LotModel,
    *,
    items: list[dict[str, Any]],
    abono_group_results: list[dict[str, Any]],
    registry: dict[str, Any] | None,
    excluded: list[dict[str, Any]],
    unresolved_cash_fn: Callable[[dict[str, Any]], Awaitable[Decimal | None]] | None = None,
) -> dict[str, Any]:
    """Cuadre por grupo/fecha tras planificar; marca ítems y grupos ABONO bloqueados."""
    lot_id_pagos = model.lot_id_pagos
    items_by_group: dict[str, list[dict[str, Any]]] = {}
    item_payment: dict[int, LotPayment] = {}
    for it in items:
        p = _payment_for_item(model, it)
        if p is None:
            continue
        item_payment[id(it)] = p
        items_by_group.setdefault(model.group_of_payment[p.index], []).append(it)

    abono_by_pago: dict[str, list[dict[str, Any]]] = {}
    for gr in abono_group_results:
        abono_by_pago.setdefault(str(gr.get("id_pago") or "").strip(), []).append(gr)

    problems: list[dict[str, Any]] = []
    confirmed: list[dict[str, Any]] = []
    groups_out: list[dict[str, Any]] = []
    credit_groups = {tok: list(model.group(key).credits) for tok, key in model.group_of_credit.items()}

    for group in model.groups:
        payments = [_payment(model, i) for i in group.payments]
        clientes = {
            tok: next((p.cliente for p in payments if tok in p.credit_paths), "") for tok in group.credits
        }
        tablas = {
            tok: next((p.tables.get(tok, "") for p in payments if p.tables.get(tok)), "")
            for tok in group.credits
        }
        base = {
            "group_key": group.key,
            "credits": list(group.credits),
            "credit_labels": {
                tok: next((p.credit_labels.get(tok, tok) for p in payments if tok in p.credit_paths), tok)
                for tok in group.credits
            },
            "clientes": clientes,
            "cliente": next((c for c in clientes.values() if c), ""),
            "id_pagos": sorted({p.id_pago for p in payments if p.id_pago}),
            "tablas": tablas,
        }
        if group.excluded:
            groups_out.append({**base, "status": "EXCLUDED", "dates": []})
            continue
        group_items = items_by_group.get(group.key, [])

        if group.assignment_problem_credits:
            problem = {
                **base,
                "problem_id": f"{ASIENTOS_REQUIEREN_ASIGNACION}|{group.key}",
                "code": ASIENTOS_REQUIEREN_ASIGNACION,
                "credits_affected": list(group.assignment_problem_credits),
                "fechas_banco": sorted({p.fecha_banco for p in payments if p.fecha_banco}),
                "confirmable": False,
                "excludable": True,
            }
            problems.append(problem)
            _block_group(group_items, payments, abono_by_pago, problem)
            groups_out.append({**base, "status": "PROBLEM", "dates": []})
            continue

        blocked_elsewhere = any(
            it.get("error_code") or str(it.get("application_status") or "") not in _OK_STATUSES
            for it in group_items
        ) or any(
            gr.get("blocking_errors") or not gr.get("group_ready_for_apply", True)
            for p in payments
            for gr in abono_by_pago.get(p.id_pago, [])
        )
        if not group_items or blocked_elsewhere:
            groups_out.append({**base, "status": "PENDING_OTHER_PROBLEMS", "dates": []})
            continue

        missing_monto = [p for p in payments if p.monto_banco is None or p.monto_banco <= 0]
        if missing_monto:
            for it in group_items:
                if not it.get("error_code"):
                    it["application_status"] = "ERROR"
                    it["error_code"] = "BANK_MONTO_BANCO_MISSING"
                    warns = list(it.get("warnings") or [])
                    warns.append("Monto bancario ausente para un pago del grupo; no se puede conciliar.")
                    it["warnings"] = warns
            groups_out.append({**base, "status": "PENDING_OTHER_PROBLEMS", "dates": []})
            continue

        bank_by_date: dict[str, Decimal] = {}
        for p in payments:
            bank_by_date[p.fecha_banco] = bank_by_date.get(p.fecha_banco, Decimal("0.00")) + (
                p.monto_banco or Decimal("0.00")
            )
        cash_by_date: dict[str, Decimal] = {d: Decimal("0.00") for d in bank_by_date}
        seen_events: set[str] = set()
        unresolved = False
        for it in group_items:
            p = item_payment[id(it)]
            ident = str(it.get("idempotency_key") or "") or f"{p.index}|{it.get('asiento_pdf_path')}|{it.get('event_index')}"
            if ident in seen_events:
                continue
            seen_events.add(ident)
            applied_elsewhere = str(it.get("applied_in_id_pago") or "").strip()
            if applied_elsewhere and applied_elsewhere not in lot_id_pagos:
                it["conciliation_cash"] = 0.0
                it["conciliation_cash_note"] = "aplicado_en_otro_lote"
                continue
            cash = _item_cash(it)
            if cash is None and unresolved_cash_fn is not None:
                cash = await unresolved_cash_fn(it)
            if cash is None:
                unresolved = True
                continue
            it["conciliation_cash"] = float(cash)
            cash_by_date[p.fecha_banco] = cash_by_date.get(p.fecha_banco, Decimal("0.00")) + cash
        if unresolved:
            groups_out.append({**base, "status": "PENDING_OTHER_PROBLEMS", "dates": []})
            continue

        dates_out: list[dict[str, Any]] = []
        group_problems: list[dict[str, Any]] = []
        exceeded = [d for d in bank_by_date if cash_by_date[d] > bank_by_date[d]]
        if exceeded and group.date_assigned:
            problem = {
                **base,
                "problem_id": f"{ASIENTOS_REQUIEREN_ASIGNACION}|{group.key}",
                "code": ASIENTOS_REQUIEREN_ASIGNACION,
                "credits_affected": list(group.credits),
                "fechas_banco": sorted(bank_by_date),
                "confirmable": False,
                "excludable": True,
            }
            group_problems.append(problem)
        for fecha in sorted(bank_by_date):
            bank = bank_by_date[fecha]
            cash = cash_by_date.get(fecha, Decimal("0.00"))
            diff = bank - cash
            key = conciliation_key(group.key, fecha)
            entry = {
                "fecha_banco": fecha,
                "monto_banco": _fmt_money(bank),
                "monto_asientos": _fmt_money(cash),
                "diferencia": _fmt_money(diff),
                "conciliation_key": key,
            }
            if diff == 0:
                entry["status"] = "OK"
            elif diff > 0:
                conf = find_confirmation(registry, key=key, monto_banco=bank, monto_asientos=cash)
                if conf is not None:
                    entry["status"] = "CONFIRMED"
                    confirmed.append(
                        {
                            **base,
                            **entry,
                            "monto_sin_aplicar": _fmt_money(diff),
                            "confirmation_id": str(conf.get("confirmation_id") or ""),
                            "nota": str(conf.get("nota") or ""),
                            "locked": bool(conf.get("locked_at")),
                        }
                    )
                else:
                    entry["status"] = "BANK_GREATER"
                    group_problems.append(
                        {
                            **base,
                            **entry,
                            "problem_id": f"{CONCILIACION_BANCO_MAYOR_ASIENTOS}|{key}",
                            "code": CONCILIACION_BANCO_MAYOR_ASIENTOS,
                            "monto_sin_aplicar": _fmt_money(diff),
                            "confirmable": True,
                            "excludable": True,
                        }
                    )
            else:
                entry["status"] = "ASIENTOS_GREATER"
                if not group.date_assigned:
                    group_problems.append(
                        {
                            **base,
                            **entry,
                            "problem_id": f"{CONCILIACION_ASIENTOS_MAYOR_BANCO}|{key}",
                            "code": CONCILIACION_ASIENTOS_MAYOR_BANCO,
                            "confirmable": False,
                            "excludable": True,
                        }
                    )
            dates_out.append(entry)

        if any(p["code"] == ASIENTOS_REQUIEREN_ASIGNACION for p in group_problems):
            group_problems = [p for p in group_problems if p["code"] == ASIENTOS_REQUIEREN_ASIGNACION]
        for it in group_items:
            _clear_superseded_advisory(it)
        if group_problems:
            problems.extend(group_problems)
            _block_group(group_items, payments, abono_by_pago, group_problems[0])
            groups_out.append({**base, "status": "PROBLEM", "dates": dates_out})
        else:
            groups_out.append({**base, "status": "OK", "dates": dates_out})

    planned_lines, planned_tables = _planned_summary(items)
    return {
        "enabled": True,
        "groups": groups_out,
        "problems": problems,
        "confirmed": confirmed,
        "excluded": excluded,
        "excluded_credits": sorted({e["credito"] for e in excluded}, key=_sort_token),
        "credit_groups": credit_groups,
        "covered_payments": sorted({p for p, _ in model.covered_pairs}),
        "covered_pairs": [{"id_pago": p, "credito": c} for p, c in sorted(model.covered_pairs)],
        "shared_asientos": model.shared_asientos,
        "planned_lines": planned_lines,
        "planned_tables": planned_tables,
        "planned_by_credit": _planned_by_credit(items),
    }


def _sort_token(tok: str) -> tuple[int, int | str]:
    return (0, int(tok)) if tok.isdigit() else (1, tok)


def _item_cash(item: dict[str, Any]) -> Decimal | None:
    codes = item.get("detected_codes")
    if not isinstance(codes, list) or not codes:
        return None
    pa = item.get("payment_application") or {}
    return cash_from_parsed(codes, pa.get("valor_pagado_cliente"))


def _block_group(
    group_items: list[dict[str, Any]],
    payments: list[LotPayment],
    abono_by_pago: dict[str, list[dict[str, Any]]],
    problem: dict[str, Any],
) -> None:
    for it in group_items:
        _mark_item_blocked(it, problem["code"], problem["problem_id"])
    for p in payments:
        for gr in abono_by_pago.get(p.id_pago, []):
            gr["group_ready_for_apply"] = False
            gr["reconciliation_status"] = "FAILED"
            errors = list(gr.get("blocking_errors") or [])
            errors.append(
                {
                    "error_code": problem["code"],
                    "message": "Conciliación del grupo pendiente",
                    "id_pago": p.id_pago,
                    "creditos_seleccionados": list(problem.get("credits") or []),
                    "conciliation_problem_id": problem["problem_id"],
                }
            )
            gr["blocking_errors"] = errors


def _planned_status(item: dict[str, Any]) -> str:
    return str(item.get("pre_conciliation_status") or item.get("application_status") or "")


def _planned_summary(items: list[dict[str, Any]]) -> tuple[int, int]:
    lines = 0
    tables: set[str] = set()
    for it in items:
        if _planned_status(it) in ("WOULD_APPLY", "WOULD_ADOPT_EXISTING") and (
            not it.get("error_code") or it.get("error_code") in CONCILIATION_CODES
        ):
            lines += 1
            tabla = normalize_sharepoint_path(str(it.get("tabla_amortizacion_path") or ""))
            if tabla:
                tables.add(tabla)
    return lines, len(tables)


def _planned_by_credit(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for it in items:
        if _planned_status(it) not in ("WOULD_APPLY", "WOULD_ADOPT_EXISTING"):
            continue
        if it.get("error_code") and it.get("error_code") not in CONCILIATION_CODES:
            continue
        tok = credit_token(it.get("credito"))
        if not tok:
            continue
        entry = out.setdefault(tok, {"lines": 0, "tables": []})
        entry["lines"] += 1
        tabla = str(it.get("tabla_amortizacion_path") or "").strip().strip("/")
        if tabla and tabla not in entry["tables"]:
            entry["tables"].append(tabla)
    return out


def completeness_waived_pairs(conciliation: dict[str, Any] | None) -> set[tuple[str, str]]:
    """Pares (ID Pago, crédito) cuyo asiento quedó asignado a otro pago del grupo."""
    if not isinstance(conciliation, dict):
        return set()
    out: set[tuple[str, str]] = set()
    for pair in conciliation.get("covered_pairs") or []:
        if isinstance(pair, dict):
            out.add((str(pair.get("id_pago") or ""), credit_token(pair.get("credito"))))
    return out


def completeness_excluded_pairs(conciliation: dict[str, Any] | None) -> set[tuple[str, str]]:
    """Pares (ID Pago, crédito) de créditos excluidos por el operador."""
    if not isinstance(conciliation, dict):
        return set()
    out: set[tuple[str, str]] = set()
    for entry in conciliation.get("excluded") or []:
        if not isinstance(entry, dict):
            continue
        tok = credit_token(entry.get("credito"))
        for id_pago in entry.get("id_pagos") or []:
            out.add((str(id_pago or ""), tok))
    return out
