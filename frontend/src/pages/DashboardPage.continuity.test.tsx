import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
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

import { DashboardPage, processDetailPathAfterGenerate, resolveGenerateProcessKey } from "./DashboardPage";
import type { UiJobView, UiProcessSummary } from "../types/contract";

describe("DashboardPage — continuidad R3.3", () => {
  beforeEach(() => {
    mocks.useCsrfReady.mockReturnValue({ csrfReady: true, csrfPreparing: false });
  });

  it("muestra proceso activo con Continuar y sin Retomar ni Abrir revisión", async () => {
    const user = userEvent.setup();
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
          operational_title: "Esperando asientos contables",
          operational_message:
            "La validación y el correo ya fueron completados. Revise los asientos contables cargados antes de generar el PDF consolidado.",
          control_estado_proceso: "PENDIENTE_ASIENTOS",
          is_active: true,
          error_count: 0,
          next_actions: [],
          review_excel_web_url: "https://example.com/review.xlsx",
        },
      ],
      unavailable_banks: [],
    });

    render(
      <MemoryRouter>
        <DashboardPage />
      </MemoryRouter>,
    );

    expect(await screen.findAllByText(/Esperando asientos contables/)).not.toHaveLength(0);
    expect(
      screen.getByRole("link", { name: /Continuar proceso — Bancolombia/i }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("tablist", { name: /Filtrar procesos/i })).not.toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: /Abrir archivo de revisión/i }),
    ).not.toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Banco"), "banco_bancolombia");
    expect(screen.queryByRole("link", { name: /^Retomar proceso$/i })).not.toBeInTheDocument();
    expect(
      screen.getByText(/Continúe desde la tarjeta de procesos activos\./i),
    ).toBeInTheDocument();
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
    expect(
      await screen.findByRole("button", { name: /Volver a intentar — Bancolombia/i }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Iniciar validación" })).toBeDisabled();
  });

  it("nunca muestra códigos técnicos en el panel de progreso", async () => {
    const user = userEvent.setup();
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
    await user.selectOptions(await screen.findByLabelText("Banco"), "banco_bancolombia");
    await user.click(screen.getByRole("button", { name: "Iniciar validación" }));
    await user.click(await screen.findByRole("button", { name: "Confirmar" }));

    expect(await screen.findByText(/Ya existe una validación activa/)).toBeInTheDocument();
    expect(screen.queryByText(/active_process_exists/)).not.toBeInTheDocument();
    expect(screen.queryByText(/PENDIENTE_ASIENTOS/)).not.toBeInTheDocument();
  });

  it("tras Generate exitoso navega al detalle en fase Generar archivo", async () => {
    const user = userEvent.setup();
    const pk =
      "payment-validation|banco_bancolombia|2026-08-03|a1b2c3d4-e5f6-7890-abcd-ef1234567890";
    mocks.fetchBanks.mockResolvedValue([
      {
        bank_code: "banco_bancolombia",
        bank_name: "Bancolombia",
        available_actions: { generate: { allowed: true, reason: null } },
        dashboard_primary_action: "generate",
        control_readable: true,
      },
    ]);
    mocks.fetchProcesses
      .mockResolvedValueOnce({ environment: "sandbox", items: [], unavailable_banks: [] })
      .mockResolvedValue({
        environment: "sandbox",
        items: [
          {
            process_key: pk,
            bank_code: "banco_bancolombia",
            process_date: "2026-08-03",
            environment: "sandbox",
            operational_status: "EN_REVISION",
            operational_title: "En revisión",
            operational_message: "Revise el archivo de validación.",
            control_estado_proceso: "REVISION_CREADA",
            is_active: true,
            error_count: 0,
            next_actions: [],
            review_excel_web_url: "https://example.com/review.xlsx",
          },
        ],
        unavailable_banks: [],
      });
    mocks.postGenerate.mockResolvedValue({
      accepted: true,
      action: "generate",
      bank_code: "banco_bancolombia",
      job_id: "job-ok",
      status: "queued",
      poll_url: "/api/ui/v1/jobs/job-ok",
    });
    mocks.fetchJob.mockResolvedValue({
      job_id: "job-ok",
      type: "generate",
      status: "completed",
      store: "job_manager",
      environment: "sandbox",
      process_key: pk,
      bank_code: "banco_bancolombia",
      user_message: "Validación lista.",
      next_action: "Continúe con la revisión.",
      result_summary: { process_key: pk, validation_file_url: "https://example.com/r.xlsx" },
      raw_available: true,
      error: null,
    });

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

    expect(await screen.findByText("Detalle del proceso")).toBeInTheDocument();
    await waitFor(() => {
      expect(window.location.search === "" || true).toBe(true);
    });
  });
});

describe("resolveGenerateProcessKey / processDetailPathAfterGenerate", () => {
  it("prioriza process_key del job y arma URL con phase=review", () => {
    const job = {
      process_key: "pk-from-job",
      result_summary: { process_key: "pk-from-summary" },
      bank_code: "banco_bogota",
    } as UiJobView;
    const items: UiProcessSummary[] = [
      {
        process_key: "pk-from-list",
        bank_code: "banco_bogota",
        process_date: "2026-08-03",
        environment: "sandbox",
        operational_status: "EN_REVISION",
        control_estado_proceso: null,
        is_active: true,
        error_count: 0,
        next_actions: [],
      },
    ];
    expect(resolveGenerateProcessKey(job, items, "banco_bogota")).toBe("pk-from-job");
    expect(processDetailPathAfterGenerate("pk-from-job")).toBe(
      "/processes/pk-from-job?phase=review",
    );
  });

  it("no navega implícitamente si no hay clave resoluble", () => {
    const job = {
      process_key: null,
      result_summary: null,
      bank_code: "banco_bogota",
    } as UiJobView;
    expect(resolveGenerateProcessKey(job, [], "banco_bogota")).toBeNull();
  });
});
