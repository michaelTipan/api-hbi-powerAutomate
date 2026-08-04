import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import type {
  UiBootstrapResponse,
  UiJobView,
  UiProcessDetail,
} from "../types/contract";

const mocks = vi.hoisted(() => ({
  fetchProcess: vi.fn(),
  fetchJob: vi.fn(),
  fetchBootstrap: vi.fn(),
  postFinalize: vi.fn(),
  postNotify: vi.fn(),
  postMerge: vi.fn(),
  postAmortization: vi.fn(),
  useCsrfReady: vi.fn(),
}));

vi.mock("../api/client", () => ({
  fetchProcess: mocks.fetchProcess,
  fetchJob: mocks.fetchJob,
  fetchBootstrap: mocks.fetchBootstrap,
  postFinalize: mocks.postFinalize,
  postNotify: mocks.postNotify,
  postMerge: mocks.postMerge,
  postAmortization: mocks.postAmortization,
  postGenerate: vi.fn(),
}));

vi.mock("../api/useCsrfReady", () => ({
  useCsrfReady: mocks.useCsrfReady,
}));

import { ProcessDetailPage } from "./ProcessDetailPage";

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
  login_required: false,
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
    control_estado_proceso: "REVISION_CREADA",
    is_active: true,
    steps: [],
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
      validation_file_path: null,
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

function failedFinalizeJob(overrides: Partial<UiJobView> = {}): UiJobView {
  return {
    job_id: "job-1",
    type: "finalize",
    status: "failed",
    store: "job_manager",
    process_key: "payment-validation|banco_bogota|2026-07-31|abc-1",
    bank_code: "banco_bogota",
    environment: "sandbox",
    created_at: null,
    started_at: null,
    finished_at: "2026-07-31T09:00:00-05:00",
    result_summary: null,
    error: { error_code: "invalid_estado_pago" },
    user_message: "La revisión requiere correcciones.",
    next_action: "Corrija el valor y vuelva a verificar.",
    severity: "warning",
    raw_available: true,
    ...overrides,
  };
}

function renderProcessDetail(processKey: string) {
  return render(
    <MemoryRouter initialEntries={[`/processes/${encodeURIComponent(processKey)}`]}>
      <Routes>
        <Route path="/processes/:processKey" element={<ProcessDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ProcessDetailPage — persistencia del error terminal (bug U4-B)", () => {
  beforeEach(() => {
    mocks.fetchProcess.mockReset();
    mocks.fetchJob.mockReset();
    mocks.fetchBootstrap.mockReset();
    mocks.postFinalize.mockReset();
    mocks.useCsrfReady.mockReturnValue({ csrfReady: true, csrfPreparing: false });
  });

  it("no borra el mensaje de un Finalize fallido cuando active_job desaparece en el siguiente load()", async () => {
    const processKey = "payment-validation|banco_bogota|2026-07-31|abc-1";
    mocks.fetchBootstrap.mockResolvedValue(bootstrap);
    mocks.fetchProcess
      .mockResolvedValueOnce(
        baseDetail({
          process_key: processKey,
          active_job: {
            job_id: "job-1",
            type: "finalize",
            status: "running",
            store: "job_manager",
            poll_path_graph: null,
            poll_path_ui: "/api/ui/v1/jobs/job-1",
            started_at: null,
            progress: null,
          },
        }),
      )
      // U4-B: el segundo load() ya no trae active_job (el job terminó) y el
      // backend tampoco proyectó todavía last_attempt; solo el estado local
      // del job sondeado debe evitar que el error desaparezca.
      .mockResolvedValue(
        baseDetail({ process_key: processKey, active_job: null, last_attempt: null }),
      );
    mocks.fetchJob.mockResolvedValue(failedFinalizeJob());

    renderProcessDetail(processKey);

    const updateButton = await screen.findByRole("button", { name: "Actualizar estado" });
    await waitFor(() => expect(mocks.fetchJob).toHaveBeenCalledTimes(1));

    const user = userEvent.setup();
    await user.click(updateButton);

    await waitFor(() => expect(mocks.fetchProcess).toHaveBeenCalledTimes(2));

    expect(
      await screen.findByText(/La revisión requiere correcciones\./),
    ).toBeInTheDocument();
    expect(screen.getByText(/Corrija el valor y vuelva a verificar\./)).toBeInTheDocument();
    // El job local nunca vuelve a "sin trabajo" mientras siga siendo terminal.
    expect(mocks.fetchJob).toHaveBeenCalledTimes(1);
  });

  it("en el modal de Finalize fallido lista issues y el enlace al Excel", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const processKey = "payment-validation|banco_bogota|2026-07-31|fin-multi";
    const detailReady = baseDetail({
      process_key: processKey,
      control_estado_proceso: "REVISION_CREADA",
      available_actions: {
        finalize: { allowed: true, reason: null },
        notify: { allowed: false, reason: null },
        merge: { allowed: false, reason: null },
        amortization: { allowed: false, reason: null },
        regenerate: { allowed: true, reason: null },
      },
      steps: [
        { name: "generate", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
        { name: "review", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
        { name: "finalize", status: "in_progress", updated_at: null, summary: null, can_retry: false, retry_action: null },
        { name: "notify", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
        { name: "merge", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
        { name: "dry_run", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
        { name: "apply", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
      ],
      links: [
        {
          rel: "review_excel",
          label: "Abrir archivo de revisión",
          path: "/review.xlsx",
          web_url: "https://sp.example/review.xlsx",
          open_mode: "sharepoint",
        },
      ],
    });
    mocks.fetchBootstrap.mockResolvedValue(bootstrap);
    mocks.fetchProcess.mockResolvedValue(detailReady);
    mocks.postFinalize.mockResolvedValue({
      accepted: true,
      action: "finalize",
      bank_code: "banco_bogota",
      process_key: processKey,
      job_id: "job-multi",
      status: "queued",
      poll_url: "/api/ui/v1/jobs/job-multi",
    });
    mocks.fetchJob.mockResolvedValue(
      failedFinalizeJob({
        job_id: "job-multi",
        user_message: "Se encontraron 2 problemas en la revisión.",
        next_action: "Corrija todos los puntos listados, guarde y vuelva a verificar.",
        error: {
          error_code: "multiple_review_errors",
          issues: [
            {
              issue_id: "HBI-FINALIZE-validar_requires_positive_total-jobmulti-0",
              user_message:
                "Marcó Validar Pago = SI pero el total aplicado es cero o negativo (NORMAL o ATRASADO).",
              location: {
                file_name: null,
                sheet: "Distribucion_Pagos",
                row: 6,
                column: "Total aplicado",
                credit: "CREDITO # 265",
                payment_id: null,
                client_name: "EQUINORTE",
              },
            },
            {
              issue_id: "HBI-FINALIZE-empty_estado_pago-jobmulti-1",
              user_message: "En Distribución hay filas con datos pero Estado Pago está vacío.",
              location: {
                file_name: null,
                sheet: "Distribucion_Pagos",
                row: 4,
                column: "Estado Pago",
                credit: null,
                payment_id: "ID2",
                client_name: null,
              },
            },
          ],
        },
      }),
    );

    renderProcessDetail(processKey);
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });

    await screen.findByRole("heading", { name: "Banco de Bogotá" });
    const ctaRoot = document.querySelector(".current-phase-panel");
    expect(ctaRoot).toBeTruthy();
    const finalizeBtn = within(ctaRoot as HTMLElement).getByRole("button", {
      name: "Finalizar revisión",
    });
    await user.click(finalizeBtn);
    await user.click(await screen.findByRole("button", { name: "Confirmar finalización" }));

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("heading", { name: "No se pudo completar" })).toBeInTheDocument();
    expect(within(dialog).getByText(/Se encontraron 2 problemas/)).toBeInTheDocument();
    expect(within(dialog).getByText(/total aplicado es cero o negativo/i)).toBeInTheDocument();
    expect(within(dialog).getByText(/Estado Pago está vacío/i)).toBeInTheDocument();
    expect(
      within(dialog).getByRole("link", { name: /Abrir archivo de revisión/i }),
    ).toHaveAttribute("href", "https://sp.example/review.xlsx");
    vi.useRealTimers();
  });

  it("abre el modal de problemas operativos cuando el backend proyecta operational_issues", async () => {
    const processKey = "payment-validation|banco_bogota|2026-07-31|def-2";
    mocks.fetchBootstrap.mockResolvedValue(bootstrap);
    mocks.fetchJob.mockResolvedValue(failedFinalizeJob());
    mocks.fetchProcess.mockResolvedValue(
      baseDetail({
        process_key: processKey,
        active_job: null,
        operational_issues: [
          {
            issue_id: "HBI-FINALIZE-invalid_estado_pago-12345678",
            stage: "finalize",
            category: "correction_required",
            severity: "warning",
            recoverable: true,
            title: "La revisión requiere correcciones.",
            user_message: "No se pudo finalizar el archivo de revisión.",
            location: {
              file_name: "validacion_pagos_demo.xlsx",
              sheet: "Distribucion_Pagos",
              row: 14,
              column: "Estado Pago",
              credit: "37",
              payment_id: null,
              client_name: null,
            },
            value_found: "PENDIENTE",
            expected_values: ["ADELANTADO", "ATRASADO", "NORMAL", "REVISION_MANUAL"],
            next_action: "Corrija el valor, guarde el archivo y vuelva a verificar.",
            retry: { allowed: true, action: "finalize", label: "Verificar nuevamente" },
            links: [],
            technical_reference: "job:job-1|code:invalid_estado_pago",
          },
        ],
      }),
    );

    renderProcessDetail(processKey);

    expect(await screen.findByText(/1 problema\(s\) operativo\(s\)/i)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Problemas operativos" })).not.toBeInTheDocument();
    expect(document.getElementById("operational-issues")).toBeNull();

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /Ver problemas operativos/i }));

    expect(
      await screen.findByRole("heading", { name: /Problemas operativos \(1\)/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("No se pudo finalizar el archivo de revisión."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Verificar nuevamente" })).toBeInTheDocument();
  });
});
