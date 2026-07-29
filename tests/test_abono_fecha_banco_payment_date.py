"""Fecha pago ABONO = Fecha banco (misma regla que PAGO)."""
from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

from openpyxl.utils.datetime import to_excel

from app.application.services.abono_dry_run import (
    AbonoCreditItem,
    AbonoDryRunGroup,
    _abono_payment_date_fields,
    _parse_banco_date,
)
from app.application.use_cases.amortization_fill_apply import _payment_date_from_item


def _group(*, fecha_banco: date | None) -> AbonoDryRunGroup:
    return AbonoDryRunGroup(
        bank_code="banco_bogota",
        process_key="pk",
        id_pago="id1",
        cliente="CLI",
        monto_banco=1_000_000,
        fecha_banco=fecha_banco,
        creditos_seleccionados=["265"],
        credit_items=[
            AbonoCreditItem(
                credito="265",
                tipo_aplicacion="ABONO CAPITAL",
                ruta_tabla_amortizacion="T/265.xlsx",
                ruta_unidad_credito="C/265",
                ruta_asientos_contables="A/265",
                asiento_pdf_paths=["A/265/a.pdf"],
                extracto_pdf_paths=[],
            )
        ],
    )


def test_parse_banco_date_excel_serial():
    serial = to_excel(date(2026, 4, 23))
    assert _parse_banco_date(serial) == date(2026, 4, 23)
    assert _parse_banco_date("23/04/2026") == date(2026, 4, 23)


def test_abono_payment_date_prefers_fecha_banco_over_asiento():
    banco = date(2026, 4, 23)
    asiento = date(2026, 7, 29)
    event = SimpleNamespace(fecha_asiento=asiento)
    fields = _abono_payment_date_fields(_group(fecha_banco=banco), event)  # type: ignore[arg-type]
    assert fields["payment_date_iso"] == "2026-04-23"
    assert fields["payment_date_source"] == "fecha_banco"
    assert fields["fecha_asiento"] == "2026-07-29"
    assert fields["payment_date_matches_asiento"] is False


def test_abono_payment_date_none_without_banco_even_if_asiento():
    event = SimpleNamespace(fecha_asiento=date(2026, 7, 29))
    fields = _abono_payment_date_fields(_group(fecha_banco=None), event)  # type: ignore[arg-type]
    assert "payment_date_iso" not in fields
    assert fields["payment_date_source"] == "none"
    assert fields["fecha_asiento"] == "2026-07-29"


def test_apply_abono_writes_fecha_banco_not_asiento():
    item = {
        "tipo_aplicacion": "ABONO CAPITAL",
        "payment_date_iso": "2026-04-23",
        "fecha_asiento": "2026-07-29",
    }
    assert _payment_date_from_item(item, {"report_date_iso": "2026-07-29"}) == date(
        2026, 4, 23
    )


def test_apply_abono_rejects_asiento_as_fecha_pago():
    item = {
        "tipo_aplicacion": "ABONO MORA",
        "fecha_asiento": "2026-07-29",
    }
    assert _payment_date_from_item(item, {"report_date_iso": "2026-07-29"}) is None
