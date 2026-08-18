/** Outcome de negocio de Generate/Regenerate a partir del job (hoja Errores). */

export function isReviewErroresIssue(issue: {
  issue_id: string;
  location?: { sheet?: string | null } | null;
}): boolean {
  return (
    issue.issue_id.startsWith("review-errores-") ||
    (issue.location?.sheet || "").toLowerCase() === "errores"
  );
}

export function reviewErrorCountFromJob(job: {
  result_summary?: Record<string, unknown> | null;
}): number | null {
  const rs = job.result_summary;
  if (!rs || typeof rs !== "object") return null;
  const nested = rs.summary;
  const fromNested =
    nested && typeof nested === "object"
      ? (nested as Record<string, unknown>).errores
      : undefined;
  const raw = fromNested ?? rs.errores;
  if (typeof raw === "number" && Number.isFinite(raw) && raw >= 0) {
    return Math.floor(raw);
  }
  if (typeof raw === "string" && raw.trim() !== "") {
    const n = Number(raw);
    if (Number.isFinite(n) && n >= 0) return Math.floor(n);
  }
  return null;
}

export function reviewErrorCountFromDetail(detail: {
  operational_issues?: readonly {
    issue_id: string;
    location?: { sheet?: string | null } | null;
  }[];
} | null | undefined): number {
  return (detail?.operational_issues ?? []).filter(isReviewErroresIssue).length;
}

/** Prefiere el conteo del job; si el GET aún no lo trae, usa issues del detalle. */
export function resolveGenerateReviewErrorCount(
  job: { result_summary?: Record<string, unknown> | null },
  detail?: {
    operational_issues?: readonly {
      issue_id: string;
      location?: { sheet?: string | null } | null;
    }[];
  } | null,
): number {
  const fromJob = reviewErrorCountFromJob(job);
  if (fromJob != null) return fromJob;
  return reviewErrorCountFromDetail(detail);
}
