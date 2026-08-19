"""
Orden de aplicación de los soportes de un mismo ID Pago en la tabla de amortización.

Cada soporte contable ocupa una fila del bloque "Aplicación del Pago". El orden de
esas filas no es cosmético: la columna de abono a capital de una fila alimenta el
capital base del período siguiente, y con ello el interés causado. Por eso el orden
no puede depender del nombre del archivo PDF.

Se replica el criterio con que contabilidad llena la tabla a mano:

1. Primero los asientos con fecha, en orden cronológico.
2. Dentro del mismo día, primero el pago con recaudo bancario y después los
   asientos sin recaudo (retenciones, ajustes de saldos menores).
3. Ante empate, el consecutivo del documento contable (menor primero).
4. Como último desempate, el orden en que venían en el manifest (estabilidad).
"""

from __future__ import annotations

from datetime import date

from app.application.services.accounting_pdf_parser import (
    PaymentApplicationEvent,
    has_bank_recaudo,
)

# Los eventos sin fecha o sin consecutivo legible no se adelantan a los que sí lo traen.
_UNDATED = date.max
_UNNUMBERED = float("inf")

EventOrderKey = tuple[int, date, int, float, int]


def _numero_asiento_value(event: PaymentApplicationEvent) -> float:
    raw = str(event.numero_asiento or "").strip()
    return float(raw) if raw.isdigit() else _UNNUMBERED


def amortization_event_order_key(
    event: PaymentApplicationEvent | None,
    *,
    original_index: int,
) -> EventOrderKey:
    """
    Clave de ordenamiento de un evento. ``event`` es ``None`` cuando el asiento no se
    pudo descargar o parsear: en ese caso conserva su posición original y el planner
    lo reporta como error más adelante.
    """
    if event is None:
        return (1, _UNDATED, 1, _UNNUMBERED, original_index)

    fecha = event.fecha_asiento
    return (
        0 if fecha is not None else 1,
        fecha if fecha is not None else _UNDATED,
        1 if not has_bank_recaudo(event) else 0,
        _numero_asiento_value(event),
        original_index,
    )
