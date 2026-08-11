/**
 * Fallos de Finalize por datos del Excel de revisión (Aplicacion_Pagos).
 * Agrupa por fila y decide cuándo el modal de job debe ser corto.
 */
import type {
  UiJobView,
  UiLink,
  UiOperationalIssue,
  UiProcessDetail,
} from "../types/contract";

/** Códigos de Control / hoja Errores: el modal de job sigue mostrando el detalle. */
const FINALIZE_JOB_DETAIL_CODES = new Set([
  "process_not_approved",
  "review_has_open_errors",
  "missing_control_state",
  "invalid_control_state",
]);

export function isFinalizeOperationalIssue(
  issue: UiOperationalIssue,
): boolean {
  if ((issue.stage || "").toLowerCase() === "finalize") return true;
  return issue.issue_id.startsWith("HBI-FINALIZE-");
}

export function finalizeErrorCodeFromJob(
  job: UiJobView | null | undefined,
): string | null {
  const code = job?.error?.error_code;
  return typeof code === "string" && code.trim() ? code.trim() : null;
}

export function extractFinalizeIssueCode(
  issue: UiOperationalIssue,
): string | null {
  const ref = (issue.technical_reference || "").trim();
  const fromRef = /(?:^|\|)code:([^|]+)/i.exec(ref);
  if (fromRef?.[1]?.trim()) return fromRef[1].trim();
  const id = issue.issue_id || "";
  const prefix = /^HBI-FINALIZE-(.+)$/i.exec(id);
  if (!prefix?.[1]) return null;
  // Sufijo típico: -<job8hex> o -<job8hex>-<idx>
  const withoutJobSuffix = prefix[1].replace(/-[0-9a-f]{8}(?:-\d+)?$/i, "");
  return withoutJobSuffix.trim() || null;
}

/** Fallos de puerta (Procesar=SI, hoja Errores, Control): no agrupar por fila. */
export function isFinalizeGateIssue(issue: UiOperationalIssue): boolean {
  if (!isFinalizeOperationalIssue(issue)) return false;
  const code = extractFinalizeIssueCode(issue);
  return Boolean(code && FINALIZE_JOB_DETAIL_CODES.has(code));
}

/**
 * Correcciones de Aplicacion_Pagos del mismo Excel de revisión.
 * Una fila puede acumular varios códigos; se agrupan en una sola tarjeta.
 */
export function isFinalizeDistributionRowIssue(
  issue: UiOperationalIssue,
): boolean {
  if (!isFinalizeOperationalIssue(issue)) return false;
  if (isFinalizeGateIssue(issue)) return false;
  const sheet = (issue.location?.sheet || "").toLowerCase();
  if (
    sheet.includes("aplicacion_pagos") ||
    sheet.includes("aplicacion pagos") ||
    sheet.includes("aplicación")
  ) {
    return true;
  }
  // Finalize expandido sin hoja explícita (p. ej. proyecciones antiguas).
  return issue.issue_id.startsWith("HBI-FINALIZE-");
}

export function shouldCompactFinalizeJobModal(
  job: UiJobView | null | undefined,
  detail: UiProcessDetail | null | undefined,
): boolean {
  const code = finalizeErrorCodeFromJob(job);
  if (code && FINALIZE_JOB_DETAIL_CODES.has(code)) return false;
  if (code === "multiple_review_errors") return true;
  if (code && !FINALIZE_JOB_DETAIL_CODES.has(code)) {
    // Un solo missing_* / amount_mismatch / etc. también va al resumen corto.
    return true;
  }
  const fromDetail = (detail?.operational_issues ?? []).filter(
    isFinalizeDistributionRowIssue,
  );
  return fromDetail.length > 0;
}

export function compactFinalizeFailureMessage(issueCount: number): string {
  if (issueCount <= 0) {
    return (
      "Hay problemas en la revisión. Revíselos en Problemas operativos, " +
      "corrija el Excel, guarde y vuelva a verificar."
    );
  }
  if (issueCount === 1) {
    return (
      "Hay 1 problema en la revisión. Revíselo en Problemas operativos, " +
      "corrija el Excel, guarde y vuelva a verificar."
    );
  }
  return (
    `Hay ${issueCount} problemas en la revisión. Revíselos en Problemas operativos, ` +
    "corrija el Excel, guarde y vuelva a verificar."
  );
}

export type FinalizeRowIssueGroup = {
  key: string;
  /** Título en español, p. ej. «Fila 12». */
  title: string;
  row: number | null;
  credit: string | null;
  paymentId: string | null;
  clientName: string | null;
  messages: string[];
  issues: UiOperationalIssue[];
};

function rowGroupKey(issue: UiOperationalIssue): string {
  const row = issue.location?.row;
  if (typeof row === "number" && Number.isFinite(row) && row > 0) {
    return `row:${row}`;
  }
  const paymentId = (issue.location?.payment_id || "").trim();
  if (paymentId) return `pago:${paymentId}`;
  const credit = (issue.location?.credit || "").trim();
  if (credit) return `credito:${credit}`;
  return `issue:${issue.issue_id}`;
}

function rowGroupTitle(issue: UiOperationalIssue, key: string): string {
  const row = issue.location?.row;
  if (typeof row === "number" && Number.isFinite(row) && row > 0) {
    return `Fila ${row}`;
  }
  if (key.startsWith("pago:")) return `Pago ${key.slice(5)}`;
  if (key.startsWith("credito:")) return `Crédito ${key.slice(8)}`;
  return "Fila sin número";
}

export function groupFinalizeIssuesByRow(
  issues: readonly UiOperationalIssue[],
): FinalizeRowIssueGroup[] {
  const map = new Map<string, FinalizeRowIssueGroup>();
  for (const issue of issues) {
    if (!isFinalizeDistributionRowIssue(issue)) continue;
    const key = rowGroupKey(issue);
    const existing = map.get(key);
    const message = (issue.user_message || "").trim();
    if (existing) {
      if (message && !existing.messages.includes(message)) {
        existing.messages.push(message);
      }
      existing.issues.push(issue);
      continue;
    }
    map.set(key, {
      key,
      title: rowGroupTitle(issue, key),
      row:
        typeof issue.location?.row === "number" ? issue.location.row : null,
      credit: issue.location?.credit?.trim() || null,
      paymentId: issue.location?.payment_id?.trim() || null,
      clientName: issue.location?.client_name?.trim() || null,
      messages: message ? [message] : [],
      issues: [issue],
    });
  }
  return [...map.values()].sort((a, b) => {
    const ar = a.row ?? Number.MAX_SAFE_INTEGER;
    const br = b.row ?? Number.MAX_SAFE_INTEGER;
    if (ar !== br) return ar - br;
    return a.title.localeCompare(b.title, "es");
  });
}

/** Enlace único al Excel de revisión (mismo destino para todas las filas). */
export function sharedReviewExcelLink(
  issues: readonly UiOperationalIssue[],
): UiLink | null {
  for (const issue of issues) {
    const link = issue.links.find(
      (l) => l.rel === "review_excel" && l.web_url,
    );
    if (link?.web_url) return link;
  }
  return null;
}

/** Acción de reintento compartida (Verificar nuevamente → finalize). */
export function sharedFinalizeRetryAction(
  issues: readonly UiOperationalIssue[],
): { action: string; label: string } | null {
  for (const issue of issues) {
    if (issue.retry?.allowed && issue.retry.action) {
      return {
        action: issue.retry.action,
        label: issue.retry.label || "Verificar nuevamente",
      };
    }
  }
  return null;
}

export function partitionOperationalIssuesForModal(
  issues: readonly UiOperationalIssue[],
): {
  rowGroups: FinalizeRowIssueGroup[];
  otherIssues: UiOperationalIssue[];
} {
  const rowSource: UiOperationalIssue[] = [];
  const otherIssues: UiOperationalIssue[] = [];
  for (const issue of issues) {
    if (isFinalizeDistributionRowIssue(issue)) rowSource.push(issue);
    else otherIssues.push(issue);
  }
  return {
    rowGroups: groupFinalizeIssuesByRow(rowSource),
    otherIssues,
  };
}
