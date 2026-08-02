import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";

const mocks = vi.hoisted(() => ({
  fetchBanks: vi.fn(),
  fetchProcesses: vi.fn(),
  fetchJob: vi.fn(),
  postGenerate: vi.fn(),
}));

vi.mock("../api/client", () => ({
  fetchBanks: mocks.fetchBanks,
  fetchProcesses: mocks.fetchProcesses,
  fetchJob: mocks.fetchJob,
  postGenerate: mocks.postGenerate,
}));

import { DashboardPage } from "./DashboardPage";

describe("DashboardPage — lenguaje operativo", () => {
  it("no expone jerga técnica (Generate/Finalize/JobManager/ProcessKey) en el copy visible", async () => {
    mocks.fetchBanks.mockResolvedValue([
      {
        bank_code: "banco_bogota",
        bank_name: "Banco Bogotá",
        available_actions: { generate: { allowed: true, reason: null } },
      },
    ]);
    mocks.fetchProcesses.mockResolvedValue({
      environment: "sandbox",
      items: [
        {
          process_key: "payment-validation|banco_bogota|2026-07-31|abc",
          bank_code: "banco_bogota",
          process_date: "2026-07-31",
          environment: "sandbox",
          operational_status: "EN_REVISION",
          control_estado_proceso: "REVISION_CREADA",
          is_active: true,
          error_count: 0,
          next_actions: [],
        },
      ],
    });

    render(
      <MemoryRouter>
        <DashboardPage />
      </MemoryRouter>,
    );

    await screen.findByText("Banco Bogotá");
    const text = document.body.textContent || "";
    expect(text).not.toMatch(/\bGenerate\b/);
    expect(text).not.toMatch(/\bFinalize\b/);
    expect(text).not.toMatch(/JobManager/);
    expect(text).not.toMatch(/ProcessKey/i);
    expect(screen.getByRole("button", { name: "Iniciar validación" })).toBeInTheDocument();
  });

  it('usa el copy operativo "Inicie la validación..." en vez de jerga de Generate/JobManager', async () => {
    mocks.fetchBanks.mockResolvedValue([]);
    mocks.fetchProcesses.mockResolvedValue({ environment: "sandbox", items: [] });
    render(
      <MemoryRouter>
        <DashboardPage />
      </MemoryRouter>,
    );
    expect(
      await screen.findByText(/Inicie la validación del archivo bancario/),
    ).toBeInTheDocument();
  });

  it("muestra el mensaje vacío cuando no hay procesos activos en Control", async () => {
    mocks.fetchBanks.mockResolvedValue([]);
    mocks.fetchProcesses.mockResolvedValue({ environment: "sandbox", items: [] });
    render(
      <MemoryRouter>
        <DashboardPage />
      </MemoryRouter>,
    );
    expect(
      await screen.findByText(/No hay procesos activos en el Control/),
    ).toBeInTheDocument();
    expect(screen.queryByRole("tablist", { name: /Filtrar procesos/i })).not.toBeInTheDocument();
  });

  it("no muestra el process_key en las tarjetas del dashboard", async () => {
    mocks.fetchBanks.mockResolvedValue([]);
    const processKey = "payment-validation|banco_bogota|2026-07-31|abc-visible-key";
    mocks.fetchProcesses.mockResolvedValue({
      environment: "sandbox",
      items: [
        {
          process_key: processKey,
          bank_code: "banco_bogota",
          process_date: "2026-07-31",
          environment: "sandbox",
          operational_status: "EN_REVISION",
          control_estado_proceso: "REVISION_CREADA",
          is_active: true,
          error_count: 0,
          next_actions: [],
        },
      ],
    });
    render(
      <MemoryRouter>
        <DashboardPage />
      </MemoryRouter>,
    );
    await screen.findByText("Revisión pendiente");
    expect(screen.queryByText(processKey)).not.toBeInTheDocument();
  });
});
