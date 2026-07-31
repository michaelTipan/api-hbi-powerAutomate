/**
 * Catálogo centralizado de textos operativos.
 *
 * Traduce claves técnicas del backend (nombre de etapa, tipo de job, estado
 * interno de control) a lenguaje que entiende un operador de negocio. Reglas:
 * - Nada de "Generate/Finalize/JobManager/ProcessKey" fuera de la sección de
 *   Detalles técnicos.
 * - Un único lugar para cambiar el texto de una etapa o estado.
 */

/** Etapas técnicas (StepName y variantes de `type` de JobManager) → texto operativo. */
export const stageLabels: Record<string, string> = {
  generate: "Preparación de la revisión",
  review: "Revisión humana",
  finalize: "Cierre de la revisión",
  notify: "Envío de la validación",
  notify_validar_extractos: "Envío de la validación",
  merge: "Consolidación de soportes",
  merge_composite_validado_pdfs: "Consolidación de soportes",
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
  return stageLabels[stage] ?? stage;
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
  blocked: "Bloqueado",
  skipped: "Omitido",
  partial: "Parcial",
};

export function statusLabel(status: string | null | undefined): string {
  if (!status) return "—";
  return statusLabels[status] ?? status;
}

/**
 * Estados operativos de negocio (`OperationalStatus`) y estados técnicos de
 * control (`control_estado_proceso`) → texto operativo. Se centralizan juntos
 * porque ambos terminan mostrándose al operador (el segundo solo dentro de
 * Detalles técnicos).
 */
export const operationalStatusLabels: Record<string, string> = {
  // OperationalStatus
  NUEVO: "Nuevo",
  GENERANDO: "Preparando la revisión",
  EN_REVISION: "Revisión pendiente",
  FINALIZANDO: "Cerrando la revisión",
  NOTIFICANDO: "Enviando la validación",
  ESPERANDO_SOPORTES: "Esperando soportes",
  CONSOLIDANDO: "Consolidando soportes",
  VALIDANDO_AMORTIZACION: "Verificando amortización",
  LISTO_PARA_APLICAR: "Listo para aplicar amortización",
  APLICANDO: "Aplicando amortización",
  COMPLETADO: "Completado",
  FINALIZADO_PARCIALMENTE: "Finalizado parcialmente",
  ERROR_RECUPERABLE: "Requiere atención",
  CORRECCION_REQUERIDA: "Requiere corrección",
  REVISION_MANUAL: "Requiere revisión manual",
  CANCELADO: "Cancelado",
  DESCONOCIDO: "Estado desconocido",
  // control_estado_proceso (solo visible en Detalles técnicos)
  VACIO: "Sin proceso activo",
  REVISION_CREADA: "Archivo de revisión disponible",
  ERROR_GENERATE: "No se pudo preparar la revisión",
  ERROR_FINALIZE: "No se pudo cerrar la revisión",
  ERROR_NOTIFY: "No se pudo enviar la validación",
  PENDIENTE_ASIENTOS: "Pendiente de soportes contables",
  CONSOLIDADO: "Soportes consolidados",
  MERGE_PARCIAL: "Consolidación parcial",
  ERROR_MERGE: "No se pudo consolidar",
  APLICANDO_AMORTIZACION: "Aplicando amortización",
  AMORTIZACION_APLICADA: "Amortización aplicada",
  AMORTIZACION_PARCIAL: "Amortización parcial",
  ERROR_APPLY: "No se pudo aplicar la amortización",
};

export function operationalStatusLabel(status: string | null | undefined): string {
  if (!status) return "—";
  return operationalStatusLabels[status] ?? status;
}

/** Nombre operativo de cada acción disponible (botones, encabezados). */
export const actionLabels = {
  generate: "Iniciar validación",
  finalize: "Finalizar revisión",
  notify: "Enviar validación",
  merge: "Consolidar soportes",
  amortization: "Procesar amortización",
} as const;

export type ActionKey = keyof typeof actionLabels;

/** Título de los modales de confirmación de cada acción. */
export const confirmTitles: Record<ActionKey, string> = {
  generate: "Iniciar validación",
  finalize: "Finalizar revisión",
  notify: "Enviar validación",
  merge: "Consolidar soportes",
  amortization: "Procesar amortización",
};

/** Texto de botón mientras la acción está en curso (aria-busy). */
export const busyLabels: Record<ActionKey, string> = {
  generate: "Iniciando validación…",
  finalize: "Verificando revisión…",
  notify: "Enviando validación…",
  merge: "Consolidando soportes…",
  amortization: "Procesando amortización…",
};

/** Fases conocidas de `job.progress.phase`. */
export const progressPhaseLabels: Record<string, string> = {
  validating: "Validando información",
  applying: "Aplicando cambios",
};

export function progressPhaseLabel(phase: string | null | undefined): string | null {
  if (!phase) return null;
  return progressPhaseLabels[phase] ?? phase;
}

export const dashboardEmptyStateMessage = "No hay procesos en esta categoría.";
