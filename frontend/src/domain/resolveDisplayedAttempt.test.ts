import { describe, expect, it } from "vitest";
import { resolveDisplayedAttempt } from "./resolveDisplayedAttempt";
import type {
  UiActiveJob,
  UiJobView,
  UiLastAttempt,
} from "../types/contract";

function activeJob(overrides: Partial<UiActiveJob> = {}): UiActiveJob {
  return {
    job_id: "job-active-1",
    type: "finalize",
    status: "running",
    store: "job_manager",
    poll_path_graph: null,
    poll_path_ui: "/api/ui/v1/jobs/job-active-1",
    started_at: "2026-07-31T10:00:00-05:00",
    progress: null,
    ...overrides,
  };
}

function polledJob(overrides: Partial<UiJobView> = {}): UiJobView {
  return {
    job_id: "job-polled-1",
    type: "finalize",
    status: "failed",
    store: "job_manager",
    process_key: "payment-validation|banco_bogota|2026-07-31|abc",
    bank_code: "banco_bogota",
    environment: "sandbox",
    created_at: null,
    started_at: null,
    finished_at: "2026-07-31T10:05:00-05:00",
    result_summary: null,
    error: { error_code: "invalid_estado_pago" },
    user_message: "La revisión requiere correcciones.",
    next_action: "Corrija el valor y vuelva a verificar.",
    severity: "warning",
    raw_available: true,
    ...overrides,
  };
}

function lastAttempt(overrides: Partial<UiLastAttempt> = {}): UiLastAttempt {
  return {
    stage: "finalize",
    job_id: "job-attempt-1",
    job_type: "finalize",
    status: "failed",
    outcome: null,
    recoverable: true,
    error_code: "invalid_estado_pago",
    severity: "warning",
    user_message: "La revisión requiere correcciones.",
    next_action: "Corrija el valor y vuelva a verificar.",
    started_at: "2026-07-31T09:00:00-05:00",
    finished_at: "2026-07-31T09:05:00-05:00",
    progress: null,
    technical_reference: "job:job-attempt-1|code:invalid_estado_pago",
    ...overrides,
  };
}

describe("resolveDisplayedAttempt", () => {
  it("prioriza un active_job en queued/running sobre cualquier otra evidencia", () => {
    const result = resolveDisplayedAttempt({
      activeJob: activeJob({ status: "queued" }),
      locallyPolledJob: polledJob(),
      lastAttempt: lastAttempt(),
    });
    expect(result.kind).toBe("active");
    expect(result.isActive).toBe(true);
    expect(result.jobId).toBe("job-active-1");
  });

  it("running también gana", () => {
    const result = resolveDisplayedAttempt({
      activeJob: activeJob({ status: "running" }),
      locallyPolledJob: null,
      lastAttempt: null,
    });
    expect(result.kind).toBe("active");
  });

  it("BUG U4-B: no vacía el error cuando active_job desaparece pero el job sondeado quedó terminal", () => {
    const result = resolveDisplayedAttempt({
      activeJob: null,
      locallyPolledJob: polledJob({ status: "failed" }),
      lastAttempt: null,
    });
    expect(result.kind).toBe("polled");
    expect(result.isTerminal).toBe(true);
    expect(result.userMessage).toBe("La revisión requiere correcciones.");
    expect(result.nextAction).toBe("Corrija el valor y vuelva a verificar.");
    expect(result.errorCode).toBe("invalid_estado_pago");
  });

  it("usa last_attempt cuando no hay active_job ni job local terminal", () => {
    const result = resolveDisplayedAttempt({
      activeJob: null,
      locallyPolledJob: null,
      lastAttempt: lastAttempt(),
    });
    expect(result.kind).toBe("last_attempt");
    expect(result.stage).toBe("finalize");
    expect(result.userMessage).toBe("La revisión requiere correcciones.");
  });

  it("ignora un job local todavía en curso (no terminal) y cae a last_attempt", () => {
    const result = resolveDisplayedAttempt({
      activeJob: null,
      locallyPolledJob: polledJob({ status: "running" }),
      lastAttempt: lastAttempt(),
    });
    expect(result.kind).toBe("last_attempt");
  });

  it("usa el más reciente de latest_attempts_by_stage si no hay last_attempt directo", () => {
    const older = lastAttempt({
      stage: "notify",
      job_id: "job-notify",
      finished_at: "2026-07-30T08:00:00-05:00",
    });
    const newer = lastAttempt({
      stage: "merge",
      job_id: "job-merge",
      finished_at: "2026-07-31T08:00:00-05:00",
    });
    const result = resolveDisplayedAttempt({
      activeJob: null,
      locallyPolledJob: null,
      lastAttempt: null,
      latestAttemptByStage: { notify: older, merge: newer },
    });
    expect(result.kind).toBe("last_attempt");
    expect(result.jobId).toBe("job-merge");
  });

  it("devuelve kind=none cuando no hay ninguna evidencia", () => {
    const result = resolveDisplayedAttempt({
      activeJob: null,
      locallyPolledJob: null,
      lastAttempt: null,
    });
    expect(result.kind).toBe("none");
    expect(result.userMessage).toBeNull();
  });

  it("un active_job con status inesperado (no queued/running) no bloquea el fallback", () => {
    const result = resolveDisplayedAttempt({
      activeJob: activeJob({ status: "unknown" }),
      locallyPolledJob: polledJob({ status: "completed" }),
      lastAttempt: null,
    });
    expect(result.kind).toBe("polled");
  });
});
