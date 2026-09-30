"""Columna «Cliente» o «Concepto» del Excel de carga del banco."""

from __future__ import annotations

from datetime import date, datetime

import openpyxl
import pytest

from app.application.job_status_enrichment import enrich_job_for_http_response
from app.application.services.bank_upload_columns import (
    BANK_CLIENT_COLUMN_MISSING_CODE,
    BankUploadInputError,
    find_client_column,
)
from app.application.services.review_error_guide import guide_texts_for_ui
from app.application.use_cases.payment_validation_generate import _parse_bank_sheet_headers
from app.application.use_cases.send_validar_extractos_notification import (
    _parse_bank_report_table_and_min_date,
)
from app.application.use_cases.validate_payment_report import _find_header_map, _get_col
from tests.bank_upload_scenarios import (
    BASE_ROWS,
    build_bank_excel,
    load_golden,
    run_generate_snapshot,
)
from tests.test_bank_upload_credit_column import _MockClient, _run_generate_client
from tests.test_generate_validation import create_excel


def _sheet(headers, rows=()):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(headers)
    for r in rows:
        ws.append(r)
    return ws


# ─── Encabezados ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "headers,expected",
    [
        (["Fecha", "Crédito", "Concepto", "Transacción"], 2),
        (["Fecha", "Crédito", "Cliente", "Transacción"], 2),
        (["Fecha", "Crédito", "CLIENTE ", "Transacción"], 2),
        (["Fecha", "Crédito", "Concepto", "Cliente"], 3),
        (["Fecha", "Crédito", "Transacción"], -1),
    ],
)
def test_find_client_column_accepts_both_and_prefers_cliente(headers, expected):
    assert find_client_column(headers) == expected


def test_generate_headers_map_cliente_column():
    col_map, *_ = _parse_bank_sheet_headers(_sheet(["Fecha", "Crédito", "Cliente", "Transacción"]))
    assert col_map["concepto"] == 2
    assert col_map["transaccion"] == 3


def test_generate_without_client_column_is_rejected_before_touching_control():
    with pytest.raises(BankUploadInputError, match=f"^{BANK_CLIENT_COLUMN_MISSING_CODE}$") as excinfo:
        _parse_bank_sheet_headers(_sheet(["Fecha", "Crédito", "Transacción"]))
    assert excinfo.value.control_untouched is True


# ─── Generate: «Cliente» produce lo mismo que «Concepto» ─────────────────────


@pytest.mark.parametrize("bank_code", ["banco_bogota", "banco_bancolombia"])
def test_generate_with_cliente_header_matches_golden(bank_code):
    headers = ["Fecha", "Crédito", "Cliente", "Transacción"]
    snap = run_generate_snapshot(build_bank_excel(headers), bank_code=bank_code)
    assert snap == load_golden()[bank_code]


def test_generate_with_both_columns_uses_cliente():
    headers = ["Fecha", "Crédito", "Concepto", "Cliente", "Transacción"]
    rows = [[r[0], r[1], "TEXTO LIBRE DEL BANCO", r[2], r[3]] for r in BASE_ROWS]
    snap = run_generate_snapshot(build_bank_excel(headers, rows), bank_code="banco_bogota")
    assert snap == load_golden()["banco_bogota"]


def test_generate_without_client_column_leaves_everything_untouched():
    rows = [[datetime(2025, 12, 23), 6500739, "PAGO PSE"]]
    client = _MockClient()
    with pytest.raises(BankUploadInputError, match=f"^{BANK_CLIENT_COLUMN_MISSING_CODE}$"):
        _run_generate_client(create_excel(["Fecha", "Crédito", "Transacción"], rows), client=client)
    assert client.put_calls == []
    assert client.delete_calls == []


# ─── Correo y merge: el encabezado se muestra tal cual ───────────────────────


def test_email_table_accepts_cliente_header_literal():
    raw = create_excel(
        ["Fecha", "Crédito", "Cliente", "Transacción"],
        [
            [datetime(2026, 9, 2), 200, "JASP", "PSE"],
            [datetime(2026, 9, 1), 100, "RUEDA", "PSE"],
        ],
    )
    report_d, headers, rows = _parse_bank_report_table_and_min_date(raw)
    # Mismo lector que usa el merge para la fecha mínima del reporte.
    assert report_d == date(2026, 9, 1)
    assert headers == ["Fecha", "Crédito", "Cliente", "Transacción"]
    assert [r[2] for r in rows] == ["JASP", "RUEDA"]


def test_email_table_without_client_or_concepto_fails_clearly():
    raw = create_excel(["Fecha", "Crédito", "Transacción"], [[datetime(2026, 9, 1), 100, "PSE"]])
    with pytest.raises(ValueError, match=r"Fecha/Crédito/Cliente"):
        _parse_bank_report_table_and_min_date(raw)


@pytest.mark.parametrize(
    "headers,expected_col",
    [
        (["Fecha", "Crédito", "Concepto"], 3),
        (["Fecha", "Crédito", "Cliente"], 3),
        (["Fecha", "Crédito", "Concepto", "Cliente"], 4),
    ],
)
def test_report_header_map_accepts_cliente_or_concepto(headers, expected_col):
    header_row, header_map = _find_header_map(_sheet(headers))
    assert header_row == 1
    assert _get_col(header_map, "Cliente", "Concepto") == expected_col


# ─── Mensajes al operador ────────────────────────────────────────────────────


def _failed_generate(message: str) -> dict:
    return enrich_job_for_http_response(
        {
            "job_id": "j",
            "type": "generate",
            "status": "failed",
            "error": {"type": "BankUploadInputError", "message": message},
        }
    )["error"]


def test_missing_client_column_message_is_plain_spanish():
    e = _failed_generate(BANK_CLIENT_COLUMN_MISSING_CODE)
    assert e["error_code"] == BANK_CLIENT_COLUMN_MISSING_CODE
    assert e["user_message"] == "Falta la columna Cliente en el Excel de carga del banco."
    assert "Cliente (o Concepto)" in e["next_action"]
    for text in (e["user_message"], e["next_action"]):
        assert "_" not in text and "BANCO_BOGOTA" not in text


def test_headers_not_found_message_is_generic_for_any_bank():
    e = _failed_generate("bank_headers_not_found")
    assert "BANCO_BOGOTA" not in e["user_message"]
    assert "Cliente" in e["user_message"]


@pytest.mark.parametrize("code", ["customer_not_found", "customer_ambiguous"])
def test_review_error_guide_speaks_of_cliente(code):
    for rec in (None, {"cliente": "ACME"}):
        _, descr, hacer = guide_texts_for_ui(code, rec)
        text = f"{descr} {hacer}"
        assert "concepto" not in text.lower()
        if rec:
            assert "«ACME»" in descr
