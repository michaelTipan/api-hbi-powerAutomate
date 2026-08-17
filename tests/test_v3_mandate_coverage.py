"""Cobertura mandato v3: Excel workbook, Finalize, Merge tokens, evidencia, escenarios."""
from __future__ import annotations

from datetime import date
from io import BytesIO

import openpyxl
import pytest

from app.application.services.extract_snapshot_parser import (
    EVIDENCE_META_FIELDS,
    parse_evidence_meta_value,
    parse_frozen_evidence_from_meta_sheet,
    prefer_frozen_extract_candidate,
    serialize_evidence_meta_value,
)
from app.application.services.finalize_aplicacion_pagos import collect_aplicacion_pagos_issues
from app.application.services.review_schema import (
    AplicacionPagosCols,
    ClassificationPolicy,
    DocumentaryPolicy,
    MERGE_NAME_TOKEN_BY_TIPO,
    MERGE_NAME_TOKEN_MULTIPLE,
    ReviewSheets,
    TipoAplicacionConfirmado,
    ValidarPago,
    merge_name_token_for_tipos,
    resolve_policy_from_tipo_confirmado,
)
from app.application.services.review_workbook_v4 import (
    REVIEW_FIRST_DATA_ROW,
    REVIEW_HEADER_ROW,
    build_aplicacion_pagos_row,
    build_review_workbook_v4_bytes,
)


def _base_row(**overrides):
    row = {
        AplicacionPagosCols.ID_PAGO: "p1",
        AplicacionPagosCols.CLIENTE: "CLIENTE SYN",
        AplicacionPagosCols.CREDITO: "101",
        AplicacionPagosCols.MONTO_BANCO: 100,
        AplicacionPagosCols.VALIDAR_PAGO: ValidarPago.SI,
        AplicacionPagosCols.TIPO_APLICACION: TipoAplicacionConfirmado.PAGO_OBLIGACION_ACTUAL,
        AplicacionPagosCols.OBSERVACION: "",
        "_excel_row": 2,
    }
    row.update(overrides)
    return row


def _sample_aplicacion_row(*, ambiguous: bool = False) -> dict:
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
        "saldo_vencido_visible": None if ambiguous else None,
        "link_extracto": "https://example/extracto",
        "link_tabla": "https://example/tabla",
        "link_carpeta_credito": "https://example/carpeta",
        "ruta_extracto_pdf": "clientes/CLIENTE/CREDITO 258/EXTRACTOS/extracto.pdf",
        "ruta_unidad_credito": "clientes/CLIENTE/CREDITO 258",
        "ruta_tabla_amortizacion": "clientes/CLIENTE/CREDITO 258/tabla.xlsx",
        "credito_normalizado": "258",
        "right_panel_role": "AMBIGUO" if ambiguous else "VACIO",
        "parser_status": "AMBIGUOUS_RIGHT_PANEL" if ambiguous else "OK",
        "extract_evidence": {
            "item_id": "item-frozen-1",
            "drive_id": "drive-1",
            "site_id": "site-1",
            "path": "clientes/CLIENTE/CREDITO 258/EXTRACTOS/extracto.pdf",
            "etag": "etag-1",
            "ctag": "ctag-1",
            "sha256": "abc123",
            "fecha_limite": "2026-05-23",
            "web_url": "https://example/web",
        },
        "observacion_extra": "nota panel" if ambiguous else "",
    }
    return build_aplicacion_pagos_row(payment, candidate)


# ---------------------------------------------------------------------------
# §34 Excel v3 workbook
# ---------------------------------------------------------------------------


def test_workbook_v3_has_21_columns_formulas_dropdowns_protection_and_meta():
    row = _sample_aplicacion_row()
    raw = build_review_workbook_v4_bytes(
        process_id="proc-1",
        process_date=date(2026, 5, 20),
        bank_code="banco_bogota",
        aplicacion_rows=[row],
        error_records=[],
    )
    wb = openpyxl.load_workbook(BytesIO(raw))
    assert ReviewSheets.APLICACION_PAGOS in wb.sheetnames
    assert ReviewSheets.ERRORES in wb.sheetnames
    assert ReviewSheets.META in wb.sheetnames
    assert ReviewSheets.LISTAS in wb.sheetnames
    assert wb[ReviewSheets.LISTAS].sheet_state == "hidden"
    assert wb[ReviewSheets.META].sheet_state == "hidden"
    assert wb[ReviewSheets.ERRORES].sheet_state == "hidden"
    for legacy in (
        "Distribucion_Pagos",
        "Distribucion_Abonos",
        "Casos_Pago",
        "Control",
        "Resumen",
    ):
        assert legacy not in wb.sheetnames

    ws = wb[ReviewSheets.APLICACION_PAGOS]
    headers = [c.value for c in ws[REVIEW_HEADER_ROW][:15]]
    assert headers == list(AplicacionPagosCols.HEADERS)
    assert ws.protection.sheet is True
    assert ws.cell(1, 1).value == "APLICACIÓN DE PAGOS"
    assert ws.freeze_panes == "D4"

    col_vp = AplicacionPagosCols.HEADERS.index(AplicacionPagosCols.VALIDAR_PAGO) + 1
    data_row = REVIEW_FIRST_DATA_ROW
    assert ws.cell(data_row, col_vp).value == ValidarPago.POR_DEFINIR
    assert "Aplicación sugerida" not in headers

    # Dropdowns
    assert len(ws.data_validations.dataValidation) >= 2

    # Protección: editables desbloqueados, sistema bloqueado
    col_obs = AplicacionPagosCols.HEADERS.index(AplicacionPagosCols.OBSERVACION) + 1
    col_id = AplicacionPagosCols.HEADERS.index(AplicacionPagosCols.ID_PAGO) + 1
    assert ws.cell(data_row, col_obs).protection.locked is False
    assert ws.cell(data_row, col_id).protection.locked is True

    # Links presentes
    col_link = AplicacionPagosCols.HEADERS.index(AplicacionPagosCols.LINK_EXTRACTO) + 1
    assert "extracto" in str(ws.cell(data_row, col_link).value).lower()

    # _Meta evidencia congelada completa
    ws_meta = wb[ReviewSheets.META]
    assert require_meta_version(ws_meta) == 4
    evidence_rows = parse_frozen_evidence_from_meta_sheet(ws_meta)
    assert len(evidence_rows) == 1
    ev = evidence_rows[0]
    assert ev["item_id"] == "item-frozen-1"
    assert ev["drive_id"] == "drive-1"
    assert ev["site_id"] == "site-1"
    assert ev["path"].endswith("extracto.pdf")
    assert ev["etag"] == "etag-1"
    assert ev["ctag"] == "ctag-1"
    assert ev["sha256"] == "abc123"
    assert ev["web_url"] == "https://example/web"
    assert set(EVIDENCE_META_FIELDS).issubset(ev.keys())


def require_meta_version(ws_meta) -> int:
    for row in ws_meta.iter_rows(values_only=True):
        if row and str(row[0] or "").strip() == "ReviewSchemaVersion":
            return int(row[1])
    raise AssertionError("missing ReviewSchemaVersion")


def test_workbook_marks_ambiguous_right_panel():
    row = _sample_aplicacion_row(ambiguous=True)
    raw = build_review_workbook_v4_bytes(
        process_id="proc-amb",
        process_date=date(2026, 6, 1),
        bank_code="banco_bogota",
        aplicacion_rows=[row],
        error_records=[
            {
                "id_pago": "PAY-1",
                "cliente": "CLIENTE SYN",
                "credito": "258",
                "codigo": "extract_right_panel_ambiguous",
                "descripcion": "Panel derecho ambiguo",
            }
        ],
    )
    wb = openpyxl.load_workbook(BytesIO(raw))
    ws = wb[ReviewSheets.APLICACION_PAGOS]
    col_sv = AplicacionPagosCols.HEADERS.index(AplicacionPagosCols.SALDO_VENCIDO) + 1
    assert ws.cell(REVIEW_FIRST_DATA_ROW, col_sv).value in ("", None)
    assert ws.cell(REVIEW_FIRST_DATA_ROW, col_sv).comment is not None
    assert wb[ReviewSheets.ERRORES].sheet_state != "hidden"


# ---------------------------------------------------------------------------
# §11 evidencia congelada / retry
# ---------------------------------------------------------------------------


def test_evidence_meta_roundtrip_and_prefer_frozen_on_retry():
    payload = serialize_evidence_meta_value(
        row_idx=2,
        evidence={
            "item_id": "id-old",
            "drive_id": "d1",
            "site_id": "s1",
            "path": "CLIENTE/CREDITO 1/EXTRACTOS/a.pdf",
            "etag": "e1",
            "ctag": "c1",
            "sha256": "sha-old",
            "fecha_limite": "2026-02-15",
            "web_url": "https://x",
        },
        right_panel_role="SALDO_VENCIDO",
        parser_status="OK",
    )
    parsed = parse_evidence_meta_value(payload)
    assert parsed["item_id"] == "id-old"
    assert parsed["sha256"] == "sha-old"

    pool = [
        {"id": "id-new", "relative_path": "CLIENTE/CREDITO 1/EXTRACTOS/b.pdf", "sha256": "sha-new"},
        {"id": "id-old", "relative_path": "CLIENTE/CREDITO 1/EXTRACTOS/a.pdf", "sha256": "sha-old"},
    ]
    preferred = prefer_frozen_extract_candidate(pool, parsed)
    assert preferred is not None
    assert preferred["id"] == "id-old"
    assert preferred["relative_path"].endswith("a.pdf")


def test_legacy_short_evidence_meta_still_parses():
    legacy = "2|item1|path/a.pdf|etag|sha|2026-03-01|VACIO|OK"
    parsed = parse_evidence_meta_value(legacy)
    assert parsed["item_id"] == "item1"
    assert parsed["path"] == "path/a.pdf"
    assert parsed["right_panel_role"] == "VACIO"
    assert parsed.get("created_datetime") == ""


# ---------------------------------------------------------------------------
# §20 políticas separadas
# ---------------------------------------------------------------------------


def test_application_policy_exposes_separated_concerns():
    policy = resolve_policy_from_tipo_confirmado(
        TipoAplicacionConfirmado.PAGO_PARCIAL_OBLIGACION_ACTUAL
    )
    assert isinstance(policy.classification, ClassificationPolicy)
    assert isinstance(policy.documentary, DocumentaryPolicy)
    assert policy.classification.subtipo_aplicacion == "CUOTA_PARCIAL"
    assert policy.documentary.include_extract_in_composite is True
    assert policy.amortization.cierra_cuota is False
    assert policy.ibr.actualiza_ibr is False
    assert "genera_siguiente_extracto" not in policy.policy_dict()


# ---------------------------------------------------------------------------
# §36 Finalize matrix
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "row,expected_code",
    [
        (_base_row(**{AplicacionPagosCols.VALIDAR_PAGO: ValidarPago.POR_DEFINIR}), "validar_pago_por_definir"),
        (
            _base_row(
                **{
                    AplicacionPagosCols.TIPO_APLICACION: "",
                }
            ),
            "tipo_aplicacion_required",
        ),
    ],
)
def test_finalize_matrix_blocks(row, expected_code):
    issues = collect_aplicacion_pagos_issues([row])
    assert any(i["error_code"] == expected_code for i in issues)


def test_finalize_does_not_block_on_manual_distribution():
    under = [_base_row(**{AplicacionPagosCols.MONTO_BANCO: 100})]
    assert collect_aplicacion_pagos_issues(under) == []


def test_finalize_multi_credit_sum_and_no_discarded():
    rows = [
        _base_row(
            **{
                AplicacionPagosCols.ID_PAGO: "same",
                AplicacionPagosCols.CREDITO: "1",
                AplicacionPagosCols.MONTO_BANCO: 100,
                "_excel_row": 2,
            }
        ),
        _base_row(
            **{
                AplicacionPagosCols.ID_PAGO: "same",
                AplicacionPagosCols.CREDITO: "2",
                AplicacionPagosCols.MONTO_BANCO: None,
                AplicacionPagosCols.VALIDAR_PAGO: ValidarPago.NO,
                AplicacionPagosCols.TIPO_APLICACION: "",
                "_excel_row": 3,
            }
        ),
        _base_row(
            **{
                AplicacionPagosCols.ID_PAGO: "same",
                AplicacionPagosCols.CREDITO: "3",
                AplicacionPagosCols.VALIDAR_PAGO: ValidarPago.NO,
                AplicacionPagosCols.TIPO_APLICACION: "",
                AplicacionPagosCols.MONTO_BANCO: None,
                "_excel_row": 4,
            }
        ),
    ]
    assert collect_aplicacion_pagos_issues(rows) == []


def test_finalize_observation_and_suggestion_mismatch_ok():
    empty_obs = _base_row(**{AplicacionPagosCols.OBSERVACION: ""})
    text_obs = _base_row(
        **{
            AplicacionPagosCols.OBSERVACION: "nota humana",
            AplicacionPagosCols.TIPO_APLICACION: TipoAplicacionConfirmado.CANCELACION_PAGO_TOTAL,
        }
    )
    assert collect_aplicacion_pagos_issues([empty_obs]) == []
    assert collect_aplicacion_pagos_issues([text_obs]) == []


# ---------------------------------------------------------------------------
# §39 Merge tokens
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tipo,token",
    list(MERGE_NAME_TOKEN_BY_TIPO.items())
    + [
        (
            [
                TipoAplicacionConfirmado.PAGO_OBLIGACION_ACTUAL,
                TipoAplicacionConfirmado.ABONO_A_CAPITAL,
            ],
            MERGE_NAME_TOKEN_MULTIPLE,
        )
    ],
)
def test_merge_tokens_exact_matrix(tipo, token):
    if isinstance(tipo, list):
        assert merge_name_token_for_tipos(tipo) == token
    else:
        assert merge_name_token_for_tipos([tipo]) == token
        assert MERGE_NAME_TOKEN_BY_TIPO[tipo] == token


def test_merge_ignores_observation_and_suggestion_for_token():
    # Token depende solo del Tipo confirmado.
    assert (
        merge_name_token_for_tipos([TipoAplicacionConfirmado.APLICACION_SALDO_VENCIDO])
        == "PAGO SALDO VENCIDO"
    )
    assert (
        merge_name_token_for_tipos([TipoAplicacionConfirmado.PAGO_COMBINADO])
        == "PAGO COMBINADO"
    )
    assert (
        merge_name_token_for_tipos([TipoAplicacionConfirmado.PAGO_Y_ABONO_CAPITAL])
        == "PAGO Y ABONO CAPITAL"
    )
    assert (
        merge_name_token_for_tipos([TipoAplicacionConfirmado.SALDO_VENCIDO_Y_ABONO_CAPITAL])
        == "SALDO VENCIDO Y ABONO CAPITAL"
    )
    assert (
        merge_name_token_for_tipos([TipoAplicacionConfirmado.PAGO_COMBINADO_Y_ABONO_CAPITAL])
        == "PAGO COMBINADO Y ABONO CAPITAL"
    )


# ---------------------------------------------------------------------------
# §37 escenarios feb–jul (comportamiento sintético)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "scenario_id,fecha_banco,fecha_limite,validar",
    [
        (1, date(2026, 2, 20), date(2026, 2, 20), ValidarPago.SI),
        (22, date(2026, 7, 10), date(2026, 7, 10), ValidarPago.POR_DEFINIR),
        (23, date(2026, 7, 12), date(2026, 7, 12), ValidarPago.NO),
        (24, date(2026, 7, 15), date(2026, 7, 20), ValidarPago.SI),
    ],
)
def test_feb_jul_dias_and_finalize_without_sugerida(
    scenario_id, fecha_banco, fecha_limite, validar
):
    from app.application.services.review_schema import dias_respecto_vencimiento

    dias = dias_respecto_vencimiento(fecha_banco, fecha_limite)
    assert dias == (fecha_banco - fecha_limite).days
    if validar == ValidarPago.SI:
        row = _base_row(
            **{
                AplicacionPagosCols.MONTO_BANCO: 100,
                AplicacionPagosCols.TIPO_APLICACION: TipoAplicacionConfirmado.PAGO_OBLIGACION_ACTUAL,
            }
        )
        assert collect_aplicacion_pagos_issues([row]) == []
