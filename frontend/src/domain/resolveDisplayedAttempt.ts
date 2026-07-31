/**
 * Resuelve qué intento mostrar en el detalle de proceso.
 *
 * Regla central (bug U4-B): un `active_job` activo (queued/running) siempre
 * gana. Si no hay activo, un job local recién sondeado (`locallyPolledJob`)
 * que quedó en estado terminal se conserva — nunca se "limpia" solo porque
 * `active_job` desapareció del último `load()`. Si tampoco hay job local
 * terminal, se usa `last_attempt` (o, en su defecto, el más reciente de
 * `latest_attempts_by_stage`) que ya viaja en la proyección del backend.
 */
import type {
  UiActiveJob,
  UiJobView,
  UiLastAttempt,
} from "../types/contract";

export const ACTIVE_JOB_STATUSES: ReadonlySet<string> = new Set([
  "queued",
  "running",
]);

export const TERMINAL_JOB_STATUSES: ReadonlySet<string> = new Set([
  "completed",
  "failed",
  "cancelled",
  "canceled",
  "interrupted",
]);

export type DisplayedAttemptKind = "active" | "polled" | "last_attempt" | "none";

export interface DisplayedAttempt {
  kind: DisplayedAttemptKind;
  status: string | null;
  jobId: string | null;
  jobType: string | null;
  stage: string | null;
  isActive: boolean;
  isTerminal: boolean;
  userMessage: string | null;
  nextAction: string | null;
  errorCode: string | null;
  severity: string | null;
}

export interface ResolveDisplayedAttemptInput {
  activeJob: UiActiveJob | null | undefined;
  locallyPolledJob: UiJobView | null | undefined;
  lastAttempt: UiLastAttempt | null | undefined;
  latestAttemptByStage?: Record<string, UiLastAttempt> | null | undefined;
}

function normalizeStatus(status: string | null | undefined): string {
  return (status || "").toLowerCase();
}

export function isActiveStatus(status: string | null | undefined): boolean {
  return ACTIVE_JOB_STATUSES.has(normalizeStatus(status));
}

export function isTerminalStatus(status: string | null | undefined): boolean {
  return TERMINAL_JOB_STATUSES.has(normalizeStatus(status));
}

export function isTerminalUiJob(job: UiJobView | null | undefined): boolean {
  return Boolean(job) && isTerminalStatus(job?.status);
}

function jobErrorCode(job: UiJobView): string | null {
  const code = job.error?.error_code;
  return typeof code === "string" && code.trim() ? code : null;
}

/** Espejo liviano de `pick_last_attempt` del backend: el más reciente por timestamp. */
export function pickLatestAttempt(
  byStage: Record<string, UiLastAttempt> | null | undefined,
): UiLastAttempt | null {
  const values = Object.values(byStage || {});
  if (values.length === 0) return null;
  return values.reduce((latest, current) => {
    const latestTs = latest.finished_at || latest.started_at || "";
    const currentTs = current.finished_at || current.started_at || "";
    return currentTs > latestTs ? current : latest;
  });
}

const NONE_ATTEMPT: DisplayedAttempt = {
  kind: "none",
  status: null,
  jobId: null,
  jobType: null,
  stage: null,
  isActive: false,
  isTerminal: false,
  userMessage: null,
  nextAction: null,
  errorCode: null,
  severity: null,
};

export function resolveDisplayedAttempt(
  input: ResolveDisplayedAttemptInput,
): DisplayedAttempt {
  const { activeJob, locallyPolledJob, lastAttempt, latestAttemptByStage } = input;

  if (activeJob && isActiveStatus(activeJob.status)) {
    return {
      kind: "active",
      status: activeJob.status,
      jobId: activeJob.job_id,
      jobType: activeJob.type,
      stage: null,
      isActive: true,
      isTerminal: false,
      userMessage: null,
      nextAction: null,
      errorCode: null,
      severity: null,
    };
  }

  if (locallyPolledJob && isTerminalStatus(locallyPolledJob.status)) {
    return {
      kind: "polled",
      status: locallyPolledJob.status,
      jobId: locallyPolledJob.job_id,
      jobType: locallyPolledJob.type,
      stage: null,
      isActive: false,
      isTerminal: true,
      userMessage: locallyPolledJob.user_message ?? null,
      nextAction: locallyPolledJob.next_action ?? null,
      errorCode: jobErrorCode(locallyPolledJob),
      severity: locallyPolledJob.severity ?? null,
    };
  }

  const attempt = lastAttempt ?? pickLatestAttempt(latestAttemptByStage);
  if (attempt) {
    return {
      kind: "last_attempt",
      status: attempt.status,
      jobId: attempt.job_id,
      jobType: attempt.job_type,
      stage: attempt.stage,
      isActive: isActiveStatus(attempt.status),
      isTerminal: isTerminalStatus(attempt.status),
      userMessage: attempt.user_message,
      nextAction: attempt.next_action,
      errorCode: attempt.error_code,
      severity: attempt.severity,
    };
  }

  return NONE_ATTEMPT;
}
