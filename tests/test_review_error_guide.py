"""Guía operativa de la hoja Errores (textos quirúrgicos v4)."""
from __future__ import annotations

from app.application.services.review_error_guide import (
    error_record_to_sheet_row,
    guide_texts_for_ui,
)
from app.application.services.review_schema import ErroresCols


def test_extract_not_found_fills_tipo_descripcion_and_action() -> None:
    rec = {
        "id_pago": "PAY-1",
        "cliente": "EQUINORTE",
        "credito": "CREDITO # 258",
        "code": "extract_not_found",
    }
    row = error_record_to_sheet_row(rec)
    by_col = dict(zip(ErroresCols.HEADERS, row))
    assert by_col[ErroresCols.TIPO_CASO] == "Extracto"
    assert "EQUINORTE" in str(by_col[ErroresCols.DESCRIPCION])
    assert "258" in str(by_col[ErroresCols.DESCRIPCION])
    assert "EXTRACTOS" in str(by_col[ErroresCols.QUE_DEBE_HACER])
    assert by_col[ErroresCols.CODIGO_TECNICO] == "extract_not_found"


def test_readable_fail_lists_problem_files() -> None:
    rec = {
        "id_pago": "PAY-2",
        "cliente": "GEOEXCON",
        "credito": "CREDITO # 99",
        "code": "fecha_limite_extracto_not_readable",
        "archivos_problema": [
            {
                "name": "extracto_roto.pdf",
                "reason": "fecha_limite_not_readable",
            }
        ],
    }
    row = error_record_to_sheet_row(rec)
    by_col = dict(zip(ErroresCols.HEADERS, row))
    assert "extracto_roto.pdf" in str(by_col[ErroresCols.DESCRIPCION])
    assert "fecha límite no reconocida" in str(by_col[ErroresCols.DESCRIPCION])
    assert str(by_col[ErroresCols.QUE_DEBE_HACER]).strip()


def test_readable_fail_distinguishes_scanned_pdf() -> None:
    rec = {
        "code": "fecha_limite_extracto_not_readable",
        "archivos_problema": [
            {"name": "escaneado.pdf", "reason": "pdf_no_text"},
        ],
    }
    row = error_record_to_sheet_row(rec)
    by_col = dict(zip(ErroresCols.HEADERS, row))
    assert "escaneado.pdf" in str(by_col[ErroresCols.DESCRIPCION])
    assert "sin texto" in str(by_col[ErroresCols.DESCRIPCION]).lower()


def test_download_failed_shows_http_detail() -> None:
    rec = {
        "code": "fecha_limite_extracto_not_readable",
        "archivos_problema": [
            {"name": "extracto.pdf", "reason": "download_failed", "detail": "HTTP 503"},
        ],
    }
    row = error_record_to_sheet_row(rec)
    by_col = dict(zip(ErroresCols.HEADERS, row))
    assert "HTTP 503" in str(by_col[ErroresCols.DESCRIPCION])


def test_guide_texts_for_ui_covers_legacy_as_of_code() -> None:
    tipo, descr, hacer = guide_texts_for_ui(
        "extract_as_of_not_found",
        {"cliente": "EQUINORTE", "credito": "CREDITO # 258"},
    )
    assert tipo == "Extracto"
    assert "EQUINORTE" in descr
    assert "extracto" in descr.lower()
    assert "generar" in hacer.lower()
