/**
 * Presentación del fallo de Finalize en el modal de resultado:
 * lista de problemas concretos + enlace al Excel de revisión.
 */
import type {
  UiIssueLocation,
  UiJobView,
  UiLink,
  UiOperationalIssue,
  UiProcessDetail,
} from "../types/contract";
import { actionLabels } from "../copy/labels";

export type JobFailureIssue = {
  id: string;
  message: string;
  location: string | null;
};

export function formatIssueLocation(
  loc: UiIssueLocation | null | undefined,
): string | null {
  if (!loc) return null;
  const parts = [
    loc.sheet ? `Hoja: ${loc.sheet}` : null,
    loc.row != null ? `Fila: ${loc.row}` : null,
    loc.column ? `Columna: ${loc.column}` : null,
    loc.client_name ? `Cliente: ${loc.client_name}` : null,
    loc.credit ? `Crédito: ${loc.credit}` : null,
    loc.payment_id ? `ID pago: ${loc.payment_id}` : null,
  ].filter((p): p is string => Boolean(p));
  return parts.length > 0 ? parts.join(" · ") : null;
}

function fromOperationalIssue(issue: UiOperationalIssue): JobFailureIssue {
  return {
    id: issue.issue_id,
    message: issue.user_message,
    location: formatIssueLocation(issue.location),
  };
}

function isFinalizeOperationalIssue(issue: UiOperationalIssue): boolean {
  if ((issue.stage || "").toLowerCase() === "finalize") return true;
  return issue.issue_id.startsWith("HBI-FINALIZE-");
}

/** Issues de Finalize ya proyectados en el detalle del proceso. */
export function finalizeIssuesFromDetail(
  detail: UiProcessDetail | null | undefined,
): JobFailureIssue[] {
  if (!detail) return [];
  return detail.operational_issues
    .filter(isFinalizeOperationalIssue)
    .map(fromOperationalIssue);
}

function asLocation(value: unknown): UiIssueLocation | null {
  if (!value || typeof value !== "object") return null;
  const o = value as Record<string, unknown>;
  return {
    file_name: typeof o.file_name === "string" ? o.file_name : null,
    sheet: typeof o.sheet === "string" ? o.sheet : null,
    row: typeof o.row === "number" ? o.row : null,
    column: typeof o.column === "string" ? o.column : null,
    credit: typeof o.credit === "string" ? o.credit : null,
    payment_id: typeof o.payment_id === "string" ? o.payment_id : null,
    client_name: typeof o.client_name === "string" ? o.client_name : null,
  };
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
      location: formatIssueLocation(asLocation(o.location)),
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
