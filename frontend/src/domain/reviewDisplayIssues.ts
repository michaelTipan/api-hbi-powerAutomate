/**
 * Issues de revisión (fase 1) con prioridad efímera del job terminal → detalle Graph.
 * Evita banners stale cuando Control va atrasado respecto al JSON del job.
 */

import type { UiJobView, UiOperationalIssue, UiProcessDetail } from "../types/contract";
import {
  isReviewErroresIssue,
  reviewErrorCountFromDetail,
  reviewErrorCountFromJob,
} from "./generateJobOutcome";
import { isFinalizeJob } from "./finalizeJobFailure";
import { parseOperationalIssuesFromUnknown } from "./amortizationOperationalIssues";

function isReviewStageIssue(issue: UiOperationalIssue): boolean {
  const stage = (issue.stage || "").trim().toLowerCase();
  if (!stage) return true;
  if (stage === "merge" || stage === "amortization" || stage === "apply") return false;
  if (stage.startsWith("amortization_")) return false;
  return true;
}

function nonMergeIssues(
  issues: readonly UiOperationalIssue[],
): UiOperationalIssue[] {
  return issues.filter(isReviewStageIssue);
}

function parseJobErrorIssues(job: UiJobView): UiOperationalIssue[] {
  const err = job.error;
  if (!err || typeof err !== "object") return [];
  const raw = (err as Record<string, unknown>).issues;
  return parseOperationalIssuesFromUnknown(raw).map((issue, index) => ({
    ...issue,
    stage: isFinalizeJob(job) ? "finalize" : issue.stage === "amortization" ? "review" : issue.stage,
    issue_id: issue.issue_id || `review-job-issue-${index + 1}`,
  }));
}

/** Issues de revisión desde result_summary / error del job terminal. */
export function buildReviewOperationalIssuesFromJob(job: UiJobView): UiOperationalIssue[] {
  const summary = job.result_summary;
  const rawSummary =
    summary && typeof summary === "object" ? summary.operational_issues : null;
  const fromSummary = nonMergeIssues(parseOperationalIssuesFromUnknown(rawSummary));
  if (fromSummary.length > 0) return fromSummary;

  const fromError = nonMergeIssues(parseJobErrorIssues(job));
  if (fromError.length > 0) return fromError;

  const jobErrores = reviewErrorCountFromJob(job);
  if (jobErrores != null && jobErrores > 0) {
    return Array.from({ length: jobErrores }, (_, index) => ({
      issue_id: `review-errores-job-${index + 1}`,
      stage: "review",
      category: "correction_required",
      severity: "business",
      recoverable: true,
      title: "Caso en Errores",
      user_message: "Revise la hoja Errores del archivo de revisión.",
      location: { sheet: "Errores", file_name: null, row: null, column: null, credit: null, payment_id: null, client_name: null },
      value_found: null,
      expected_values: [],
      next_action: null,
      retry: null,
      links: [],
      technical_reference: null,
    }));
  }

  return [];
}

/** Preferencia: efímeros del job → operational_issues del detalle (sin merge). */
export function resolveReviewDisplayIssues(input: {
  operational_issues: readonly UiOperationalIssue[];
  ephemeralIssues: readonly UiOperationalIssue[];
}): UiOperationalIssue[] {
  const fresh = nonMergeIssues(input.ephemeralIssues);
  if (fresh.length > 0) return fresh;
  return nonMergeIssues(input.operational_issues);
}

/** Une listas de issues de revisión sin duplicar issue_id. */
export function mergeReviewOperationalIssues(
  ...sources: readonly (readonly UiOperationalIssue[])[]
): UiOperationalIssue[] {
  const seen = new Set<string>();
  const out: UiOperationalIssue[] = [];
  for (const list of sources) {
    for (const issue of list) {
      const id = (issue.issue_id || "").trim();
      const key = id || `msg:${(issue.user_message || "").trim()}:${out.length}`;
      if (seen.has(key)) continue;
      seen.add(key);
      out.push(issue);
    }
  }
  return nonMergeIssues(out);
}

/**
 * Issues de revisión para banner/modal tras job terminal: job inmediato +
 * detalle proyectado (el más completo gana por unión).
 */
export function resolveReviewEphemeralFromTerminal(
  job: UiJobView,
  detail?: UiProcessDetail | null,
): UiOperationalIssue[] {
  const jobType = (job.type || "").toLowerCase();
  const jobStatus = (job.status || "").toLowerCase();
  const fromJob = buildReviewOperationalIssuesFromJob(job);
  const fromDetail = detail ? nonMergeIssues(detail.operational_issues) : [];

  if (jobType.includes("generate") && jobStatus === "completed") {
    const errores = reviewErrorCountFromJob(job);
    if (errores === 0) return [];
    if (fromJob.length > 0) return fromJob;
  }

  if (fromJob.length > 0) {
    if (areSyntheticErroresJobIssues(fromJob)) {
      return fromJob;
    }
    return mergeReviewOperationalIssues(fromJob, fromDetail);
  }
  return fromDetail;
}

/** Mensaje unificado para modales/banners de revisión con el mismo conteo. */
export function formatReviewOutcomeMessage(issues: readonly UiOperationalIssue[]): string {
  return (
    formatReviewStatusMessage(issues) ||
    compactReviewOutcomeFallback(issues.length)
  );
}

function compactReviewOutcomeFallback(count: number): string {
  if (count <= 0) {
    return (
      "Hay problemas en la revisión. Revíselos en Problemas operativos, " +
      "corrija el Excel, guarde y vuelva a verificar."
    );
  }
  if (count === 1) {
    return (
      "Hay 1 problema en la revisión. Revíselo en Problemas operativos, " +
      "corrija el Excel, guarde y vuelva a verificar."
    );
  }
  return (
    `Hay ${count} problemas en la revisión. Revíselos en Problemas operativos, ` +
    "corrija el Excel, guarde y vuelva a verificar."
  );
}

function issueSetsMatch(
  detailIssues: readonly UiOperationalIssue[],
  expected: readonly UiOperationalIssue[],
): boolean {
  if (expected.length === 0) return true;
  if (detailIssues.length < expected.length) return false;
  const detailIds = new Set(
    detailIssues.map((issue) => (issue.issue_id || "").trim()).filter(Boolean),
  );
  if (detailIds.size === 0) return false;
  return expected.every((issue) => {
    const id = (issue.issue_id || "").trim();
    return Boolean(id && detailIds.has(id));
  });
}

function areSyntheticErroresJobIssues(issues: readonly UiOperationalIssue[]): boolean {
  return (
    issues.length > 0 &&
    issues.every((issue) => (issue.issue_id || "").startsWith("review-errores-job-"))
  );
}

/**
 * True cuando el GET ya trae los mismos issues de revisión que el job terminal
 * (o el conteo de hoja Errores coincide con result_summary.errores).
 */
export function reviewIssuesProjectionFresh(
  detail: UiProcessDetail,
  job: UiJobView,
): boolean {
  const jobType = (job.type || "").toLowerCase();
  const jobStatus = (job.status || "").toLowerCase();
  const detailReview = nonMergeIssues(detail.operational_issues);
  const expectedFromJob = buildReviewOperationalIssuesFromJob(job);

  if (expectedFromJob.length > 0) {
    if (areSyntheticErroresJobIssues(expectedFromJob)) {
      if (detail.operational_status !== "CORRECCION_REQUERIDA") return false;
      return reviewErrorCountFromDetail(detail) === expectedFromJob.length;
    }
    if (detailReview.length < expectedFromJob.length) return false;
    return issueSetsMatch(detailReview, expectedFromJob);
  }

  const jobErrores = reviewErrorCountFromJob(job);
  if (jobErrores != null && jobType.includes("generate")) {
    if (jobErrores > 0) {
      if (detail.operational_status !== "CORRECCION_REQUERIDA") return false;
      return reviewErrorCountFromDetail(detail) === jobErrores;
    }
    return detail.operational_status === "EN_REVISION";
  }

  if (jobStatus === "failed" && jobType.includes("finalize")) {
    if (expectedFromJob.length === 0) return true;
    if (detailReview.length === 0) return false;
    return issueSetsMatch(detailReview, expectedFromJob);
  }

  return true;
}

export function formatReviewErroresBannerCount(count: number): string {
  return `${count} caso(s) en la hoja Errores`;
}

export function formatReviewOperationalBannerCount(count: number): string {
  return `${count} problema(s) operativo(s).`;
}

/** Encabezado del banner fase 1: mismo total que el modal Problemas operativos. */
export function formatReviewBannerHeadline(issues: readonly UiOperationalIssue[]): string | null {
  const total = issues.length;
  if (total <= 0) return null;
  const errores = issues.filter(isReviewErroresIssue).length;
  if (errores > 0 && errores === total) {
    return formatReviewErroresBannerCount(errores);
  }
  return formatReviewOperationalBannerCount(total);
}

/** Hint secundario del banner: solo copy de Errores cuando todos son de esa hoja. */
export function reviewBannerUsesErroresHint(issues: readonly UiOperationalIssue[]): boolean {
  const total = issues.length;
  if (total <= 0) return false;
  return issues.filter(isReviewErroresIssue).length === total;
}

/** Mensaje bajo el badge cuando hay issues frescos del job. */
export function formatReviewStatusMessage(issues: readonly UiOperationalIssue[]): string | null {
  const total = issues.length;
  if (total <= 0) return null;
  const errores = issues.filter(isReviewErroresIssue).length;
  if (errores > 0 && errores === total) {
    if (errores === 1) {
      return "Hay 1 caso en la hoja Errores. Revíselo en Problemas operativos, corrija el Excel, guarde y vuelva a verificar.";
    }
    return `Hay ${errores} casos en la hoja Errores. Revíselos en Problemas operativos, corrija el Excel, guarde y vuelva a verificar.`;
  }
  if (total === 1) {
    return "Hay 1 problema en la revisión. Revíselo en Problemas operativos, corrija el Excel, guarde y vuelva a verificar.";
  }
  return `Hay ${total} problemas en la revisión. Revíselos en Problemas operativos, corrija el Excel, guarde y vuelva a verificar.`;
}
