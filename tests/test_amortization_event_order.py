"""Criterio de orden de los soportes dentro del bloque Aplicación del Pago."""

from __future__ import annotations

from datetime import date

from app.application.services.accounting_pdf_parser import (
    ACCOUNT_SALDOS_MENORES,
    ACCOUNT_VALOR_PAGADO_CLIENTE,
    PaymentApplicationEvent,
)
from app.application.services.amortization_event_order import (
    amortization_event_order_key,
)


def _event(
    *,
    fecha: date | None = date(2026, 4, 23),
    numero: str = "",
    intereses: float = 0.0,
    mora: float = 0.0,
    saldos_menores: float = 0.0,
    con_recaudo_banco: bool = True,
) -> PaymentApplicationEvent:
    codes: list[str] = []
    if con_recaudo_banco:
        codes.append(ACCOUNT_VALOR_PAGADO_CLIENTE)
    if saldos_menores > 0:
        codes.append(ACCOUNT_SALDOS_MENORES)
    return PaymentApplicationEvent(
        id_pago="7785e37e",
        cliente="EQUINORTE",
        credito="265",
        asiento_pdf_path="asiento.pdf",
        comprobante="",
        fecha_asiento=fecha,
        valor_pagado_cliente=1.0,
        capital=1.0,
        intereses=intereses,
        mora=mora,
        retenciones=0.0,
        saldos_menores=saldos_menores,
        raw_text="",
        detected_codes=tuple(codes),
        numero_asiento=numero,
    )


def _order(events: list[PaymentApplicationEvent | None]) -> list[int]:
    """Índices originales en el orden en que quedarían las filas."""
    decorated = [
        (amortization_event_order_key(ev, original_index=i), i)
        for i, ev in enumerate(events)
    ]
    decorated.sort(key=lambda x: x[0])
    return [i for _key, i in decorated]


def test_pago_de_cuota_va_antes_que_ajuste_de_saldos_menores():
    """Caso EQUINORTE 265: el ajuste de 285 llegaba primero por orden alfabético."""
    ajuste = _event(numero="3495", saldos_menores=285.0, con_recaudo_banco=False)
    cuota = _event(numero="3494", intereses=578111.0, mora=285.0)
    assert _order([ajuste, cuota]) == [1, 0]


def test_fecha_del_asiento_manda_sobre_el_tipo():
    ajuste_viejo = _event(
        fecha=date(2026, 4, 20), saldos_menores=285.0, con_recaudo_banco=False
    )
    cuota_nueva = _event(fecha=date(2026, 4, 23), intereses=578111.0)
    assert _order([cuota_nueva, ajuste_viejo]) == [1, 0]


def test_desempate_por_consecutivo_del_documento():
    segundo = _event(numero="3496", intereses=100.0)
    primero = _event(numero="3494", intereses=200.0)
    assert _order([segundo, primero]) == [1, 0]


def test_eventos_sin_fecha_conservan_su_posicion_al_final():
    sin_fecha = _event(fecha=None, numero="3400", intereses=100.0)
    con_fecha = _event(numero="3499", intereses=200.0)
    assert _order([sin_fecha, con_fecha]) == [1, 0]


def test_evento_no_parseable_no_se_adelanta_y_es_estable():
    con_fecha = _event(numero="3494", intereses=100.0)
    assert _order([None, con_fecha, None]) == [1, 0, 2]


def test_orden_es_estable_cuando_todo_empata():
    a = _event(numero="3494", intereses=100.0)
    b = _event(numero="3494", intereses=100.0)
    assert _order([a, b]) == [0, 1]
