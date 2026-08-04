/**
 * Issues de corrección de amortización desde result_summary.operational_issues
 * (o detalle de proceso). Presentación operativa; sin jerga técnica al operador.
 */

import type {
  ErrorSeverity,
  IssueCategory,
  UiIssueLocation,
  UiIssueRetry,
  UiJobView,
  UiLink,
  UiOperationalIssue,
} from "../types/contract";
import { jobNextAction, jobUserMessage, looksTechnical } from "./jobMessages";
import { amortizationOutcomeFromJob } from "./jobProjectionSync";

const ISSUE_CATEGORIES = new Set<IssueCategory>([
  "correction_required",
  "temporary_failure",
  "system_failure",
  "warning",
  "partial_result",
]);

const SEVERITIES = new Set<ErrorSeverity>([
  "info",
  "warning",
  "recoverable",
  "business",
  "fatal",
]);

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}

function textOrNull(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const t = value.trim();
  return t || null;
}

function humanTextOrNull(value: unknown): string | null {
  const t = textOrNull(value);
  if (!t || looksTechnical(t)) return null;
  return t;
}

function sanitizeLink(raw: unknown): UiLink | null {
  const row = asRecord(raw);
  if (!row) return null;
  const rel = textOrNull(row.rel);
  if (!rel) return null;
  const openRaw = textOrNull(row.open_mode);
  const open_mode =
    openRaw === "external" || openRaw === "sharepoint" ? openRaw : "sharepoint";
  return {
    rel,
    label: textOrNull(row.label) || "Abrir enlace",
    path: textOrNull(row.path),
    web_url: textOrNull(row.web_url),
    open_mode,
  };
}

function sanitizeLocation(raw: unknown): UiIssueLocation | null {
  const row = asRecord(raw);
  if (!row) return null;
  const rowNum = row.row;
  return {
    file_name: textOrNull(row.file_name),
    sheet: textOrNull(row.sheet),
    row: typeof rowNum === "number" && Number.isFinite(rowNum) ? rowNum : null,
    column: textOrNull(row.column),
    credit: textOrNull(row.credit),
    payment_id: textOrNull(row.payment_id),
    client_name: textOrNull(row.client_name),
  };
}

function sanitizeRetry(raw: unknown): UiIssueRetry | null {
  const row = asRecord(raw);
  if (!row) return null;
  return {
    allowed: Boolean(row.allowed),
    action: textOrNull(row.action),
    label: textOrNull(row.label),
  };
}

function sanitizeCategory(raw: unknown): IssueCategory {
  const t = textOrNull(raw);
  if (t && ISSUE_CATEGORIES.has(t as IssueCategory)) return t as IssueCategory;
  return "correction_required";
}

function sanitizeSeverity(raw: unknown): ErrorSeverity {
  const t = textOrNull(raw);
  if (t && SEVERITIES.has(t as ErrorSeverity)) return t as ErrorSeverity;
  return "business";
}

/** Normaliza un objeto crudo a UiOperationalIssue; descarta filas inválidas. */
export function sanitizeOperationalIssue(
  raw: unknown,
  index: number,
): UiOperationalIssue | null {
  const row = asRecord(raw);
  if (!row) return null;
  const title =
    humanTextOrNull(row.title) ||
    textOrNull(row.title) ||
    "Problema de amortización";
  const user_message =
    humanTextOrNull(row.user_message) ||
    textOrNull(row.user_message) ||
    "Revise los datos de amortización y corrija antes de reintentar.";
  const expectedRaw = row.expected_values;
  const expected_values = Array.isArray(expectedRaw)
    ? expectedRaw
        .map((v) => (typeof v === "string" ? v.trim() : String(v ?? "").trim()))
        .filter(Boolean)
    : [];
  const linksRaw = row.links;
  const links = Array.isArray(linksRaw)
    ? linksRaw.map(sanitizeLink).filter((l): l is UiLink => l != null)
    : [];
  const issue_id =
    textOrNull(row.issue_id) || `amortization-issue-${index + 1}`;
  const stage = textOrNull(row.stage) || "amortization";
  return {
    issue_id,
    stage,
    category: sanitizeCategory(row.category),
    severity: sanitizeSeverity(row.severity),
    recoverable: row.recoverable !== false,
    title,
    user_message,
    location: sanitizeLocation(row.location),
    value_found: textOrNull(row.value_found),
    expected_values,
    next_action: humanTextOrNull(row.next_action) ?? textOrNull(row.next_action),
    retry: sanitizeRetry(row.retry),
    links,
    technical_reference: textOrNull(row.technical_reference),
  };
}

/** Parsea un array crudo (job result_summary o detalle). */
export function parseOperationalIssuesFromUnknown(
  raw: unknown,
): UiOperationalIssue[] {
  if (!Array.isArray(raw) || raw.length === 0) return [];
  const out: UiOperationalIssue[] = [];
  raw.forEach((item, index) => {
    const issue = sanitizeOperationalIssue(item, index);
    if (issue) out.push(issue);
  });
  return out;
}

/**
 * Issues de amortización proyectados en el detalle del proceso
 * (cuando el backend los adjunta a operational_issues).
 */
export function amortizationIssuesFromDetail(
  issues: readonly UiOperationalIssue[],
): UiOperationalIssue[] {
  return issues.filter((issue) => {
    const stage = String(issue.stage || "").trim().toLowerCase();
    if (
      stage === "amortization" ||
      stage === "apply" ||
      stage === "dry_run" ||
      stage === "amortization_process" ||
      stage === "amortization_apply" ||
      stage === "amortization_dry_run"
    ) {
      return true;
    }
    const id = String(issue.issue_id || "").toLowerCase();
    return id.startsWith("amortization-") || id.startsWith("amort-");
  });
}

/**
 * Mapea result_summary.operational_issues del job.
 * Si vacío pero outcome=requires_correction, sintetiza un issue de respaldo.
 */
export function buildAmortizationOperationalIssuesFromJob(
  job: UiJobView,
): UiOperationalIssue[] {
  const summary = job.result_summary;
  const fromSummary = parseOperationalIssuesFromUnknown(
    summary && typeof summary === "object" ? summary.operational_issues : null,
  ).map((issue) => ({
    ...issue,
    stage: issue.stage || "amortization",
  }));
  if (fromSummary.length > 0) return fromSummary;

  if (amortizationOutcomeFromJob(job) !== "requires_correction") return [];

  const msg =
    jobUserMessage(job) ||
    "La amortización requiere correcciones antes de continuar.";
  const next = jobNextAction(job);
  return [
    {
      issue_id: "amortization-correction-fallback",
      stage: "amortization",
      category: "correction_required",
      severity: "business",
      recoverable: true,
      title: "Corrección de amortización",
      user_message: msg,
      location: null,
      value_found: null,
      expected_values: [],
      next_action: next,
      retry: null,
      links: [],
      technical_reference: null,
    },
  ];
}

/** Texto del banner en la fase de amortización. */
export function formatAmortizationIssuesBanner(count: number): string {
  return `${count} problema(s) de amortización.`;
}

/** Resumen corto para JobStatusModal (sin listar cada caso). */
export function amortizationIssuesJobSummary(count: number): string {
  if (count <= 0) {
    return "La amortización requiere correcciones antes de continuar.";
  }
  if (count === 1) {
    return "Se encontró 1 problema de amortización. Revise el detalle y corrija antes de reintentar.";
  }
  return `Se encontraron ${count} problemas de amortización. Revise el detalle y corrija antes de reintentar.`;
}
