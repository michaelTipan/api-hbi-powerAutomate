/**
 * Reconciliación del job local cuando la proyección ya no trae `active_job`.
 *
 * - Jobs terminales: se conservan (U4-B: no borrar el veredicto al desaparecer active_job).
 * - Jobs aún queued/running: se conservan en pantalla, pero el caller debe
 *   reconsultar ese job_id. Si no se reconsulta, un remount mid-Regenerar deja
 *   «Regenerando…» eterno cuando el backend ya marcó completed.
 */
import type { UiJobView } from "../types/contract";
import { isActiveStatus, isTerminalUiJob } from "./resolveDisplayedAttempt";

export type LocalJobWhenActiveAbsent = {
  /** Valor a mostrar de inmediato (antes o en ausencia de refresh). */
  keep: UiJobView | null;
  /** Si no es null, reconsultar JobManager con este id y sustituir `keep`. */
  refreshJobId: string | null;
};

export function resolveLocalJobWhenActiveAbsent(
  prev: UiJobView | null | undefined,
): LocalJobWhenActiveAbsent {
  if (isTerminalUiJob(prev)) {
    return { keep: prev ?? null, refreshJobId: null };
  }
  const jobId = (prev?.job_id || "").trim();
  if (prev && isActiveStatus(prev.status) && jobId) {
    return { keep: prev, refreshJobId: jobId };
  }
  return { keep: null, refreshJobId: null };
}
