"""Workbook de revisión v4: 16 columnas, visual operador, sin distribución manual."""
from __future__ import annotations

from datetime import date
from io import BytesIO

import openpyxl

from app.application.services.review_schema import (
    REVIEW_SCHEMA_VERSION,
    AplicacionPagosCols,
    AplicacionPagosColsV3,
    MANUAL_DISTRIBUTION_HEADERS_V3,
    MetaCols,
    ReviewSheets,
    ValidarPago,
    require_review_schema_v4,
)
from app.application.services.review_workbook_v4 import (
    REVIEW_FIRST_DATA_ROW,
    REVIEW_HEADER_ROW,
    build_aplicacion_pagos_row,
    build_review_workbook_v4_bytes,
)

_EXPECTED_V4 = [
    "ID Pago",
    "Cliente",
    "Crédito",
    "Monto banco",
    "Fecha banco",
    "Fecha límite",
    "Días respecto vencimiento",
    "Valor obligación actual",
    "Saldo vencido",
    "Validar Pago",
    "Aplicación sugerida",
    "Tipo de aplicación",
    "Link extracto",
    "Link tabla amortización",
    "Link carpeta crédito",
    "Observación",
]


def _sample_row() -> dict:
    payment = {
        "id_pago": "PAY-1",
        "cliente": "CLIENTE SYN",
        "monto_banco": 1_500_000,
        "fecha_banco": date(2026, 5, 20),
    }
    candidate = {
        "credito": "258",
        "fecha_limite": date(2026, 5, 23),
        "valor_obligacion_actual": 1_500_000,
        "saldo_vencido_visible": None,
        "link_extracto": "https://example/extracto",
        "link_tabla": "https://example/tabla",
        "link_carpeta_credito": "https://example/carpeta",
        "ruta_extracto_pdf": "clientes/CLIENTE/CREDITO 258/EXTRACTOS/extracto.pdf",
        "ruta_unidad_credito": "clientes/CLIENTE/CREDITO 258",
        "ruta_tabla_amortizacion": "clientes/CLIENTE/CREDITO 258/tabla.xlsx",
        "credito_normalizado": "258",
        "right_panel_role": "VACIO",
        "parser_status": "OK",
        "extract_evidence": {},
    }
    return build_aplicacion_pagos_row(payment, candidate)


def _load_v4():
    raw = build_review_workbook_v4_bytes(
        process_id="proc-1",
        process_date=date(2026, 5, 20),
        bank_code="banco_bogota",
        aplicacion_rows=[_sample_row()],
        error_records=[],
    )
    wb = openpyxl.load_workbook(BytesIO(raw))
    return raw, wb


def test_review_schema_version_is_4():
    assert REVIEW_SCHEMA_VERSION == 4


def test_v4_has_exactly_16_visible_columns_in_order():
    assert list(AplicacionPagosCols.HEADERS) == _EXPECTED_V4
    assert len(AplicacionPagosCols.HEADERS) == 16


def test_removed_manual_distribution_headers_not_in_v4():
    names = set(AplicacionPagosCols.HEADERS)
    assert names.isdisjoint(MANUAL_DISTRIBUTION_HEADERS_V3)
    assert MANUAL_DISTRIBUTION_HEADERS_V3.issubset(set(AplicacionPagosColsV3.HEADERS))
    assert len(AplicacionPagosColsV3.HEADERS) == 21


def test_workbook_v4_opens_with_openpyxl_and_layout():
    _raw, wb = _load_v4()
    ws = wb[ReviewSheets.APLICACION_PAGOS]
    assert ws.cell(1, 1).value == "APLICACIÓN DE PAGOS"
    assert ws.cell(2, 1).value
    headers = [ws.cell(REVIEW_HEADER_ROW, c).value for c in range(1, 17)]
    assert headers == _EXPECTED_V4
    assert ws.cell(REVIEW_FIRST_DATA_ROW, 1).value == "PAY-1"
    assert ws.freeze_panes == "D4"
    assert ws.auto_filter.ref
    assert ws.sheet_view.showGridLines is False
    assert str(ws.sheet_properties.tabColor.rgb).endswith("00B050")
    assert wb[ReviewSheets.META].sheet_state == "hidden"
    assert wb[ReviewSheets.LISTAS].sheet_state == "hidden"


def test_workbook_v4_does_not_contain_removed_headers_or_avk_formulas():
    _raw, wb = _load_v4()
    ws = wb[ReviewSheets.APLICACION_PAGOS]
    visible = [ws.cell(REVIEW_HEADER_ROW, c).value for c in range(1, 40)]
    visible = [v for v in visible if v]
    for banned in MANUAL_DISTRIBUTION_HEADERS_V3:
        assert banned not in visible
    data_row = REVIEW_FIRST_DATA_ROW
    for c in range(1, 17):
        val = ws.cell(data_row, c).value
        if isinstance(val, str) and val.startswith("="):
            low = val.lower()
            assert "sumifs" not in low
            assert "+k" not in low.replace(" ", "")
            header = ws.cell(REVIEW_HEADER_ROW, c).value
            assert header == AplicacionPagosCols.APLICACION_SUGERIDA


def test_workbook_v4_editables_and_observacion_optional():
    _raw, wb = _load_v4()
    ws = wb[ReviewSheets.APLICACION_PAGOS]
    r = REVIEW_FIRST_DATA_ROW
    col_vp = AplicacionPagosCols.HEADERS.index(AplicacionPagosCols.VALIDAR_PAGO) + 1
    col_tipo = AplicacionPagosCols.HEADERS.index(AplicacionPagosCols.TIPO_APLICACION) + 1
    col_obs = AplicacionPagosCols.HEADERS.index(AplicacionPagosCols.OBSERVACION) + 1
    col_id = AplicacionPagosCols.HEADERS.index(AplicacionPagosCols.ID_PAGO) + 1
    assert ws.cell(r, col_vp).protection.locked is False
    assert ws.cell(r, col_tipo).protection.locked is False
    assert ws.cell(r, col_obs).protection.locked is False
    assert ws.cell(r, col_id).protection.locked is True
    assert ws.cell(r, col_vp).value == ValidarPago.POR_DEFINIR


def test_workbook_v4_meta_version_and_finalize_accepts():
    _raw, wb = _load_v4()
    meta = {row[0]: row[1] for row in wb[ReviewSheets.META].iter_rows(values_only=True) if row}
    assert meta.get(MetaCols.ROW_REVIEW_SCHEMA_VERSION) == 4
    assert require_review_schema_v4(wb) == 4


def test_sugerencia_uses_canonical_monto_when_secondary_row_visible_empty():
    """Candidato 1 NO con Monto banco; candidato 2 SI con celda vacía → sugerencia canónica."""
    from app.application.services.review_schema import (
        AplicacionSugerida,
        TipoAplicacionConfirmado,
        compute_aplicacion_sugerida,
    )

    payment = {
        "id_pago": "PAY-CANON",
        "cliente": "CLI",
        "monto_banco": 1_500_000,
        "fecha_banco": date(2026, 5, 20),
    }

    def _cand(credito: str, oblig: float) -> dict:
        return {
            "credito": credito,
            "fecha_limite": date(2026, 5, 23),
            "valor_obligacion_actual": oblig,
            "saldo_vencido_visible": None,
            "link_extracto": "https://example/extracto",
            "link_tabla": "https://example/tabla",
            "link_carpeta_credito": "https://example/carpeta",
            "ruta_extracto_pdf": f"clientes/CLI/CREDITO {credito}/EXTRACTOS/e.pdf",
            "ruta_unidad_credito": f"clientes/CLI/CREDITO {credito}",
            "ruta_tabla_amortizacion": f"clientes/CLI/CREDITO {credito}/tabla.xlsx",
            "credito_normalizado": credito,
            "right_panel_role": "VACIO",
            "parser_status": "OK",
            "extract_evidence": {},
        }

    row_no = build_aplicacion_pagos_row(payment, _cand("1", 900_000))
    row_si = build_aplicacion_pagos_row(payment, _cand("2", 1_500_000))
    row_no[AplicacionPagosCols.VALIDAR_PAGO] = ValidarPago.NO
    row_si[AplicacionPagosCols.VALIDAR_PAGO] = ValidarPago.SI
    row_si[AplicacionPagosCols.TIPO_APLICACION] = TipoAplicacionConfirmado.PAGO_OBLIGACION_ACTUAL
    # Simula fila secundaria sin monto local (como en el Excel visible).
    row_si[AplicacionPagosCols.MONTO_BANCO] = None

    sug_si = compute_aplicacion_sugerida(
        validar_pago=row_si[AplicacionPagosCols.VALIDAR_PAGO],
        valor_obligacion_actual=row_si[AplicacionPagosCols.VALOR_OBLIGACION_ACTUAL],
        saldo_vencido=row_si[AplicacionPagosCols.SALDO_VENCIDO],
        monto_banco=payment["monto_banco"],
    )
    assert sug_si == AplicacionSugerida.PAGO_OBLIGACION_ACTUAL
    assert sug_si != "POR DISTRIBUIR"

    raw = build_review_workbook_v4_bytes(
        process_id="proc-canon",
        process_date=date(2026, 5, 20),
        bank_code="banco_bogota",
        aplicacion_rows=[row_no, row_si],
        error_records=[],
    )
    wb = openpyxl.load_workbook(BytesIO(raw))
    ws = wb[ReviewSheets.APLICACION_PAGOS]
    col_monto = AplicacionPagosCols.HEADERS.index(AplicacionPagosCols.MONTO_BANCO) + 1
    col_sug = AplicacionPagosCols.HEADERS.index(AplicacionPagosCols.APLICACION_SUGERIDA) + 1
    r1 = REVIEW_FIRST_DATA_ROW
    r2 = r1 + 1
    assert ws.cell(r1, col_monto).value == 1_500_000
    assert ws.cell(r2, col_monto).value in (None, "")
    formula = str(ws.cell(r2, col_sug).value or "")
    assert formula.startswith("=")
    assert "SUMIF(" in formula
    assert "POR DISTRIBUIR" not in formula
    assert AplicacionSugerida.REVISAR_TIPO in formula
    assert "POR DISTRIBUIR" not in (ws.cell(1, 1).value or "")
    assert "POR DISTRIBUIR" not in (ws.cell(2, 1).value or "")
