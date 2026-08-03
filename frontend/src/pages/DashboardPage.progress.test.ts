import { describe, expect, it } from "vitest";
import type { UiJobView } from "../types/contract";
import { progressFromJob } from "./DashboardPage";

function jobWithProgress(progress: Record<string, unknown> | null): UiJobView {
  return {
    job_id: "j1",
    type: "generate",
    status: "running",
    store: "job_manager",
    process_key: null,
    bank_code: "banco_bogota",
    environment: "sandbox",
    created_at: null,
    started_at: null,
    finished_at: null,
    result_summary: null,
    error: null,
    progress,
    raw_available: false,
  };
}

describe("progressFromJob (Dashboard Seguimiento)", () => {
  it("oculta «0 de N» sin avance real (cualquier total)", () => {
    expect(progressFromJob(jobWithProgress({ bank_rows_done: 0, bank_rows_total: 2 }))).toBeNull();
    expect(progressFromJob(jobWithProgress({ bank_rows_done: 0, bank_rows_total: 50 }))).toBeNull();
    expect(progressFromJob(jobWithProgress({ bank_rows_done: 0, bank_rows_total: 1 }))).toBeNull();
  });

  it("mantiene la barra cuando hay avance real", () => {
    expect(progressFromJob(jobWithProgress({ bank_rows_done: 1, bank_rows_total: 2 }))).toEqual({
      current: 1,
      total: 2,
    });
    expect(progressFromJob(jobWithProgress({ bank_rows_done: 12, bank_rows_total: 40 }))).toEqual({
      current: 12,
      total: 40,
    });
  });

  it("sin progress o sin campos de filas → null", () => {
    expect(progressFromJob(jobWithProgress(null))).toBeNull();
    expect(progressFromJob(jobWithProgress({ phase: "bank_rows" }))).toBeNull();
  });
});
