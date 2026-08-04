/**
 * Paleta semántica de estados para chips/píldoras del operador.
 *
 * Un solo mapeo → clases `.status-pill.{ok|info|warn|danger}` (CSS vars
 * --success / --info / --warning / --error). Evita hex sueltos y que un
 * «Listo…» herede ámbar de un estado técnico de espera.
 *
 * | Tono    | Significado                         | Color  |
 * |---------|-------------------------------------|--------|
 * | ok      | listo / completado / éxito          | verde  |
 * | info    | en curso / fase activa / revisión   | azul   |
 * | warn    | pendiente externo / parcial / wait  | ámbar  |
 * | danger  | error / bloqueado / corrección      | rojo   |
 * | neutral | desconocido / sin clase             | gris   |
 */

export type StatusTone = "ok" | "info" | "warn" | "danger" | "neutral";

/**
 * Clave sintética cuando merge_readiness=ready pero Control sigue en
 * ESPERANDO_SOPORTES: el copy dice «Listo para consolidar» y el tono debe
 * ser éxito, no advertencia.
 */
export const LISTO_PARA_CONSOLIDAR = "LISTO_PARA_CONSOLIDAR";

/** Tono semántico a partir de OperationalStatus, StepStatus, job status, etc. */
export function statusTone(status: string | null | undefined): StatusTone {
  const raw = String(status || "").trim();
  if (!raw) return "neutral";
  const upper = raw.toUpperCase();
  const lower = raw.toLowerCase();

  // Listo / completado / éxito (incluye override de merge readiness).
  if (
    upper === "COMPLETADO" ||
    lower === "completed" ||
    upper.startsWith("LISTO_") ||
    upper === "CONSOLIDADO" ||
    upper === "AMORTIZACION_APLICADA" ||
    upper === "FINALIZADO" ||
    upper === "REVISION_CREADA"
  ) {
    return "ok";
  }

  // Error / corrección / bloqueo.
  if (
    upper.includes("ERROR") ||
    lower.includes("failed") ||
    upper === "CORRECCION_REQUERIDA" ||
    upper === "REVISION_MANUAL" ||
    lower === "blocked"
  ) {
    return "danger";
  }

  // Espera externa / incompleto / parcial (ámbar).
  if (
    upper.includes("PARCIAL") ||
    upper.includes("ESPERANDO") ||
    upper === "PENDIENTE_ASIENTOS" ||
    lower === "partial"
  ) {
    return "warn";
  }

  // Procesando / cola / fase activa (azul).
  if (
    upper === "EN_REVISION" ||
    upper === "NUEVO" ||
    upper === "GENERANDO" ||
    upper === "FINALIZANDO" ||
    upper === "PENDIENTE_NOTIFICACION" ||
    upper === "NOTIFICANDO" ||
    upper === "CONSOLIDANDO" ||
    upper === "VALIDANDO_AMORTIZACION" ||
    upper === "APLICANDO" ||
    upper === "APLICANDO_AMORTIZACION" ||
    upper === "SINCRONIZANDO" ||
    lower === "sync_pending" ||
    lower === "queued" ||
    lower === "running" ||
    lower === "in_progress" ||
    lower === "not_started"
  ) {
    return "info";
  }

  if (
    upper === "DESCONOCIDO" ||
    upper === "CANCELADO" ||
    upper === "CERRADO_SIN_AMORTIZAR" ||
    lower === "cancelled" ||
    lower === "canceled" ||
    lower === "skipped" ||
    lower === "interrupted"
  ) {
    return "warn";
  }

  return "neutral";
}

/**
 * Clase CSS de `.status-pill` (`ok` | `info` | `warn` | `danger` | `""`).
 * Compatible con usos existentes de `statusClass(...)`.
 */
export function statusClass(status: string | null | undefined): string {
  const tone = statusTone(status);
  return tone === "neutral" ? "" : tone;
}

/**
 * Estado efectivo del badge de detalle: si los soportes ya están listos,
 * no heredar el tono ámbar de ESPERANDO_SOPORTES.
 */
export function resolveProcessBadgeStatus(input: {
  operationalStatus: string;
  mergeReadinessStatus?: string | null;
}): string {
  const merge = String(input.mergeReadinessStatus || "")
    .trim()
    .toLowerCase();
  if (input.operationalStatus === "ESPERANDO_SOPORTES" && merge === "ready") {
    return LISTO_PARA_CONSOLIDAR;
  }
  return input.operationalStatus;
}
