"""
Enriquecimiento de documentos de job para respuestas HTTP homogéneas (Power Automate).

Solo afecta la salida de GET job; no modifica lógica de negocio ni almacenamiento interno
más allá de devolver una copia enriquecida desde los routers.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.application.operational_message_policy import apply_audience_policy

ENRICHABLE_JOB_TYPES = frozenset(
    {
        "generate",
        "finalize",
        "cancel_active_process",
        "soft_close_process",
        "notify_validar_extractos",
        "merge_composite_validado_pdfs",
        "amortization_dry_run",
        "amortization_apply",
        # UI: un solo job visible que prepara + aplica (o requires_correction).
        "amortization_process",
    }
)

_UNKNOWN_USER = (
    "No fue posible completar el proceso debido a un inconveniente técnico."
)
_UNKNOWN_NEXT = (
    "No continúe con el siguiente paso. Contacte a soporte e indique el banco, "
    "la fecha y la etapa en la que se produjo el error."
)


def _mapped(code: str, user: str, next_a: str) -> tuple[str, str, str]:
    u, n = apply_audience_policy(code, user, next_a)
    return u, n, code

# Los mensajes al operador nombran las carpetas por su rol, no por su número, para que
# sigan siendo correctos cuando SharePoint se reorganiza o se renumeran las carpetas.
_PROCESS_CONTROL_FILES_HINT = (
    "el control de proceso del banco en la carpeta de control "
    "(control_proceso_validacion_pagos_banco_bogota.xlsx o "
    "control_proceso_validacion_pagos_banco_bancolombia.xlsx)"
)

_GENERATE_MESSAGES: dict[str, tuple[str, str]] = {
    "review_folder_not_empty": (
        "No se pudo generar el archivo nuevo porque en la carpeta de revisión todavía hay un Excel "
        "de una ejecución anterior (o un archivo pendiente de archivar).",
        "Mueva o archive los archivos validacion_pagos_*.xlsx de la carpeta de revisión y vuelva a ejecutar "
        "la generación. Deje solo el reporte del banco actualizado en su carpeta.",
    ),
    "invalid_bank_code": (
        "No fue posible iniciar el proceso porque el banco indicado no es válido.",
        "No continúe con el siguiente paso. Contacte a soporte e indique el banco, la fecha y la etapa del proceso.",
    ),
    "active_process_exists": (
        "Ya existe una validación activa para este banco. Abra el proceso existente "
        "para continuar desde el último paso completado.",
        "Use Retomar proceso en el panel del banco (no inicie una validación nueva). "
        "No intente editar el Excel de control: está protegido.",
    ),
    "force_regenerate_not_allowed": (
        "No se puede regenerar el Excel de revisión en el estado actual del proceso.",
        "Regenerar solo aplica mientras el proceso está en revisión (antes de finalizar). "
        "Si ya finalizó, continúe con el correo o el siguiente paso.",
    ),
    "missing_sharepoint_folder": (
        "No fue posible completar el proceso debido a un inconveniente de configuración en SharePoint.",
        "No continúe con el siguiente paso. Contacte a soporte e indique el banco, la fecha y la etapa del proceso.",
    ),
    "bank_headers_not_found": (
        "El archivo BANCO_BOGOTA.xlsx no tiene las columnas que el sistema espera (fecha, monto/crédito, concepto).",
        "Revise el formato del reporte del banco. Debe coincidir con la plantilla habitual. "
        "Corrija el Excel, vuelva a subirlo y ejecute de nuevo la generación.",
    ),

    "tipo_aplicacion_column_duplicate": (
        "El archivo de revisión tiene más de una columna Tipo de aplicación; el sistema no puede determinar cuál usar.",
        "Use la plantilla Aplicacion_Pagos vigente (una sola columna Tipo de aplicación) y vuelva a finalizar.",
    ),
    "tipo_aplicacion_required": (
        "Hay filas en Validar Pago = SI sin Tipo de aplicación confirmado.",
        "En Aplicacion_Pagos, elija el Tipo de aplicación en cada fila SI y vuelva a finalizar.",
    ),
    "tipo_aplicacion_invalid": (
        "Hay un Tipo de aplicación no válido en Aplicacion_Pagos.",
        "Use solo los valores del desplegable de Tipo de aplicación. Guarde y vuelva a finalizar.",
    ),
    "generic_abono_not_supported": (
        "El valor «ABONO» genérico ya no se acepta.",
        "En Aplicacion_Pagos confirme un Tipo de aplicación válido (p. ej. ABONO A CAPITAL) y vuelva a finalizar.",
    ),
    "payment_without_selected_credit": (
        "Un pago no tiene ningún crédito marcado en Validar Pago = SI.",
        "En Aplicacion_Pagos marque SI en al menos un crédito de ese pago, elija Tipo de aplicación "
        "en esa fila y pulse Finalizar.",
    ),
    "invalid_monetary_value": (
        "Hay un monto del banco que no es un número válido.",
        "Revise la columna Monto banco en Aplicacion_Pagos (sin letras). Guarde y pulse Finalizar.",
    ),
    "invalid_validar_pago": (
        "Hay un valor de Validar Pago que no es SI ni NO.",
        "Use solo SI o NO (o deje la celda vacía, que equivale a NO). Guarde y pulse Finalizar.",
    ),
    "no_row_must_have_empty_tipo": (
        "Una fila en Validar Pago = NO todavía tiene Tipo de aplicación.",
        "Si no va a validar esa fila, deje Tipo de aplicación vacío. Si sí la valida, ponga Validar Pago = SI.",
    ),
    "validar_pago_por_definir": (
        "Quedó un valor antiguo de Validar Pago (POR DEFINIR).",
        "Ponga SI solo en las filas a validar; el resto en NO o vacío. Guarde y pulse Finalizar.",
    ),
    "customer_not_found": (
        "En el reporte del banco hay un pago cuyo Concepto no coincide con ninguna carpeta de cliente en SharePoint.",
        "En la carpeta raíz de información de créditos de clientes, cree o corrija la carpeta del cliente "
        "para que el nombre coincida con el concepto del banco. Vuelva a generar.",
    ),
    "customer_ambiguous": (
        "El concepto del banco coincide con más de una carpeta de cliente; el sistema no sabe cuál usar.",
        "En SharePoint, deje un solo nombre de carpeta por cliente (sin duplicados parecidos). Vuelva a generar.",
    ),
    "credit_folder_not_found": (
        "No se encontró ninguna carpeta de crédito asociada al cliente del pago (estructura de carpetas incompleta).",
        "Dentro de la carpeta del cliente, verifique que existan carpetas de crédito con extractos y tabla de amortización. "
        "Corrija en SharePoint y vuelva a generar.",
    ),
    "extract_not_found": (
        "Falta el PDF del extracto en la carpeta del crédito (o no se detectó con la palabra configurada, por ejemplo Extracto).",
        "Suba el extracto en la carpeta del crédito, en la subcarpeta EXTRACTOS si aplica. Vuelva a generar.",
    ),
    "extract_amount_not_found": (
        "Hay extracto PDF pero el sistema no pudo leer el valor TOTAL A PAGAR.",
        "Use un PDF legible (no escaneado borroso) o el formato de extracto habitual. Vuelva a generar.",
    ),
    "pending_installment_not_found": (
        "En la tabla de amortización del crédito no hay una cuota pendiente clara para aplicar el pago.",
        "Revise el Excel de amortización en la carpeta del crédito (cuotas pendientes marcadas). Corrija y vuelva a generar.",
    ),
    "amortization_table_not_found": (
        "En la carpeta del crédito no hay archivo de tabla de amortización.",
        "Suba la tabla de amortización del crédito en la carpeta correspondiente y vuelva a generar.",
    ),
    "amortization_sheet_not_found": (
        "La tabla de amortización existe pero no tiene la hoja o estructura que el sistema espera.",
        "Abra el Excel de amortización y ajuste hojas o encabezados según el formato usado en otros créditos que sí funcionan. "
        "Vuelva a generar.",
    ),
}

_FINALIZE_MESSAGES: dict[str, tuple[str, str]] = {
    "review_has_open_errors": (
        "No se puede finalizar porque en la hoja Errores del Excel de revisión aún hay casos pendientes.",
        "Abra la hoja Errores, corrija documentos o carpetas según cada fila y use «Regenerar archivo de revisión». "
        "Cuando la hoja Errores quede sin casos, complete Validar Pago y Tipo de aplicación y pulse Finalizar.",
    ),
    "process_not_approved": (
        "Aún no se marcó el archivo como listo para procesar.",
        "Complete Validar Pago y Tipo de aplicación en Aplicacion_Pagos, guarde y cierre el Excel, "
        "y pulse Finalizar en la aplicación.",
    ),
    "missing_control_state": (
        "Este resultado corresponde a un esquema de revisión anterior (hoja Control).",
        "Ejecute Generate de nuevo, complete Validar Pago y Tipo de aplicación y pulse Finalizar en la aplicación.",
    ),
    "invalid_control_state": (
        "Este paso se ejecutó fuera de momento: la revisión ya no está pendiente de cierre "
        "(puede haberse finalizado antes).",
        "Si aún no ha cerrado el día, complete Aplicacion_Pagos y pulse Finalizar. "
        "Si ya finalizó, no repita este paso; continúe con el correo o el siguiente flujo del día.",
    ),
    "tipo_aplicacion_column_duplicate": (
        "El archivo de revisión tiene más de una columna Tipo de aplicación; el sistema no puede determinar cuál usar.",
        "Use la plantilla Aplicacion_Pagos vigente (una sola columna Tipo de aplicación) y vuelva a finalizar.",
    ),
    "tipo_aplicacion_required": (
        "Hay filas en Validar Pago = SI sin Tipo de aplicación confirmado.",
        "En Aplicacion_Pagos, elija el Tipo de aplicación en cada fila SI y vuelva a finalizar.",
    ),
    "tipo_aplicacion_invalid": (
        "Hay un Tipo de aplicación no válido en Aplicacion_Pagos.",
        "Use solo los valores del desplegable de Tipo de aplicación. Guarde y vuelva a finalizar.",
    ),
    "generic_abono_not_supported": (
        "El valor «ABONO» genérico ya no se acepta.",
        "En Aplicacion_Pagos confirme un Tipo de aplicación válido (p. ej. ABONO A CAPITAL) y vuelva a finalizar.",
    ),
    "payment_without_selected_credit": (
        "Un pago no tiene ningún crédito marcado en Validar Pago = SI.",
        "En Aplicacion_Pagos marque SI en al menos un crédito de ese pago, elija Tipo de aplicación "
        "en esa fila y pulse Finalizar.",
    ),
    "invalid_monetary_value": (
        "Hay un monto del banco que no es un número válido.",
        "Revise la columna Monto banco en Aplicacion_Pagos (sin letras). Guarde y pulse Finalizar.",
    ),
    "invalid_validar_pago": (
        "Hay un valor de Validar Pago que no es SI ni NO.",
        "Use solo SI o NO (o deje la celda vacía, que equivale a NO). Guarde y pulse Finalizar.",
    ),
    "no_row_must_have_empty_tipo": (
        "Una fila en Validar Pago = NO todavía tiene Tipo de aplicación.",
        "Si no va a validar esa fila, deje Tipo de aplicación vacío. Si sí la valida, ponga Validar Pago = SI.",
    ),
    "validar_pago_por_definir": (
        "Quedó un valor antiguo de Validar Pago (POR DEFINIR).",
        "Ponga SI solo en las filas a validar; el resto en NO o vacío. Guarde y pulse Finalizar.",
    ),
    "empty_estado_pago": (
        "En Aplicacion_Pagos hay filas con datos pero Estado Pago está vacío.",
        "En cada fila con pago, elija un valor de la lista: ADELANTADO, ATRASADO, NORMAL o REVISIÓN MANUAL. "
        "Guarde y vuelva a finalizar.",
    ),
    "multiple_review_errors": (
        "Se encontraron N problemas en la revisión.",
        "Corrija todos los puntos listados, guarde y vuelva a verificar.",
    ),
    "invalid_estado_pago": (
        "Hay un Estado Pago escrito a mano o un valor que no está en la lista permitida.",
        "Use solo la lista desplegable: ADELANTADO, ATRASADO, NORMAL, REVISIÓN MANUAL. "
        "No escriba texto libre. Guarde y vuelva a finalizar.",
    ),
    "INCOMPLETO_NOT_SUPPORTED": (
        "El estado INCOMPLETO ya no forma parte del flujo operativo.",
        "Clasifique el movimiento como PAGO si cierra el extracto o como ABONO si corresponde a una aplicación parcial.",
    ),
    "estado_pago_no_finalizable": (
        "Quedan filas en REVISIÓN MANUAL sin resolver; no se puede cerrar el día.",
        "Revise esas filas en Aplicacion_Pagos: cambie el estado cuando el caso esté resuelto o ajuste Validar Pago. "
        "Guarde y vuelva a finalizar.",
    ),
    "no_validar_requires_observation": (
        "Marcó Validar Pago = NO en una fila NORMAL pero no puso observación.",
        "En esa fila, escriba en Observación el motivo (por qué no se valida). Guarde y vuelva a finalizar.",
    ),
    # LEGACY: códigos de jobs históricos pre-v4. El Finalize actual no los emite.
    # Copy: no pedir ingresar ni distribuir montos.
    "missing_valor_intereses": (
        "Este resultado corresponde a un esquema de revisión anterior (columnas de montos manuales).",
        "Ejecute Generate de nuevo y complete solo Validar Pago y Tipo de aplicación. "
        "No se piden montos en el Excel actual.",
    ),
    "missing_abono_k": (
        "Este resultado corresponde a un esquema de revisión anterior (columnas de montos manuales).",
        "Ejecute Generate de nuevo y complete solo Validar Pago y Tipo de aplicación. "
        "No se piden montos en el Excel actual.",
    ),
    "missing_abono_capital": (
        "Este resultado corresponde a un esquema de revisión anterior (columnas de montos manuales).",
        "Ejecute Generate de nuevo y complete solo Validar Pago y Tipo de aplicación. "
        "No se piden montos en el Excel actual.",
    ),
    "missing_mora_a_aplicar": (
        "Este resultado corresponde a un esquema de revisión anterior (columnas de montos manuales).",
        "Ejecute Generate de nuevo y complete solo Validar Pago y Tipo de aplicación. "
        "No se piden montos en el Excel actual.",
    ),
    "missing_otros_valores": (
        "Este resultado corresponde a un esquema de revisión anterior (columnas de montos manuales).",
        "Ejecute Generate de nuevo y complete solo Validar Pago y Tipo de aplicación. "
        "No se piden montos en el Excel actual.",
    ),
    "review_schema_version_1_requires_regenerate": (
        "El archivo de revisión usa un esquema antiguo (ReviewSchemaVersion 1).",
        "Ejecute Generate de nuevo para obtener el workbook de revisión actual.",
    ),
    "review_schema_requires_regeneration": (
        "El archivo de revisión usa el esquema anterior (21 columnas con distribución manual).",
        "Ejecute Generate de nuevo para obtener el Excel simplificado (Validar Pago y Tipo de aplicación). "
        "No se puede finalizar un archivo v3 con el proceso actual.",
    ),
    "unsupported_review_schema_version": (
        "El archivo de revisión no tiene un esquema reconocido (ReviewSchemaVersion).",
        "Ejecute Generate de nuevo. No se interpreta un archivo antiguo por el número de columnas.",
    ),
    "review_schema_inconsistent": (
        "El archivo de revisión no es coherente: la versión en _Meta no coincide con las columnas reales.",
        "Ejecute Generate de nuevo. No se interpreta un archivo mezclado (meta v4 con columnas antiguas o incompletas).",
    ),
    # LEGACY: jobs históricos pre-v4.
    "missing_mora": (
        "Este resultado corresponde a un esquema de revisión anterior (columnas de montos manuales).",
        "Ejecute Generate de nuevo y complete solo Validar Pago y Tipo de aplicación. "
        "No se piden montos en el Excel actual.",
    ),
    "duplicate_bank_amount_in_payment_group": (
        "Monto banco está repetido en más de una fila del mismo ID Pago en Aplicacion_Pagos.",
        "Deje Monto banco solo en la primera fila del pago (como en workbooks generados). "
        "Borre el valor duplicado en filas secundarias y vuelva a finalizar.",
    ),
    "amount_mismatch": (
        "El monto del banco no coincide con la suma de los asientos del mismo ID Pago.",
        "Revise los asientos contables reales (valor pagado cliente) frente al monto banco. "
        "No se usan montos manuales del Excel de revisión.",
    ),
    "missing_extract_route": (
        "Una fila validada no tiene ruta o enlace al extracto, o el PDF ya no está en SharePoint.",
        "Vuelva a ejecutar Generate para regenerar enlaces, o corrija Link extracto y la carpeta del crédito. "
        "Guarde y vuelva a finalizar.",
    ),
    "missing_ruta_unidad_credito": (
        "Falta la columna o dato Ruta unidad de crédito necesario para ubicar carpetas.",
        "Ejecute de nuevo Generate con el banco actual (regenera columnas técnicas). No edite a mano columnas bloqueadas. "
        "Vuelva a finalizar.",
    ),
    "credit_number_not_resolved": (
        "No se pudo identificar el número de crédito para crear la carpeta de asientos.",
        "Revise las columnas Crédito y Ruta unidad de crédito en Aplicacion_Pagos. Corrija nombres de carpeta en SharePoint si están mal.",
    ),
    "asientos_folder_create_failed": (
        "SharePoint no dejó crear la carpeta de asientos contables del crédito.",
        "Verifique permisos de escritura y que la ruta del crédito sea correcta. Si el Excel estaba abierto, ciérrelo y reintente.",
    ),
    "missing_ruta_asientos_contables": (
        "Al armar el histórico falta la ruta de la carpeta ASIENTOS CONTABLES.",
        "Ejecute Generate de nuevo y luego Finalize del mismo día, sin saltarse Generate.",
    ),
    "no_validation_file_found": (
        "No hay ningún Excel validacion_pagos_... en la carpeta de revisión para finalizar.",
        "Ejecute primero la generación del archivo de revisión del día. Cuando exista el archivo y esté completo, ejecute la finalización.",
    ),
    "upload_failed": (
        "El proceso validó bien pero no pudo guardar el histórico o el archivo de asientos en SharePoint (red, permisos o archivo bloqueado).",
        "Cierre Excel en escritorio y en el navegador. Verifique espacio y permisos. Reintente Finalize; "
        "si persiste, contacte soporte con la hora del error.",
    ),
    "invalid_validar_abono": (
        "Hay un valor no permitido en Validar Abono (solo se acepta SI o NO).",
        "Abra Aplicacion_Pagos y use la lista desplegable. Guarde y vuelva a finalizar.",
    ),
    "abono_without_selected_credit": (
        "Un abono no tiene ningún crédito seleccionado.",
        "Abra Aplicacion_Pagos y marque SI en al menos un crédito para ese abono.",
    ),
    "abono_duplicate_selected_credit": (
        "Un abono tiene el mismo crédito seleccionado más de una vez.",
        "En Aplicacion_Pagos deje solo una fila en SI por crédito para ese ID Pago.",
    ),
    "abono_group_inconsistent": (
        "Las filas seleccionadas de un abono no son consistentes (cliente, monto, fecha o tipo).",
        "Revise Aplicacion_Pagos: todas las filas SI del mismo ID Pago deben coincidir en cliente, monto y fecha.",
    ),
    "abono_credit_without_unit_path": (
        "Un crédito de abono seleccionado no tiene ruta de unidad de crédito.",
        "Ejecute Generate de nuevo para regenerar rutas técnicas y vuelva a finalizar.",
    ),
    "abono_credit_without_amortization_path": (
        "Un crédito de abono seleccionado no tiene ruta de tabla de amortización.",
        "Ejecute Generate de nuevo y verifique la tabla en SharePoint antes de finalizar.",
    ),
    "abono_missing_bank_amount": (
        "Un abono seleccionado no tiene monto bancario.",
        "Revise Aplicacion_Pagos o ejecute Generate de nuevo.",
    ),
    "abono_missing_bank_date": (
        "Un abono seleccionado no tiene fecha bancaria.",
        "Revise Aplicacion_Pagos o ejecute Generate de nuevo.",
    ),
    "abono_invalid_application_type": (
        "Una fila de Aplicacion_Pagos no está marcada correctamente como ABONO.",
        "Ejecute Generate de nuevo; no edite a mano las columnas técnicas TipoAplicacion o RequiereExtracto.",
    ),
    "abono_mora_missing_reference_extract": (
        "Un ABONO MORA seleccionado no tiene extracto de referencia.",
        "Revise Aplicacion_Pagos: cada crédito ABONO MORA con Validar Abono = SI debe tener link o ruta de extracto. "
        "Guarde y vuelva a finalizar.",
    ),
    "abono_mora_missing_reference_date": (
        "Un ABONO MORA seleccionado no tiene fecha límite de referencia.",
        "Complete Fecha límite en Aplicacion_Pagos para cada crédito ABONO MORA validado y vuelva a finalizar.",
    ),
    "missing_reference_extract_route": (
        "Un ABONO MORA validado no tiene ruta resoluble al extracto de referencia en SharePoint.",
        "Verifique el link de extracto en Aplicacion_Pagos y que el PDF exista en la carpeta del crédito. "
        "Guarde y vuelva a finalizar.",
    ),
    # LEGACY: jobs históricos pre-v4 (columnas de montos). El Finalize actual no los emite.
    "pago_y_abono_capital_missing_parte_cuota": (
        "Este resultado corresponde a un esquema de revisión anterior (parte de cuota en el Excel).",
        "Ejecute Generate de nuevo y complete solo Validar Pago y Tipo de aplicación. "
        "Los importes salen del asiento, no del Excel.",
    ),
    "pago_y_abono_capital_missing_capital": (
        "Este resultado corresponde a un esquema de revisión anterior (abono a capital en el Excel).",
        "Ejecute Generate de nuevo y complete solo Validar Pago y Tipo de aplicación. "
        "Los importes salen del asiento, no del Excel.",
    ),
    "pago_y_abono_capital_saldo_must_be_zero": (
        "Un PAGO Y ABONO CAPITAL validado no cuadra el monto banco con los asientos.",
        "Revise el asiento contable frente al monto banco y vuelva a finalizar.",
    ),
    "missing_control_sheet": (
        "Este resultado corresponde a un esquema de revisión anterior (hoja Control).",
        "Ejecute Generate de nuevo y trabaje solo sobre el archivo que genera el sistema. "
        "El cierre se confirma con Finalizar en la aplicación, no en una hoja Control.",
    ),
    "missing_distribucion_sheet": (
        "El archivo de revisión no tiene la hoja Aplicacion_Pagos.",
        "Ejecute Generate y use solo el archivo que genera el sistema.",
    ),
    "missing_sheet_headers": (
        "Las tablas de Aplicacion_Pagos u otra hoja no tienen los encabezados esperados; el archivo fue modificado de más.",
        "Vuelva a ejecutar Generate. No borre filas de encabezado ni renombre columnas.",
    ),
    "credit_folder_not_found": (
        "Al cerrar el día, no se encontró la carpeta del crédito para un extracto validado.",
        "Verifique en SharePoint que la carpeta del crédito exista y coincida con el nombre en Aplicacion_Pagos. "
        "Corrija y vuelva a finalizar.",
    ),
    "credit_folder_ambiguous": (
        "Hay varias carpetas posibles para el mismo crédito; el sistema no puede elegir una.",
        "Deje una sola carpeta por crédito (nombres únicos en SharePoint). Vuelva a finalizar.",
    ),
    # LEGACY: jobs históricos pre-v4. El Finalize actual no exige total aplicado del Excel.
    "validar_requires_positive_total": (
        "Este resultado corresponde a un esquema de revisión anterior (total aplicado en el Excel).",
        "Ejecute Generate de nuevo y complete solo Validar Pago y Tipo de aplicación. "
        "No se piden montos en el Excel actual.",
    ),
    "invalid_bank_code": (
        "No fue posible finalizar el proceso porque el banco indicado no es válido.",
        "No continúe con el siguiente paso. Contacte a soporte e indique el banco, la fecha y la etapa del proceso.",
    ),
    "NO_READY_PROCESS": (
        "Este paso se ejecutó antes de tiempo: todavía no hay una revisión lista para finalizar.",
        "Haga primero: genere el Excel de revisión del banco, complete Validar Pago y Tipo de aplicación "
        "y pulse Finalizar en la aplicación.",
    ),
    "MULTIPLE_READY_PROCESSES": (
        "Hay más de un banco con revisión lista para finalizar al mismo tiempo.",
        "Indique en la solicitud cuál banco desea finalizar (Bogotá o Bancolombia) y vuelva a ejecutar este paso. "
        "Si no puede indicar el banco, contacte a soporte con ambos nombres y la fecha.",
    ),
    "control_not_ready_for_finalize": (
        "Este paso se ejecutó antes de tiempo: aún no hay un Excel de revisión activo para ese banco.",
        "Ejecute primero la generación del archivo de revisión (Generate). Cuando el Excel esté en la carpeta de "
        "revisión y lo haya completado, vuelva a ejecutar la finalización.",
    ),
    "missing_validation_file_path": (
        "Este paso se ejecutó antes de tiempo: el sistema aún no tiene registrada la ruta del Excel de revisión.",
        "Ejecute de nuevo la generación del archivo de revisión para ese banco y, cuando exista el Excel en la "
        "carpeta de revisión, vuelva a finalizar.",
    ),
    "active_process_exists": (
        "Ya existe un proceso activo en el control del banco y no se puede finalizar otro proceso distinto.",
        "Ejecute Cancelar proceso activo solo si el lote aún está en revisión y realmente debe abortarse; "
        "si el proceso ya avanzó (Finalize/Merge), contacte a soporte. No edite el Excel de control.",
    ),
}

_CANCEL_MESSAGES: dict[str, tuple[str, str]] = {
    "cancel_not_allowed": (
        "No se puede cancelar este proceso en el estado actual.",
        "Espere a que termine la operación en curso o continúe desde la fase indicada. "
        "No edite el Excel de control: está protegido.",
    ),
    "cancel_not_allowed_financial_writes": (
        "No se puede cancelar porque ya existen escrituras en tablas de amortización.",
        "No hay rollback automático. Continúe con la recuperación o el reintento de "
        "amortización del mismo proceso.",
    ),
    "cancel_not_allowed_financial_writes_unknown": (
        "No se puede cancelar porque no es posible descartar escrituras financieras previas.",
        "Por seguridad no se libera el lote. Revise la recuperación de amortización "
        "del mismo proceso.",
    ),
    "cancel_cleanup_failed": (
        "No se completó la limpieza segura de los artefactos reversibles.",
        "El proceso sigue activo y no se liberó el lote. Revise el problema operativo "
        "y vuelva a intentar la cancelación.",
    ),
    "process_key_mismatch": (
        "La clave de proceso indicada no coincide con el proceso activo en el control del banco.",
        "Verifique el banco y la clave del proceso (o omita process_key) y vuelva a ejecutar "
        "Cancelar proceso activo.",
    ),
    "MULTIPLE_READY_PROCESSES": (
        "Hay más de un banco con un proceso de revisión activo al mismo tiempo.",
        "Indique bank_code (banco_bogota o banco_bancolombia) en Cancelar proceso activo "
        "y vuelva a ejecutar. No edite el Excel de control.",
    ),
    "invalid_bank_code": (
        "No fue posible cancelar el proceso porque el banco indicado no es válido.",
        "Use banco_bogota o banco_bancolombia y vuelva a intentar.",
    ),
    "bank_code_required": (
        "No fue posible cancelar el proceso porque falta el código del banco.",
        "Indique bank_code (banco_bogota o banco_bancolombia) y vuelva a intentar.",
    ),
    "missing_sharepoint_folder": (
        "No fue posible cancelar el proceso debido a un inconveniente de configuración en SharePoint.",
        "No continúe con el siguiente paso. Contacte a soporte e indique el banco y la etapa del proceso.",
    ),
    "process_control_invalid_structure": (
        "El control de proceso del banco no tiene la estructura esperada.",
        "Contacte a soporte. No edite el Excel de control a mano.",
    ),
}

_SOFT_CLOSE_MESSAGES: dict[str, tuple[str, str]] = {
    "soft_close_not_allowed": (
        "No se puede cerrar sin amortizar en el estado actual del proceso.",
        "Esta opción solo aplica cuando el proceso ya consolidó o está en amortización. "
        "Si aún está en revisión, use «Cancelar lote» o «Regenerar». "
        "No edite el Excel de control: está protegido.",
    ),
    "soft_close_reason_required": (
        "Debe indicar un motivo corto para cerrar el proceso sin amortizar.",
        "Escriba el motivo en el diálogo de confirmación y vuelva a confirmar.",
    ),
    "soft_close_reason_too_long": (
        "El motivo es demasiado largo.",
        "Resuma el motivo en pocas palabras y vuelva a confirmar.",
    ),
    "process_key_mismatch": (
        "La clave de proceso indicada no coincide con el proceso activo en el control del banco.",
        "Actualice el detalle del proceso y vuelva a intentar.",
    ),
    "process_key_required": (
        "Falta la clave del proceso para cerrar sin amortizar.",
        "Abra el detalle del proceso desde el panel e intente de nuevo.",
    ),
    "invalid_bank_code": (
        "No fue posible cerrar el proceso porque el banco indicado no es válido.",
        "Use banco_bogota o banco_bancolombia y vuelva a intentar.",
    ),
    "missing_sharepoint_folder": (
        "No fue posible cerrar el proceso debido a un inconveniente de configuración en SharePoint.",
        "Contacte a soporte e indique el banco y la etapa del proceso.",
    ),
}

_GLOBAL_ERROR_MESSAGES: dict[str, tuple[str, str]] = {
    "amortization_table_ambiguous": (
        "Hay más de una tabla de amortización posible para un crédito y no fue posible determinar cuál usar.",
        "Deje una sola tabla de amortización por crédito en SharePoint y vuelva a ejecutar la generación del archivo de revisión. "
        "Si el error continúa, contacte a soporte.",
    ),
    "bank_amount_parse_error": (
        "No fue posible leer el monto bancario de un grupo; el valor no tiene formato numérico válido.",
        "Revise el monto en Aplicacion_Pagos o Aplicacion_Pagos y vuelva a ejecutar la finalización.",
    ),
    "bank_code_and_process_date_required": (
        "No fue posible continuar porque faltan datos internos del proceso.",
        "No continúe con la validación previa ni con la aplicación. Contacte a soporte para revisar el estado del proceso.",
    ),
    "bank_date_parse_error": (
        "No fue posible leer la fecha bancaria de un abono.",
        "Corrija la fecha en Aplicacion_Pagos y vuelva a ejecutar la finalización.",
    ),
    "control_not_ready_for_dry_run": (
        "Este paso se ejecutó antes de tiempo: todavía no se puede hacer la validación previa de amortización.",
        "Haga primero la unión de PDF (Unir PDFs / consolidar asientos contables) hasta que termine bien. "
        "Cuando eso esté listo, vuelva a ejecutar la validación previa de amortización.",
    ),
    "control_not_ready_for_merge": (
        "Este paso se ejecutó antes de tiempo: todavía no se puede unir los PDF de asientos contables.",
        "Haga primero: 1) finalizar la revisión del día y 2) enviar el correo de extractos. "
        "Después cargue los asientos contables en cada crédito y vuelva a ejecutar Unir PDFs.",
    ),
    "destination_name_exhausted": (
        "No se encontró un nombre disponible para guardar un PDF consolidado sin sobrescribir otro archivo.",
        "Revise la carpeta destino del consolidado, archive PDF antiguos si hace falta y vuelva a ejecutar la unión de PDF.",
    ),
    "missing_distribucion_abonos_headers": (
        "El histórico no tiene los encabezados esperados en Aplicacion_Pagos.",
        "Vuelva a ejecutar la finalización con la plantilla actual; no edite los encabezados a mano.",
    ),
    "missing_distribucion_pagos_sheet": (
        "El histórico no tiene la hoja Aplicacion_Pagos necesaria para este paso.",
        "Vuelva a ejecutar la finalización con el archivo generado por el sistema (no utilice una copia manual).",
    ),
    "missing_merge_manifest_path": (
        "No fue posible localizar el registro interno de la unión de documentos.",
        "No continúe con la validación previa ni con la aplicación. Contacte a soporte para revisar el estado del proceso.",
    ),
    "pdf_no_text": (
        "El PDF cargado no contiene texto legible para la automatización.",
        "Verifique que el documento sea correcto y que su contenido pueda seleccionarse. "
        "Cargue una copia legible y vuelva a ejecutar la validación previa. Si el error continúa, contacte a soporte.",
    ),
    "preflight_errors": (
        "La validación previa detectó errores que impiden continuar.",
        "Revise los asientos, extractos y tablas indicados en el resumen de la validación previa. "
        "Corrija los documentos y vuelva a ejecutar la validación previa.",
    ),
    "preflight_revision_manual": (
        "La validación previa requiere revisión manual de uno o más movimientos.",
        "Revise el Excel de revisión o el histórico según el tipo de problema y vuelva a ejecutar la validación previa.",
    ),
    "preflight_warnings_not_allowed": (
        "La validación previa encontró advertencias que no están permitidas para continuar.",
        "Corrija las advertencias señaladas en el resumen y vuelva a ejecutar la validación previa.",
    ),
    "process_control_invalid_structure": (
        "El control de proceso del banco no tiene la estructura esperada.",
        "No continúe con el siguiente paso. Contacte a soporte para revisar el estado del proceso.",
    ),
}


_MERGE_SKIP_OPERATOR_HINTS: tuple[tuple[str, str, str], ...] = (
    (
        "PDF_TEXT_NOT_EXTRACTABLE",
        "El PDF no trae texto que se pueda leer automáticamente (puede ser solo imagen).",
        "Exporte de nuevo el asiento desde el ERP con texto seleccionable, "
        "reemplácelo en ASIENTOS y vuelva a unir PDFs.",
    ),
    (
        "ACCOUNTING_PARSE_FAILED",
        "El PDF no tiene el formato de asiento contable esperado.",
        "Vuelva a exportarlo desde el ERP (cuenta y monto en la misma línea), "
        "reemplácelo en ASIENTOS y vuelva a unir PDFs.",
    ),
    (
        "MISSING_BANK_VALUE_BUT_HAS_ACCOUNTING_LINES",
        "Se vieron movimientos contables, pero falta la línea del recaudo del banco.",
        "Revise el renglón del banco en el asiento, reemplace el PDF en ASIENTOS "
        "y vuelva a unir PDFs.",
    ),
    (
        "ASIENTO_ASSIGNMENT_PARSE_FAILED",
        "Hay un PDF de asiento que no se pudo leer como asiento contable.",
        "Abra el PDF en ASIENTOS, use la exportación del ERP con texto seleccionable "
        "y vuelva a unir PDFs.",
    ),
    (
        "ASIENTO_ASSIGNMENT_NO_MATCH",
        "Los montos de los asientos no cuadran con el monto banco del pago.",
        "Revise el monto banco en el histórico y deje en ASIENTOS un PDF por crédito "
        "cuyo valor cuadre con el banco.",
    ),
    (
        "ASIENTO_ASSIGNMENT_AMBIGUOUS",
        "Hay más de una forma de cuadrar los asientos con los pagos del lote.",
        "Deje en ASIENTOS solo los PDF de este lote y vuelva a unir PDFs.",
    ),
    (
        "ASIENTO_ASSIGNMENT_COMPLEXITY_LIMIT",
        "Hay demasiadas combinaciones posibles entre asientos y pagos.",
        "Deje en ASIENTOS únicamente los asientos de este lote y vuelva a unir PDFs.",
    ),
    (
        "extract_routes_missing",
        "Falta la ruta del extracto PDF en el histórico o el archivo no está en SharePoint.",
        "Verifique el extracto en la carpeta del crédito y vuelva a finalizar si hace falta; "
        "luego reintente la consolidación.",
    ),
    (
        "asiento_contable_not_found",
        "No hay PDF de asiento usable en la carpeta ASIENTOS del crédito.",
        "Cargue el asiento contable en ASIENTOS CONTABLES del crédito y vuelva a unir PDFs.",
    ),
    (
        "missing_ruta_asientos_contables",
        "El histórico no tiene la ruta de la carpeta ASIENTOS del crédito.",
        "Vuelva a finalizar la revisión para provisionar las rutas y reintente la consolidación.",
    ),
)


def _merge_skip_blob(result: dict[str, Any]) -> str:
    parts: list[str] = []
    for line in result.get("skipped") or []:
        parts.append(str(line))
    for group in result.get("incomplete_groups") or []:
        if not isinstance(group, dict):
            continue
        for line in group.get("skip_lines") or []:
            parts.append(str(line))
    return " ".join(parts)


def merge_skip_operator_copy(code: str) -> tuple[str, str] | None:
    """Copy quirúrgico para un código de skip/faltante de Merge."""
    want = str(code or "").strip()
    if not want:
        return None
    for mapped, user, nxt in _MERGE_SKIP_OPERATOR_HINTS:
        if mapped == want:
            return user, nxt
    return None


def _merge_failure_operator_message(result: dict[str, Any]) -> tuple[str, str] | None:
    blob = _merge_skip_blob(result)
    if not blob.strip():
        return None
    for code, user, nxt in _MERGE_SKIP_OPERATOR_HINTS:
        if code in blob:
            return user, nxt
    return None


def finalize_message_for_code(code: str) -> tuple[str, str]:
    """
    Devuelve (user_message, next_action) para un código de error de Finalize.

    Uso: proyección UI de issues individuales dentro de multiple_review_errors,
    donde cada punto listado necesita su propio mensaje operativo (no el genérico
    del contenedor «Se encontraron N problemas...»).
    """
    if code in _FINALIZE_MESSAGES:
        return _FINALIZE_MESSAGES[code]
    if code in _GLOBAL_ERROR_MESSAGES:
        return _GLOBAL_ERROR_MESSAGES[code]
    if code in _GENERATE_MESSAGES:
        return _GENERATE_MESSAGES[code]
    return (_UNKNOWN_USER, _UNKNOWN_NEXT)


def _strip_exception_prefix(message: str) -> str:
    s = (message or "").strip()
    m = re.match(r"^(?:ValueError|RuntimeError|GraphConfigError|HTTPStatusError|Exception)\s*:\s*(.*)$", s, re.I | re.S)
    if m:
        return m.group(1).strip()
    return s


def _pick_table_code(table: dict[str, tuple[str, str]], raw: str) -> str | None:
    if raw in table:
        return raw
    for k in sorted(table.keys(), key=len, reverse=True):
        if k in raw:
            return k
    return None


def _error_code_from_generate_or_finalize_message(job_type: str, message: str) -> str:
    raw = _strip_exception_prefix(message)
    if "|" in raw and raw.lower().startswith("upload_failed"):
        return "upload_failed"
    if job_type == "generate":
        hit = _pick_table_code(_GENERATE_MESSAGES, raw)
        if hit:
            return hit
    if job_type == "finalize":
        for code in _FINALIZE_MESSAGES:
            if raw == code or raw.startswith(code + "|") or raw.startswith(code + " "):
                return code
        hit = _pick_table_code(_FINALIZE_MESSAGES, raw)
        if hit:
            return hit
        for code in _GENERATE_MESSAGES:
            if raw == code or raw.startswith(code + "|") or raw.startswith(code + " "):
                return code
        hit = _pick_table_code(_GENERATE_MESSAGES, raw)
        if hit:
            return hit
    if job_type == "cancel_active_process":
        for code in _CANCEL_MESSAGES:
            if raw == code or raw.startswith(code + "|") or raw.startswith(code + " "):
                return code
        hit = _pick_table_code(_CANCEL_MESSAGES, raw)
        if hit:
            return hit
    if job_type == "soft_close_process":
        for code in _SOFT_CLOSE_MESSAGES:
            if raw == code or raw.startswith(code + "|") or raw.startswith(code + " "):
                return code
        hit = _pick_table_code(_SOFT_CLOSE_MESSAGES, raw)
        if hit:
            return hit
    return raw.split("|", 1)[0].strip()[:120] or "unknown_error"


def _multiple_review_errors_count(message: str) -> int | None:
    """Extrae «count» del payload JSON de multiple_review_errors|{...}."""
    raw = (message or "").strip()
    if "|" not in raw:
        return None
    _, rest = raw.split("|", 1)
    rest = rest.strip()
    if not rest.startswith("{"):
        return None
    try:
        parsed = json.loads(rest)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if isinstance(parsed, dict):
        count = parsed.get("count")
        if isinstance(count, int) and count > 0:
            return count
    return None


def _lookup_generate_finalize(job_type: str, code: str, full_message: str) -> tuple[str, str, str]:
    if job_type == "generate":
        table = _GENERATE_MESSAGES
    elif job_type == "finalize":
        table = _FINALIZE_MESSAGES
    elif job_type == "cancel_active_process":
        table = _CANCEL_MESSAGES
    elif job_type == "soft_close_process":
        table = _SOFT_CLOSE_MESSAGES
    else:
        return _mapped("unknown_error", _UNKNOWN_USER, _UNKNOWN_NEXT)

    if code in _GLOBAL_ERROR_MESSAGES:
        u, n = _GLOBAL_ERROR_MESSAGES[code]
        return _mapped(code, u, n)
    if code == "multiple_review_errors" and code in table:
        u, n = table[code]
        count = _multiple_review_errors_count(full_message)
        if count is not None:
            u = f"Se encontraron {count} problemas en la revisión."
        return _mapped(code, u, n)
    if code in table:
        u, n = table[code]
        return _mapped(code, u, n)
    hit = _pick_table_code(table, _strip_exception_prefix(full_message))
    if hit and hit in table:
        u, n = table[hit]
        return _mapped(hit, u, n)
    # Códigos v4 de revisión pueden vivir en Generate o Finalize; no caer a soporte.
    if job_type in ("generate", "finalize"):
        other = _GENERATE_MESSAGES if table is _FINALIZE_MESSAGES else _FINALIZE_MESSAGES
        if code in other:
            u, n = other[code]
            return _mapped(code, u, n)
        hit_other = _pick_table_code(other, _strip_exception_prefix(full_message))
        if hit_other and hit_other in other:
            u, n = other[hit_other]
            return _mapped(hit_other, u, n)
    resolved = code if code and code != "unknown_error" else "unknown_error"
    return _mapped(resolved, _UNKNOWN_USER, _UNKNOWN_NEXT)


def _notify_merge_string_mapping(job_type: str, msg: str) -> tuple[str, str, str]:
    mlow = msg.lower()
    base_code = msg.strip().split("|", 1)[0].strip()
    if base_code in _GLOBAL_ERROR_MESSAGES:
        u, n = _GLOBAL_ERROR_MESSAGES[base_code]
        return _mapped(base_code, u, n)

    if job_type == "notify_validar_extractos":
        mstripped = msg.strip()
        if mstripped == "NO_READY_PROCESS":
            return (
                "Este paso se ejecutó antes de tiempo: todavía no hay un histórico listo para enviar el correo de extractos.",
                "Haga primero la finalización de la revisión del banco (Finalize). "
                "Cuando esa finalización termine bien, vuelva a ejecutar el envío del correo.",
                "NO_READY_PROCESS",
            )
        if mstripped.startswith("MULTIPLE_READY_PROCESSES"):
            return _mapped(
                "MULTIPLE_READY_PROCESSES",
                "Hay más de un banco listo para enviar el correo de extractos al mismo tiempo.",
                "Indique en la solicitud cuál banco desea notificar (Bogotá o Bancolombia) y vuelva a ejecutar este paso. "
                "Si no puede indicar el banco, contacte a soporte con ambos nombres y la fecha.",
            )
        if mstripped == "control_not_ready_for_notify":
            return (
                "Este paso se ejecutó antes de tiempo: el banco aún no está listo para el correo de extractos.",
                "Si todavía no cerró el día, ejecute primero la finalización de la revisión. "
                "Cuando Finalize termine, vuelva a ejecutar el envío del correo.",
                "control_not_ready_for_notify",
            )
        if mstripped == "already_notified":
            return (
                "El correo de extractos de este proceso ya se envió; no es necesario repetir este paso.",
                "Revise la bandeja de los destinatarios. El siguiente paso es cargar los asientos contables "
                "y luego ejecutar Unir PDFs (consolidación de asientos contables).",
                "already_notified",
            )
        if mstripped == "missing_historical_file_path" or mstripped.startswith(
            "missing_historical_file_path|"
        ):
            return _mapped(
                "missing_historical_file_path",
                "No se pudo resolver el histórico para el correo (falta la ruta del Excel cartera_validada).",
                "Ejecute Finalizar validación de pagos (Flujo 2) para ese banco y, si el error continúa, contacte a soporte.",
            )
        if mstripped.startswith("historical_file_not_found"):
            return (
                "No se pudo abrir el archivo histórico de validación en SharePoint (no existe, fue movido o sin permiso).",
                "Confirme que el Flujo 2 terminó correctamente y que el histórico del día sigue en la carpeta de "
                "histórico. Si fue movido o borrado, contacte a soporte antes de volver a ejecutar el Flujo 2.",
                "historical_file_not_found",
            )
        if "no hay excel" in mlow and "hist" in mlow:
            return (
                "No se encontró el Excel histórico del día en la carpeta de histórico de validación de pagos.",
                "Verifique en la carpeta de histórico que exista cartera_validada con la fecha del reporte. "
                "Si falta, ejecute Finalize de nuevo antes del correo.",
                "historical_file_not_found",
            )
        if mstripped == "missing_distribucion_headers" or mstripped.startswith(
            "missing_distribucion_headers|"
        ) or (
            "no se encontró una hoja llamada" in mlow and "distribución" in mlow
        ):
            return (
                "El archivo histórico no tiene la hoja Aplicacion_Pagos que el correo necesita leer.",
                "Use el histórico generado por Finalize del mismo flujo (no un Excel copiado a mano). "
                "Si el archivo es antiguo, vuelva a ejecutar Finalize y reintente el correo.",
                "missing_distribucion_headers",
            )
        if mstripped == "missing_distribucion_status_column" or mstripped.startswith(
            "missing_distribucion_status_column|"
        ):
            return (
                "En el histórico falta la columna para saber qué pagos van en el correo "
                "(Validar Pago, o Estado en archivos viejos).",
                "Vuelva a ejecutar Finalize con el Excel de revisión actual del sistema. "
                "No edite manualmente los encabezados de Aplicacion_Pagos.",
                "missing_distribucion_status_column",
            )
        if mstripped == "missing_distribucion_route_column" or mstripped.startswith(
            "missing_distribucion_route_column|"
        ):
            return (
                "En el histórico falta la columna Ruta, necesaria para adjuntar los PDF de extractos.",
                "Ejecute de nuevo Generate y Finalize del día para regenerar la columna Ruta. "
                "Luego reintente el envío de correo.",
                "missing_distribucion_route_column",
            )
        if "no se encontraron encabezados" in mlow and "distribución" in mlow:
            return (
                "La hoja Aplicacion_Pagos del histórico no tiene la fila de encabezados que el sistema espera.",
                "No modifique la primera fila de títulos del histórico. Regenere el archivo con Finalize.",
                "missing_distribucion_headers",
            )
        if "faltan columnas" in mlow or (
            "estado" in mlow and "línea" in mlow and "ruta" in mlow and "requeridas" in mlow
        ):
            return (
                "El histórico no tiene todas las columnas necesarias (estado y ruta de extractos).",
                "Ejecute Finalize otra vez con la plantilla actual. Revise que Aplicacion_Pagos conserve Ruta y Estado Pago.",
                "missing_ruta_column",
            )
        if "no hay filas" in mlow and ("estado" in mlow or "línea" in mlow or "linea" in mlow):
            return (
                "En el histórico no hay filas marcadas para enviar en el correo "
                "(Validar Pago = SI o estado VALIDAR según configuración).",
                "Abra el histórico en Aplicacion_Pagos y confirme que haya pagos validados para el día. "
                "Si no se marcaron filas, corrija el Excel de revisión y vuelva a ejecutar la finalización.",
                "no_validated_rows",
            )
        if "no hay destinatarios" in mlow or (
            "receptores" in mlow and "vacía" in mlow
        ):
            return (
                "El correo no se envió porque no hay destinatarios válidos (columna RECEPTORES vacía o correos mal escritos).",
                "Abra CORREOS.xlsx en la carpeta de control: la columna RECEPTORES debe tener al menos un correo por fila. "
                "Guarde el archivo y vuelva a ejecutar Finalizar validación de pagos (Flujo 2).",
                "recipients_not_configured",
            )
        if "emisor" in mlow or "receptores" in mlow or "correos" in mlow or "remitente" in mlow:
            return (
                "Falta configurar quién envía o quién recibe el correo en CORREOS.xlsx (EMISOR y RECEPTORES).",
                "En CORREOS.xlsx de la carpeta de control complete EMISOR (un correo) y RECEPTORES (uno o más correos). "
                "Guarde el archivo en SharePoint y vuelva a ejecutar Finalizar validación de pagos (Flujo 2).",
                "recipients_not_configured",
            )
        if "no hay columna fecha" in mlow and "banco" in mlow:
            return (
                "El reporte del banco BANCO_BOGOTA.xlsx no tiene columna Fecha; el correo no puede saber el día del abono.",
                "Revise el Excel del banco en la carpeta de carga de transacciones del banco y agregue la columna "
                "Fecha como en días anteriores. Suba el archivo y reintente.",
                "bank_report_missing_date_column",
            )
        if "ninguna fecha válida" in mlow and "fecha" in mlow:
            return (
                "El reporte del banco tiene columna Fecha pero ninguna fecha se pudo leer (celdas vacías o formato distinto).",
                "Revise que las filas de pagos tengan fecha en formato habitual (dd/mm/aaaa o similar). "
                "Corrija BANCO_BOGOTA.xlsx y reintente el correo.",
                "bank_report_no_valid_dates",
            )
        if "banco bogotá" in mlow or "banco bogota" in mlow:
            if "filas" in mlow or "columnas" in mlow:
                return (
                    "El reporte del banco no tiene datos completos para armar la tabla del correo "
                    "(filas vacías, columnas faltantes o celdas incompletas).",
                    "Abra BANCO_BOGOTA.xlsx: cada fila del correo debe tener todos los campos llenos según la plantilla. "
                    "Suba el archivo corregido a SharePoint y reintente.",
                    "bank_report_invalid_data",
                )
        if "define graph" in mlow or "graphconfigerror" in mlow.replace(" ", ""):
            return (
                "Falta configuración del sistema para ubicar carpetas de histórico o correo.",
                "No continúe con el siguiente paso. Contacte a soporte e indique el banco, la fecha y la etapa del proceso.",
                "notify_config_missing",
            )
        if "descarg" in mlow or ("no se pudo" in mlow and "pdf" in mlow):
            return (
                "Uno de los PDF de extractos que debían adjuntarse al correo no se encontró o no se pudo descargar.",
                "En el histórico, columna Ruta: abra cada enlace y confirme que el PDF existe en SharePoint. "
                "Suba el extracto faltante y reintente.",
                "extract_pdf_not_found",
            )
        if "sendmail" in mlow or ("graph" in mlow and ("401" in msg or "403" in msg or "error" in mlow)):
            return (
                "No fue posible enviar el correo de extractos (permisos del buzón, remitente o destinatarios).",
                "Verifique en CORREOS.xlsx que EMISOR sea un buzón autorizado y que RECEPTORES tenga correos válidos. "
                "Luego vuelva a ejecutar Finalizar validación de pagos (Flujo 2). Si persiste, contacte a soporte.",
                "graph_sendmail_failed",
            )

    if job_type == "merge_composite_validado_pdfs":
        mstripped = msg.strip()
        if mstripped == "NO_READY_PROCESS":
            return (
                "Este paso se ejecutó antes de tiempo: todavía no se puede unir los PDF de asientos contables.",
                "Haga primero, en este orden: 1) finalizar la revisión del día y 2) enviar el correo de extractos. "
                "Después cargue los PDF de asientos contables en cada crédito y vuelva a ejecutar Unir PDFs.",
                "NO_READY_PROCESS",
            )
        if mstripped.startswith("MULTIPLE_READY_PROCESSES"):
            return _mapped(
                "MULTIPLE_READY_PROCESSES",
                "Hay más de un banco listo para Unir PDFs al mismo tiempo.",
                "Indique en la solicitud cuál banco desea consolidar (Bogotá o Bancolombia) y vuelva a ejecutar Unir PDFs. "
                "Si no puede indicar el banco, contacte a soporte con ambos nombres y la fecha.",
            )
        if mstripped == "merge_control_no_pending_process":
            return (
                "Este paso se ejecutó antes de tiempo: el sistema aún no tiene registrado el correo del día para Unir PDFs.",
                "Ejecute primero la finalización de la revisión y luego el envío del correo de extractos. "
                "Cuando el correo se haya enviado, cargue los asientos y vuelva a ejecutar Unir PDFs.",
                "merge_control_no_pending_process",
            )
        if mstripped == "missing_historical_file_path":
            return (
                "Este paso se ejecutó antes de tiempo: falta el histórico del día necesario para Unir PDFs.",
                "Ejecute de nuevo el envío del correo de extractos (después de Finalize). "
                "Si el error continúa, contacte a soporte.",
                "missing_historical_file_path",
            )
        if mstripped == "missing_email_pdf_path":
            return (
                "Este paso se ejecutó antes de tiempo: falta la copia PDF del correo del día.",
                "Ejecute de nuevo el envío del correo y confirme que el PDF quede en la carpeta de correos enviados. "
                "Luego vuelva a ejecutar Unir PDFs.",
                "missing_email_pdf_path",
            )
        if mstripped == "merge_control_workbook_not_found":
            return (
                f"No existe {_PROCESS_CONTROL_FILES_HINT}; sin ese archivo no puede iniciar la unión de PDFs.",
                "No continúe con el siguiente paso. Contacte a soporte para revisar la configuración del control de proceso.",
                "merge_control_workbook_not_found",
            )
        if mstripped == "merge_control_invalid_structure":
            return (
                f"El control de proceso del banco está dañado o fue editado (falta hoja Procesos, encabezados o fila 2).",
                f"No modifique {_PROCESS_CONTROL_FILES_HINT} a mano. Ejecute setup o pida a soporte y repita correo + Unir PDFs.",
                "merge_control_invalid_structure",
            )
        if "no se encontró pdf de correo" in mlow:
            return (
                "No se encontró en la carpeta de correos enviados el PDF del correo para la fecha del reporte del banco.",
                "Ejecute primero el envío de correo del día y verifique que el PDF se guarde en la carpeta de "
                "correos enviados de validación de pagos. Luego reintente Unir PDFs.",
                "email_pdf_not_found",
            )
        if mstripped == "missing_distribucion_headers" or mstripped.startswith(
            "missing_distribucion_headers|"
        ) or (
            "no se encontró una hoja llamada" in mlow and "distribución" in mlow
        ):
            return (
                "El histórico del día no tiene la hoja Aplicacion_Pagos que se necesita para saber qué pagos unir.",
                "Use el cartera_validada generado por Finalize del mismo flujo. Si el archivo es copia manual, "
                "vuelva a ejecutar Finalize y reintente.",
                "missing_distribucion_headers",
            )
        if mstripped == "missing_distribucion_status_column" or mstripped.startswith(
            "missing_distribucion_status_column|"
        ) or (
            "estado pago" in mlow and "requieren columnas" in mlow
        ):
            return (
                "El histórico no indica qué pagos deben consolidarse (falta Validar Pago o Estado línea).",
                "Ejecute de nuevo Generate y Finalize del día. No altere encabezados de Aplicacion_Pagos en el histórico.",
                "missing_distribucion_status_column",
            )
        if mstripped == "missing_distribucion_route_column" or mstripped.startswith(
            "missing_distribucion_route_column|"
        ) or (
            "rutaasientoscontables" in mlow.replace(" ", "")
            and "requieren" in mlow
        ):
            return (
                "Al histórico le faltan columnas obligatorias: Ruta (extractos), RutaAsientosContables e ID Pago.",
                "Regenere el histórico con Finalize actual (incluye rutas técnicas). Luego correo y Unir PDFs.",
                "missing_distribucion_route_column",
            )
        if "en distribución se requieren columnas" in mlow:
            return (
                "El histórico no tiene todas las columnas para armar los PDF unidos (estado, rutas, ID Pago).",
                "Vuelva a Finalize con la plantilla vigente. Revise Aplicacion_Pagos: Ruta, RutaAsientosContables, ID Pago.",
                "missing_distribucion_columns",
            )
        if "no hay filas cuyo estado" in mlow or "estado línea contenga" in mlow or "estado linea contenga" in mlow:
            return (
                "No hay pagos en el histórico marcados para consolidar (ninguna fila coincide con VALIDAR / Validar Pago = SI).",
                "En el histórico, hoja Aplicacion_Pagos, confirme que haya filas validadas para el día. "
                "Si la revisión no quedó cerrada correctamente, corrija el Excel y vuelva a ejecutar la finalización antes del correo y este paso.",
                "no_validated_rows_merge",
            )
        if "extract_routes_missing" in msg or "sin rutas de extracto" in mlow or "extract_routes_missing" in mlow:
            return (
                "Un pago no tiene ruta de extracto en el histórico o el PDF no está en SharePoint.",
                "En Aplicacion_Pagos, columna Ruta: abra el enlace y confirme que el extracto exista. "
                "Si falta, corrija con Generate/Finalize o suba el PDF al crédito.",
                "extract_routes_missing",
            )
        if mstripped == "missing_ruta_asientos_contables" or "missing_ruta_asientos_contables" in msg:
            return (
                "Un pago no tiene carpeta de asientos contables registrada en el histórico (columna RutaAsientosContables).",
                "Ejecute la finalización de la revisión de nuevo para regenerar esa columna. Debe haberse completado la revisión antes.",
                "missing_ruta_asientos_contables",
            )
        if "credit_number_not_resolved" in msg:
            return (
                "No se pudo identificar el número de crédito de un extracto para buscar su asiento contable.",
                "Revise que la ruta del extracto pase por una carpeta CREDITO # número o que la columna Crédito "
                "en Aplicacion_Pagos tenga el número correcto.",
                "credit_number_not_resolved",
            )
        if "asiento_folder_list_failed" in msg:
            return (
                "No se pudo abrir la carpeta de asientos contables de un crédito en SharePoint.",
                "Verifique que la ruta RutaAsientosContables del histórico sea correcta y que tenga permiso de lectura. "
                "Confirme que la carpeta ASIENTOS CONTABLES del crédito exista.",
                "asiento_folder_list_failed",
            )
        if "asiento_contable_not_found" in msg:
            return (
                "Falta al menos un PDF de asiento contable válido en la carpeta del crédito.",
                "En la carpeta ASIENTOS CONTABLES del crédito suba al menos un PDF cuyo nombre incluya el número "
                "de crédito (sin confundir con otros números, ej. 264 vs 1264). Vuelva a ejecutar Unir PDFs.",
                "missing_asiento_contable_pdf",
            )
        if "asiento_contable_credit_mismatch" in msg:
            return (
                "Hay PDF de asiento en la carpeta del crédito que no coincide con el número de crédito esperado.",
                "Renombre o retire los PDF que no correspondan al crédito; los válidos deben incluir el número de "
                "crédito en el nombre. Vuelva a ejecutar Unir PDFs.",
                "asiento_contable_credit_mismatch",
            )
        if "asiento_contable_ambiguous" in msg:
            return (
                "No se pudo determinar qué PDF de asiento usar para el crédito.",
                "Revise los archivos en la carpeta ASIENTOS CONTABLES y vuelva a ejecutar Unir PDFs.",
                "asiento_contable_ambiguous",
            )
        if "extracto_download_failed" in msg or "no se descargó extracto" in mlow:
            return (
                "No se pudo descargar el PDF de un extracto indicado en el histórico.",
                "Compruebe que el archivo siga en SharePoint en la ruta de la columna Ruta y que no esté borrado o renombrado.",
                "extract_pdf_download_failed",
            )
        if "asiento_download_failed" in msg or "no se descargó asiento" in mlow:
            return (
                "No se pudo descargar el PDF de asiento contable aunque la carpeta existe.",
                "Verifique que el archivo no esté corrupto, bloqueado o sin permisos. Vuelva a subir el asiento en "
                "ASIENTOS CONTABLES del crédito.",
                "asiento_pdf_download_failed",
            )
        if "consolidated_upload_failed" in msg or "put_bytes" in mlow or ("upload" in mlow and "423" in msg) or "locked" in mlow:
            return (
                "Se armó el PDF unido pero no se pudo guardar en la carpeta destino del consolidado "
                "(permisos o archivo bloqueado).",
                "Cierre PDFs abiertos en SharePoint. Verifique espacio y permisos de escritura en la carpeta de salida. "
                "Reintente Unir PDFs.",
                "consolidated_upload_failed",
            )
        if "upload" in mlow and "consolidated" not in mlow:
            return (
                "No se pudo subir uno de los PDF consolidados a SharePoint.",
                "Revise permisos en la carpeta destino del consolidado y que ningún PDF consolidado esté abierto "
                "en el navegador.",
                "consolidated_upload_failed",
            )

    if job_type in ("amortization_dry_run", "amortization_apply"):
        mstripped = msg.strip()
        if mstripped == "NO_READY_PROCESS":
            paso = (
                "la validación previa de amortización"
                if job_type == "amortization_dry_run"
                else "la aplicación de amortización"
            )
            return (
                f"Este paso se ejecutó antes de tiempo: todavía no se puede hacer {paso}.",
                "Haga primero Unir PDFs (consolidación de asientos contables) hasta que termine bien. "
                f"Cuando eso esté listo, vuelva a ejecutar {paso}.",
                "NO_READY_PROCESS",
            )
        if mstripped.startswith("MULTIPLE_READY_PROCESSES"):
            return _mapped(
                "MULTIPLE_READY_PROCESSES",
                "Hay más de un banco listo para amortización al mismo tiempo.",
                "Indique en la solicitud cuál banco desea procesar (Bogotá o Bancolombia) y vuelva a intentar. "
                "Si no puede indicar el banco, contacte a soporte con ambos nombres y la fecha.",
            )
        if mstripped == "merge_control_manifest_path_missing":
            return _mapped(
                "merge_control_manifest_path_missing",
                "No fue posible localizar el registro interno de la unión de documentos en el control del banco.",
                "No continúe con la validación previa ni con la aplicación. Contacte a soporte para revisar el estado del proceso.",
            )
        if mstripped == "merge_control_amortization_not_ready":
            return (
                "Este paso se ejecutó antes de tiempo: la unión de PDF todavía no terminó para este banco.",
                "Espere a que Unir PDFs finalice correctamente. Cuando termine, vuelva a ejecutar la amortización.",
                "merge_control_amortization_not_ready",
            )
        if mstripped == "merge_control_workbook_not_found":
            return (
                f"No existe el control de proceso del banco en SharePoint.",
                "Ejecute setup de controles por banco y el flujo Notify/Merge antes de amortización.",
                "merge_control_workbook_not_found",
            )
        if mstripped in (
            "merge_control_invalid_structure",
            "missing_historical_file_path",
        ):
            return (
                f"El control de proceso del banco no tiene la estructura esperada o faltan rutas.",
                "Ejecute setup de controles por banco o contacte soporte; no edite encabezados a mano.",
                mstripped,
            )

    if job_type == "amortization_dry_run":
        mstripped = msg.strip()
        if mstripped == "report_date_iso_required" or mstripped.startswith("report_date_iso_required"):
            return _mapped(
                "report_date_iso_required",
                "No fue posible continuar porque faltan datos internos del proceso de unión de documentos.",
                "No continúe con la validación previa ni con la aplicación. Contacte a soporte para revisar el estado del proceso.",
            )
        if mstripped.startswith("merge_manifest_not_found"):
            return _mapped(
                "merge_manifest_not_found",
                "No se encontró el registro de la unión de documentos para la fecha indicada.",
                "Ejecute la unión de PDF para ese día y vuelva a ejecutar la validación previa. "
                "Si el error continúa, contacte a soporte.",
            )
        if mstripped.startswith("invalid_merge_manifest_json"):
            return _mapped(
                "invalid_merge_manifest_json",
                "El registro de la unión de documentos existe pero no tiene un formato válido.",
                "No continúe con el siguiente paso. Contacte a soporte e indique el banco, la fecha y la etapa del proceso.",
            )
        if "graph_config" in mlow or "missing environment variable" in mlow:
            return _mapped(
                "graph_config_error",
                "No fue posible completar el proceso debido a un inconveniente de configuración.",
                "No continúe con el siguiente paso. Contacte a soporte e indique el banco, la fecha y la etapa del proceso.",
            )

    return _mapped("unknown_error", _UNKNOWN_USER, _UNKNOWN_NEXT)


def _build_standard_error_payload(
    job_type: str,
    *,
    exc_type: str | None,
    message: str,
) -> dict[str, Any]:
    msg = _strip_exception_prefix(message)
    if job_type in ("generate", "finalize", "cancel_active_process", "soft_close_process"):
        code = _error_code_from_generate_or_finalize_message(job_type, msg)
        user, next_a, _ = _lookup_generate_finalize(job_type, code, msg)
    else:
        user, next_a, code = _notify_merge_string_mapping(job_type, msg)

    user, next_a = apply_audience_policy(code, user, next_a)
    return {
        "type": exc_type or "Error",
        "message": message,
        "error_code": code,
        "technical_message": message,
        "user_message": user,
        "next_action": next_a,
        "severity": "error",
    }


def _merge_completed_enrichment(job_type: str, result: dict[str, Any]) -> tuple[str, str, str]:
    if job_type == "generate":
        custom_um = str(result.get("user_message") or "").strip()
        custom_na = str(result.get("next_action") or "").strip()
        if custom_um:
            return (
                custom_um,
                custom_na
                or "Abra el Excel de la carpeta de revisión, complete Validar Pago y Tipo de aplicación "
                "y pulse Finalizar en la aplicación.",
                "success",
            )
        return (
            "Se generó el archivo de revisión del día. Ya puede abrirlo en la carpeta de revisión de SharePoint.",
            "Abra ese Excel, complete Aplicacion_Pagos (Validar Pago y Tipo de aplicación en cada fila) "
            "y pulse Finalizar en la aplicación cuando termine.",
            "success",
        )
    if job_type == "cancel_active_process":
        if result.get("already_cancelled"):
            return (
                "No había un proceso activo que cancelar: el control del banco ya estaba libre.",
                "Puede iniciar una validación nueva para ese banco.",
                "success",
            )
        bank = str(result.get("bank_name") or result.get("bank_code") or "el banco").strip()
        return (
            f"Se canceló el lote de {bank}. El banco quedó libre para una validación nueva.",
            "Puede iniciar una validación nueva desde el panel. No es necesario editar el Excel de control.",
            "success",
        )
    if job_type == "soft_close_process":
        if result.get("already_closed"):
            return (
                "Este proceso ya estaba cerrado sin amortizar. El banco permanece libre.",
                "Puede iniciar una validación nueva desde el panel.",
                "success",
            )
        bank = str(result.get("bank_name") or result.get("bank_code") or "el banco").strip()
        return (
            f"Se cerró el proceso de {bank} sin amortizar. "
            "Los archivos ya generados se conservan y el banco quedó libre.",
            "Puede iniciar una validación nueva desde el panel. "
            "Si necesita llenar tablas a mano, use los archivos en SharePoint.",
            "success",
        )
    if job_type == "finalize":
        custom_um = str(result.get("user_message") or "").strip()
        custom_na = str(result.get("next_action") or "").strip()
        if custom_um:
            return (
                custom_um,
                custom_na
                or "Abra el archivo de asientos contables y cargue los PDF en cada carpeta ASIENTOS CONTABLES.",
                "success",
            )
        return (
            "Se finalizó la revisión correctamente. Se guardó el histórico del día y el archivo "
            "para cargar los asientos contables.",
            "Abra Asientos_Pendientes, cargue cada PDF en la carpeta ASIENTOS CONTABLES del crédito correspondiente "
            "y continúe con el envío del correo de extractos cuando corresponda.",
            "success",
        )
    if job_type == "notify_validar_extractos":
        ec = str(result.get("merge_control_error_code") or "").strip()
        wtxt = str(result.get("merge_control_warning") or "").strip()
        if ec == "merge_control_active_process_exists":
            return (
                "Se envió el correo correctamente; los destinatarios deberían haberlo recibido.",
                "Para el siguiente paso (unir PDFs): el control del banco ya tiene un proceso pendiente. "
                "Termine o cancele ese proceso antes de volver a registrar uno nuevo.",
                "warning",
            )
        if ec == "missing_email_pdf_path_for_merge_control":
            return (
                "Se envió el correo correctamente; los destinatarios deberían haberlo recibido.",
                "No se guardó el PDF copia del correo en la carpeta de correos enviados ni se registró el paso para "
                "unir PDFs después. Revise esa carpeta en SharePoint y que la exportación del PDF esté activa; luego "
                "reintente solo el registro en control o contacte soporte antes de ejecutar Unir PDFs.",
                "warning",
            )
        if ec == "merge_control_workbook_not_found":
            return (
                "Se envió el correo correctamente; los destinatarios deberían haberlo recibido.",
                "No se actualizó el control de proceso del banco porque no existe en la carpeta de control. "
                "Ejecute setup de controles por banco; después el flujo de correo quedará listo para unir PDFs.",
                "warning",
            )
        if ec == "merge_control_invalid_structure":
            return (
                "Se envió el correo correctamente; los destinatarios deberían haberlo recibido.",
                f"No se pudo actualizar el control de proceso del banco: formato no esperado "
                "(hoja Procesos, encabezados o fila 2). Ejecute setup o pida a soporte restaurar el control del banco.",
                "warning",
            )
        if ec in ("merge_control_read_failed", "merge_control_write_failed"):
            return (
                "Se envió el correo correctamente; los destinatarios deberían haberlo recibido.",
                wtxt
                or f"No se pudo leer o guardar el control de proceso del banco (permisos o archivo abierto). "
                "Cierre el Excel del banco en SharePoint y reintente; si persiste, contacte soporte.",
                "warning",
            )
        if not result.get("merge_control_updated") and wtxt and not ec:
            return (
                "Se envió el correo correctamente; los destinatarios deberían haberlo recibido.",
                wtxt,
                "warning",
            )
        abono_groups = int(result.get("abono_groups_included") or 0)
        if abono_groups > 0:
            return (
                "El correo de movimientos bancarios se envió correctamente. Los pagos incluyeron sus extractos "
                "y los abonos se reportaron sin extracto, según corresponde.",
                "Revise la bandeja de los destinatarios (y correo no deseado). Cargue los asientos en las carpetas de asientos; "
                "cuando termine, ejecute Consolidación de asientos contables (Flujo 3).",
                "success",
            )
        return (
            "El correo de abonos del banco se envió correctamente con la tabla del día y los extractos configurados.",
            "Revise la bandeja de los destinatarios (y correo no deseado). Cargue los asientos en las carpetas de asientos; "
            "cuando termine, ejecute Consolidación de asientos contables (Flujo 3).",
            "success",
        )
    if job_type == "merge_composite_validado_pdfs":
        outputs = result.get("outputs") or []
        skipped = result.get("skipped") or []
        out_count = result.get("outputs_count")
        if out_count is None and isinstance(outputs, list):
            out_count = len(outputs)
        skip_count = result.get("skipped_count")
        if skip_count is None and isinstance(skipped, list):
            skip_count = len(skipped)
        if isinstance(outputs, list) and len(outputs) == 0 and isinstance(skipped, list) and len(skipped) > 0:
            specific = _merge_failure_operator_message(result)
            payment_skipped = int(result.get("payment_skipped_count") or 0)
            group_count = payment_skipped or skip_count or len(skipped)
            if specific:
                user_msg, next_act = specific
                return (
                    f"La unión de PDFs terminó sin generar ningún archivo: {user_msg}",
                    next_act,
                    "warning",
                )
            return (
                f"La unión de PDFs terminó sin generar ningún archivo: "
                f"los {group_count} pago(s) requieren documentos faltantes "
                "(asiento contable, extracto u otro requisito).",
                "Revise Asientos_Pendientes y cargue los PDF en ASIENTOS CONTABLES de cada crédito según el archivo de asientos contables. "
                "Corrija y vuelva a ejecutar Consolidación de asientos contables (Flujo 3).",
                "warning",
            )
        incomplete_count = int(result.get("incomplete_groups_count") or 0)
        if incomplete_count > 0:
            specific = _merge_failure_operator_message(result)
            if specific:
                user_msg, next_act = specific
                return (
                    f"La consolidación quedó incompleta ({incomplete_count} grupo(s)): {user_msg}",
                    next_act,
                    "warning",
                )
        if isinstance(outputs, list) and len(outputs) > 0:
            if isinstance(skipped, list) and len(skipped) > 0:
                return (
                    f"Se unieron {out_count or len(outputs)} grupo(s) completo(s); "
                    f"quedan {skip_count or len(skipped)} omisión(es) documentales.",
                    "Revise Asientos_Pendientes y cargue los documentos pendientes. "
                    "Vuelva a ejecutar Consolidación de asientos contables (Flujo 3).",
                    "warning",
                )
            abono_out = int(result.get("abono_outputs_count") or 0)
            if abono_out > 0:
                return (
                    "La consolidación generó los asientos de pagos y abonos. Los abonos se consolidaron con sus "
                    "asientos contables, sin exigir extractos.",
                    "Revise en SharePoint la carpeta destino del consolidado y, cuando confirme que los PDF "
                    "consolidados están completos, ejecute Llenar tabla de amortización (Flujo 4).",
                    "success",
                )
            return (
                "La consolidación de asientos contables terminó correctamente: cada pago validado quedó en un solo PDF "
                "(correo del día + asientos + extractos).",
                "Revise en SharePoint la carpeta destino del consolidado y, cuando confirme que los PDF "
                "consolidados están completos, ejecute Llenar tabla de amortización (Flujo 4).",
                "success",
            )
        return (
            "La unión de PDFs terminó. Revise en SharePoint la carpeta destino del consolidado.",
            "Si quedaron pagos omitidos, revise Asientos_Pendientes y cargue los documentos faltantes antes de continuar.",
            "success",
        )
    if job_type == "amortization_dry_run":
        custom_um = str(result.get("user_message") or "").strip()
        custom_na = str(result.get("next_action") or "").strip()
        if custom_um:
            sev = "warning" if result.get("requires_business_rule") else "success"
            if not result.get("can_apply", True):
                sev = "warning"
            return (
                custom_um,
                custom_na
                or "Revise el resumen de abonos y los detalles de la validación previa antes de aplicar pagos y abonos.",
                sev,
            )
        summary = result.get("summary") or {}
        total_events = summary.get("total_events") or summary.get("total") or 0
        errors = summary.get("errors") or 0
        abono_not_reconciled = int(result.get("abono_groups_not_reconciled") or 0)
        if errors and total_events:
            return (
                f"La validación previa terminó con {total_events} evento(s) revisados; "
                f"{errors} con errores que impiden continuar.",
                "Corrija asientos, extractos o tablas según el resumen de la validación previa. "
                "No se modificó ninguna tabla de amortización.",
                "warning",
            )
        if abono_not_reconciled > 0:
            return (
                f"La validación previa detectó {abono_not_reconciled} grupo(s) de abono con errores de documentos o cuadre.",
                "Revise el resumen de abonos (montos y documentos faltantes). "
                "Cargue los asientos faltantes en la carpeta del crédito; no es necesario extracto para abonos.",
                "warning",
            )
        if result.get("can_apply") and int(result.get("abono_groups_ready") or 0) > 0:
            return (
                "La validación previa de abonos cuadró correctamente. Cada abono utilizará la siguiente fila "
                "libre de Aplicación de Pagos; el IBR no se modificará.",
                "Revise los detalles de cada asiento y fila planificada; si todo cuadra, ejecute la aplicación de pagos y abonos.",
                "success",
            )
        return (
            "La validación previa terminó correctamente y no se modificó ninguna tabla.",
            "Revise el resumen de la validación previa. Si todo cuadra, ejecute la aplicación de pagos y abonos.",
            "success",
        )
    if job_type == "amortization_apply":
        if str(result.get("status") or "") == "blocked":
            custom_um = str(result.get("user_message") or "").strip()
            custom_na = str(result.get("next_action") or "").strip()
            if custom_um:
                return (
                    custom_um,
                    custom_na
                    or "Revise los grupos de abono bloqueados antes de volver a aplicar pagos y abonos.",
                    "warning",
                )
            return (
                "La amortización no puede aplicarse: hay grupos de abono bloqueados.",
                "Revise los grupos de abono bloqueados y corrija asientos o documentos antes de volver a aplicar pagos y abonos.",
                "warning",
            )
        if result.get("already_applied"):
            custom_um = str(result.get("user_message") or "").strip()
            custom_na = str(result.get("next_action") or "").strip()
            if custom_um:
                return (custom_um, custom_na, "success")
        if str(result.get("status") or "") == "preflight_failed":
            return (
                "No fue posible actualizar las tablas de amortización porque se detectaron errores en la revisión interna.",
                "Revise los documentos y tablas indicados, corrija el inconveniente y vuelva a ejecutar "
                "Llenar tabla de amortización (Flujo 4).",
                "warning",
            )
        if str(result.get("status") or "") in ("ok", "partial"):
            custom_um = str(result.get("user_message") or "").strip()
            custom_na = str(result.get("next_action") or "").strip()
            sev = "success" if result.get("status") == "ok" else "warning"
            if custom_um:
                return (
                    custom_um,
                    custom_na
                    or (
                        "Abra cada tabla actualizada y confirme que los pagos aplicados y el cronograma "
                        "quedaron correctos. Este es el último paso automático del proceso."
                        if result.get("status") == "ok"
                        else "Revise las tablas pendientes, corrija el inconveniente y vuelva a ejecutar "
                        "Llenar tabla de amortización (Flujo 4)."
                    ),
                    sev,
                )
            tables_n = int(result.get("tables_uploaded_count") or 0)
            if result.get("status") == "partial":
                return (
                    f"Se actualizaron {tables_n} tabla(s), pero quedaron tablas pendientes de revisión.",
                    "Revise las tablas pendientes, corrija el inconveniente y vuelva a ejecutar "
                    "Llenar tabla de amortización (Flujo 4).",
                    "warning",
                )
            return (
                "El proceso de validación de pagos finalizó correctamente. "
                f"Se actualizaron {tables_n} tabla(s) de amortización en SharePoint.",
                "Abra cada tabla actualizada y confirme que los pagos aplicados y el cronograma "
                "quedaron correctos. Este es el último paso automático del proceso.",
                "success",
            )

    if job_type == "amortization_process":
        # Job UI unificado: reutiliza el mismo result (prepare/apply) con outcome explícito.
        custom_um = str(result.get("user_message") or "").strip()
        custom_na = str(result.get("next_action") or "").strip()
        outcome = str(result.get("outcome") or "").strip().lower()
        status = str(result.get("status") or "").strip().lower()

        if result.get("already_applied") or outcome == "already_applied":
            return (
                custom_um
                or "La amortización de este proceso ya fue aplicada anteriormente.",
                custom_na
                or "No es necesario volver a procesar. Consulte el estado del proceso.",
                "success",
            )

        if (
            result.get("apply_wrote_changes")
            or result.get("tables_uploaded")
            or status == "partial"
            or outcome == "partial"
        ):
            tables_n = int(result.get("tables_uploaded_count") or 0)
            if not tables_n:
                tables_n = len(result.get("tables_uploaded") or [])
            return (
                custom_um
                or (
                    f"Se actualizaron {tables_n} tabla(s), pero quedaron tablas pendientes de revisión."
                ),
                custom_na
                or (
                    "Revise las tablas pendientes, corrija el inconveniente y vuelva a ejecutar "
                    "Llenar tabla de amortización (Flujo 4)."
                ),
                "warning",
            )

        if (
            outcome == "requires_correction"
            or result.get("can_apply") is False
            or status in ("blocked", "preflight_failed")
        ):
            op_issues = result.get("operational_issues")
            if isinstance(op_issues, list) and op_issues:
                n = len(op_issues)
                return (
                    f"La amortización encontró {n} problema(s). No se modificó ninguna tabla.",
                    custom_na
                    or (
                        "Revise cada punto en el detalle, corrija los documentos en SharePoint "
                        "y vuelva a procesar la amortización."
                    ),
                    "warning",
                )
            return (
                custom_um
                or "La amortización requiere correcciones antes de continuar.",
                custom_na
                or (
                    "Revise asientos, montos y tablas en SharePoint; corrija lo indicado "
                    "y vuelva a procesar la amortización."
                ),
                "warning",
            )

        if outcome == "partial" or status == "partial":
            tables_n = int(result.get("tables_uploaded_count") or 0)
            return (
                custom_um
                or (
                    f"Se actualizaron {tables_n} tabla(s), pero quedaron tablas pendientes de revisión."
                ),
                custom_na
                or (
                    "Revise las tablas pendientes, corrija el inconveniente y vuelva a "
                    "procesar la amortización."
                ),
                "warning",
            )

        if (
            outcome in ("applied", "ok", "success")
            or status in ("ok", "applied")
            or (result.get("can_apply") and status == "")
        ):
            tables_n = int(result.get("tables_uploaded_count") or 0)
            if custom_um:
                return (
                    custom_um,
                    custom_na
                    or (
                        "Abra cada tabla actualizada y confirme que los pagos aplicados y el "
                        "cronograma quedaron correctos."
                    ),
                    "success",
                )
            return (
                "El proceso de validación de pagos finalizó correctamente. "
                f"Se actualizaron {tables_n} tabla(s) de amortización en SharePoint.",
                "Abra cada tabla actualizada y confirme que los pagos aplicados y el cronograma "
                "quedaron correctos. Este es el último paso automático del proceso.",
                "success",
            )

        if custom_um:
            return (
                custom_um,
                custom_na or "Revise el estado del proceso e intente de nuevo si hace falta.",
                "warning" if outcome == "failed" else "success",
            )

        return (
            "La amortización terminó. Revise el estado del proceso.",
            "Actualice el detalle del proceso para confirmar el resultado.",
            "success",
        )

    return "", "", ""


def enrich_job_for_http_response(job: dict[str, Any]) -> dict[str, Any]:
    """
    Devuelve una copia superficial del job con user_message, next_action, severity
    y error normalizado cuando aplica.
    """
    out = dict(job)
    jt = str(out.get("type") or "")
    if jt not in ENRICHABLE_JOB_TYPES:
        return out

    status = out.get("status")
    if status == "completed":
        result = out.get("result")
        if not isinstance(result, dict):
            result = {}
        um, na, sev = _merge_completed_enrichment(jt, result)
        if um:
            out["user_message"] = um
        if na:
            out["next_action"] = na
        if sev:
            out["severity"] = sev
        return out

    if status == "failed":
        out["severity"] = "error"
        err = out.get("error")
        if isinstance(err, dict):
            msg = str(err.get("message", ""))
            exc_type = str(err.get("type", "Error"))
            if err.get("user_message") and err.get("next_action") and err.get("error_code"):
                merged = dict(err)
                merged.setdefault("technical_message", msg)
                merged.setdefault("severity", "error")
                out["error"] = merged
                return out
            payload = _build_standard_error_payload(jt, exc_type=exc_type, message=msg)
            out["error"] = {**err, **payload}
            out["error"]["message"] = err.get("message", payload["message"])
            out["error"]["type"] = err.get("type", payload["type"])
        elif isinstance(err, str):
            out["error"] = _build_standard_error_payload(jt, exc_type=None, message=err)
        else:
            out["error"] = _build_standard_error_payload(
                jt, exc_type="Error", message=str(err) if err is not None else ""
            )
        return out

    return out


def examples_for_parse_json_tests() -> tuple[dict[str, Any], dict[str, Any]]:
    """Ejemplos estables para tests de esquema flexible."""
    completed = {
        "job_id": "ex-1",
        "type": "generate",
        "status": "completed",
        "user_message": "ok",
        "next_action": "next",
        "severity": "success",
        "result": {"validation_file": "f.xlsx"},
        "queued_at": "2026-01-01T00:00:00+00:00",
    }
    failed = {
        "job_id": "ex-2",
        "type": "finalize",
        "status": "failed",
        "severity": "error",
        "error": {
            "type": "ValueError",
            "message": "amount_mismatch",
            "error_code": "amount_mismatch",
            "technical_message": "amount_mismatch",
            "user_message": "x",
            "next_action": "y",
            "severity": "error",
        },
    }
    return completed, failed
