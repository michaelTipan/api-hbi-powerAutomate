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

describe("DashboardPage — continuidad R3.3", () => {
  beforeEach(() => {
    mocks.useCsrfReady.mockReturnValue({ csrfReady: true, csrfPreparing: false });
  });

  it("muestra proceso activo y Retomar proceso en vez de Iniciar validación", async () => {
    const pk =
      "payment-validation|banco_bancolombia|2026-07-31|c217f87c-38cf-4853-a7e4-27304f2dca22";
    mocks.fetchBanks.mockResolvedValue([
      {
        bank_code: "banco_bogota",
        bank_name: "Banco Bogotá",
        available_actions: { generate: { allowed: true, reason: null } },
        dashboard_primary_action: "generate",
        control_readable: true,
        active_process_key: null,
      },
      {
        bank_code: "banco_bancolombia",
        bank_name: "Bancolombia",
        available_actions: {
          generate: {
            allowed: false,
            reason: "Ya existe una validación activa para este banco.",
          },
        },
        dashboard_primary_action: "resume",
        control_readable: true,
        active_process_key: pk,
        active_operational_status: "ESPERANDO_SOPORTES",
        active_control_estado: "PENDIENTE_ASIENTOS",
      },
    ]);
    mocks.fetchProcesses.mockResolvedValue({
      environment: "sandbox",
      items: [
        {
          process_key: pk,
          bank_code: "banco_bancolombia",
          process_date: "2026-07-31",
          environment: "sandbox",
          operational_status: "ESPERANDO_SOPORTES",
          operational_title: "Esperando documentos contables",
          operational_message:
            "La validación y el correo ya fueron completados. Revise los documentos contables cargados antes de generar el PDF consolidado.",
          control_estado_proceso: "PENDIENTE_ASIENTOS",
          is_active: true,
          error_count: 0,
          next_actions: [],
        },
      ],
      unavailable_banks: [],
    });

    render(
      <MemoryRouter>
        <DashboardPage />
      </MemoryRouter>,
    );

    expect(await screen.findAllByText(/Esperando documentos contables/)).not.toHaveLength(0);
    expect(await screen.findAllByText(/Retomar proceso/)).not.toHaveLength(0);
    expect(screen.queryByRole("button", { name: "Iniciar validación" })).toBeInTheDocument(); // Bogotá libre
    const resumeLinks = screen.getAllByRole("link", { name: /Retomar proceso/i });
    expect(resumeLinks.length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/Esperando documentos \(1\)/)).toBeInTheDocument();
  });

  it("no presenta un fallo de lectura como cero procesos: ofrece Volver a intentar", async () => {
    mocks.fetchBanks.mockResolvedValue([
      {
        bank_code: "banco_bancolombia",
        bank_name: "Bancolombia",
        available_actions: {
          generate: {
            allowed: false,
            reason: "No pudimos leer el estado de este banco.",
          },
        },
        dashboard_primary_action: "retry_read",
        control_readable: false,
        active_process_key: null,
      },
    ]);
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

    expect(await screen.findByText(/No pudimos leer el estado de Bancolombia/)).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Volver a intentar" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Iniciar validación" })).not.toBeInTheDocument();
  });

  it("nunca muestra códigos técnicos en el panel de progreso", async () => {
    mocks.fetchBanks.mockResolvedValue([
      {
        bank_code: "banco_bancolombia",
        bank_name: "Bancolombia",
        available_actions: { generate: { allowed: true, reason: null } },
        dashboard_primary_action: "generate",
        control_readable: true,
      },
    ]);
    mocks.fetchProcesses.mockResolvedValue({ environment: "sandbox", items: [], unavailable_banks: [] });
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
        message:
          "active_process_exists|payment-validation|banco_bancolombia|2026-07-31|abc|PENDIENTE_ASIENTOS",
        user_message:
          "Ya existe una validación activa para este banco. Abra el proceso existente para continuar desde el último paso completado.",
        next_action: "Abra el proceso existente.",
      },
    });

    render(
      <MemoryRouter>
        <DashboardPage />
      </MemoryRouter>,
    );
    (await screen.findByRole("button", { name: "Iniciar validación" })).click();
    (await screen.findByRole("button", { name: "Confirmar" })).click();

    expect(await screen.findByText(/Ya existe una validación activa/)).toBeInTheDocument();
    expect(screen.queryByText(/active_process_exists/)).not.toBeInTheDocument();
    expect(screen.queryByText(/PENDIENTE_ASIENTOS/)).not.toBeInTheDocument();
  });
});
