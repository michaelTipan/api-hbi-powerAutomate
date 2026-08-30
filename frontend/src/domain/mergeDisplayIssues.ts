/**
 * Issues de soporte merge (fase 3) con prioridad efímera del job terminal.
 */

import type { UiJobView, UiOperationalIssue } from "../types/contract";
import { parseOperationalIssuesFromUnknown } from "./amortizationOperationalIssues";

function isMergeStageIssue(issue: UiOperationalIssue): boolean {
  return (issue.stage || "").trim().toLowerCase() === "merge";
}

export function buildMergeOperationalIssuesFromJob(job: UiJobView): UiOperationalIssue[] {
  const summary = job.result_summary;
  const raw =
    summary && typeof summary === "object" ? summary.operational_issues : null;
  return parseOperationalIssuesFromUnknown(raw).filter(isMergeStageIssue);
}

export function resolveMergeJobIssues(input: {
  operational_issues: readonly UiOperationalIssue[];
  ephemeralIssues: readonly UiOperationalIssue[];
}): UiOperationalIssue[] {
  const fresh = input.ephemeralIssues.filter(isMergeStageIssue);
  if (fresh.length > 0) return fresh;
  return input.operational_issues.filter(isMergeStageIssue);
}

export function mergeIssuesProjectionFresh(
  detailIssues: readonly UiOperationalIssue[],
  job: UiJobView,
): boolean {
  const expected = buildMergeOperationalIssuesFromJob(job);
  if (expected.length === 0) return true;
  const detailMerge = detailIssues.filter(isMergeStageIssue);
  if (detailMerge.length < expected.length) return false;
  const expectedIds = new Set(expected.map((i) => i.issue_id));
  return expected.every((issue) => expectedIds.has(issue.issue_id) &&
    detailMerge.some((d) => d.issue_id === issue.issue_id));
}

function mergeIssueKey(issue: UiOperationalIssue): string {
  const credit = (issue.location?.credit || "").trim();
  const ref = (issue.technical_reference || "").trim();
  const fromRef = /(?:^|\|)code:([^|]+)/i.exec(ref);
  const code = (fromRef?.[1] || ref).trim();
  const id = (issue.issue_id || "").trim();
  if (id) return `id:${id}`;
  return `credit:${credit}|code:${code}`;
}

/** Job terminal + detalle: misma regla que revisión (unión sin duplicados). */
export function resolveMergeEphemeralFromTerminal(
  job: UiJobView,
  detailIssues: readonly UiOperationalIssue[],
): UiOperationalIssue[] {
  const fromJob = buildMergeOperationalIssuesFromJob(job);
  const fromDetail = detailIssues.filter(isMergeStageIssue);
  const seen = new Set<string>();
  const out: UiOperationalIssue[] = [];
  for (const issue of [...fromJob, ...fromDetail]) {
    const key = mergeIssueKey(issue);
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(issue);
  }
  return out;
}
