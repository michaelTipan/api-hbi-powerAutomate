import { describe, expect, it, vi } from "vitest";
import type { UiJobView, UiProcessDetail, UiProcessSummary, UiStepState } from "../types/contract";
import {
  POST_JOB_RELOAD_DELAYS_AMORTIZATION_MS,
  POST_JOB_RELOAD_DELAYS_MS,
  delaysForTerminalJob,
  processListReflectsGenerateJob,
  projectionReflectsTerminalJob,
  reloadUntilProjectionMatchesJob,
} from "./jobProjectionSync";

function step(name: UiStepState["name"], status: UiStepState["status"]): UiStepState {
  return { name, status, updated_at: null, summary: null, can_retry: false, retry_action: null };
}

function detail(overrides: Partial<UiProcessDetail>): UiProcessDetail {
  return {
    process_key: "pk",
    process_id: "id",
    bank_code: "banco_bancolombia",
    bank_name: "Bancolombia",
    process_date: "2026-08-01",
    environment: "sandbox",
    operational_status: "EN_REVISION",
    control_estado_proceso: "REVISION_CREADA",
    is_active: true,
    steps: [
      step("generate", "completed"),
      step("review", "in_progress"),
      step("finalize", "not_started"),
      step("notify", "not_started"),
      step("merge", "not_started"),
      step("dry_run", "not_started"),
      step("apply", "not_started"),
    ],
    items: [],
    active_job: null,
    last_attempt: null,
    latest_attempts_by_stage: {},
    attempts: [],
    next_actions: [],
    available_actions: {},
    errors: [],
    operational_issues: [],
    links: [],
    files: {
      validation_file_path: "rev.xlsx",
      historical_file_path: null,
      secretary_file_path: null,
      email_pdf_path: null,
      merge_manifest_path: null,
      control_file_path: null,
      execution_log_path: null,
    },
    idempotency: {
      notify_idempotency_key: null,
      merge_idempotency_key: null,
      apply_idempotency_key: null,
    },
    trigger_source: null,
    requested_by: null,
    operator_checklist: [],
    merge_readiness: null,
    amortization_readiness: null,
    ...overrides,
  };
}

function job(overrides: Partial<UiJobView>): UiJobView {
  return {
    job_id: "j1",
    type: "finalize",
    status: "completed",
    store: "job_manager",
    process_key: "pk",
    bank_code: "banco_bancolombia",
    environment: "sandbox",
    created_at: null,
    started_at: null,
    finished_at: null,
    result_summary: null,
    error: null,
    user_message: "Se finalizó la revisión correctamente.",
    next_action: null,
    raw_available: true,
    ...overrides,
  };
}

function summary(overrides: Partial<UiProcessSummary>): UiProcessSummary {
  return {
    process_key: "pk",
    bank_code: "banco_bancolombia",
    process_date: "2026-08-01",
    environment: "sandbox",
    operational_status: "EN_REVISION",
    control_estado_proceso: "REVISION_CREADA",
    is_active: true,
    error_count: 0,
    next_actions: [],
    ...overrides,
  };
}

describe("projectionReflectsTerminalJob", () => {
  it("Finalize: SINCRONIZANDO / sync_pending no está sincronizado", () => {
    const stale = detail({
      operational_status: "SINCRONIZANDO",
      control_estado_proceso: "REVISION_CREADA",
      steps: [
        step("generate", "completed"),
        step("review", "in_progress"),
        step("finalize", "sync_pending"),
        step("notify", "not_started"),
        step("merge", "not_started"),
        step("dry_run", "not_started"),
        step("apply", "not_started"),
      ],
    });
    expect(projectionReflectsTerminalJob(stale, job({ type: "finalize", status: "completed" }))).toBe(
      false,
    );
  });

  it("Finalize: evidencia en Control sí sincroniza", () => {
    const fresh = detail({
      operational_status: "PENDIENTE_NOTIFICACION",
      control_estado_proceso: "FINALIZADO",
      steps: [
        step("generate", "completed"),
        step("review", "completed"),
        step("finalize", "completed"),
        step("notify", "not_started"),
        step("merge", "not_started"),
        step("dry_run", "not_started"),
        step("apply", "not_started"),
      ],
      files: {
        ...detail({}).files,
        historical_file_path: "hist.xlsx",
      },
    });
    expect(projectionReflectsTerminalJob(fresh, job({ type: "finalize", status: "completed" }))).toBe(
      true,
    );
  });

  it("Merge: PENDIENTE_ASIENTOS no confirma sincronización tras Merge completed", () => {
    const stale = detail({
      operational_status: "ESPERANDO_SOPORTES",
      control_estado_proceso: "PENDIENTE_ASIENTOS",
      steps: [
        step("generate", "completed"),
        step("review", "completed"),
        step("finalize", "completed"),
        step("notify", "completed"),
        step("merge", "blocked"),
        step("dry_run", "not_started"),
        step("apply", "not_started"),
      ],
    });
    expect(
      projectionReflectsTerminalJob(stale, job({ type: "merge_composite_validado_pdfs", status: "completed" })),
    ).toBe(false);
  });

  it("Merge: CONSOLIDADO sí sincroniza", () => {
    const fresh = detail({
      operational_status: "LISTO_PARA_APLICAR",
      control_estado_proceso: "CONSOLIDADO",
      steps: [
        step("generate", "completed"),
        step("review", "completed"),
        step("finalize", "completed"),
        step("notify", "completed"),
        step("merge", "completed"),
        step("dry_run", "not_started"),
        step("apply", "not_started"),
      ],
    });
    expect(
      projectionReflectsTerminalJob(fresh, job({ type: "merge_composite_validado_pdfs", status: "completed" })),
    ).toBe(true);
  });

  it("Notify: sync_pending no sincroniza; ESPERANDO_SOPORTES sí", () => {
    const pending = detail({
      operational_status: "SINCRONIZANDO",
      steps: [
        step("generate", "completed"),
        step("review", "completed"),
        step("finalize", "completed"),
        step("notify", "sync_pending"),
        step("merge", "not_started"),
        step("dry_run", "not_started"),
        step("apply", "not_started"),
      ],
    });
    expect(projectionReflectsTerminalJob(pending, job({ type: "notify", status: "completed" }))).toBe(
      false,
    );

    const ok = detail({
      operational_status: "ESPERANDO_SOPORTES",
      control_estado_proceso: "PENDIENTE_ASIENTOS",
      steps: [
        step("generate", "completed"),
        step("review", "completed"),
        step("finalize", "completed"),
        step("notify", "completed"),
        step("merge", "blocked"),
        step("dry_run", "not_started"),
        step("apply", "not_started"),
      ],
      files: { ...detail({}).files, email_pdf_path: "mail.pdf" },
    });
    expect(projectionReflectsTerminalJob(ok, job({ type: "notify", status: "completed" }))).toBe(true);
  });

  it("Apply: sync_pending no sincroniza; COMPLETADO sí", () => {
    const pending = detail({
      operational_status: "SINCRONIZANDO",
      steps: [
        step("generate", "completed"),
        step("review", "completed"),
        step("finalize", "completed"),
        step("notify", "completed"),
        step("merge", "completed"),
        step("dry_run", "completed"),
        step("apply", "sync_pending"),
      ],
    });
    expect(
      projectionReflectsTerminalJob(pending, job({ type: "amortization_process", status: "completed" })),
    ).toBe(false);

    const ok = detail({
      operational_status: "COMPLETADO",
      control_estado_proceso: "AMORTIZACION_APLICADA",
      steps: [
        step("generate", "completed"),
        step("review", "completed"),
        step("finalize", "completed"),
        step("notify", "completed"),
        step("merge", "completed"),
        step("dry_run", "completed"),
        step("apply", "completed"),
      ],
    });
    expect(
      projectionReflectsTerminalJob(ok, job({ type: "amortization_process", status: "completed" })),
    ).toBe(true);
  });

  it("Apply: outcome=applied cierra sync aunque Control esté SINCRONIZANDO", () => {
    const pending = detail({
      operational_status: "SINCRONIZANDO",
      control_estado_proceso: "CONSOLIDADO",
      steps: [
        step("generate", "completed"),
        step("review", "completed"),
        step("finalize", "completed"),
        step("notify", "completed"),
        step("merge", "completed"),
        step("dry_run", "completed"),
        step("apply", "sync_pending"),
      ],
    });
    expect(
      projectionReflectsTerminalJob(
        pending,
        job({
          type: "amortization_process",
          status: "completed",
          result_summary: { outcome: "applied" },
        }),
      ),
    ).toBe(true);
  });

  it("Apply: requires_correction no exige AMORTIZACION_APLICADA", () => {
    const pending = detail({
      operational_status: "SINCRONIZANDO",
      steps: [
        step("generate", "completed"),
        step("review", "completed"),
        step("finalize", "completed"),
        step("notify", "completed"),
        step("merge", "completed"),
        step("dry_run", "completed"),
        step("apply", "sync_pending"),
      ],
    });
    expect(
      projectionReflectsTerminalJob(
        pending,
        job({
          type: "amortization_process",
          status: "completed",
          result_summary: { outcome: "requires_correction" },
        }),
      ),
    ).toBe(true);
  });

  it("delaysForTerminalJob alarga ventana solo para amortización", () => {
    expect(delaysForTerminalJob(job({ type: "finalize" }))).toEqual(POST_JOB_RELOAD_DELAYS_MS);
    expect(delaysForTerminalJob(job({ type: "amortization_process" }))).toEqual(
      POST_JOB_RELOAD_DELAYS_AMORTIZATION_MS,
    );
  });

  it("Generate: sync_pending no sincroniza; EN_REVISION sí", () => {
    const pending = detail({
      operational_status: "SINCRONIZANDO",
      steps: [
        step("generate", "sync_pending"),
        step("review", "not_started"),
        step("finalize", "not_started"),
        step("notify", "not_started"),
        step("merge", "not_started"),
        step("dry_run", "not_started"),
        step("apply", "not_started"),
      ],
      files: { ...detail({}).files, validation_file_path: null },
    });
    expect(projectionReflectsTerminalJob(pending, job({ type: "generate", status: "completed" }))).toBe(
      false,
    );

    const ok = detail({ operational_status: "EN_REVISION" });
    expect(projectionReflectsTerminalJob(ok, job({ type: "generate", status: "completed" }))).toBe(true);
  });

  it("acepta jobs fallidos sin reintentar sincronización", () => {
    expect(
      projectionReflectsTerminalJob(detail({}), job({ type: "finalize", status: "failed" })),
    ).toBe(true);
  });
});

describe("processListReflectsGenerateJob", () => {
  it("no sincroniza si la lista aún muestra SINCRONIZANDO", () => {
    expect(
      processListReflectsGenerateJob(
        [summary({ operational_status: "SINCRONIZANDO" })],
        job({ type: "generate", status: "completed" }),
      ),
    ).toBe(false);
  });

  it("sincroniza con EN_REVISION", () => {
    expect(
      processListReflectsGenerateJob(
        [summary({ operational_status: "EN_REVISION" })],
        job({ type: "generate", status: "completed" }),
      ),
    ).toBe(true);
  });
});

describe("reloadUntilProjectionMatchesJob", () => {
  it("reintenta hasta reflejar el job y reporta synced", async () => {
    const loads = [
      detail({ operational_status: "SINCRONIZANDO", steps: [
        step("generate", "completed"),
        step("review", "in_progress"),
        step("finalize", "sync_pending"),
        step("notify", "not_started"),
        step("merge", "not_started"),
        step("dry_run", "not_started"),
        step("apply", "not_started"),
      ]}),
      detail({
        operational_status: "PENDIENTE_NOTIFICACION",
        control_estado_proceso: "FINALIZADO",
        steps: [
          step("generate", "completed"),
          step("review", "completed"),
          step("finalize", "completed"),
          step("notify", "not_started"),
          step("merge", "not_started"),
          step("dry_run", "not_started"),
          step("apply", "not_started"),
        ],
      }),
    ];
    let i = 0;
    const sleep = vi.fn(async () => undefined);
    const result = await reloadUntilProjectionMatchesJob(
      async () => loads[Math.min(i++, loads.length - 1)]!,
      job({ type: "finalize", status: "completed" }),
      projectionReflectsTerminalJob,
      POST_JOB_RELOAD_DELAYS_MS,
      sleep,
    );
    expect(result.synced).toBe(true);
    expect(result.data.operational_status).toBe("PENDIENTE_NOTIFICACION");
    expect(sleep).toHaveBeenCalled();
  });

  it("agota reintentos sin marcar synced", async () => {
    const sleep = vi.fn(async () => undefined);
    const stale = detail({
      operational_status: "SINCRONIZANDO",
      steps: [
        step("generate", "completed"),
        step("review", "in_progress"),
        step("finalize", "sync_pending"),
        step("notify", "not_started"),
        step("merge", "not_started"),
        step("dry_run", "not_started"),
        step("apply", "not_started"),
      ],
    });
    const result = await reloadUntilProjectionMatchesJob(
      async () => stale,
      job({ type: "finalize", status: "completed" }),
      projectionReflectsTerminalJob,
      [0, 1, 1],
      sleep,
    );
    expect(result.synced).toBe(false);
  });
});
