import type { UiJobView, UiOperationalIssue } from "../types/contract";
import { parseOperationalIssuesFromUnknown } from "./amortizationOperationalIssues";

function isMergeStageIssue(issue: UiOperationalIssue): boolean {
  const stage = (issue.stage || "").toLowerCase();
  return stage === "merge" || stage === "apply" || stage === "amortization_apply";
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
  hasTerminalJob?: boolean;
}): UiOperationalIssue[] {
  const fresh = input.ephemeralIssues.filter(isMergeStageIssue);
  if (input.hasTerminalJob || fresh.length > 0) return fresh;
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


/** Job terminal + detalle: se reemplazan los viejos del detail si hay frescos del job. */
export function resolveMergeEphemeralFromTerminal(
  job: UiJobView,
  detailIssues: readonly UiOperationalIssue[],
): UiOperationalIssue[] {
  const fromJob = buildMergeOperationalIssuesFromJob(job);
  if (fromJob.length > 0) return fromJob;
  return detailIssues.filter(isMergeStageIssue);
}
