/**
 * Tras un job terminal, el Control puede ir unos segundos atrasado respecto
 * del JSON del job (desfase temporal job↔Control). La proyección BE marca
 * `sync_pending` / `SINCRONIZANDO`; el FE reintenta GET con la misma regla
 * en dashboard y detalle.
 */
import type { UiJobView, UiProcessDetail, UiProcessSummary } from "../types/contract";

export const SYNC_RESULTS_MESSAGE = "Sincronizando resultados…";

export const SYNC_TIMEOUT_MESSAGE =
  "No se pudo confirmar la actualización del estado. " +
  "El trabajo ya terminó; actualice en unos segundos. " +
  "Esto no indica que el proceso haya fallado.";

/** Timeout suave solo para amortización/apply (no pintar como error duro). */
export const AMORT_SYNC_SOFT_TIMEOUT_TITLE = "Estado pendiente de confirmar";

export const AMORT_SYNC_SOFT_TIMEOUT_MESSAGE =
  "La amortización ya terminó en el sistema, pero aún no pudimos confirmar " +
  "el estado del proceso. Use «Actualizar estado» en unos segundos. " +
  "Esto no indica que el proceso haya fallado.";

/** Timeout suave Merge/reconsolidar: el PDF ya se escribió; Control puede ir atrasado. */
export const MERGE_SYNC_SOFT_TIMEOUT_TITLE = "Estado pendiente de confirmar";

export const MERGE_SYNC_SOFT_TIMEOUT_MESSAGE =
  "La consolidación ya terminó en el sistema, pero aún no pudimos confirmar " +
  "el estado del proceso. Use «Actualizar estado» en unos segundos. " +
  "Esto no indica que el proceso haya fallado.";

/** Delays entre reintentos de GET tras job terminal (ms). */
export const POST_JOB_RELOAD_DELAYS_MS: readonly number[] = [0, 700, 1500, 3000];

/**
 * Amortización escribe Control al final; Graph puede tardar más que ~5 s.
 * Ventana ~30 s de reintentos solo para este tipo de job.
 */
export const POST_JOB_RELOAD_DELAYS_AMORTIZATION_MS: readonly number[] = [
  0, 700, 1500, 3000, 5000, 8000, 12000,
];

/**
 * Merge/reconsolidar: misma ventana larga que amort (Control pasa por CONSOLIDANDO
 * y Graph a veces sirve fila stale unos segundos tras el job completed).
 */
export const POST_JOB_RELOAD_DELAYS_MERGE_MS: readonly number[] =
  POST_JOB_RELOAD_DELAYS_AMORTIZATION_MS;

export function isAmortizationJobType(jobType: string | null | undefined): boolean {
  const t = (jobType || "").toLowerCase();
  return t.includes("amortization") || t.includes("apply");
}

export function isMergeJobType(jobType: string | null | undefined): boolean {
  return (jobType || "").toLowerCase().includes("merge");
}

export function delaysForTerminalJob(job: UiJobView): readonly number[] {
  if (isAmortizationJobType(job.type)) {
    return POST_JOB_RELOAD_DELAYS_AMORTIZATION_MS;
  }
  if (isMergeJobType(job.type)) {
    return POST_JOB_RELOAD_DELAYS_MERGE_MS;
  }
  return POST_JOB_RELOAD_DELAYS_MS;
}

/** Alias usado por ProcessDetailPage y tests de copy. */
export function postJobReloadDelaysFor(job: UiJobView): readonly number[] {
  return delaysForTerminalJob(job);
}

/** Outcomes de negocio terminales: no exigen AMORTIZACION_APLICADA en Control. */
const AMORTIZATION_BUSINESS_TERMINAL_OUTCOMES = new Set([
  "requires_correction",
  "failed",
  "partial",
  "blocked",
  "input_changed_requires_retry",
]);

/** outcome del result_summary (minúsculas) o cadena vacía. */
export function amortizationOutcomeFromJob(job: UiJobView): string {
  const summary = job.result_summary;
  if (!summary || typeof summary !== "object") return "";
  const raw = summary.outcome;
  return typeof raw === "string" ? raw.trim().toLowerCase() : "";
}

/**
 * True si el job completed trae un outcome de negocio que no debe esperar
 * evidencia AMORTIZACION_APLICADA (corrección / fallo parcial / etc.).
 */
export function amortizationJobHasBusinessTerminalOutcome(job: UiJobView): boolean {
  if (!isAmortizationJobType(job.type)) return false;
  if ((job.status || "").toLowerCase() !== "completed") return false;
  return AMORTIZATION_BUSINESS_TERMINAL_OUTCOMES.has(amortizationOutcomeFromJob(job));
}

function isTerminalFailure(jobStatus: string): boolean {
  return (
    jobStatus === "failed" || jobStatus === "cancelled" || jobStatus === "canceled"
  );
}

function stepStatus(detail: UiProcessDetail, name: string): string {
  return (detail.steps.find((s) => s.name === name)?.status || "").toLowerCase();
}

type AmortJobEvidence = "applied" | "needs_attention" | null;

/** Evidencia de negocio en result_summary del job (sin depender solo de Control). */
export function amortizationJobEvidence(job: UiJobView): AmortJobEvidence {
  const rs = job.result_summary;
  if (!rs || typeof rs !== "object") {
    return null;
  }
  const record = rs as Record<string, unknown>;
  if (record.already_applied === true) {
    return "applied";
  }
  const outcome = String(record.outcome || "").trim().toLowerCase();
  if (outcome === "applied" || outcome === "already_applied") {
    return "applied";
  }
  const controlEstado = String(record.process_control_estado || "")
    .trim()
    .toUpperCase();
  if (controlEstado === "AMORTIZACION_APLICADA") {
    return "applied";
  }
  if (
    outcome === "requires_correction" ||
    outcome === "failed" ||
    outcome === "partial" ||
    outcome === "blocked"
  ) {
    return "needs_attention";
  }
  return null;
}

const MERGE_SUCCESS_CONTROL_STATES = new Set(["CONSOLIDADO", "MERGE_PARCIAL"]);

/**
 * Evidencia de Merge en result_summary (cierra sync aunque Control Graph esté stale).
 * Cubre primer Merge y reconsolidar (`force_rebuild_used`).
 */
export function mergeJobEvidence(job: UiJobView): boolean {
  if (!isMergeJobType(job.type)) return false;
  if ((job.status || "").toLowerCase() !== "completed") return false;
  const rs = job.result_summary;
  if (!rs || typeof rs !== "object") return false;
  const record = rs as Record<string, unknown>;
  if (record.already_merged === true) return true;
  const mergeStatus = String(record.merge_control_status || "")
    .trim()
    .toUpperCase();
  if (MERGE_SUCCESS_CONTROL_STATES.has(mergeStatus)) return true;
  const controlEstado = String(record.process_control_estado || "")
    .trim()
    .toUpperCase();
  if (MERGE_SUCCESS_CONTROL_STATES.has(controlEstado)) return true;
  // Reconsolidar OK: el worker marcó force_rebuild_used tras subir PDF + Control.
  if (record.force_rebuild_used === true) return true;
  const links = record.merge_pdf_links;
  return Array.isArray(links) && links.length > 0;
}

/**
 * True cuando la proyección ya refleja el resultado del job (o el job falló
 * y no hace falta esperar evidencia de Control).
 */
export function projectionReflectsTerminalJob(
  detail: UiProcessDetail,
  job: UiJobView,
): boolean {
  const jobType = (job.type || "").toLowerCase();
  const jobStatus = (job.status || "").toLowerCase();
  if (isTerminalFailure(jobStatus)) {
    return true;
  }
  if (jobStatus !== "completed") {
    return false;
  }

  // Amortización: el result del job puede cerrar sync aunque Control aún esté stale.
  if (isAmortizationJobType(jobType)) {
    const evidence = amortizationJobEvidence(job);
    if (evidence === "applied" || evidence === "needs_attention") {
      return true;
    }
  }

  // Merge/reconsolidar: misma idea (result_summary antes que SINCRONIZANDO).
  if (isMergeJobType(jobType) && mergeJobEvidence(job)) {
    return true;
  }

  if (detail.operational_status === "SINCRONIZANDO") {
    return false;
  }

  if (jobType.includes("finalize")) {
    if (stepStatus(detail, "finalize") === "sync_pending") return false;
    return (
      stepStatus(detail, "finalize") === "completed" ||
      (detail.control_estado_proceso || "").toUpperCase() === "FINALIZADO" ||
      detail.operational_status === "PENDIENTE_NOTIFICACION"
    );
  }
  if (jobType.includes("notify")) {
    if (stepStatus(detail, "notify") === "sync_pending") return false;
    return (
      stepStatus(detail, "notify") === "completed" ||
      detail.operational_status === "ESPERANDO_SOPORTES" ||
      Boolean(detail.files.email_pdf_path)
    );
  }
  if (jobType.includes("merge")) {
    if (stepStatus(detail, "merge") === "sync_pending") return false;
    // PENDIENTE_ASIENTOS NO confirma Merge completed (puede ser estado previo).
    return (
      stepStatus(detail, "merge") === "completed" ||
      stepStatus(detail, "merge") === "partial" ||
      (detail.control_estado_proceso || "").toUpperCase() === "CONSOLIDADO" ||
      (detail.control_estado_proceso || "").toUpperCase() === "MERGE_PARCIAL" ||
      detail.operational_status === "LISTO_PARA_APLICAR" ||
      detail.operational_status === "FINALIZADO_PARCIALMENTE"
    );
  }
  if (isAmortizationJobType(jobType)) {
    if (stepStatus(detail, "apply") === "sync_pending") return false;
    return (
      stepStatus(detail, "apply") === "completed" ||
      stepStatus(detail, "apply") === "partial" ||
      detail.operational_status === "COMPLETADO" ||
      (detail.control_estado_proceso || "").toUpperCase() === "AMORTIZACION_APLICADA"
    );
  }
  if (jobType.includes("generate")) {
    if (stepStatus(detail, "generate") === "sync_pending") return false;
    return (
      stepStatus(detail, "generate") === "completed" ||
      detail.operational_status === "EN_REVISION" ||
      detail.operational_status === "CORRECCION_REQUERIDA" ||
      Boolean(detail.files.validation_file_path)
    );
  }
  // Otros tipos: basta con que el GET haya corrido una vez (caller reintenta N veces).
  return true;
}

/**
 * Dashboard Generate: la lista refleja el proceso listo (no SINCRONIZANDO ni
 * corrección falsa por desfase).
 */
export function processListReflectsGenerateJob(
  items: readonly UiProcessSummary[],
  job: UiJobView,
): boolean {
  const jobStatus = (job.status || "").toLowerCase();
  if (isTerminalFailure(jobStatus)) {
    return true;
  }
  if (jobStatus !== "completed") {
    return false;
  }

  const processKey = (job.process_key || "").trim();
  const bank = (job.bank_code || "").trim().toLowerCase();
  const hit =
    items.find((i) => processKey && i.process_key === processKey) ||
    items.find((i) => bank && (i.bank_code || "").toLowerCase() === bank);

  if (!hit) {
    return false;
  }
  if (hit.operational_status === "SINCRONIZANDO") {
    return false;
  }
  // Error real de negocio (p. ej. archivo ausente confirmado): dejar de reintentar.
  if (hit.operational_status === "CORRECCION_REQUERIDA") {
    return true;
  }
  return (
    hit.operational_status === "EN_REVISION" ||
    hit.operational_status === "FINALIZANDO" ||
    hit.operational_status === "PENDIENTE_NOTIFICACION"
  );
}

export type ReloadSyncResult<T> = {
  data: T;
  synced: boolean;
};

/**
 * Reintenta `load` hasta que `reflects` confirme sincronización o se agoten
 * los delays. Misma lógica para dashboard y detalle.
 */
export async function reloadUntilProjectionMatchesJob<T>(
  load: () => Promise<T>,
  terminalJob: UiJobView,
  reflects: (data: T, job: UiJobView) => boolean,
  delaysMs: readonly number[] = POST_JOB_RELOAD_DELAYS_MS,
  sleep: (ms: number) => Promise<void> = (ms) =>
    new Promise((resolve) => {
      window.setTimeout(resolve, ms);
    }),
): Promise<ReloadSyncResult<T>> {
  let last = await load();
  if (reflects(last, terminalJob)) {
    return { data: last, synced: true };
  }
  for (const delayMs of delaysMs.slice(1)) {
    await sleep(delayMs);
    last = await load();
    if (reflects(last, terminalJob)) {
      return { data: last, synced: true };
    }
  }
  return { data: last, synced: false };
}
