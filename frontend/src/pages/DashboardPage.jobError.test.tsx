import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";

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
    vi.clearAllMocks();
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

    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <DashboardPage />
      </MemoryRouter>,
    );
    await user.selectOptions(await screen.findByLabelText("Banco"), "banco_bancolombia");
    await user.click(screen.getByRole("button", { name: "Iniciar validación" }));
    await user.click(await screen.findByRole("button", { name: "Confirmar" }));

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

  it("ante un 502 al consultar el avance, no marca fallo y sigue reconectando", async () => {
    mocks.postGenerate.mockResolvedValue({
      accepted: true,
      action: "generate",
      bank_code: "banco_bancolombia",
      job_id: "job-502",
      status: "queued",
      poll_url: "/api/ui/v1/jobs/job-502",
    });
    mocks.fetchJob.mockRejectedValue(new Error("Error HTTP 502"));

    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <DashboardPage />
      </MemoryRouter>,
    );
    await user.selectOptions(await screen.findByLabelText("Banco"), "banco_bancolombia");
    await user.click(screen.getByRole("button", { name: "Iniciar validación" }));
    await user.click(await screen.findByRole("button", { name: "Confirmar" }));

    expect(
      await screen.findByText(/Reintentando conexión con el servidor/i),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Error HTTP 502/i)).not.toBeInTheDocument();
    // No pintar «Con problemas» por un corte de poll: el job puede seguir OK.
    expect(screen.queryByText(/Con problemas/i)).not.toBeInTheDocument();
  });

  it(
    "tras un 502 transitorio, recupera el job completado sin pedir reinicio",
    async () => {
      mocks.postGenerate.mockResolvedValue({
        accepted: true,
        action: "generate",
        bank_code: "banco_bancolombia",
        job_id: "job-recover",
        status: "queued",
        poll_url: "/api/ui/v1/jobs/job-recover",
      });
      mocks.fetchJob
        .mockRejectedValueOnce(new Error("Error HTTP 502"))
        .mockResolvedValue({
          job_id: "job-recover",
          type: "generate",
          status: "completed",
          store: "job_manager",
          process_key: "payment-validation|banco_bancolombia|2026-08-01|abc",
          bank_code: "banco_bancolombia",
          environment: "sandbox",
          user_message: "Validación generada correctamente.",
          next_action: null,
          result_summary: null,
          raw_available: true,
          error: null,
        });
      // Tras completed, el sync de proyección debe ver EN_REVISION (solo GET).
      mocks.fetchProcesses.mockResolvedValue({
        environment: "sandbox",
        items: [
          {
            process_key: "payment-validation|banco_bancolombia|2026-08-01|abc",
            bank_code: "banco_bancolombia",
            process_date: "2026-08-01",
            environment: "sandbox",
            operational_status: "EN_REVISION",
            control_estado_proceso: "REVISION_CREADA",
            is_active: true,
            error_count: 0,
            next_actions: [],
          },
        ],
      });

      const user = userEvent.setup();
      render(
        <MemoryRouter initialEntries={["/"]}>
          <Routes>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/processes/:processKey" element={<div>Detalle del proceso</div>} />
          </Routes>
        </MemoryRouter>,
      );
      await user.selectOptions(await screen.findByLabelText("Banco"), "banco_bancolombia");
      await user.click(screen.getByRole("button", { name: "Iniciar validación" }));
      await user.click(await screen.findByRole("button", { name: "Confirmar" }));

      expect(
        await screen.findByText(/Reintentando conexión con el servidor/i),
      ).toBeInTheDocument();

      // Tras recuperar el job completado, el Panel navega al detalle (phase=review).
      expect(await screen.findByText("Detalle del proceso", undefined, { timeout: 5000 })).toBeInTheDocument();
      expect(screen.queryByText(/Con problemas/i)).not.toBeInTheDocument();
      expect(mocks.postGenerate).toHaveBeenCalledTimes(1);
    },
    10000,
  );
});
