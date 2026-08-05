/**
 * Presentación del fallo de Finalize en el modal de resultado:
 * - Procesar≠SI / puertas de Control: detalle + enlace al Excel.
 * - Correcciones de Distribución: mensaje corto → Problemas operativos.
 */
import type {
  UiJobView,
  UiLink,
  UiOperationalIssue,
  UiProcessDetail,
} from "../types/contract";
import { actionLabels } from "../copy/labels";
import {
  compactFinalizeFailureMessage,
  isFinalizeOperationalIssue,
  shouldCompactFinalizeJobModal,
} from "./finalizeDistributionIssues";

export type JobFailureIssue = {
  id: string;
  message: string;
  location: string | null;
};

function fromOperationalIssue(issue: UiOperationalIssue): JobFailureIssue {
  return {
    id: issue.issue_id,
    message: issue.user_message,
    // Ubicación técnica (archivo/hoja/fila/IDs) no se muestra en el modal de job.
    location: null,
  };
}

export {
  compactFinalizeFailureMessage,
  shouldCompactFinalizeJobModal,
};

/** Issues de Finalize ya proyectados en el detalle del proceso. */
export function finalizeIssuesFromDetail(
  detail: UiProcessDetail | null | undefined,
): JobFailureIssue[] {
  if (!detail) return [];
  return detail.operational_issues
    .filter(isFinalizeOperationalIssue)
    .map(fromOperationalIssue);
}

/**
 * Issues adjuntos por GET /jobs (error.issues) tras un Finalize fallido.
 * Forma laxa: el contrato sigue siendo dict en error.
 */
export function finalizeIssuesFromJob(job: UiJobView | null | undefined): JobFailureIssue[] {
  const err = job?.error;
  if (!err || typeof err !== "object") return [];
  const raw = err.issues;
  if (!Array.isArray(raw) || raw.length === 0) return [];
  const out: JobFailureIssue[] = [];
  for (let i = 0; i < raw.length; i += 1) {
    const item = raw[i];
    if (!item || typeof item !== "object") continue;
    const o = item as Record<string, unknown>;
    const message =
      (typeof o.user_message === "string" && o.user_message.trim()) ||
      (typeof o.message === "string" && o.message.trim()) ||
      "";
    if (!message) continue;
    const id =
      (typeof o.issue_id === "string" && o.issue_id.trim()) ||
      `finalize-issue-${i}`;
    out.push({
      id,
      message,
      location: null,
    });
  }
  return out;
}

export function reviewExcelLinkFromDetail(
  detail: UiProcessDetail | null | undefined,
): UiLink | null {
  if (!detail) return null;
  return detail.links.find((l) => l.rel === "review_excel" && l.web_url) ?? null;
}

/** Enlace de revisión con etiqueta operativa estable. */
export function reviewExcelModalLink(
  detail: UiProcessDetail | null | undefined,
): UiLink | null {
  const link = reviewExcelLinkFromDetail(detail);
  if (!link?.web_url) return null;
  return {
    ...link,
    label: link.label || actionLabels.open_review_excel,
  };
}

/**
 * Combina job + detalle: prioriza issues del job (inmediatos tras el poll),
 * luego los del detalle proyectado.
 */
export function resolveFinalizeFailureIssues(
  job: UiJobView | null | undefined,
  detail: UiProcessDetail | null | undefined,
): JobFailureIssue[] {
  const fromJob = finalizeIssuesFromJob(job);
  if (fromJob.length > 0) return fromJob;
  return finalizeIssuesFromDetail(detail);
}

export function isFinalizeJob(job: { type?: string | null } | null | undefined): boolean {
  return (job?.type || "").toLowerCase().includes("finalize");
}
