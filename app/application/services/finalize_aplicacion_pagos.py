"""
Helpers de lectura/validación Finalize para schema v3 (Aplicacion_Pagos).
"""
from __future__ import annotations

import math
from typing import Any

from app.application.services.review_schema import (
    MONEY_EQ_TOLERANCE,
    AplicacionPagosCols,
    ValidarPago,
    is_validar_pago_si,
    money_eq,
    normalize_tipo_aplicacion_confirmado,
    normalize_validar_pago_value,
    require_tipo_aplicacion_confirmado,
    resolve_policy_from_tipo_confirmado,
)


class InvalidMonetaryValue(ValueError):
    """Monto editable no normalizable (no coerce a 0)."""

    def __init__(self, raw: Any, field: str | None = None) -> None:
        self.raw = raw
        self.field = field
        super().__init__("invalid_monetary_value")


def parse_editable_money(value: Any) -> float:
    """
    Vacío/None → 0 válido.
    Número finito >= 0 → válido.
    Texto normalizable (1.234,56 / 1234.56) → válido.
    Inválido / NaN / Inf / negativo → InvalidMonetaryValue (NO coerce 0).
    """
    if value is None:
        return 0.0
    if isinstance(value, bool):
        raise InvalidMonetaryValue(value)
    if isinstance(value, (int, float)):
        f = float(value)
        if not math.isfinite(f):
            raise InvalidMonetaryValue(value)
        if f < -MONEY_EQ_TOLERANCE:
            raise InvalidMonetaryValue(value)
        if f < 0:
            return 0.0
        return f
    s = str(value).strip()
    if not s:
        return 0.0
    s = s.replace("$", "").replace(" ", "")
    # Letra O en lugar de cero, etc.
    if any(c.isalpha() for c in s):
        raise InvalidMonetaryValue(value)
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        f = float(s)
    except ValueError as exc:
        raise InvalidMonetaryValue(value) from exc
    if not math.isfinite(f):
        raise InvalidMonetaryValue(value)
    if f < -MONEY_EQ_TOLERANCE:
        raise InvalidMonetaryValue(value)
    if f < 0:
        return 0.0
    return f


def _cell_filled(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str) and not value.strip():
        return False
    return True


def _issue(
    row: dict[str, Any],
    error_code: str,
    *,
    field: str | None = None,
    severity: str = "BLOCKER",
    **extra: Any,
) -> dict[str, Any]:
    issue: dict[str, Any] = {
        "error_code": error_code,
        "severity": severity,
        "excel_row": row.get("_excel_row"),
        "id_pago": str(row.get(AplicacionPagosCols.ID_PAGO) or "").strip(),
        "credito": str(row.get(AplicacionPagosCols.CREDITO) or "").strip(),
        "cliente": str(row.get(AplicacionPagosCols.CLIENTE) or "").strip(),
        "sheet": "Aplicacion_Pagos",
    }
    if field:
        issue["field"] = field
    issue.update(extra)
    return issue


def iter_aplicacion_pago_row_issues(row: dict[str, Any]) -> list[dict[str, Any]]:
    """Validaciones por fila (fail-closed). Observación nunca genera issue."""
    issues: list[dict[str, Any]] = []
    vp_raw = row.get(AplicacionPagosCols.VALIDAR_PAGO)
    vp = normalize_validar_pago_value(vp_raw)

    if not vp:
        issues.append(
            _issue(row, "invalid_validar_pago", field=AplicacionPagosCols.VALIDAR_PAGO, value_found=vp_raw)
        )
        return issues

    if vp == ValidarPago.POR_DEFINIR:
        issues.append(
            _issue(
                row,
                "validar_pago_por_definir",
                field=AplicacionPagosCols.VALIDAR_PAGO,
                user_message="Quedan filas con Validar Pago = POR DEFINIR.",
            )
        )
        return issues

    a_raw = row.get(AplicacionPagosCols.APLICAR_OBLIGACION_ACTUAL)
    v_raw = row.get(AplicacionPagosCols.APLICAR_SALDO_VENCIDO)
    k_raw = row.get(AplicacionPagosCols.ABONO_ADICIONAL_CAPITAL)

    try:
        a_f = parse_editable_money(a_raw)
        v_f = parse_editable_money(v_raw)
        k_f = parse_editable_money(k_raw)
    except InvalidMonetaryValue as exc:
        field = (
            AplicacionPagosCols.APLICAR_OBLIGACION_ACTUAL
            if exc.raw is a_raw
            else AplicacionPagosCols.APLICAR_SALDO_VENCIDO
            if exc.raw is v_raw
            else AplicacionPagosCols.ABONO_ADICIONAL_CAPITAL
        )
        # Re-parse individually for precise field
        for fname, raw in (
            (AplicacionPagosCols.APLICAR_OBLIGACION_ACTUAL, a_raw),
            (AplicacionPagosCols.APLICAR_SALDO_VENCIDO, v_raw),
            (AplicacionPagosCols.ABONO_ADICIONAL_CAPITAL, k_raw),
        ):
            try:
                parse_editable_money(raw)
            except InvalidMonetaryValue:
                issues.append(
                    _issue(
                        row,
                        "invalid_monetary_value",
                        field=fname,
                        value_found=raw,
                    )
                )
        return issues

    tipo_raw = row.get(AplicacionPagosCols.TIPO_APLICACION)
    tipo_norm = normalize_tipo_aplicacion_confirmado(tipo_raw)

    if vp == ValidarPago.NO:
        if a_f > MONEY_EQ_TOLERANCE or v_f > MONEY_EQ_TOLERANCE or k_f > MONEY_EQ_TOLERANCE:
            issues.append(
                _issue(
                    row,
                    "no_row_must_have_zero_distribution",
                    field=AplicacionPagosCols.VALIDAR_PAGO,
                )
            )
        if tipo_norm:
            issues.append(
                _issue(
                    row,
                    "no_row_must_have_empty_tipo",
                    field=AplicacionPagosCols.TIPO_APLICACION,
                    value_found=tipo_raw,
                )
            )
        return issues

    # SI
    if not tipo_norm:
        issues.append(
            _issue(
                row,
                "tipo_aplicacion_required",
                field=AplicacionPagosCols.TIPO_APLICACION,
                value_found=tipo_raw,
            )
        )
    else:
        try:
            require_tipo_aplicacion_confirmado(tipo_norm)
            row["_policy"] = resolve_policy_from_tipo_confirmado(tipo_norm)
        except ValueError:
            issues.append(
                _issue(
                    row,
                    "tipo_aplicacion_invalid",
                    field=AplicacionPagosCols.TIPO_APLICACION,
                    value_found=tipo_raw,
                )
            )

    total = a_f + v_f + k_f
    row[AplicacionPagosCols.TOTAL_ASIGNADO] = round(total, 2)
    if total <= MONEY_EQ_TOLERANCE:
        issues.append(
            _issue(
                row,
                "validar_requires_positive_total",
                field=AplicacionPagosCols.TOTAL_ASIGNADO,
            )
        )

    # AMBIGUO: Generate marca WARNING_REVIEW_REQUIRED; Finalize acepta SI+tipo+distribución.
    # Observación NUNCA es override.
    parser_status = str(row.get("_parser_status") or row.get("parser_status") or "")
    right_role = str(row.get("_right_panel_role") or row.get("right_panel_role") or "")
    if (
        parser_status == "AMBIGUOUS_RIGHT_PANEL" or right_role == "AMBIGUO"
    ) and tipo_norm and total > MONEY_EQ_TOLERANCE:
        row["human_review_override"] = True

    # NO exigir sugerencia == tipo; NO Observación; NO extracto == banco.
    return issues


def collect_saldo_por_asignar_issues(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Por ID Pago: Monto banco − SUM(total SI only) ≈ 0."""
    issues: list[dict[str, Any]] = []
    by_id: dict[str, list[dict[str, Any]]] = {}
    monto_by_id: dict[str, float] = {}

    for row in rows:
        id_pago = str(row.get(AplicacionPagosCols.ID_PAGO) or "").strip()
        if not id_pago:
            continue
        by_id.setdefault(id_pago, []).append(row)
        try:
            monto_by_id.setdefault(
                id_pago, parse_editable_money(row.get(AplicacionPagosCols.MONTO_BANCO))
            )
        except InvalidMonetaryValue:
            monto_by_id.setdefault(id_pago, 0.0)

    for id_pago, group in by_id.items():
        assigned = 0.0
        first_si: dict[str, Any] | None = None
        any_row = group[0]
        for row in group:
            if not is_validar_pago_si(row):
                continue
            try:
                a = parse_editable_money(row.get(AplicacionPagosCols.APLICAR_OBLIGACION_ACTUAL))
                v = parse_editable_money(row.get(AplicacionPagosCols.APLICAR_SALDO_VENCIDO))
                k = parse_editable_money(row.get(AplicacionPagosCols.ABONO_ADICIONAL_CAPITAL))
            except InvalidMonetaryValue:
                continue
            assigned += a + v + k
            if first_si is None:
                first_si = row
        if first_si is None:
            # Todos NO / sin SI → blocker (no silent continue)
            issues.append(
                _issue(
                    any_row,
                    "payment_without_selected_credit",
                    field=AplicacionPagosCols.VALIDAR_PAGO,
                    user_message="El ID Pago no tiene ningún crédito en Validar Pago = SI.",
                )
            )
            continue
        monto = monto_by_id.get(id_pago, 0.0)
        saldo = round(monto - assigned, 2)
        # Recalcular en filas SI para consumidores
        for row in group:
            if is_validar_pago_si(row):
                row[AplicacionPagosCols.SALDO_POR_ASIGNAR] = saldo
        if not money_eq(assigned, monto):
            issues.append(
                _issue(
                    first_si,
                    "amount_mismatch",
                    field=AplicacionPagosCols.SALDO_POR_ASIGNAR,
                    assigned=round(assigned, 2),
                    monto_banco=monto,
                    saldo_por_asignar=saldo,
                    delta=round(assigned - monto, 2),
                )
            )
    return issues


def collect_aplicacion_pagos_issues(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for row in rows:
        issues.extend(iter_aplicacion_pago_row_issues(row))
    issues.extend(collect_saldo_por_asignar_issues(rows))
    return issues


def blocker_issues_only(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [i for i in issues if i.get("severity", "BLOCKER") == "BLOCKER"]
