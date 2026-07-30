"""Checklist operativo Finalize — textos alineados a review_schema / use case.

No evalúa el Excel; solo guía al operador. Los nombres vienen de constantes.
"""
from __future__ import annotations

from app.application.services.review_schema import (
    ControlCols,
    DistribucionCols,
    EstadoPago,
    ReviewSheets,
    ValidarPago,
)


def build_finalize_operator_checklist() -> list[str]:
    """Instrucciones exactas según schema v2 vigente (sin valores retirados)."""
    estados = ", ".join(EstadoPago.OPTIONS_ORDERED)
    return [
        f"Abra el Excel de revisión correcto (hoja {ReviewSheets.CONTROL} y {ReviewSheets.DISTRIBUCION_PAGOS}).",
        f"En {ReviewSheets.CONTROL}, deje {ControlCols.ROW_PROCESAR} = {ControlCols.VAL_PROCESAR_SI}.",
        f"En {ReviewSheets.CONTROL}, conserve {ControlCols.ROW_ESTADO} = EN_REVISION.",
        f"En {ReviewSheets.DISTRIBUCION_PAGOS}, complete {DistribucionCols.ESTADO_PAGO} con: {estados}.",
        f"Resuelva todas las filas {EstadoPago.REVISION_MANUAL} antes de finalizar (bloquean el cierre).",
        f"Complete {DistribucionCols.VALIDAR_PAGO} ({ValidarPago.SI}/{ValidarPago.NO}) en cada fila.",
        f"Si {DistribucionCols.ESTADO_PAGO}={EstadoPago.NORMAL} y {DistribucionCols.VALIDAR_PAGO}={ValidarPago.NO}, "
        f"llene {DistribucionCols.OBSERVACION}.",
        f"Si valida ({ValidarPago.SI}), complete {DistribucionCols.APLICAR_A_EXTRACTO}, "
        f"{DistribucionCols.MORA_A_APLICAR}, {DistribucionCols.ABONO_A_CAPITAL}, {DistribucionCols.OTROS_VALORES} "
        f"y verifique que la suma por {DistribucionCols.ID_PAGO} cuadre con {DistribucionCols.MONTO_BANCO}.",
        f"Deje la hoja {ReviewSheets.ERRORES} sin casos abiertos.",
        "Guarde el Excel, espere la sincronización de SharePoint y cierre Excel Online antes de Finalizar.",
    ]
