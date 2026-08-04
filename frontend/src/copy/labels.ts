/**
 * Catálogo centralizado de textos operativos.
 *
 * Traduce claves técnicas del backend (nombre de etapa, tipo de job, estado
 * interno de control) a lenguaje que entiende un operador de negocio. Reglas:
 * - Nada de "Generate/Finalize/JobManager/ProcessKey" en la UI del operador.
 * - Segunda persona de respeto (usted); nunca «secretaría» ni jerga de cargos.
 * - Un único lugar para cambiar el texto de una etapa o estado.
 * - Códigos desconocidos → mensaje operativo de respaldo (nunca el código crudo).
 */

/** Etapas técnicas (StepName y variantes de `type` de JobManager) → texto operativo. */
export const stageLabels: Record<string, string> = {
  generate: "Preparación de la revisión",
  review: "Revisión humana",
  finalize: "Cierre de la revisión",
  notify: "Envío del correo",
  notify_validar_extractos: "Envío del correo",
  merge: "Generación del PDF consolidado",
  merge_composite_validado_pdfs: "Generación del PDF consolidado",
  dry_run: "Verificación de amortización",
  apply: "Aplicación de amortización",
  amortization: "Procesamiento financiero",
  amortization_process: "Procesamiento financiero",
  amortization_dry_run: "Verificación de amortización",
  amortization_apply: "Aplicación de amortización",
  cancel_active_process: "Cancelación del proceso",
};

export function stageLabel(stage: string | null | undefined): string {
  if (!stage) return "Proceso";
  return stageLabels[stage] ?? "Etapa del proceso";
}

/** Estados de job/etapa (JobManager status y StepStatus) → texto operativo. */
export const statusLabels: Record<string, string> = {
  queued: "En cola",
  running: "En curso",
  completed: "Completado",
  failed: "Con problemas",
  cancelled: "Cancelado",
  canceled: "Cancelado",
  interrupted: "Interrumpido",
  not_started: "Sin iniciar",
  in_progress: "En curso",
  failed_retryable: "Con problemas · se puede reintentar",
  failed_business: "Requiere corrección",
  sync_pending: "Sincronizando resultados",
  blocked: "Bloqueado",
  skipped: "Omitido",
  partial: "Parcial",
};

export function statusLabel(status: string | null | undefined): string {
  if (!status) return "—";
  return statusLabels[status] ?? "Estado en revisión";
}

/**
 * Estados operativos de negocio (`OperationalStatus`) y, si hace falta mapear
 * un estado de control residual, su etiqueta humana equivalente.
 */
export const operationalStatusLabels: Record<string, string> = {
  // OperationalStatus
  NUEVO: "Nuevo",
  GENERANDO: "Preparando la revisión",
  EN_REVISION: "Revisión pendiente",
  FINALIZANDO: "Cerrando la revisión",
  PENDIENTE_NOTIFICACION: "Pendiente de envío",
  NOTIFICANDO: "Enviando la validación",
  ESPERANDO_SOPORTES: "Esperando asientos contables",
  CONSOLIDANDO: "Generando PDF consolidado",
  VALIDANDO_AMORTIZACION: "Verificando amortización",
  LISTO_PARA_APLICAR: "Listo para aplicar amortización",
  APLICANDO: "Aplicando amortización",
  COMPLETADO: "Completado",
  FINALIZADO_PARCIALMENTE: "Finalizado parcialmente",
  SINCRONIZANDO: "Sincronizando resultados",
  ERROR_RECUPERABLE: "Requiere atención",
  CORRECCION_REQUERIDA: "Requiere corrección",
  REVISION_MANUAL: "Requiere revisión manual",
  CANCELADO: "Cancelado",
  DESCONOCIDO: "No se pudo determinar el estado",
  // Equivalentes humanos de estados de control (si llegan a la UI)
  VACIO: "Sin proceso activo",
  FINALIZADO: "Revisión finalizada",
  REVISION_CREADA: "Archivo de revisión disponible",
  ERROR_GENERATE: "No se pudo preparar la revisión",
  ERROR_FINALIZE: "No se pudo cerrar la revisión",
  ERROR_NOTIFY: "No se pudo enviar la validación",
  PENDIENTE_ASIENTOS: "Esperando asientos contables",
  CONSOLIDADO: "PDF consolidado listo",
  MERGE_PARCIAL: "PDF consolidado parcial",
  ERROR_MERGE: "No se pudo generar el PDF consolidado",
  APLICANDO_AMORTIZACION: "Aplicando amortización",
  AMORTIZACION_APLICADA: "Amortización aplicada",
  AMORTIZACION_PARCIAL: "Amortización parcial",
  ERROR_APPLY: "No se pudo aplicar la amortización",
};

export function operationalStatusLabel(status: string | null | undefined): string {
  if (!status) return "—";
  return operationalStatusLabels[status] ?? "Estado en revisión";
}

/** Estados operativos con trabajo en curso (spinner en tarjeta / dashboard). */
const BUSY_OPERATIONAL_STATUSES = new Set([
  "GENERANDO",
  "FINALIZANDO",
  "NOTIFICANDO",
  "CONSOLIDANDO",
  "VALIDANDO_AMORTIZACION",
  "APLICANDO",
  "SINCRONIZANDO",
]);

export function isOperationalStatusBusy(status: string | null | undefined): boolean {
  return Boolean(status && BUSY_OPERATIONAL_STATUSES.has(status));
}

/** Nombre operativo de cada acción disponible (botones, encabezados). */
export const actionLabels = {
  generate: "Iniciar validación",
  resume: "Retomar proceso",
  retry_read: "Volver a intentar",
  regenerate: "Regenerar archivo de revisión",
  finalize: "Finalizar revisión",
  notify: "Enviar correo",
  merge: "Generar PDF consolidado",
  amortization: "Procesar amortización",
  refresh_documents: "Actualizar documentos",
  /** Visible solo cuando conviene releer docs en SharePoint (no en toda fase). */
  refresh_documents_hint:
    "Después de cargar, reemplazar o renombrar documentos en SharePoint, actualice la información para verificar nuevamente el proceso.",
  /** Relee merge_readiness tras corregir ASIENTOS en SharePoint. */
  verify_merge_supports: "Actualizar / verificar soportes",
  open_asientos_folder: "Abrir carpeta ASIENTOS",
  open_documents: "Ver archivos del proceso",
  back_to_dashboard: "Volver al panel",
  view_detail: "Ver detalle",
  open_bank_template: "Abrir archivo del banco",
  open_review_excel: "Abrir archivo de revisión",
  continue_process: "Continuar proceso",
} as const;

export type ActionKey = keyof typeof actionLabels;

/** Título de los modales de confirmación de cada acción mutable. */
export const confirmTitles: Record<
  "generate" | "regenerate" | "finalize" | "notify" | "merge" | "amortization",
  string
> = {
  generate: "Iniciar validación",
  regenerate: "Regenerar archivo de revisión",
  finalize: "Finalizar revisión",
  notify: "Enviar correo",
  merge: "Generar PDF consolidado",
  amortization: "Procesar amortización",
};

/** Texto de botón mientras la acción está en curso (aria-busy). */
export const busyLabels: Record<
  | "generate"
  | "regenerate"
  | "finalize"
  | "notify"
  | "merge"
  | "amortization"
  | "retry_read"
  | "verify_merge_supports",
  string
> = {
  generate: "Iniciando validación…",
  regenerate: "Regenerando archivo…",
  finalize: "Verificando revisión…",
  notify: "Enviando correo…",
  merge: "Generando PDF consolidado…",
  amortization: "Procesando amortización…",
  retry_read: "Consultando estado…",
  verify_merge_supports: "Verificando soportes…",
};

/** Explicaciones cortas bajo botones / en modales. */
export const actionExplanations = {
  /** Una sola frase: modal de confirmación (sin párrafos extra). */
  regenerate:
    "Se cancela este lote y se crea un Excel nuevo con la misma fecha, leyendo el archivo del banco actual.",
  /** @deprecated Usar `regenerate`; se mantiene por compatibilidad de imports. */
  regenerate_missing_file:
    "Se cancela este lote y se crea un Excel nuevo con la misma fecha, leyendo el archivo del banco actual.",
  review_errores_warning:
    "Hay casos en la hoja Errores. Corrija archivos o carpetas en SharePoint y regenere antes de finalizar.",
  review_file_missing_warning:
    "Falta el Excel de revisión en SharePoint. Regenérelo para continuar con el banco actual.",
  /** Banner/alerta: el único CTA Regenerar vive en la fase actual (arriba). */
  regenerate_use_phase_cta:
    "Cuando haya corregido los casos, use el botón Regenerar de la fase actual (arriba).",
  /** Lista larga de problemas: destinos en modal. */
  correction_targets_drawer_hint:
    "Hay varios casos. Use «Ver destinos de corrección» para abrir el archivo o la carpeta indicada en SharePoint.",
  correction_targets_cta: "Ver destinos de corrección",
  /** Al consultar una fase ya completada desde el header. */
  phase_completed_readonly:
    "Esta fase ya está completa. Puede consultarla, pero no vuelve a ejecutarse.",
  merge:
    "Reúne el PDF del correo que envió, los extractos y los documentos contables en un único PDF para que pueda continuar con la amortización.",
  amortization: "Registra los movimientos que ya validó en las tablas de amortización.",
  pending_asientos:
    "Ya completó la validación y el envío del correo. Revise los asientos contables cargados antes de generar el PDF consolidado.",
  /** Tras corregir PDF/nombre en SharePoint (fase Merge). */
  merge_verify_after_fix:
    "Cuando haya cargado o renombrado el PDF en SharePoint, use «Actualizar / verificar soportes».",
  process_completed:
    "La validación del banco finalizó correctamente. Ya no hay acciones pendientes en este proceso.",
} as const;

/** Resultados de éxito del modal de job (título + mensaje). */
export const jobSuccessCopy = {
  generate: {
    title: "Archivo de revisión listo",
    message:
      "Se generó el archivo de revisión del día. Ábralo en SharePoint para completar la distribución.",
  },
  regenerate: {
    title: "Archivo regenerado",
    message:
      "Se generó un archivo de revisión nuevo. Si ya no hay casos en Errores, continúe con Finalizar revisión.",
  },
  finalize: {
    title: "Revisión finalizada",
    message:
      "Se finalizó la revisión correctamente. Se guardó el histórico del día y el soporte para cargar los asientos contables.",
  },
  amortization: {
    title: "Proceso completado",
    message:
      "La amortización se aplicó correctamente. El proceso de validación ha finalizado.",
  },
  notify: {
    title: "Correo enviado",
    message:
      "El correo se envió correctamente. Abra el PDF del correo generado para revisarlo y continúe con los asientos contables.",
  },
  merge: {
    title: "PDF consolidado listo",
    message:
      "La consolidación terminó correctamente. Abra el PDF consolidado para revisarlo y continúe con la amortización.",
  },
  default: {
    title: "Operación completada",
    message: "La operación finalizó correctamente.",
  },
} as const;

/** Fases conocidas de `job.progress.phase`. */
export const progressPhaseLabels: Record<string, string> = {
  validating: "Validando información",
  applying: "Aplicando cambios",
};

export function progressPhaseLabel(phase: string | null | undefined): string | null {
  if (!phase) return null;
  return progressPhaseLabels[phase] ?? "Progreso del trabajo";
}

export const dashboardEmptyStateMessage =
  "No hay procesos activos en el Control. Inicie una validación desde el bloque superior.";

export const historyEmptyStateMessage =
  "No hay procesos para mostrar. Los activos salen del Control; los cerrados, del archivo.";

export const FALLBACK_OPERATOR_MESSAGE =
  "No pudimos completar la operación. Revise el estado del proceso y vuelva a intentar, o contacte a soporte si el problema continúa.";
