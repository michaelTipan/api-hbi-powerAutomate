import { describe, expect, it } from "vitest";
import { FALLBACK_OPERATOR_MESSAGE } from "../copy/labels";
import { jobNextAction, jobUserMessage, looksTechnical } from "./jobMessages";
import type { UiJobView } from "../types/contract";

function makeJob(overrides: Partial<UiJobView> = {}): UiJobView {
  return {
    job_id: "job-1",
    type: "generate",
    status: "failed",
    store: "job_manager",
    process_key: null,
    bank_code: "banco_bancolombia",
    environment: "sandbox",
    created_at: null,
    started_at: null,
    finished_at: null,
    result_summary: null,
    error: null,
    user_message: null,
    next_action: null,
    raw_available: true,
    ...overrides,
  };
}

describe("jobUserMessage / jobNextAction", () => {
  it("prefiere el mensaje de nivel superior cuando existe", () => {
    const job = makeJob({
      status: "completed",
      user_message: "Se generó el archivo de revisión.",
      next_action: "Abra el Excel y complete la distribución.",
      error: { message: "no debería usarse" },
    });
    expect(jobUserMessage(job)).toBe("Se generó el archivo de revisión.");
    expect(jobNextAction(job)).toBe("Abra el Excel y complete la distribución.");
  });

  it("usa error.user_message en jobs fallidos en vez del código técnico", () => {
    const job = makeJob({
      error: {
        error_code: "active_process_exists",
        message:
          "active_process_exists|payment-validation|banco_bancolombia|2026-07-31|abc|PENDIENTE_ASIENTOS",
        user_message:
          "Ya existe un proceso activo en el control del banco y no se puede iniciar otro Generate.",
        next_action: "Termine o cancele ese proceso y vuelva a generar la revisión.",
      },
    });
    expect(jobUserMessage(job)).toBe(
      "Ya existe un proceso activo en el control del banco y no se puede iniciar otro Generate.",
    );
    expect(jobNextAction(job)).toBe(
      "Termine o cancele ese proceso y vuelva a generar la revisión.",
    );
  });

  it("nunca muestra el código técnico al operador", () => {
    const job = makeJob({
      error: {
        message:
          "active_process_exists|payment-validation|banco_bancolombia|2026-07-31|abc|PENDIENTE_ASIENTOS",
      },
    });
    expect(jobUserMessage(job)).toBe(FALLBACK_OPERATOR_MESSAGE);
    expect(jobUserMessage(job)).not.toContain("|");
    expect(jobUserMessage(job)).not.toContain("active_process_exists");
  });

  it("detecta cadenas técnicas", () => {
    expect(looksTechnical("active_process_exists|x|y")).toBe(true);
    expect(looksTechnical("process_read_failed")).toBe(true);
    expect(looksTechnical("Ya existe una validación activa.")).toBe(false);
  });

  it("devuelve null en jobs no fallidos sin mensaje", () => {
    expect(jobUserMessage(makeJob({ status: "running" }))).toBeNull();
    expect(jobNextAction(makeJob())).toBeNull();
  });
});
