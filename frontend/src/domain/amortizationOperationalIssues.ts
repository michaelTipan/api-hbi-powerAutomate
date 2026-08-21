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
  UiProcessDetail,
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
  const sizeRaw = row.file_size;
  const fileSize =
    typeof sizeRaw === "number" && Number.isFinite(sizeRaw)
      ? sizeRaw
      : typeof sizeRaw === "string" && /^\d+$/.test(sizeRaw.trim())
        ? Number(sizeRaw.trim())
        : null;
  return {
    file_name: textOrNull(row.file_name),
    sheet: textOrNull(row.sheet),
    row: typeof rowNum === "number" && Number.isFinite(rowNum) ? rowNum : null,
    column: textOrNull(row.column),
    credit: textOrNull(row.credit),
    payment_id: textOrNull(row.payment_id),
    client_name: textOrNull(row.client_name),
    file_etag: textOrNull(row.file_etag),
    file_size: fileSize,
    file_last_modified: textOrNull(row.file_last_modified),
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

/** Issues persistidos en ``last_amortization_attempt`` (sobreviven refresh). */
export function amortizationIssuesFromLastAttempt(
  detail: Pick<UiProcessDetail, "last_amortization_attempt">,
): UiOperationalIssue[] {
  const raw = detail.last_amortization_attempt?.operational_issues;
  if (!raw?.length) return [];
  return parseOperationalIssuesFromUnknown(raw);
}

/** Preferencia: intento persistido → operational_issues del detalle → estado efímero del job. */
export function resolveAmortizationDisplayIssues(input: {
  last_amortization_attempt?: UiProcessDetail["last_amortization_attempt"];
  operational_issues: readonly UiOperationalIssue[];
  ephemeralIssues: readonly UiOperationalIssue[];
}): UiOperationalIssue[] {
  const persisted = amortizationIssuesFromLastAttempt({
    last_amortization_attempt: input.last_amortization_attempt,
  });
  if (persisted.length > 0) return persisted;
  const fromDetail = amortizationIssuesFromDetail(input.operational_issues);
  if (fromDetail.length > 0) return fromDetail;
  return [...input.ephemeralIssues];
}

const TABLE_REFERENCE_CODES = new Set([
  "TABLE_PATH_NOT_FOUND",
  "TABLE_DOWNLOAD_FAILED",
  "AMORTIZATION_SHEET_NOT_FOUND",
  "FECHA_LIMITE_NOT_FOUND",
  "DUE_DATE_ROW_NOT_FOUND",
  "REQUIRES_APPLICATION_ROW",
  "APPLICATION_ROW_NOT_FOUND",
  "APPLICATION_GROWTH_BLOCKED",
  "AMBIGUOUS_HEADER_MAPPING",
  "ABONO_TABLA_AMORTIZACION_MISSING",
  "PAYOFF_NOT_ACHIEVED",
  "RETENCIONES_COLUMN_MISSING",
  "AMORTIZATION_TABLE_CHANGED_REQUIRES_REVALIDATION",
  "TABLE_APPLY_FAILED",
  "EXCEL_LOCKED",
  "APPLY_SAFETY_ABORT",
  "VERIFICATION_FAILED",
  "VERIFICATION_FORMULA_FAILED",
]);

function creditDigits(raw: string | null | undefined): string {
  const digits = String(raw || "").replace(/\D/g, "");
  return digits.replace(/^0+/, "") || digits;
}

function catalogPathKey(path: string | null | undefined): string {
  return (path || "").replace(/\\/g, "/").replace(/^\/+|\/+$/g, "").toLowerCase();
}

function linkMentionsCredit(link: UiLink, credit: string): boolean {
  const digits = creditDigits(credit);
  if (!digits) return false;
  const hay = `${link.label || ""} ${link.path || ""}`.toLowerCase();
  return (
    hay.includes(digits) ||
    hay.includes(`crédito ${digits}`) ||
    hay.includes(`credito ${digits}`) ||
    hay.includes(`cred ${digits}`)
  );
}

function isAsientosLikeRel(rel: string): boolean {
  return (
    rel === "asientos" ||
    rel === "secretary_file" ||
    rel.startsWith("asientos")
  );
}

function isTableLikeRel(rel: string): boolean {
  return (
    rel === "amortization_table" ||
    rel === "credit_folder" ||
    rel.startsWith("amort_table")
  );
}

function collectAmortizationCatalogLinks(
  detail: Pick<UiProcessDetail, "links" | "document_groups" | "merge_readiness">,
): UiLink[] {
  const out: UiLink[] = [];
  for (const link of detail.links ?? []) {
    if (link.web_url || link.path) out.push(link);
  }
  for (const group of detail.document_groups ?? []) {
    for (const link of group.links ?? []) {
      if (link.web_url || link.path) out.push(link);
    }
  }
  for (const folder of detail.merge_readiness?.folder_links ?? []) {
    if (!folder.path && !folder.web_url) continue;
    const credito = (folder.credito || "").trim();
    out.push({
      rel: "asientos",
      label: credito
        ? `Abrir carpeta ASIENTOS · Crédito ${credito}`
        : folder.label || "Abrir carpeta ASIENTOS",
      path: folder.path ?? null,
      web_url: folder.web_url ?? null,
      open_mode: "sharepoint",
    });
  }
  return out;
}

function fillLinkWebUrl(link: UiLink, catalog: readonly UiLink[]): UiLink {
  if (link.web_url) return link;
  const path = catalogPathKey(link.path);
  if (!path) return link;
  const match = catalog.find((candidate) => {
    if (!candidate.web_url) return false;
    const candidatePath = catalogPathKey(candidate.path);
    if (!candidatePath) return false;
    return (
      candidatePath === path ||
      candidatePath.endsWith(`/${path}`) ||
      path.endsWith(`/${candidatePath}`)
    );
  });
  return match?.web_url ? { ...link, web_url: match.web_url } : link;
}

function dedupeLinks(links: readonly UiLink[]): UiLink[] {
  const out: UiLink[] = [];
  const seen = new Set<string>();
  for (const link of links) {
    const key = catalogPathKey(link.path) || (link.web_url || "").toLowerCase();
    if (!key || seen.has(key)) continue;
    seen.add(key);
    out.push(link);
  }
  return out;
}

/**
 * Garantiza destino clicable: completa web_url desde el detalle del proceso
 * y, si el issue no trae links, toma ASIENTOS/tabla/asientos pendientes del mismo crédito.
 */
export function hydrateAmortizationIssueLinks(
  issues: readonly UiOperationalIssue[],
  detail: Pick<UiProcessDetail, "links" | "document_groups" | "merge_readiness">,
): UiOperationalIssue[] {
  const catalog = collectAmortizationCatalogLinks(detail);
  return issues.map((issue) => {
    const filled = (issue.links ?? []).map((link) => fillLinkWebUrl(link, catalog));
    const openable = filled.filter((link) => Boolean((link.web_url || "").trim()));
    if (openable.length > 0) {
      return { ...issue, links: filled };
    }
    const credit = issue.location?.credit || "";
    const ref = (issue.technical_reference || "").toUpperCase();
    const preferTable = TABLE_REFERENCE_CODES.has(ref);
    const byCredit = catalog.filter(
      (link) => Boolean(link.web_url) && (!credit || linkMentionsCredit(link, credit)),
    );
    let picked = preferTable
      ? byCredit.filter(
          (link) =>
            isTableLikeRel(link.rel) ||
            (link.path || "").toLowerCase().includes(".xls"),
        )
      : byCredit.filter(
          (link) =>
            isAsientosLikeRel(link.rel) ||
            (link.path || "").toUpperCase().includes("ASIENTO"),
        );
    if (picked.length === 0) picked = byCredit;
    if (picked.length === 0) {
      const secretary = catalog.find((l) => l.rel === "secretary_file" && l.web_url);
      const asientos = catalog.find((l) => isAsientosLikeRel(l.rel) && l.web_url);
      const table = catalog.find((l) => isTableLikeRel(l.rel) && l.web_url);
      picked = [secretary, asientos, table].filter((l): l is UiLink => Boolean(l));
    }
    return {
      ...issue,
      links: dedupeLinks([...filled, ...picked]).slice(0, 2),
    };
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

  const outcome = amortizationOutcomeFromJob(job);
  if (outcome !== "requires_correction" && outcome !== "partial" && outcome !== "failed") {
    return [];
  }

  const msg =
    jobUserMessage(job) ||
    (outcome === "partial"
      ? "La amortización terminó de forma parcial. Quedan tablas pendientes. Al reintentar se aplican solo esas; las ya aplicadas no se duplican."
      : "La amortización requiere correcciones antes de continuar.");
  const next = jobNextAction(job);
  return [
    {
      issue_id:
        outcome === "partial"
          ? "amortization-partial-fallback"
          : "amortization-correction-fallback",
      stage: "amortization",
      category: outcome === "partial" ? "partial_result" : "correction_required",
      severity: "business",
      recoverable: true,
      title:
        outcome === "partial" ? "Amortización parcial" : "Corrección de amortización",
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

/** Códigos que requieren corregir ASIENTOS y luego reconsolidar antes de amortizar. */
export const AMORT_RECONSOLIDATE_FAMILY_CODES = new Set([
  "ACCOUNTING_PARSE_FAILED",
  "PDF_TEXT_NOT_EXTRACTABLE",
  "MISSING_BANK_VALUE_BUT_HAS_ACCOUNTING_LINES",
  "ABONO_ASIENTOS_NO_CUADRAN",
]);

export function isAmortReconsolidateFamilyIssue(
  issue: UiOperationalIssue,
): boolean {
  const ref = (issue.technical_reference || "").trim().toUpperCase();
  return Boolean(ref) && AMORT_RECONSOLIDATE_FAMILY_CODES.has(ref);
}

export function hasAmortFormatRecoveryIssues(
  issues: readonly UiOperationalIssue[],
): boolean {
  return issues.some(isAmortReconsolidateFamilyIssue);
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
