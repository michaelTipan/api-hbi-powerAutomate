"""Verificación de fase 3 (Consolidar): lee los asientos y dice qué créditos están listos.

Módulo puro (sin Graph). Recibe los pagos del histórico, los asientos leídos de cada
carpeta, la cuota/saldo de la tabla (solo lectura) y el registro de decisiones del
proceso, y devuelve un resumen por grupo de créditos.

Reglas (las mismas de la fase 4, para que las decisiones se compartan):

* Grupo = pagos (ID Pago) que comparten crédito. Clave del grupo y clave de conciliación
  (grupo + fecha de pago) iguales a las de la fase 4.
* Dinero del asiento = línea de banco solo si el asiento la trae (``cash_from_parsed``).
* Cuadre por (grupo, fecha de pago) en pesos exactos: igual → listo; asientos < banco →
  «Continuar con los asientos»; asientos > banco → problema.
* Un asiento cuyo crédito puede ir a pagos de varias fechas se asigna solo si su fecha
  coincide con la de uno de esos pagos (igual que fase 4); si no, «Asignar asientos a sus
  pagos». El monto nunca asigna solo: la propuesta se muestra y el usuario confirma.
* Tipo según asientos: solo grupos de un pago y un crédito con tipo de la familia PAGO
  (cambiar de familia cambiaría cómo se amortiza). Comparación con la cuota/saldo de la
  tabla con tolerancia de redondeo de $1 (los asientos se contabilizan en pesos enteros).
"""
from __future__ import annotations

import itertools
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from app.application.services.amortization_decisions import (
    active_exclusions,
    conciliation_key,
    credit_token,
    exclusion_for_credit,
    find_confirmation,
    group_assignments,
    group_key_for_credits,
    tipo_correction_for_pago,
    unused_asientos,
)
from app.application.services.historical_application_rows import _policy_fields_from_row
from app.application.services.lot_conciliation import cash_from_parsed, cents
from app.application.services.review_schema import (
    TipoAplicacion,
    TipoAplicacionConfirmado,
    resolve_policy_from_tipo_confirmado,
)
from app.application.use_cases.merge_composite_validado_pdfs import (
    _group_meta_from_rows,
    _ruta_asientos_from_cell,
    normalize_sharepoint_path,
)

FALTA_ASIENTO = "FALTA_ASIENTO"
ASIENTO_OTRO_CREDITO = "ASIENTO_OTRO_CREDITO"
ASIENTO_PAGO_ANTERIOR = "ASIENTO_PAGO_ANTERIOR"
DIFERENCIA_BANCO = "DIFERENCIA_BANCO"
CONFIRMAR_TIPO = "CONFIRMAR_TIPO"
ASIGNAR_ASIENTOS = "ASIGNAR_ASIENTOS"
ASIENTO_ILEGIBLE = "ASIENTO_ILEGIBLE"
FALTA_EXTRACTO = "FALTA_EXTRACTO"
FALTA_DOCUMENTO = "FALTA_DOCUMENTO"

MOTIVO_LABELS: dict[str, str] = {
    FALTA_ASIENTO: "Falta el asiento",
    ASIENTO_OTRO_CREDITO: "Asiento de otro crédito",
    ASIENTO_PAGO_ANTERIOR: "Asiento de un pago anterior",
    DIFERENCIA_BANCO: "Diferencia con el banco",
    CONFIRMAR_TIPO: "Confirmar tipo",
    ASIGNAR_ASIENTOS: "Asignar asientos a sus pagos",
    ASIENTO_ILEGIBLE: "Asiento ilegible",
    FALTA_EXTRACTO: "Falta el extracto",
    FALTA_DOCUMENTO: "Falta un documento",
}

_MISSING_CODE_MOTIVO: dict[str, str] = {
    "asiento_contable_not_found": FALTA_ASIENTO,
    "missing_ruta_asientos_contables": FALTA_ASIENTO,
    "document_missing": FALTA_ASIENTO,
    "asiento_contable_credit_mismatch": ASIENTO_OTRO_CREDITO,
    "PDF_TEXT_NOT_EXTRACTABLE": ASIENTO_ILEGIBLE,
    "ACCOUNTING_PARSE_FAILED": ASIENTO_ILEGIBLE,
    "MISSING_BANK_VALUE_BUT_HAS_ACCOUNTING_LINES": ASIENTO_ILEGIBLE,
    "asiento_download_failed": ASIENTO_ILEGIBLE,
    "extract_routes_missing": FALTA_EXTRACTO,
}

STATE_USABLE = "usable"
STATE_SIN_DATOS = "sin_datos"
STATE_OTRO_CREDITO = "otro_credito"
STATE_PAGO_ANTERIOR = "pago_anterior"
STATE_YA_APLICADO = "ya_aplicado"
STATE_NO_USADO = "no_usado"
STATE_ILEGIBLE = "ilegible"

_COUNTED_STATES = frozenset({STATE_USABLE})
# Un PDF con el mismo nombre que uno de PROCESADOS no se consolida (igual que el job de
# merge): se muestra en gris y no bloquea.
_BLOCKING_STATES = {
    STATE_OTRO_CREDITO: ASIENTO_OTRO_CREDITO,
    STATE_PAGO_ANTERIOR: ASIENTO_PAGO_ANTERIOR,
    STATE_ILEGIBLE: ASIENTO_ILEGIBLE,
}

ASSIGNMENT_COMBINATIONS_MAX = 50_000
TIPO_ROUNDING_TOLERANCE = Decimal("1.00")
_ZERO = Decimal("0.00")

_RE_RAD = re.compile(r"No\.?\s*Rad\.?\s*:?\s*(\d+)", flags=re.IGNORECASE)

# Partes de cada tipo confirmado (familia PAGO) para comparar con los asientos.
_MORA, _CUOTA, _CAPITAL, _TOTAL = "mora", "cuota", "capital", "total"
_TIPO_PARTS: dict[str, frozenset[str]] = {
    TipoAplicacionConfirmado.PAGO_OBLIGACION_ACTUAL: frozenset({_CUOTA}),
    TipoAplicacionConfirmado.APLICACION_SALDO_VENCIDO: frozenset({_MORA}),
    TipoAplicacionConfirmado.PAGO_COMBINADO: frozenset({_MORA, _CUOTA}),
    TipoAplicacionConfirmado.PAGO_Y_ABONO_CAPITAL: frozenset({_CUOTA, _CAPITAL}),
    TipoAplicacionConfirmado.PAGO_COMBINADO_Y_ABONO_CAPITAL: frozenset({_MORA, _CUOTA, _CAPITAL}),
    TipoAplicacionConfirmado.CANCELACION_PAGO_TOTAL: frozenset({_TOTAL}),
}
PAGO_FAMILY_OPTIONS: tuple[str, ...] = tuple(
    t for t in TipoAplicacionConfirmado.OPTIONS_ORDERED if t in _TIPO_PARTS
)


@dataclass
class AsientoRead:
    """Un PDF de la carpeta ASIENTOS de un crédito, ya leído (o no legible)."""

    credito: str
    path: str
    name: str
    web_url: str = ""
    processed: bool = False
    processed_at: str = ""
    format_error: str = ""
    events: list[dict[str, Any]] | None = None


@dataclass
class _Payment:
    id_pago: str
    familia: str
    cliente: str
    fecha: str
    monto: Decimal | None
    tipo: str
    tipo_declarado: str
    concepto: str
    credits: list[str] = field(default_factory=list)
    labels: dict[str, str] = field(default_factory=dict)
    tablas: dict[str, str] = field(default_factory=dict)
    limites: dict[str, str] = field(default_factory=dict)
    folders: dict[str, str] = field(default_factory=dict)


# --- lectura de asientos ------------------------------------------------------------


def rad_credits_from_text(text: str) -> list[str]:
    out: list[str] = []
    for m in _RE_RAD.finditer(text or ""):
        tok = credit_token(m.group(1))
        if tok and tok not in out:
            out.append(tok)
    return out


def event_facts(event: Any) -> dict[str, Any]:
    """Datos de un asiento (``PaymentApplicationEvent``) que usa la verificación."""
    fecha = getattr(event, "fecha_asiento", None)
    codes = tuple(getattr(event, "detected_codes", ()) or ())
    return {
        "numero": str(getattr(event, "numero_asiento", "") or getattr(event, "comprobante", "") or ""),
        "fecha": fecha.isoformat() if isinstance(fecha, date) else "",
        "cash": cash_from_parsed(codes, getattr(event, "valor_pagado_cliente", 0)),
        "capital": cents(getattr(event, "capital", 0)) or _ZERO,
        "intereses": cents(getattr(event, "intereses", 0)) or _ZERO,
        "mora": cents(getattr(event, "mora", 0)) or _ZERO,
        "retenciones": cents(getattr(event, "retenciones", 0)) or _ZERO,
        "saldos_menores": cents(getattr(event, "saldos_menores", 0)) or _ZERO,
        "rad_credits": rad_credits_from_text(str(getattr(event, "raw_text", "") or "")),
    }


# --- tipo corregido -----------------------------------------------------------------


def override_row_tipo(row: dict[str, Any], tipo_nuevo: str) -> dict[str, Any]:
    """Fila con el tipo usado para el consolidado; nunca cambia de familia PAGO/ABONO."""
    try:
        policy = resolve_policy_from_tipo_confirmado(tipo_nuevo)
    except ValueError:
        return row
    if policy.tipo_aplicacion_canonica != row.get("tipo_aplicacion"):
        return row
    out = dict(row)
    out.update(_policy_fields_from_row(policy))
    out["tipo_aplicacion_declarado"] = row.get("tipo_aplicacion_declarado") or row.get(
        "tipo_aplicacion_original"
    )
    return out


def apply_tipo_corrections(
    all_groups: list[tuple[str, str, list[dict[str, Any]]]],
    registry: dict[str, Any] | None,
) -> list[tuple[str, str, list[dict[str, Any]]]]:
    out: list[tuple[str, str, list[dict[str, Any]]]] = []
    for id_pago, familia, rows in all_groups:
        corr = tipo_correction_for_pago(registry, str(id_pago)) if registry else None
        if corr is not None:
            rows = [override_row_tipo(r, str(corr.get("tipo_nuevo") or "")) for r in rows]
        out.append((id_pago, familia, rows))
    return out


# --- pagos y grupos -----------------------------------------------------------------


def _iso(value: Any) -> str:
    if isinstance(value, date):
        return value.isoformat()
    text = str(value or "").strip()
    return text[:10] if re.match(r"^\d{4}-\d{2}-\d{2}", text) else ""


def build_payments(all_groups: list[tuple[str, str, list[dict[str, Any]]]]) -> list[_Payment]:
    payments: list[_Payment] = []
    for id_pago, familia, rows in all_groups:
        cliente, monto, fecha, _ = _group_meta_from_rows(rows, tipo_aplicacion=familia)
        ref = rows[0] if rows else {}
        tipo = str(ref.get("tipo_aplicacion_original") or "").strip()
        p = _Payment(
            id_pago=str(id_pago),
            familia=familia,
            cliente=cliente,
            fecha=_iso(fecha),
            monto=cents(monto),
            tipo=tipo,
            tipo_declarado=str(ref.get("tipo_aplicacion_declarado") or tipo).strip(),
            concepto=str(ref.get("observacion") or "").strip(),
        )
        for row in rows:
            tok = credit_token(row.get("credito_digits") or row.get("credito_label"))
            if not tok:
                continue
            if tok not in p.credits:
                p.credits.append(tok)
            p.labels.setdefault(tok, str(row.get("credito_label") or tok).strip() or tok)
            tabla = str(row.get("ruta_tabla_amortizacion") or "").strip().strip("/")
            if tabla:
                p.tablas.setdefault(tok, tabla)
            limite = _iso(row.get("fecha_limite"))
            if limite:
                p.limites.setdefault(tok, limite)
            folder = _ruta_asientos_from_cell(row.get("ruta_asientos_cell"))
            if folder:
                p.folders.setdefault(tok, folder)
        payments.append(p)
    return payments


def _group_payments(payments: list[_Payment]) -> list[list[_Payment]]:
    parent = list(range(len(payments)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    first: dict[str, int] = {}
    for i, p in enumerate(payments):
        for tok in p.credits:
            if tok in first:
                a, b = find(first[tok]), find(i)
                if a != b:
                    parent[max(a, b)] = min(a, b)
            else:
                first[tok] = i
    members: dict[int, list[_Payment]] = {}
    for i, p in enumerate(payments):
        members.setdefault(find(i), []).append(p)
    return [members[k] for k in sorted(members)]


def _sort_token(tok: str) -> tuple[int, int | str]:
    return (0, int(tok)) if tok.isdigit() else (1, tok)


def excluded_id_pagos(
    all_groups: list[tuple[str, str, list[dict[str, Any]]]],
    registry: dict[str, Any] | None,
) -> set[str]:
    """ID Pago de los grupos con algún crédito excluido (el grupo sale completo)."""
    if not registry or not active_exclusions(registry):
        return set()
    out: set[str] = set()
    for group in _group_payments(build_payments(all_groups)):
        credits = {tok for p in group for tok in p.credits}
        if any(exclusion_for_credit(registry, tok) is not None for tok in credits):
            out.update(p.id_pago for p in group)
    return out


def table_fact_requests(
    all_groups: list[tuple[str, str, list[dict[str, Any]]]],
) -> dict[str, tuple[str, str]]:
    """Créditos a los que se les compara el tipo: {crédito: (tabla, fecha límite ISO)}."""
    out: dict[str, tuple[str, str]] = {}
    for group in _group_payments(build_payments(all_groups)):
        if len(group) != 1 or len(group[0].credits) != 1:
            continue
        p = group[0]
        if p.tipo not in _TIPO_PARTS:
            continue
        tok = p.credits[0]
        tabla, limite = p.tablas.get(tok, ""), p.limites.get(tok, "")
        if tabla and limite:
            out[tok] = (tabla, limite)
    return out


# --- evaluación ---------------------------------------------------------------------


def _money(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def _fmt_ddmm(iso: str) -> str:
    return f"{iso[8:10]}/{iso[5:7]}" if len(iso) >= 10 else ""


def _norm(path: str) -> str:
    return normalize_sharepoint_path(path) or str(path or "").strip().strip("/").casefold()


def _asiento_fecha(a: AsientoRead) -> str:
    fechas = [e["fecha"] for e in a.events or [] if e.get("fecha")]
    return max(fechas) if fechas else ""


def _asiento_cash(a: AsientoRead) -> Decimal | None:
    if a.events is None:
        return None
    return sum((e["cash"] for e in a.events), _ZERO)


def _sum(a: AsientoRead, key: str) -> Decimal:
    return sum((e.get(key) or _ZERO for e in a.events or []), _ZERO)


def _asiento_state(a: AsientoRead, unused: dict[str, dict[str, Any]], lot_min_fecha: str) -> str:
    if _norm(a.path) in unused:
        return STATE_NO_USADO
    if a.format_error:
        return STATE_ILEGIBLE
    if a.processed:
        return STATE_YA_APLICADO
    if a.events is None:
        return STATE_SIN_DATOS
    rads = [r for e in a.events for r in e.get("rad_credits") or []]
    if rads and credit_token(a.credito) not in rads:
        return STATE_OTRO_CREDITO
    fecha = _asiento_fecha(a)
    if fecha and lot_min_fecha and fecha < lot_min_fecha:
        return STATE_PAGO_ANTERIOR
    return STATE_USABLE


def _state_label(state: str, a: AsientoRead) -> str:
    if state == STATE_YA_APLICADO:
        ddmm = _fmt_ddmm(a.processed_at)
        return f"Ya aplicado el {ddmm}" if ddmm else "Ya aplicado"
    return {
        STATE_OTRO_CREDITO: "Asiento de otro crédito",
        STATE_PAGO_ANTERIOR: "Asiento de un pago anterior",
        STATE_NO_USADO: "No corresponde a este pago",
        STATE_ILEGIBLE: "No se pudo leer el PDF",
    }.get(state, "")


def _payment_label(p: _Payment) -> str:
    monto = f"${int(p.monto):,}".replace(",", ".") if p.monto is not None else "$—"
    return f"{_fmt_ddmm(p.fecha)} · {monto}"


def _eligible(group: list[_Payment], a: AsientoRead) -> list[_Payment]:
    tok = credit_token(a.credito)
    cands = [p for p in group if tok in p.credits]
    fecha = _asiento_fecha(a)
    if fecha:
        cands = [p for p in cands if p.fecha and p.fecha <= fecha]
    return cands


def _preferred(cands: list[_Payment]) -> _Payment:
    latest = max(p.fecha for p in cands)
    same = [p for p in cands if p.fecha == latest]
    for p in same:
        if p.familia != TipoAplicacion.ABONO.value:
            return p
    return same[0]


def propose_assignment(
    group: list[_Payment], asientos: list[AsientoRead]
) -> tuple[dict[str, str], bool, bool]:
    """Propuesta asiento→pago: (propuesta por path, empate, imposible).

    Exacta si existe única; si no, la de menor faltante sin excesos. Empate → sin
    propuesta. Los asientos sin dinero (saldos menores, retención sin recaudo) van al
    pago elegible más reciente (no cambian el cuadre).
    """
    eligible = {a.path: _eligible(group, a) for a in asientos}
    if any(not c for c in eligible.values()):
        return {}, False, True
    zero = [a for a in asientos if (_asiento_cash(a) or _ZERO) == 0]
    money_ones = [a for a in asientos if (_asiento_cash(a) or _ZERO) > 0]
    fixed = {a.path: _preferred(eligible[a.path]).id_pago for a in zero}
    if not money_ones:
        return fixed, False, False
    total = 1
    for a in money_ones:
        total *= len(eligible[a.path])
        if total > ASSIGNMENT_COMBINATIONS_MAX:
            return {}, False, False
    bank = {p.id_pago: p.monto or _ZERO for p in group}
    best: Decimal | None = None
    best_combos: list[tuple[str, ...]] = []
    for combo in itertools.product(*[[p.id_pago for p in eligible[a.path]] for a in money_ones]):
        assigned: dict[str, Decimal] = {}
        for a, pid in zip(money_ones, combo):
            assigned[pid] = assigned.get(pid, _ZERO) + (_asiento_cash(a) or _ZERO)
        if any(v > bank.get(pid, _ZERO) for pid, v in assigned.items()):
            continue
        short = sum((bank[pid] - assigned.get(pid, _ZERO) for pid in bank), _ZERO)
        if best is None or short < best:
            best, best_combos = short, [combo]
        elif short == best:
            best_combos.append(combo)
    if best is None:
        return {}, False, True
    if len(best_combos) > 1:
        return {}, True, False
    proposal = dict(fixed)
    proposal.update({a.path: pid for a, pid in zip(money_ones, best_combos[0])})
    return proposal, False, False


def _explicit_for_group(
    registry: dict[str, Any] | None, group_key: str, group: list[_Payment], usable: list[AsientoRead]
) -> dict[str, str] | None:
    entries = group_assignments(registry, group_key)
    if not entries:
        return None
    by_path = {_norm(str(e.get("asiento_pdf_path") or "")): str(e.get("id_pago") or "") for e in entries}
    out: dict[str, str] = {}
    for a in usable:
        pid = by_path.get(_norm(a.path))
        if not pid or pid not in {p.id_pago for p in _eligible(group, a)}:
            return None
        out[a.path] = pid
    return out


def _resolve_targets(
    group: list[_Payment],
    usable: list[AsientoRead],
    registry: dict[str, Any] | None,
    group_key: str,
    assignment: dict[str, Any],
) -> dict[str, str]:
    """Asiento (path) → ID Pago. Marca ``required``/``explicit`` en ``assignment``.

    Con ``required`` devuelve {} (el operador debe asignar en «Asignar»).
    """
    by_id = {p.id_pago: p for p in group}
    shared_multi = [
        a
        for a in usable
        if len({p.fecha for p in group if credit_token(a.credito) in p.credits}) > 1
    ]
    explicit = _explicit_for_group(registry, group_key, group, usable) if shared_multi else None
    if explicit is not None:
        assignment["explicit"] = True
        locked = any(e.get("locked_at") for e in group_assignments(registry, group_key))
        assignment["can_undo"] = not locked
        return explicit
    target: dict[str, str] = {}
    for a in usable:
        cands = [p for p in group if credit_token(a.credito) in p.credits]
        cand_dates = {p.fecha for p in cands}
        if len(cand_dates) == 1:
            target[a.path] = _preferred(cands).id_pago
            continue
        fecha = _asiento_fecha(a)
        matches = [p for p in cands if p.fecha == fecha]
        if matches:
            target[a.path] = _preferred(matches).id_pago
        else:
            assignment["required"] = True
    if not assignment["required"] and shared_multi:
        bank_d: dict[str, Decimal] = {}
        cash_d: dict[str, Decimal] = {}
        for p in group:
            bank_d[p.fecha] = bank_d.get(p.fecha, _ZERO) + (p.monto or _ZERO)
        for a in usable:
            f = by_id[target[a.path]].fecha
            cash_d[f] = cash_d.get(f, _ZERO) + (_asiento_cash(a) or _ZERO)
        if any(cash_d.get(f, _ZERO) > bank_d[f] for f in bank_d):
            assignment["required"] = True
    return {} if assignment["required"] else target


def group_payments(payments: list[_Payment]) -> list[list[_Payment]]:
    """Grupos de pagos que comparten crédito (misma regla que la fase 4)."""
    return _group_payments(payments)


def group_key_of(group: list[_Payment]) -> str:
    credits = sorted({tok for p in group for tok in p.credits}, key=_sort_token)
    return group_key_for_credits(credits) or f"pago:{group[0].id_pago}"


def group_needs_asiento_dates(group: list[_Payment]) -> bool:
    """True si algún crédito del grupo tiene pagos de más de una fecha."""
    credits = {tok for p in group for tok in p.credits}
    return any(len({p.fecha for p in group if tok in p.credits}) > 1 for tok in credits)


def single_date_target(group: list[_Payment], credito: str) -> str:
    """Pago al que va un asiento cuando su crédito tiene una sola fecha de pago."""
    cands = [p for p in group if credit_token(credito) in p.credits]
    return _preferred(cands).id_pago if cands else ""


def consolidation_targets(
    group: list[_Payment],
    usable: list[AsientoRead],
    registry: dict[str, Any] | None,
) -> dict[str, str] | None:
    """Asignación asiento → ID Pago para consolidar un grupo de varias fechas.

    Misma decisión que muestra «Verificar»: asignación del operador si cubre todos los
    asientos; si no, automática por fecha sin exceder ningún pago. None si falta
    asignar (o no se pueden leer montos/fechas).
    """
    if not usable:
        return {}
    evaluable = all(a.events is not None for a in usable) and all(
        p.fecha and p.monto is not None and p.monto > 0 for p in group
    )
    if not evaluable:
        return None
    assignment: dict[str, Any] = {"required": False, "explicit": False, "can_undo": False}
    target = _resolve_targets(group, usable, registry, group_key_of(group), assignment)
    if assignment["required"]:
        return None
    return target


def consolidados_count(groups_out: list[dict[str, Any]]) -> int:
    """Un consolidado por (grupo, fecha de pago) de los grupos no excluidos."""
    return sum(
        len({c.get("fecha") or "" for c in g.get("consignaciones") or []})
        for g in groups_out
        if g.get("status") != "excluded"
    )


def _detect_tipo(
    p: _Payment, usable: list[AsientoRead], facts: dict[str, Any] | None
) -> tuple[frozenset[str] | None, str | None]:
    """Partes según los asientos y el tipo sugerido (None si coincide o no hay certeza)."""
    declared = _TIPO_PARTS.get(p.tipo_declarado) or _TIPO_PARTS.get(p.tipo)
    if declared is None or _TOTAL in declared:
        return None, None
    capital = sum((_sum(a, "capital") for a in usable), _ZERO)
    intereses = sum((_sum(a, "intereses") for a in usable), _ZERO)
    mora = sum((_sum(a, "mora") for a in usable), _ZERO)
    parts = set(declared)
    if mora > 0:
        parts.add(_MORA)
    elif _MORA in parts and intereses > 0:
        parts.discard(_MORA)
        parts.add(_CUOTA)
    cuota = (facts or {}).get("cuota")
    if isinstance(cuota, Decimal) and cuota > 0 and _CAPITAL not in parts:
        if capital + intereses > cuota + TIPO_ROUNDING_TOLERANCE:
            parts.add(_CAPITAL)
    saldo = (facts or {}).get("saldo_capital")
    if isinstance(saldo, Decimal) and saldo > 0 and capital + TIPO_ROUNDING_TOLERANCE >= saldo:
        parts = {_TOTAL}
    detected = frozenset(parts)
    if detected == declared:
        return detected, None
    sugerido = next((t for t, tp in _TIPO_PARTS.items() if tp == detected), None)
    return detected, sugerido or ""


def _tipo_options(declared: str, sugerido: str, detected: frozenset[str]) -> list[str]:
    wanted = {declared}
    if sugerido:
        wanted.add(sugerido)
    for t, tp in _TIPO_PARTS.items():
        if tp & detected:
            wanted.add(t)
    return [t for t in PAGO_FAMILY_OPTIONS if t in wanted]


def evaluate_verification(
    all_groups: list[tuple[str, str, list[dict[str, Any]]]],
    *,
    asientos: list[AsientoRead],
    missing_items: list[dict[str, Any]],
    registry: dict[str, Any] | None,
    table_facts: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Resumen por grupo. ``all_groups`` ya trae aplicado el tipo corregido."""
    payments = build_payments(all_groups)
    unused = {_norm(str(u.get("path") or "")): u for u in unused_asientos(registry)}
    lot_fechas = [p.fecha for p in payments if p.fecha]
    lot_min_fecha = min(lot_fechas) if lot_fechas else ""
    by_credit: dict[str, list[AsientoRead]] = {}
    seen_paths: set[str] = set()
    for a in asientos:
        key = _norm(a.path)
        if key in seen_paths:
            continue
        seen_paths.add(key)
        by_credit.setdefault(credit_token(a.credito), []).append(a)
    missing_by_pago: dict[str, list[dict[str, Any]]] = {}
    for item in missing_items:
        missing_by_pago.setdefault(str(item.get("id_pago") or ""), []).append(item)

    groups_out: list[dict[str, Any]] = []
    for group in _group_payments(payments):
        groups_out.append(
            _evaluate_group(
                group,
                by_credit=by_credit,
                missing_by_pago=missing_by_pago,
                registry=registry,
                unused=unused,
                lot_min_fecha=lot_min_fecha,
                table_facts=table_facts or {},
            )
        )

    credits_total = sum(len(g["credits"]) for g in groups_out)
    excluded = [g for g in groups_out if g["status"] == "excluded"]
    ready = [g for g in groups_out if g["status"] == "ready"]
    attention = [g for g in groups_out if g["status"] == "attention"]
    return {
        "groups": groups_out,
        "credits_total": credits_total,
        "credits_ready": sum(len(g["credits"]) for g in ready),
        "credits_excluded": sum(len(g["credits"]) for g in excluded),
        "credits_attention": sum(len(g["credits"]) for g in attention),
        "consolidados": consolidados_count(groups_out),
        "excluded": [
            {
                "credito": tok,
                "cliente": g["clientes"].get(tok, ""),
                "motivo": (g["exclusion"] or {}).get("motivo", ""),
            }
            for g in excluded
            for tok in g["credits"]
        ],
        "all_excluded": bool(groups_out) and len(excluded) == len(groups_out),
        "unused_asientos": [
            {
                "path": str(u.get("path") or ""),
                "credito": str(u.get("credito_carpeta") or ""),
                "motivo": str(u.get("motivo") or u.get("nota") or ""),
                "can_undo": not u.get("locked_at"),
            }
            for u in unused_asientos(registry)
        ],
        "active_exclusions": len(active_exclusions(registry)),
    }


def _evaluate_group(
    group: list[_Payment],
    *,
    by_credit: dict[str, list[AsientoRead]],
    missing_by_pago: dict[str, list[dict[str, Any]]],
    registry: dict[str, Any] | None,
    unused: dict[str, dict[str, Any]],
    lot_min_fecha: str,
    table_facts: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    credits: list[str] = []
    labels: dict[str, str] = {}
    clientes: dict[str, str] = {}
    tablas: dict[str, str] = {}
    folders: dict[str, str] = {}
    for p in group:
        for tok in p.credits:
            if tok not in credits:
                credits.append(tok)
            labels.setdefault(tok, p.labels.get(tok, tok))
            if p.cliente:
                clientes.setdefault(tok, p.cliente)
            if p.tablas.get(tok):
                tablas.setdefault(tok, p.tablas[tok])
            if p.folders.get(tok):
                folders.setdefault(tok, p.folders[tok])
    credits.sort(key=_sort_token)
    group_key = group_key_for_credits(credits) or f"pago:{group[0].id_pago}"
    base: dict[str, Any] = {
        "group_key": group_key,
        "credits": credits,
        "credit_labels": labels,
        "clientes": clientes,
        "cliente": next((c for c in clientes.values() if c), ""),
        "tablas": tablas,
        "folders": [{"credito": tok, "path": folders[tok]} for tok in credits if folders.get(tok)],
        "consignaciones": [
            {
                "id_pago": p.id_pago,
                "fecha": p.fecha,
                "monto": _money(p.monto),
                "concepto": p.concepto,
                "tipo": p.tipo,
                "credits": list(p.credits),
                "label": _payment_label(p),
            }
            for p in sorted(group, key=lambda x: (x.fecha, x.id_pago))
        ],
    }
    consignado = sum((p.monto or _ZERO for p in group), _ZERO)
    base["consignado"] = _money(consignado)

    exclusion = next(
        (e for e in (exclusion_for_credit(registry, tok) for tok in credits) if e is not None),
        None,
    )
    if exclusion is not None:
        return {
            **base,
            "status": "excluded",
            "motivos": [],
            "primary_action": None,
            "segun_asientos": None,
            "pendiente": None,
            "asientos": [],
            "fechas": [],
            "assignment": None,
            "tipo": None,
            "exclusion": {
                "exclusion_id": str(exclusion.get("exclusion_id") or ""),
                "motivo": str(exclusion.get("motivo") or ""),
                "motivo_codigo": str(exclusion.get("motivo_codigo") or ""),
                "nota": str(exclusion.get("nota") or ""),
                "quien": str(exclusion.get("quien") or ""),
                "cuando": str(exclusion.get("cuando") or ""),
                "fase": str(exclusion.get("fase") or ""),
                "can_undo": not exclusion.get("locked_at"),
            },
            "actions": _actions(),
            "has_retenciones": False,
            "has_saldos_menores": False,
        }

    motivos: list[str] = []

    def add(code: str) -> None:
        if code not in motivos:
            motivos.append(code)

    for p in group:
        for item in missing_by_pago.get(p.id_pago, []):
            add(_MISSING_CODE_MOTIVO.get(str(item.get("error_code") or ""), FALTA_DOCUMENTO))

    rows: list[tuple[AsientoRead, str]] = []
    for tok in credits:
        for a in by_credit.get(tok, []):
            state = _asiento_state(a, unused, lot_min_fecha)
            rows.append((a, state))
            if state in _BLOCKING_STATES:
                add(_BLOCKING_STATES[state])
    usable = [a for a, s in rows if s in _COUNTED_STATES]
    unknown_amounts = any(s == STATE_SIN_DATOS for _, s in rows)
    segun = None if unknown_amounts else sum((_asiento_cash(a) or _ZERO for a in usable), _ZERO)

    by_id = {p.id_pago: p for p in group}
    dates = sorted({p.fecha for p in group if p.fecha})
    evaluable = not unknown_amounts and bool(usable) and all(
        p.fecha and p.monto is not None and p.monto > 0 for p in group
    )
    target: dict[str, str] = {}
    assignment: dict[str, Any] = {
        "required": False,
        "explicit": False,
        "proposal": {},
        "tie": False,
        "impossible": False,
        "payments": [
            {"id_pago": p.id_pago, "fecha": p.fecha, "monto": _money(p.monto), "label": _payment_label(p)}
            for p in sorted(group, key=lambda x: (x.fecha, x.id_pago))
        ],
        "can_undo": False,
    }
    if evaluable:
        target = _resolve_targets(group, usable, registry, group_key, assignment)
        if assignment["required"]:
            proposal, tie, impossible = propose_assignment(group, usable)
            assignment.update({"proposal": proposal, "tie": tie, "impossible": impossible})
            add(ASIGNAR_ASIENTOS)
        if group_assignments(registry, group_key) and not assignment["explicit"]:
            assignment["can_undo"] = not any(
                e.get("locked_at") for e in group_assignments(registry, group_key)
            )

    fechas_out: list[dict[str, Any]] = []
    if evaluable and target:
        bank_by_date: dict[str, Decimal] = {}
        for p in group:
            bank_by_date[p.fecha] = bank_by_date.get(p.fecha, _ZERO) + (p.monto or _ZERO)
        cash_by_date = {d: _ZERO for d in bank_by_date}
        for a in usable:
            f = by_id[target[a.path]].fecha
            cash_by_date[f] = cash_by_date.get(f, _ZERO) + (_asiento_cash(a) or _ZERO)
        for fecha in sorted(bank_by_date):
            bank, cash = bank_by_date[fecha], cash_by_date.get(fecha, _ZERO)
            diff = bank - cash
            key = conciliation_key(group_key, fecha)
            entry: dict[str, Any] = {
                "fecha": fecha,
                "monto_banco": _money(bank),
                "monto_asientos": _money(cash),
                "diferencia": _money(diff),
                "conciliation_key": key,
                "confirmation": None,
            }
            if diff == 0:
                entry["status"] = "OK"
            elif diff > 0:
                conf = find_confirmation(registry, key=key, monto_banco=bank, monto_asientos=cash)
                if conf is not None:
                    entry["status"] = "CONFIRMED"
                    entry["confirmation"] = {
                        "nota": str(conf.get("nota") or ""),
                        "quien": str(conf.get("quien") or ""),
                        "cuando": str(conf.get("cuando") or ""),
                        "can_undo": not conf.get("locked_at"),
                    }
                else:
                    entry["status"] = "BANK_GREATER"
                    add(DIFERENCIA_BANCO)
            else:
                entry["status"] = "ASIENTOS_GREATER"
                add(DIFERENCIA_BANCO)
            fechas_out.append(entry)

    tipo_out: dict[str, Any] | None = None
    if (
        evaluable
        and len(group) == 1
        and len(credits) == 1
        and not assignment["required"]
        and (group[0].tipo in _TIPO_PARTS or group[0].tipo_declarado in _TIPO_PARTS)
    ):
        p = group[0]
        corr = tipo_correction_for_pago(registry, p.id_pago)
        detected, sugerido = _detect_tipo(p, usable, table_facts.get(credits[0]))
        if corr is not None:
            tipo_out = {
                "id_pago": p.id_pago,
                "declarado": str(corr.get("tipo_anterior") or p.tipo_declarado),
                "actual": str(corr.get("tipo_nuevo") or p.tipo),
                "sugerido": sugerido or None,
                "opciones": [],
                "needed": False,
                "correction": {
                    "nota": str(corr.get("nota") or ""),
                    "quien": str(corr.get("quien") or ""),
                    "cuando": str(corr.get("cuando") or ""),
                    "can_undo": not corr.get("locked_at"),
                },
            }
        elif sugerido is not None and detected is not None:
            tipo_out = {
                "id_pago": p.id_pago,
                "declarado": p.tipo_declarado,
                "actual": p.tipo,
                "sugerido": sugerido or None,
                "opciones": _tipo_options(p.tipo_declarado, sugerido, detected),
                "needed": True,
                "correction": None,
            }
            add(CONFIRMAR_TIPO)

    asientos_out: list[dict[str, Any]] = []
    for a, state in rows:
        cash = _asiento_cash(a)
        eligible = _eligible(group, a) if state in _COUNTED_STATES else []
        unused_entry = unused.get(_norm(a.path))
        asientos_out.append(
            {
                "path": a.path,
                "name": a.name,
                "credito": credit_token(a.credito),
                "numero": ", ".join(e["numero"] for e in a.events or [] if e.get("numero")),
                "fecha": _asiento_fecha(a),
                "cash": _money(cash),
                "capital": _money(_sum(a, "capital")) if a.events is not None else None,
                "intereses": _money(_sum(a, "intereses")) if a.events is not None else None,
                "mora": _money(_sum(a, "mora")) if a.events is not None else None,
                "retenciones": _money(_sum(a, "retenciones")) if a.events is not None else None,
                "saldos_menores": _money(_sum(a, "saldos_menores")) if a.events is not None else None,
                "web_url": a.web_url,
                "state": state,
                "state_label": _state_label(state, a),
                "assigned_id_pago": target.get(a.path) if state in _COUNTED_STATES else None,
                "eligible_id_pagos": [p.id_pago for p in sorted(eligible, key=lambda x: (x.fecha, x.id_pago))],
                "can_mark_unused": state not in (STATE_NO_USADO, STATE_YA_APLICADO),
                "can_undo_unused": bool(unused_entry) and not (unused_entry or {}).get("locked_at"),
            }
        )

    has_ret = any((x.get("retenciones") or 0) > 0 for x in asientos_out)
    has_saldos = any((x.get("saldos_menores") or 0) > 0 for x in asientos_out)
    status = "attention" if motivos else "ready"
    primary = None
    if motivos:
        primary = "asignar" if ASIGNAR_ASIENTOS in motivos else "revisar"
    return {
        **base,
        "status": status,
        "motivos": [{"code": c, "label": MOTIVO_LABELS[c]} for c in motivos],
        "primary_action": primary,
        "segun_asientos": _money(segun),
        "pendiente": _money(consignado - segun) if segun is not None else None,
        "asientos": asientos_out,
        "fechas": fechas_out,
        "assignment": assignment,
        "tipo": tipo_out,
        "exclusion": None,
        "actions": _actions(
            continuar=any(f["status"] == "BANK_GREATER" for f in fechas_out),
            no_corresponde=any(x["can_mark_unused"] for x in asientos_out),
            asignar=bool(assignment["required"] or assignment["explicit"]),
            tipo=bool(tipo_out and tipo_out["needed"]),
            excluir=True,
        ),
        "has_retenciones": has_ret,
        "has_saldos_menores": has_saldos,
    }


def _actions(
    *,
    continuar: bool = False,
    no_corresponde: bool = False,
    asignar: bool = False,
    tipo: bool = False,
    excluir: bool = False,
) -> dict[str, bool]:
    return {
        "continuar": continuar,
        "no_corresponde": no_corresponde,
        "asignar": asignar,
        "tipo": tipo,
        "excluir": excluir,
    }


def find_group(verification: dict[str, Any] | None, credit: str) -> dict[str, Any] | None:
    tok = credit_token(credit)
    for g in (verification or {}).get("groups") or []:
        if tok in g.get("credits", []):
            return g
    return None


def find_group_by_key(verification: dict[str, Any] | None, group_key: str) -> dict[str, Any] | None:
    for g in (verification or {}).get("groups") or []:
        if g.get("group_key") == group_key:
            return g
    return None


__all__ = [
    "ASIGNAR_ASIENTOS",
    "AsientoRead",
    "CONFIRMAR_TIPO",
    "DIFERENCIA_BANCO",
    "MOTIVO_LABELS",
    "PAGO_FAMILY_OPTIONS",
    "apply_tipo_corrections",
    "build_payments",
    "consolidados_count",
    "consolidation_targets",
    "evaluate_verification",
    "event_facts",
    "excluded_id_pagos",
    "find_group",
    "find_group_by_key",
    "group_key_of",
    "group_needs_asiento_dates",
    "group_payments",
    "override_row_tipo",
    "propose_assignment",
    "rad_credits_from_text",
    "single_date_target",
    "table_fact_requests",
]
