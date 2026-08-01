import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const mocks = vi.hoisted(() => ({
  fetchBanks: vi.fn(),
  fetchProcesses: vi.fn(),
  fetchJob: vi.fn(),
  postGenerate: vi.fn(),
  useCsrfReady: vi.fn(),
}));

vi.mock("../api/client", () => ({
  fetchBanks: mocks.fetchBanks,
  fetchProcesses: mocks.fetchProcesses,
  fetchJob: mocks.fetchJob,
  postGenerate: mocks.postGenerate,
}));

vi.mock("../api/useCsrfReady", () => ({
  useCsrfReady: mocks.useCsrfReady,
}));

import { DashboardPage } from "./DashboardPage";

const TECHNICAL =
  "active_process_exists|payment-validation|banco_bancolombia|2026-07-31|abc-123|PENDIENTE_ASIENTOS";

describe("DashboardPage — errores de job legibles", () => {
  beforeEach(() => {
    vi.useRealTimers();
    mocks.useCsrfReady.mockReturnValue({ csrfReady: true, csrfPreparing: false });
    mocks.fetchBanks.mockResolvedValue([
      {
        bank_code: "banco_bancolombia",
        bank_name: "Bancolombia",
        available_actions: { generate: { allowed: true, reason: null } },
      },
    ]);
    mocks.fetchProcesses.mockResolvedValue({ environment: "sandbox", items: [] });
  });

  it("muestra el mensaje al operador y la siguiente acción, no el código técnico", async () => {
    mocks.postGenerate.mockResolvedValue({
      accepted: true,
      action: "generate",
      bank_code: "banco_bancolombia",
      job_id: "job-1",
      status: "queued",
      poll_url: "/api/ui/v1/jobs/job-1",
    });
    mocks.fetchJob.mockResolvedValue({
      job_id: "job-1",
      type: "generate",
      status: "failed",
      store: "job_manager",
      environment: "sandbox",
      user_message: null,
      next_action: null,
      result_summary: null,
      raw_available: true,
      error: {
        error_code: "active_process_exists",
        message: TECHNICAL,
        user_message:
          "Ya existe un proceso activo en el control del banco y no se puede iniciar otro Generate.",
        next_action: "Termine o cancele ese proceso y vuelva a generar la revisión.",
      },
    });

    render(
      <MemoryRouter>
        <DashboardPage />
      </MemoryRouter>,
    );
    const btn = await screen.findByRole("button", { name: "Iniciar validación" });
    btn.click();
    const confirm = await screen.findByRole("button", { name: "Confirmar" });
    confirm.click();

    expect(
      await screen.findByText(/Ya existe un proceso activo en el control del banco/),
    ).toBeInTheDocument();
    expect(
      await screen.findByText(/Termine o cancele ese proceso/),
    ).toBeInTheDocument();
    expect(screen.queryByText(TECHNICAL)).not.toBeInTheDocument();
  });

  it("avisa cuando el backend no pudo leer el control de un banco", async () => {
    mocks.fetchProcesses.mockResolvedValue({
      environment: "sandbox",
      items: [],
      unavailable_banks: ["banco_bancolombia"],
    });

    render(
      <MemoryRouter>
        <DashboardPage />
      </MemoryRouter>,
    );

    expect(
      await screen.findByText(/No pudimos leer el estado de Bancolombia/),
    ).toBeInTheDocument();
  });
});
