/**
 * U4-RC: axe de página completa.
 *
 * Regla color-contrast deshabilitada en jsdom: axe-core no tiene motor de
 * layout/CSS computado fiable aquí; el contraste se valida en responsive live
 * del sandbox (bloqueante 5). Resto de reglas: cero críticas/serias.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { axe } from "vitest-axe";
import type { UiBootstrapResponse, UiProcessDetail } from "../types/contract";
import { AppShell } from "../components/AppShell";
import { LoginPage } from "./LoginPage";
import { DashboardPage } from "./DashboardPage";
import { ProcessDetailPage } from "./ProcessDetailPage";

const axeOpts = {
  rules: {
    "color-contrast": { enabled: false },
  },
};

async function expectNoSeriousOrCritical(container: HTMLElement) {
  const results = await axe(container, axeOpts);
  const bad = results.violations.filter(
    (v) => v.impact === "critical" || v.impact === "serious",
  );
  expect(bad, JSON.stringify(bad, null, 2)).toEqual([]);
  expect(results.violations, JSON.stringify(results.violations, null, 2)).toEqual([]);
}

const apiMocks = vi.hoisted(() => ({
  fetchBanks: vi.fn(),
  fetchProcesses: vi.fn(),
  fetchJob: vi.fn(),
  postGenerate: vi.fn(),
  fetchProcess: vi.fn(),
  fetchBootstrap: vi.fn(),
  postFinalize: vi.fn(),
  postNotify: vi.fn(),
  postMerge: vi.fn(),
  postAmortization: vi.fn(),
  loginLocal: vi.fn(),
  fetchNotifyRecipientsPreview: vi.fn(),
  fetchIbrPreview: vi.fn(),
}));

vi.mock("../api/client", () => ({
  fetchBanks: apiMocks.fetchBanks,
  fetchProcesses: apiMocks.fetchProcesses,
  fetchJob: apiMocks.fetchJob,
  postGenerate: apiMocks.postGenerate,
  fetchProcess: apiMocks.fetchProcess,
  fetchBootstrap: apiMocks.fetchBootstrap,
  fetchNotifyRecipientsPreview: apiMocks.fetchNotifyRecipientsPreview,
  fetchIbrPreview: apiMocks.fetchIbrPreview,
  postFinalize: apiMocks.postFinalize,
  postNotify: apiMocks.postNotify,
  postMerge: apiMocks.postMerge,
  postAmortization: apiMocks.postAmortization,
  postCancelLote: vi.fn(),
  postSoftClose: vi.fn(),
  loginLocal: apiMocks.loginLocal,
  isMockMode: () => false,
}));

const bootstrap: UiBootstrapResponse = {
  ui_enabled: true,
  writes_allowed: true,
  finalize_allowed: true,
  notify_allowed: true,
  merge_allowed: true,
  amortization_allowed: true,
  notify_test_recipients_configured: true,
  active_environment: "sandbox",
  display_label: "Entorno de validación",
  auth_mode: "local_session",
  login_required: true,
};

function baseDetail(overrides: Partial<UiProcessDetail> = {}): UiProcessDetail {
  return {
    process_key: "payment-validation|banco_bogota|2026-07-31|abc-1",
    process_id: "abc-1",
    bank_code: "banco_bogota",
    bank_name: "Banco de Bogotá",
    process_date: "2026-07-31",
    environment: "sandbox",
    operational_status: "EN_REVISION",
    operational_title: "Revisión pendiente",
    operational_message: "Revise el Excel en SharePoint.",
    control_estado_proceso: "REVISION_CREADA",
    is_active: true,
    steps: [
      {
        name: "generate",
        status: "completed",
        updated_at: null,
        summary: "Excel disponible",
        can_retry: false,
        retry_action: null,
      },
      {
        name: "review",
        status: "in_progress",
        updated_at: null,
        summary: "Pendiente",
        can_retry: false,
        retry_action: null,
      },
      {
        name: "finalize",
        status: "not_started",
        updated_at: null,
        summary: null,
        can_retry: false,
        retry_action: null,
      },
      {
        name: "notify",
        status: "not_started",
        updated_at: null,
        summary: null,
        can_retry: false,
        retry_action: null,
      },
      {
        name: "merge",
        status: "not_started",
        updated_at: null,
        summary: null,
        can_retry: false,
        retry_action: null,
      },
      {
        name: "dry_run",
        status: "not_started",
        updated_at: null,
        summary: null,
        can_retry: false,
        retry_action: null,
      },
      {
        name: "apply",
        status: "not_started",
        updated_at: null,
        summary: null,
        can_retry: false,
        retry_action: null,
      },
    ],
    items: [],
    active_job: null,
    last_attempt: null,
    latest_attempts_by_stage: {},
    attempts: [],
    next_actions: [{ code: "finalize", label: "Finalizar revisión", enabled: true, reason: null }],
    available_actions: {
      finalize: { allowed: true, reason: null },
      notify: { allowed: false, reason: null },
      merge: { allowed: false, reason: null },
      amortization: { allowed: false, reason: null },
    },
    errors: [],
    operational_issues: [],
    links: [
      {
        rel: "review_excel",
        label: "Abrir Excel de revisión",
        path: "revision/x.xlsx",
        web_url: "https://example.com/x.xlsx",
        open_mode: "sharepoint",
      },
    ],
    files: {
      validation_file_path: "revision/x.xlsx",
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
    operator_checklist: ["Guarde el Excel"],
    merge_readiness: null,
    amortization_readiness: null,
    ...overrides,
  };
}

const PROCESS_DETAIL_PATH =
  "/processes/payment-validation%7Cbanco_bogota%7C2026-07-31%7Cabc-1";

describe("a11y página completa (axe)", () => {
  beforeEach(() => {
    apiMocks.fetchNotifyRecipientsPreview.mockResolvedValue({
      ok: true,
      source_path: "CTL/CORREOS.xlsx",
      sheet: "CORREOS",
      emisor: "ops@hbi.test",
      receptores: ["dest@hbi.test"],
      receptores_raw_count: 1,
      file_last_modified: "11 ago 2026, 10:00 a. m.",
      warnings: [],
      user_message: "Se enviará desde ops@hbi.test a dest@hbi.test.",
    });
    apiMocks.fetchIbrPreview.mockResolvedValue({
      ok: true,
      source_path: "CTL/IBR_DIARIO.xlsx",
      process_key: "payment-validation|banco_bogota|2026-07-31|abc-1",
      process_date: "2026-07-31",
      rate: 0.1058,
      rate_pct: 10.58,
      rate_status: "found",
      dates_source: "process_key",
      rates: [],
      ranges: [],
      file_last_modified: "11 ago 2026, 11:00 a. m.",
      warnings: [],
      user_message: "Tasa IBR lista.",
    });
  });

  it("Login", async () => {
    const { container } = render(
      <LoginPage displayLabel="Entorno de validación" onSuccess={vi.fn()} />,
    );
    expect(screen.getByRole("heading", { name: "Acceso operativo" })).toBeInTheDocument();
    await expectNoSeriousOrCritical(container);
  });

  it("Dashboard", async () => {
    apiMocks.fetchBanks.mockResolvedValue([
      {
        bank_code: "banco_bogota",
        bank_name: "Banco Bogotá",
        available_actions: { generate: { allowed: true, reason: null } },
      },
    ]);
    apiMocks.fetchProcesses.mockResolvedValue({
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
    const { container } = render(
      <MemoryRouter>
        <AppShell
          environment={{
            environment: "sandbox",
            display_label: "Entorno de validación",
            ui_enabled: true,
            ui_write_enabled: true,
            ui_auth_mode: "local_session",
          }}
        >
          <DashboardPage />
        </AppShell>
      </MemoryRouter>,
    );
    await screen.findByText("Bogotá");
    await expectNoSeriousOrCritical(container);
  });

  it("Detalle sin errores", async () => {
    apiMocks.fetchBootstrap.mockResolvedValue(bootstrap);
    apiMocks.fetchProcess.mockResolvedValue(baseDetail());
    const { container } = render(
      <MemoryRouter initialEntries={["/processes/payment-validation%7Cbanco_bogota%7C2026-07-31%7Cabc-1"]}>
        <AppShell
          environment={{
            environment: "sandbox",
            display_label: "Entorno de validación",
            ui_enabled: true,
            ui_write_enabled: true,
            ui_auth_mode: "local_session",
          }}
        >
          <Routes>
            <Route path="/processes/:processKey" element={<ProcessDetailPage />} />
          </Routes>
        </AppShell>
      </MemoryRouter>,
    );
    await screen.findByText("Banco de Bogotá");
    await expectNoSeriousOrCritical(container);
  });

  it("Detalle con OperationalIssuePanel", async () => {
    apiMocks.fetchBootstrap.mockResolvedValue(bootstrap);
    apiMocks.fetchProcess.mockResolvedValue(
      baseDetail({
        operational_status: "CORRECCION_REQUERIDA",
        operational_title: "Requiere corrección",
        operational_message: "Hay datos que deben corregirse.",
        operational_issues: [
          {
            issue_id: "i1",
            stage: "finalize",
            category: "correction_required",
            severity: "warning",
            recoverable: true,
            title: "Estado Pago inválido",
            user_message: "Hay un Estado Pago no permitido.",
            location: {
              sheet: "Aplicacion_Pagos",
              row: 8,
              column: "Estado Pago",
              file_name: "x.xlsx",
              credit: null,
              payment_id: null,
              client_name: null,
            },
            value_found: "PAGADO",
            expected_values: ["NORMAL", "ATRASADO"],
            next_action: "Corrija y vuelva a verificar.",
            retry: { action: "finalize", allowed: true, label: "Verificar nuevamente" },
            links: [],
            technical_reference: null,
          },
        ],
      }),
    );
    const { container } = render(
      <MemoryRouter initialEntries={[PROCESS_DETAIL_PATH]}>
        <Routes>
          <Route path="/processes/:processKey" element={<ProcessDetailPage />} />
        </Routes>
      </MemoryRouter>,
    );
    const openIssues = await screen.findByRole("button", {
      name: /Ver problemas operativos/i,
    });
    await userEvent.setup().click(openIssues);
    await screen.findByRole("heading", { name: /Problemas operativos \(1\)/i });
    await expectNoSeriousOrCritical(container);
  });

  it("Modal Generate", async () => {
    const user = userEvent.setup();
    apiMocks.fetchBanks.mockResolvedValue([
      {
        bank_code: "banco_bogota",
        bank_name: "Banco Bogotá",
        available_actions: { generate: { allowed: true, reason: null } },
      },
    ]);
    apiMocks.fetchProcesses.mockResolvedValue({ environment: "sandbox", items: [] });
    const { container } = render(
      <MemoryRouter>
        <DashboardPage />
      </MemoryRouter>,
    );
    await user.selectOptions(await screen.findByLabelText("Banco"), "banco_bogota");
    await user.click(screen.getByRole("button", { name: "Iniciar validación" }));
    await screen.findByRole("dialog");
    await expectNoSeriousOrCritical(container);
  });

  it("Modal Finalize", async () => {
    const user = userEvent.setup();
    apiMocks.fetchBootstrap.mockResolvedValue(bootstrap);
    apiMocks.fetchProcess.mockResolvedValue(baseDetail());
    const { container } = render(
      <MemoryRouter initialEntries={[PROCESS_DETAIL_PATH]}>
        <Routes>
          <Route path="/processes/:processKey" element={<ProcessDetailPage />} />
        </Routes>
      </MemoryRouter>,
    );
    await screen.findByText("Banco de Bogotá");
    await user.click(await screen.findByRole("button", { name: "Finalizar revisión" }));
    await screen.findByRole("dialog", { name: "Finalizar revisión" });
    await expectNoSeriousOrCritical(container);
  });

  it("Modal Notify", async () => {
    const user = userEvent.setup();
    apiMocks.fetchBootstrap.mockResolvedValue(bootstrap);
    apiMocks.fetchProcess.mockResolvedValue(
      baseDetail({
        operational_status: "PENDIENTE_NOTIFICACION",
        operational_title: "Validación finalizada",
        operational_message: "La revisión fue finalizada correctamente.",
        control_estado_proceso: "FINALIZADO",
        next_actions: [{ code: "notify", label: "Enviar correo.", enabled: true, reason: null }],
        available_actions: {
          finalize: { allowed: false, reason: null },
          notify: { allowed: true, reason: null },
          merge: { allowed: false, reason: null },
          amortization: { allowed: false, reason: null },
        },
        steps: baseDetail().steps.map((s) =>
          s.name === "finalize"
            ? { ...s, status: "completed", summary: "La revisión fue finalizada correctamente." }
            : s.name === "review"
              ? { ...s, status: "completed" }
              : s,
        ),
        files: {
          ...baseDetail().files,
          historical_file_path: "historico/h.xlsx",
        },
      }),
    );
    const { container } = render(
      <MemoryRouter initialEntries={[PROCESS_DETAIL_PATH]}>
        <Routes>
          <Route path="/processes/:processKey" element={<ProcessDetailPage />} />
        </Routes>
      </MemoryRouter>,
    );
    await screen.findByRole("heading", { name: "Banco de Bogotá" });
    await user.click(await screen.findByRole("button", { name: "Enviar correo" }));
    await screen.findByRole("dialog", { name: "Enviar correo" });
    await expectNoSeriousOrCritical(container);
  });

  it("Modal Merge", async () => {
    const user = userEvent.setup();
    apiMocks.fetchBootstrap.mockResolvedValue(bootstrap);
    apiMocks.fetchProcess.mockResolvedValue(
      baseDetail({
        operational_status: "ESPERANDO_SOPORTES",
        control_estado_proceso: "PENDIENTE_ASIENTOS",
        available_actions: {
          finalize: { allowed: false, reason: null },
          notify: { allowed: false, reason: null },
          merge: { allowed: true, reason: null },
          amortization: { allowed: false, reason: null },
        },
        steps: baseDetail().steps.map((s) =>
          ["generate", "review", "finalize", "notify"].includes(s.name)
            ? { ...s, status: "completed" as const }
            : s.name === "merge"
              ? { ...s, status: "blocked" as const }
              : s,
        ),
        merge_readiness: {
          status: "ready",
          expected_groups: 1,
          ready_groups: 1,
          missing_groups: 0,
          missing_items: [],
          folder_links: [],
          checked_at: null,
          user_message: "Listo",
          next_action: "Consolidar",
        },
      }),
    );
    const { container } = render(
      <MemoryRouter initialEntries={[PROCESS_DETAIL_PATH]}>
        <Routes>
          <Route path="/processes/:processKey" element={<ProcessDetailPage />} />
        </Routes>
      </MemoryRouter>,
    );
    await screen.findByText("Banco de Bogotá");
    const mergeButtons = await screen.findAllByRole("button", {
      name: "Generar PDF consolidado",
    });
    await user.click(mergeButtons[0]!);
    await screen.findByRole("dialog", { name: "Generar PDF consolidado" });
    await expectNoSeriousOrCritical(container);
  });

  it("Modal amortización", async () => {
    const user = userEvent.setup();
    apiMocks.fetchBootstrap.mockResolvedValue(bootstrap);
    apiMocks.fetchProcess.mockResolvedValue(
      baseDetail({
        operational_status: "LISTO_PARA_APLICAR",
        control_estado_proceso: "CONSOLIDADO",
        available_actions: {
          finalize: { allowed: false, reason: null },
          notify: { allowed: false, reason: null },
          merge: { allowed: false, reason: null },
          amortization: { allowed: true, reason: null },
        },
        steps: baseDetail().steps.map((s) =>
          ["generate", "review", "finalize", "notify", "merge"].includes(s.name)
            ? { ...s, status: "completed" as const }
            : s,
        ),
        amortization_readiness: {
          status: "ready",
          can_start: true,
          expected_items: 1,
          ready_items: 1,
          missing_items: [],
          warnings: [],
          checked_at: null,
          user_message: "Listo",
          next_action: "Procesar",
        },
      }),
    );
    const { container } = render(
      <MemoryRouter initialEntries={[PROCESS_DETAIL_PATH]}>
        <Routes>
          <Route path="/processes/:processKey" element={<ProcessDetailPage />} />
        </Routes>
      </MemoryRouter>,
    );
    await screen.findByText("Banco de Bogotá");
    const amortButtons = await screen.findAllByRole("button", {
      name: "Procesar amortización",
    });
    await user.click(amortButtons[0]!);
    await screen.findByRole("dialog", { name: "Procesar amortización" });
    await expectNoSeriousOrCritical(container);
  });
});
