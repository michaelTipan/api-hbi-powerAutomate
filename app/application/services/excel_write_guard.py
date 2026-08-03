"""
Validaciones previas a escrituras Excel / SharePoint del flujo de validación de pagos.

Centraliza reglas que deben bloquear el submit antes de cualquier put_bytes o
actualización de control, con códigos estables reutilizables por routers y use cases.
"""

from __future__ import annotations

import os
import re
import unicodedata
from datetime import date, datetime
from typing import Any

from app.application.config.payment_validation_settings import (
    get_payment_validation_paths,
    validate_bank_code,
)
from app.application.services.review_schema import (
    CasosPagoCols,
    DistribucionAbonosCols,
    DistribucionCols,
    EstadoPago,
    is_validar_abono_si,
    is_validar_pago_si,
    normalize_credito_digits,
)


class ExcelWriteGuardError(ValueError):
    """Error de validación con código estable para mensajes operativos."""

    def __init__(self, code: str, **details: Any) -> None:
        self.error_code = code
        self.details = dict(details)
        payload = code
        if details:
            parts = [f"{k}={v}" for k, v in details.items() if v is not None and str(v) != ""]
            if parts:
                payload = f"{code}|{','.join(parts)}"
        super().__init__(payload)


def _norm_text(value: str) -> str:
    text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return text.strip().lower()


def _norm_path(path: str) -> str:
    return str(path or "").replace("\\", "/").strip().strip("/")


def raise_guard(code: str, **details: Any) -> None:
    raise ExcelWriteGuardError(code, **details)


def validate_bank_code_or_raise(bank_code: str | None) -> str:
    code = str(bank_code or "").strip()
    if not code:
        raise_guard("bank_code_required")
    try:
        validate_bank_code(code)
    except ValueError as exc:
        raise ExcelWriteGuardError("invalid_bank_code") from exc
    return code


def validate_process_date_or_raise(raw: str | date | None) -> date:
    if raw is None or str(raw).strip() == "":
        return date.today()
    if isinstance(raw, date):
        return raw
    if isinstance(raw, datetime):
        return raw.date()
    text = str(raw).strip()
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ExcelWriteGuardError("invalid_process_date", value=text) from exc


def validate_relative_path_or_raise(
    path: str | None,
    *,
    allowed_prefixes: tuple[str, ...] | None = None,
    field: str = "path",
) -> str:
    """Rechaza rutas vacías, traversal o fuera de prefijos permitidos."""
    raw = str(path or "").strip()
    if not raw:
        raise_guard("empty_path", field=field)
    norm = _norm_path(raw)
    if norm.startswith("/") or ".." in norm.split("/"):
        raise_guard("invalid_path", field=field, path=norm)
    if allowed_prefixes:
        roots = tuple(_norm_path(p) for p in allowed_prefixes if str(p or "").strip())
        if roots and not any(norm.lower().startswith(r.lower()) for r in roots):
            raise_guard("path_outside_allowed_roots", field=field, path=norm)
    return norm


def validate_validation_file_path_or_raise(path: str | None) -> str:
    """Ruta manual del Excel de revisión debe vivir bajo la carpeta REVISION."""
    try:
        review_root = _norm_path(get_payment_validation_paths().review)
    except Exception:
        # Default por rol (sin prefijo numerado); el número vive en payment_validation_settings.
        review_root = _norm_path(os.getenv("GRAPH_PAYMENT_VALIDATION_REVIEW_PATH", "REVISION"))
    return validate_relative_path_or_raise(
        path,
        allowed_prefixes=(review_root,),
        field="validation_file_path",
    )


def validate_generate_request(
    *,
    bank_code: str | None,
    process_date: str | date | None,
    source_file_path: str | None = None,
) -> tuple[str, date]:
    bc = validate_bank_code_or_raise(bank_code)
    pd = validate_process_date_or_raise(process_date)
    if source_file_path and str(source_file_path).strip():
        validate_relative_path_or_raise(source_file_path, field="source_file_path")
    return bc, pd


def validate_finalize_request(
    *,
    bank_code: str | None,
    process_date: str | date | None,
    validation_file_path: str | None = None,
) -> tuple[str | None, date]:
    bc = str(bank_code or "").strip() or None
    if bc:
        validate_bank_code_or_raise(bc)
    pd = validate_process_date_or_raise(process_date)
    vpath = str(validation_file_path or "").strip() or None
    if vpath:
        validate_validation_file_path_or_raise(vpath)
    return bc, pd


def validate_amortization_request(
    *,
    bank_code: str | None,
    report_date_iso: str | None,
    merge_manifest_path: str | None = None,
    historical_file_path: str | None = None,
) -> None:
    bc = str(bank_code or "").strip()
    if bc:
        validate_bank_code_or_raise(bc)
    if report_date_iso and str(report_date_iso).strip():
        validate_process_date_or_raise(str(report_date_iso).strip())
    if merge_manifest_path and str(merge_manifest_path).strip():
        validate_relative_path_or_raise(merge_manifest_path, field="merge_manifest_path")
    if historical_file_path and str(historical_file_path).strip():
        validate_relative_path_or_raise(historical_file_path, field="historical_file_path")


def _row_requires_payment_validation(dist: dict[str, Any]) -> bool:
    ep = str(dist.get(DistribucionCols.ESTADO_PAGO, "")).strip().upper()
    return ep in EstadoPago.SECRETARY_AND_RUTA and is_validar_pago_si(dist)


def _coerce_positive_amount(value: Any) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if text.startswith("="):
        return None
    try:
        return float(text)
    except ValueError:
        try:
            return float(text.replace(".", "").replace(",", "."))
        except ValueError:
            return None


def _validate_credit_unit_path_order(
    *,
    cliente: str,
    credito: str,
    ruta_unidad: str,
    excel_row: int | str,
) -> None:
    """El cliente debe aparecer antes que el crédito en la ruta interna."""
    norm = _norm_path(ruta_unidad).lower()
    if not norm:
        return
    cli_norm = _norm_text(cliente)
    if cli_norm and cli_norm not in norm:
        raise_guard(
            "ruta_client_mismatch",
            excel_row=excel_row,
            cliente=cliente,
            ruta=ruta_unidad,
        )
    cred_label = str(credito or "").strip()
    cred_digits = normalize_credito_digits(cred_label) or cred_label
    if not cred_digits:
        return
    parts = norm.split("/")
    cli_idx = next(
        (i for i, seg in enumerate(parts) if cli_norm and cli_norm in _norm_text(seg)),
        -1,
    )
    cred_idx = next(
        (
            i
            for i, seg in enumerate(parts)
            if cred_digits in _norm_text(seg) or _norm_text(cred_label) in _norm_text(seg)
        ),
        -1,
    )
    if cli_idx >= 0 and cred_idx >= 0 and cred_idx < cli_idx:
        raise_guard(
            "ruta_folder_order_invalid",
            excel_row=excel_row,
            cliente=cliente,
            credito=credito,
            ruta=ruta_unidad,
        )


def validate_distrib_rows_before_write(rows: list[dict[str, Any]]) -> None:
    """Valida filas Distribución antes de crear carpetas o subir histórico."""
    for dist in rows:
        row_no = dist.get("_excel_row", "?")
        if not _row_requires_payment_validation(dist):
            continue
        cliente = str(dist.get(DistribucionCols.CLIENTE) or "").strip()
        credito = str(dist.get(DistribucionCols.CREDITO) or "").strip()
        if not cliente:
            raise_guard("empty_cliente", excel_row=row_no)
        if not credito:
            raise_guard("empty_credito", excel_row=row_no)
        if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", cliente + credito):
            raise_guard("invalid_text_characters", excel_row=row_no)
        fb = dist.get(DistribucionCols.FECHA_BANCO)
        if fb is not None and str(fb).strip():
            if not isinstance(fb, (date, datetime)):
                try:
                    validate_process_date_or_raise(str(fb).strip()[:10])
                except ExcelWriteGuardError:
                    raise_guard("invalid_fecha_banco", excel_row=row_no)
        monto = _coerce_positive_amount(dist.get(DistribucionCols.MONTO_BANCO))
        if monto is not None and monto < 0:
            raise_guard("invalid_monto_banco", excel_row=row_no, monto=monto)
        ruta_uc = str(dist.get(DistribucionCols.RUTA_UNIDAD_CREDITO) or "").strip()
        if not ruta_uc:
            raise_guard("missing_ruta_unidad_credito", excel_row=row_no)
        _validate_credit_unit_path_order(
            cliente=cliente,
            credito=credito,
            ruta_unidad=ruta_uc,
            excel_row=row_no,
        )


def validate_abono_rows_before_write(rows: list[dict[str, Any]]) -> None:
    """Valida filas Distribución Abonos seleccionadas antes de escrituras."""
    for abono in rows:
        if not is_validar_abono_si(abono):
            continue
        row_no = abono.get("_excel_row", "?")
        cliente = str(abono.get(DistribucionAbonosCols.CLIENTE) or "").strip()
        credito = str(abono.get(DistribucionAbonosCols.CREDITO) or "").strip()
        if not cliente:
            raise_guard("empty_cliente", excel_row=row_no, sheet="Distribucion_Abonos")
        if not credito:
            raise_guard("empty_credito", excel_row=row_no, sheet="Distribucion_Abonos")
        ruta_uc = str(abono.get(DistribucionAbonosCols.RUTA_UNIDAD_CREDITO) or "").strip()
        if not ruta_uc:
            raise_guard("abono_credit_without_unit_path", excel_row=row_no)
        _validate_credit_unit_path_order(
            cliente=cliente,
            credito=credito,
            ruta_unidad=ruta_uc,
            excel_row=row_no,
        )
        tabla = str(abono.get(DistribucionAbonosCols.RUTA_TABLA_AMORTIZACION) or "").strip()
        if not tabla:
            raise_guard("abono_credit_without_amortization_path", excel_row=row_no)


def validate_casos_pago_before_write(
    casos: dict[str, float],
    *,
    distrib_rows: list[dict[str, Any]],
) -> None:
    """Casos de pago referenciados en Distribución deben existir con monto > 0."""
    referenced: set[str] = set()
    for dist in distrib_rows:
        if not _row_requires_payment_validation(dist):
            continue
        id_pago = str(dist.get(DistribucionCols.ID_PAGO) or "").strip()
        if id_pago:
            referenced.add(id_pago)
    for id_pago in sorted(referenced):
        if id_pago not in casos:
            raise_guard("missing_caso_pago", id_pago=id_pago)
        if casos[id_pago] <= 0:
            raise_guard("invalid_caso_pago_monto", id_pago=id_pago)


def validate_review_workbook_before_finalize_writes(
    *,
    distributions: list[dict[str, Any]],
    abono_rows: list[dict[str, Any]],
    monto_casos: dict[str, float],
) -> None:
    """Última barrera síncrona antes de provisionar carpetas o subir archivos."""
    validate_casos_pago_before_write(monto_casos, distrib_rows=distributions)
    validate_distrib_rows_before_write(distributions)
    validate_abono_rows_before_write(abono_rows)
