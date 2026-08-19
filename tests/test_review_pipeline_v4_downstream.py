"""Pipeline v4: Generate → editar VP+Tipo → Finalize → histórico → Merge/manifest → dry-run.

El cuadre banco↔asientos usa Monto banco canónico e importes del asiento, no A/V/K.
"""
from __future__ import annotations

from datetime import date
from io import BytesIO
from types import SimpleNamespace

import openpyxl

from app.application.services.historical_application_rows import read_validated_application_rows
from app.application.services.review_schema import (
    AplicacionPagosCols,
    ReviewSheets,
    TipoAplicacion,
    TipoAplicacionConfirmado,
    ValidarPago,
)
from app.application.services.review_workbook_v4 import (
    REVIEW_FIRST_DATA_ROW,
    build_aplicacion_pagos_row,
    build_review_workbook_v4_bytes,
)
from app.application.use_cases.amortization_fill_apply import _event_from_planned_item
from app.application.use_cases.amortization_fill_dry_run import (
    BANK_ASIENTOS_NO_CUADRAN,
    _payment_application_dict,
    _reconcile_bank_vs_asientos_for_payment_outputs,
)
from app.application.use_cases.payment_validation_finalize import finalize_payment_validation
from tests.test_finalize_validation import MockGraphClient, _run, set_env_vars


def _item(*, id_pago="P1", vp=100.0, extracto=None, asiento="asiento.pdf"):
    return {
        "id_pago": id_pago,
        "tipo_aplicacion": TipoAplicacion.PAGO.value,
        "asiento_pdf_path": asiento,
        "extracto_pdf_path": extracto,
        "payment_application": {"valor_pagado_cliente": vp},
        "warnings": [],
    }


def test_dry_run_blocks_when_bank_ne_sum_asientos():
    items = [_item(vp=80.0)]
    out = _reconcile_bank_vs_asientos_for_payment_outputs(
        [{"id_pago": "P1", "monto_banco": 100.0}],
        items,
    )
    assert out[0].get("error_code") != BANK_ASIENTOS_NO_CUADRAN
    assert out[0].get("advisory_code") == BANK_ASIENTOS_NO_CUADRAN
    assert out[0].get("application_status") != "ERROR"


def test_dry_run_ok_when_bank_eq_sum_asientos():
    items = [_item(vp=100.0)]
    out = _reconcile_bank_vs_asientos_for_payment_outputs(
        [{"id_pago": "P1", "monto_banco": 100.0}],
        items,
    )
    assert not out[0].get("error_code")


def test_dry_run_does_not_block_only_because_extract_differs():
    items = [_item(vp=100.0, extracto="extracto_otro.pdf")]
    out = _reconcile_bank_vs_asientos_for_payment_outputs(
        [{"id_pago": "P1", "monto_banco": 100.0}],
        items,
    )
    assert not out[0].get("error_code")


def _candidate(credito: str, oblig: float) -> dict:
    return {
        "credito": credito,
        "fecha_limite": date(2026, 5, 15),
        "valor_obligacion_actual": oblig,
        "saldo_vencido_visible": None,
        "link_extracto": f"https://mock.invalid/{credito}/extracto",
        "link_tabla": "https://mock.invalid/tabla",
        "link_carpeta_credito": f"https://mock.invalid/{credito}",
        "ruta_extracto_pdf": f"clientes/CLI/{credito}/extractos/e.pdf",
        "ruta_unidad_credito": f"clientes/CLI/{credito}",
        "ruta_tabla_amortizacion": f"clientes/CLI/{credito}/tabla.xlsx",
        "credito_normalizado": credito,
        "right_panel_role": "VACIO",
        "parser_status": "OK",
        "extract_evidence": {},
    }


def test_generate_edit_finalize_hist_manifest_dry_run_canonical_bank():
    """ID Pago 2 créditos: NO con monto + SI vacío; canónico llega a histórico y dry-run."""
    payment = {
        "id_pago": "ID1",
        "cliente": "CLI",
        "monto_banco": 1_500_000,
        "fecha_banco": date(2026, 5, 10),
    }
    row_no = build_aplicacion_pagos_row(payment, _candidate("CRED_A", 900_000))
    row_si = build_aplicacion_pagos_row(payment, _candidate("CRED_B", 1_500_000))
    # Generate deja ambas POR DEFINIR; la humana solo edita VP + Tipo.
    row_no[AplicacionPagosCols.VALIDAR_PAGO] = ValidarPago.NO
    row_no[AplicacionPagosCols.TIPO_APLICACION] = ""
    row_si[AplicacionPagosCols.VALIDAR_PAGO] = ValidarPago.SI
    row_si[AplicacionPagosCols.TIPO_APLICACION] = TipoAplicacionConfirmado.PAGO_OBLIGACION_ACTUAL
    row_si[AplicacionPagosCols.MONTO_BANCO] = None

    raw = build_review_workbook_v4_bytes(
        process_id="proc-pipe",
        process_date=date(2026, 5, 10),
        bank_code="banco_bogota",
        aplicacion_rows=[row_no, row_si],
        error_records=[],
    )
    wb_gen = openpyxl.load_workbook(BytesIO(raw))
    ws_gen = wb_gen[ReviewSheets.APLICACION_PAGOS]
    col_monto = AplicacionPagosCols.HEADERS.index(AplicacionPagosCols.MONTO_BANCO) + 1
    assert ws_gen.cell(REVIEW_FIRST_DATA_ROW, col_monto).value == 1_500_000
    assert ws_gen.cell(REVIEW_FIRST_DATA_ROW + 1, col_monto).value in (None, "")
    for row_idx in range(REVIEW_FIRST_DATA_ROW, REVIEW_FIRST_DATA_ROW + 2):
        for c, header in enumerate(AplicacionPagosCols.HEADERS, start=1):
            if header in AplicacionPagosCols.SECRETARY_EDITABLE:
                continue
            val = ws_gen.cell(row_idx, c).value
            if isinstance(val, str):
                assert "Aplicar a obligación" not in val
                assert "Abono adicional" not in val

    async def run_test():
        set_env_vars()
        client = MockGraphClient()
        client.downloaded_files["revision/val_latest.xlsx"] = raw
        res = await finalize_payment_validation(
            client, "val_latest.xlsx", process_date=date(2026, 5, 10), bank_code="banco_bogota"
        )
        assert res["status"] == "success"
        hist_path = next(p for p in client.uploaded_files if "cartera_validada" in p)
        hist_wb = openpyxl.load_workbook(BytesIO(client.uploaded_files[hist_path]))
        rows = read_validated_application_rows(hist_wb)
        assert len(rows) == 1
        si = rows[0]
        assert si["id_pago"] == "ID1"
        assert si["monto_banco"] == 1_500_000.0
        assert "CRED_B" in str(si.get("credito_raw") or si.get("credito_digits") or "")
        dumped = str(si)
        assert "Aplicar a obligación actual" not in dumped
        assert "Abono adicional a capital" not in dumped

        asiento_pa = {
            "valor_pagado_cliente": 1_500_000.0,
            "capital": 900_000.0,
            "intereses": 500_000.0,
            "mora": 100_000.0,
            "retenciones": 0.0,
            "saldos_menores": 0.0,
        }
        items = [
            {
                "id_pago": "ID1",
                "tipo_aplicacion": TipoAplicacion.PAGO.value,
                "asiento_pdf_path": "clientes/CLI/CRED_B/asiento.pdf",
                "payment_application": asiento_pa,
                "warnings": [],
            }
        ]
        recon = _reconcile_bank_vs_asientos_for_payment_outputs(
            [{"id_pago": r["id_pago"], "monto_banco": r["monto_banco"]} for r in rows],
            items,
        )
        assert not recon[0].get("error_code")

        event = _event_from_planned_item(items[0])
        apply_pa = _payment_application_dict(event)
        assert apply_pa["valor_pagado_cliente"] == 1_500_000.0
        assert apply_pa["capital"] == 900_000.0
        assert apply_pa["intereses"] == 500_000.0
        assert apply_pa["mora"] == 100_000.0
        # Los componentes no existen como columnas del workbook de revisión.
        hist_headers = [
            hist_wb[ReviewSheets.APLICACION_PAGOS].cell(REVIEW_FIRST_DATA_ROW - 1, c).value
            for c in range(1, 20)
        ]
        assert "Capital" not in hist_headers
        assert "Intereses" not in hist_headers
        fake_from_workbook = SimpleNamespace(
            valor_pagado_cliente=None, capital=None, intereses=None, mora=None,
            retenciones=None, saldos_menores=None,
        )
        assert apply_pa != _payment_application_dict(fake_from_workbook)

    _run(run_test())
