import { describe, expect, it } from "vitest";
import { resolveLocalJobWhenActiveAbsent } from "./reconcileLocalJob";
import type { UiJobView } from "../types/contract";

function job(partial: Partial<UiJobView> & Pick<UiJobView, "status">): UiJobView {
  return {
    job_id: partial.job_id ?? "job-1",
    type: partial.type ?? "generate",
    status: partial.status,
    store: partial.store ?? "job_manager",
    process_key: partial.process_key ?? null,
    bank_code: partial.bank_code ?? "banco_bancolombia",
    environment: partial.environment ?? "sandbox",
    created_at: partial.created_at ?? null,
    started_at: partial.started_at ?? null,
    finished_at: partial.finished_at ?? null,
    result_summary: partial.result_summary ?? null,
    error: partial.error ?? null,
    user_message: partial.user_message ?? null,
    next_action: partial.next_action ?? null,
    progress: partial.progress ?? null,
    raw_available: partial.raw_available ?? false,
  };
}

describe("resolveLocalJobWhenActiveAbsent", () => {
  it("conserva jobs terminales sin pedir refresh (U4-B)", () => {
    const prev = job({ status: "failed" });
    expect(resolveLocalJobWhenActiveAbsent(prev)).toEqual({
      keep: prev,
      refreshJobId: null,
    });
  });

  it("pide refresh cuando el local sigue running (evita Regenerando eterno)", () => {
    const prev = job({
      job_id: "job-gen-1",
      status: "running",
      progress: { bank_rows_done: 11, bank_rows_total: 11 },
    });
    expect(resolveLocalJobWhenActiveAbsent(prev)).toEqual({
      keep: prev,
      refreshJobId: "job-gen-1",
    });
  });

  it("limpia si no hay job local", () => {
    expect(resolveLocalJobWhenActiveAbsent(null)).toEqual({
      keep: null,
      refreshJobId: null,
    });
  });

  it("limpia si el status no es activo ni terminal reconocible", () => {
    expect(resolveLocalJobWhenActiveAbsent(job({ status: "unknown" }))).toEqual({
      keep: null,
      refreshJobId: null,
    });
  });
});
