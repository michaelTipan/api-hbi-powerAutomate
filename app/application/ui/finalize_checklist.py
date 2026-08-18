"""Checklist operativo Finalize — textos alineados a review schema v4.

No evalúa el Excel; solo guía al operador.
"""
from __future__ import annotations

from app.application.services.review_schema import (
    AplicacionPagosCols,
    ReviewSheets,
    TipoAplicacionConfirmado,
    ValidarPago,
)


def build_finalize_operator_checklist() -> list[str]:
    """Instrucciones exactas según schema v4 (Aplicacion_Pagos)."""
    tipos = ", ".join(TipoAplicacionConfirmado.OPTIONS_ORDERED)
    return [
        f"Abra el Excel de revisión (hoja {ReviewSheets.APLICACION_PAGOS}).",
        f"Marque {AplicacionPagosCols.VALIDAR_PAGO} = {ValidarPago.SI} solo en las filas que desea cerrar. "
        f"El resto puede quedar en {ValidarPago.NO} o vacío (no se valida).",
        f"En filas {ValidarPago.SI}, elija {AplicacionPagosCols.TIPO_APLICACION} ({tipos}).",
        f"En filas {ValidarPago.NO} (o vacías), deje {AplicacionPagosCols.TIPO_APLICACION} vacío.",
        "No ingrese montos: el banco define el monto recibido y el asiento los valores a aplicar.",
        f"{AplicacionPagosCols.OBSERVACION} es opcional y nunca bloquea el cierre.",
        f"Deje la hoja {ReviewSheets.ERRORES} sin casos abiertos (u oculta si no hay).",
        "Guarde el Excel, espere la sincronización de SharePoint y cierre Excel Online antes de Finalizar.",
    ]
