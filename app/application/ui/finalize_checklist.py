"""Checklist operativo Finalize — textos alineados a review schema v3.

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
    """Instrucciones exactas según schema v3 (Aplicacion_Pagos)."""
    tipos = ", ".join(TipoAplicacionConfirmado.OPTIONS_ORDERED)
    return [
        f"Abra el Excel de revisión (hoja {ReviewSheets.APLICACION_PAGOS}).",
        f"Resuelva todas las filas con {AplicacionPagosCols.VALIDAR_PAGO} = {ValidarPago.POR_DEFINIR} "
        f"(debe quedar {ValidarPago.SI} o {ValidarPago.NO}).",
        f"En filas {ValidarPago.SI}, complete {AplicacionPagosCols.APLICAR_OBLIGACION_ACTUAL}, "
        f"{AplicacionPagosCols.APLICAR_SALDO_VENCIDO} y {AplicacionPagosCols.ABONO_ADICIONAL_CAPITAL} "
        f"para que la suma por {AplicacionPagosCols.ID_PAGO} cuadre con {AplicacionPagosCols.MONTO_BANCO}.",
        f"En filas {ValidarPago.SI}, elija {AplicacionPagosCols.TIPO_APLICACION} ({tipos}).",
        f"En filas {ValidarPago.NO}, deje montos en 0/vacío y {AplicacionPagosCols.TIPO_APLICACION} vacío.",
        f"{AplicacionPagosCols.OBSERVACION} es opcional y nunca bloquea el cierre.",
        f"Deje la hoja {ReviewSheets.ERRORES} sin casos abiertos (u oculta si no hay).",
        "Guarde el Excel, espere la sincronización de SharePoint y cierre Excel Online antes de Finalizar.",
    ]
