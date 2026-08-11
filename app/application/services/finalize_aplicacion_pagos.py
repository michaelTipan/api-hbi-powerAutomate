"""Helpers de lectura/validación Finalize para schema v3 (Aplicacion_Pagos)."""
from __future__ import annotations

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


def _safe_float(v: Any) -> float:
    if v is None or str(v).strip() == "":
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace("$", "").replace(" ", "")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


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
    **extra: Any,
) -> dict[str, Any]:
    issue: dict[str, Any] = {
        "error_code": error_code,
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

    a = row.get(AplicacionPagosCols.APLICAR_OBLIGACION_ACTUAL)
    v = row.get(AplicacionPagosCols.APLICAR_SALDO_VENCIDO)
    k = row.get(AplicacionPagosCols.ABONO_ADICIONAL_CAPITAL)
    a_f, v_f, k_f = _safe_float(a), _safe_float(v), _safe_float(k)

    for field_name, raw, fval in (
        (AplicacionPagosCols.APLICAR_OBLIGACION_ACTUAL, a, a_f),
        (AplicacionPagosCols.APLICAR_SALDO_VENCIDO, v, v_f),
        (AplicacionPagosCols.ABONO_ADICIONAL_CAPITAL, k, k_f),
    ):
        if _cell_filled(raw) and fval < -MONEY_EQ_TOLERANCE:
            issues.append(_issue(row, "negative_distribution_amount", field=field_name, value_found=raw))

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

    # NO exigir sugerencia == tipo; NO Observación; NO extracto == banco.
    return issues


def collect_saldo_por_asignar_issues(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Por ID Pago: suma(total SI) debe ≈ Monto banco."""
    issues: list[dict[str, Any]] = []
    by_id: dict[str, list[dict[str, Any]]] = {}
    monto_by_id: dict[str, float] = {}

    for row in rows:
        id_pago = str(row.get(AplicacionPagosCols.ID_PAGO) or "").strip()
        if not id_pago:
            continue
        by_id.setdefault(id_pago, []).append(row)
        monto_by_id.setdefault(id_pago, _safe_float(row.get(AplicacionPagosCols.MONTO_BANCO)))

    for id_pago, group in by_id.items():
        assigned = 0.0
        first_si: dict[str, Any] | None = None
        for row in group:
            if not is_validar_pago_si(row):
                continue
            a = _safe_float(row.get(AplicacionPagosCols.APLICAR_OBLIGACION_ACTUAL))
            v = _safe_float(row.get(AplicacionPagosCols.APLICAR_SALDO_VENCIDO))
            k = _safe_float(row.get(AplicacionPagosCols.ABONO_ADICIONAL_CAPITAL))
            assigned += a + v + k
            if first_si is None:
                first_si = row
        if first_si is None:
            continue
        monto = monto_by_id.get(id_pago, 0.0)
        if not money_eq(assigned, monto):
            issues.append(
                _issue(
                    first_si,
                    "amount_mismatch",
                    field=AplicacionPagosCols.SALDO_POR_ASIGNAR,
                    assigned=round(assigned, 2),
                    monto_banco=monto,
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
