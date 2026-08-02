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
  notify: "Envío de la validación",
  notify_validar_extractos: "Envío de la validación",
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
  ESPERANDO_SOPORTES: "Esperando documentos contables",
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
  PENDIENTE_ASIENTOS: "Esperando documentos contables",
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

/** Nombre operativo de cada acción disponible (botones, encabezados). */
export const actionLabels = {
  generate: "Iniciar validación",
  resume: "Retomar proceso",
  retry_read: "Volver a intentar",
  finalize: "Finalizar revisión",
  notify: "Enviar validación",
  merge: "Generar PDF consolidado",
  amortization: "Procesar amortización",
  refresh_documents: "Actualizar documentos",
  /** Visible solo cuando conviene releer docs en SharePoint (no en toda fase). */
  refresh_documents_hint:
    "Después de cargar, reemplazar o renombrar documentos en SharePoint, actualice la información para verificar nuevamente el proceso.",
  open_documents: "Ver archivos del proceso",
} as const;

export type ActionKey = keyof typeof actionLabels;

/** Título de los modales de confirmación de cada acción mutable. */
export const confirmTitles: Record<
  "generate" | "finalize" | "notify" | "merge" | "amortization",
  string
> = {
  generate: "Iniciar validación",
  finalize: "Finalizar revisión",
  notify: "Enviar validación",
  merge: "Generar PDF consolidado",
  amortization: "Procesar amortización",
};

/** Texto de botón mientras la acción está en curso (aria-busy). */
export const busyLabels: Record<
  "generate" | "finalize" | "notify" | "merge" | "amortization" | "retry_read",
  string
> = {
  generate: "Iniciando validación…",
  finalize: "Verificando revisión…",
  notify: "Enviando validación…",
  merge: "Generando PDF consolidado…",
  amortization: "Procesando amortización…",
  retry_read: "Consultando estado…",
};

/** Explicaciones cortas bajo botones / en modales. */
export const actionExplanations = {
  merge:
    "Reúne el PDF del correo que envió, los extractos y los documentos contables en un único PDF para que pueda continuar con la amortización.",
  amortization: "Registra los movimientos que ya validó en las tablas de amortización.",
  pending_asientos:
    "Ya completó la validación y el envío del correo. Revise los documentos contables cargados antes de generar el PDF consolidado.",
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

export const dashboardEmptyStateMessage = "No hay procesos en esta categoría.";

export const FALLBACK_OPERATOR_MESSAGE =
  "No pudimos completar la operación. Revise el estado del proceso y vuelva a intentar, o contacte a soporte si el problema continúa.";
