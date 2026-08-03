"""Rechazo de datos inválidos antes de escrituras Excel / SharePoint."""

from __future__ import annotations

from datetime import date

import pytest

from app.application.services.excel_write_guard import (
    ExcelWriteGuardError,
    validate_amortization_request,
    validate_distrib_rows_before_write,
    validate_finalize_request,
    validate_generate_request,
    validate_review_workbook_before_finalize_writes,
    validate_validation_file_path_or_raise,
)
from app.application.services.review_schema import (
    DistribucionAbonosCols,
    DistribucionCols,
    EstadoPago,
    ValidarAbono,
    ValidarPago,
)


def _dist_row(**overrides):
    base = {
        DistribucionCols.ID_PAGO: "P1",
        DistribucionCols.CLIENTE: "EQUINORTE",
        DistribucionCols.CREDITO: "CREDITO # 264",
        DistribucionCols.MONTO_BANCO: 100000,
        DistribucionCols.FECHA_BANCO: date(2026, 5, 10),
        DistribucionCols.ESTADO_PAGO: EstadoPago.NORMAL,
        DistribucionCols.VALIDAR_PAGO: ValidarPago.SI,
        DistribucionCols.RUTA_UNIDAD_CREDITO: "clientes/EQUINORTE/CREDITO # 264",
        "_excel_row": 4,
    }
    base.update(overrides)
    return base


def test_generate_rejects_invalid_bank_code():
    with pytest.raises(ExcelWriteGuardError, match="invalid_bank_code"):
        validate_generate_request(bank_code="banco_fake", process_date="2026-05-10")


def test_generate_rejects_invalid_process_date():
    with pytest.raises(ExcelWriteGuardError, match="invalid_process_date"):
        validate_generate_request(bank_code="banco_bogota", process_date="10-05-2026")


def test_finalize_rejects_validation_path_outside_review(monkeypatch):
    monkeypatch.setenv(
        "PAYMENT_VALIDATION_REVIEW_FOLDER",
        "02 VALIDACION PAGOS/01 REVISION",
    )
    with pytest.raises(ExcelWriteGuardError, match="path_outside_allowed_roots"):
        validate_validation_file_path_or_raise("otra/carpeta/archivo.xlsx")


def test_distrib_rejects_empty_cliente_on_validar():
    row = _dist_row(**{DistribucionCols.CLIENTE: ""})
    with pytest.raises(ExcelWriteGuardError, match="empty_cliente"):
        validate_distrib_rows_before_write([row])


def test_distrib_rejects_ruta_client_mismatch():
    row = _dist_row(
        **{
            DistribucionCols.CLIENTE: "EQUINORTE",
            DistribucionCols.RUTA_UNIDAD_CREDITO: "clientes/OTRO_CLIENTE/CREDITO # 264",
        }
    )
    with pytest.raises(ExcelWriteGuardError, match="ruta_client_mismatch"):
        validate_distrib_rows_before_write([row])


def test_distrib_rejects_wrong_folder_order():
    row = _dist_row(
        **{
            DistribucionCols.RUTA_UNIDAD_CREDITO: "clientes/CREDITO # 264/EQUINORTE",
        }
    )
    with pytest.raises(ExcelWriteGuardError, match="ruta_folder_order_invalid"):
        validate_distrib_rows_before_write([row])


def test_review_workbook_rejects_missing_caso_pago():
    dist = [_dist_row()]
    with pytest.raises(ExcelWriteGuardError, match="missing_caso_pago"):
        validate_review_workbook_before_finalize_writes(
            distributions=dist,
            abono_rows=[],
            monto_casos={},
        )


def test_review_workbook_happy_path():
    dist = [_dist_row()]
    validate_review_workbook_before_finalize_writes(
        distributions=dist,
        abono_rows=[],
        monto_casos={"P1": 100000.0},
    )


def test_abono_rejects_missing_amortization_path():
    abono = {
        DistribucionAbonosCols.ID_PAGO: "A1",
        DistribucionAbonosCols.CLIENTE: "CLI",
        DistribucionAbonosCols.CREDITO: "CRED",
        DistribucionAbonosCols.VALIDAR_ABONO: ValidarAbono.SI,
        DistribucionAbonosCols.RUTA_UNIDAD_CREDITO: "clientes/CLI/CRED",
        DistribucionAbonosCols.RUTA_TABLA_AMORTIZACION: "",
        "_excel_row": 5,
    }
    with pytest.raises(ExcelWriteGuardError, match="abono_credit_without_amortization_path"):
        validate_review_workbook_before_finalize_writes(
            distributions=[],
            abono_rows=[abono],
            monto_casos={},
        )


def test_finalize_request_accepts_minimal_body():
    bc, pd = validate_finalize_request(
        bank_code="banco_bogota",
        process_date="2026-05-10",
        validation_file_path=None,
    )
    assert bc == "banco_bogota"
    assert pd == date(2026, 5, 10)


def test_amortization_rejects_bad_report_date():
    with pytest.raises(ExcelWriteGuardError, match="invalid_process_date"):
        validate_amortization_request(
            bank_code=None,
            report_date_iso="no-es-fecha",
        )
