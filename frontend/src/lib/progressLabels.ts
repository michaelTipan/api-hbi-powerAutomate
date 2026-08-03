import type { UiJobView, UiProcessDetail } from "../types/contract";

/** Estados de job que mantienen el overlay de progreso activo. */
export function isJobRunningStatus(status: string | null | undefined): boolean {
  const s = (status || "").toLowerCase();
  return s === "queued" || s === "running" || s === "accepted" || s === "pending";
}

export function progressLabelForDetail(
  detail: UiProcessDetail | null | undefined,
): string {
  const jobType = (detail?.active_job?.type || "").toLowerCase();
  if (jobType.includes("finalize")) return "Finalizando revisión…";
  if (jobType.includes("notify")) return "Enviando notificación…";
  if (jobType.includes("merge")) return "Consolidando PDFs…";
  if (jobType.includes("amortization") || jobType.includes("apply")) {
    return "Aplicando amortización…";
  }
  if (jobType.includes("generate")) return "Generando revisión…";
  return "Procesando…";
}

function readStringField(
  bag: Record<string, unknown> | null | undefined,
  key: string,
): string | null {
  if (!bag) return null;
  const v = bag[key];
  return typeof v === "string" && v.trim() ? v.trim() : null;
}

export function formatJobAmounts(job: UiJobView): string | null {
  const result = job.result_summary;
  if (!result || typeof result !== "object") return null;
  const parts: string[] = [];
  for (const key of ["matched_count", "rows_processed", "ready_groups", "ready_items"]) {
    const v = result[key];
    if (typeof v === "number" && Number.isFinite(v)) {
      parts.push(`${key}: ${v}`);
    }
  }
  return parts.length ? parts.join(" · ") : null;
}

export function successMessageFromJob(job: UiJobView): string | null {
  const msg = (job.user_message || "").trim();
  if (msg) return msg;
  return readStringField(job.result_summary ?? undefined, "user_message");
}

export function jobFailureMessage(job: UiJobView): string {
  const err = job.error;
  const fromErr =
    readStringField(err ?? undefined, "user_message") ||
    readStringField(err ?? undefined, "message");
  if (fromErr) return fromErr;
  if (job.user_message?.trim()) return job.user_message.trim();
  return "La operación no se completó. Revise los errores del proceso.";
}
