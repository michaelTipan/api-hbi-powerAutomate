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
    vi.useRealTimers();
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

  it("en el modal de Finalize fallido muestra resumen corto y CTA a problemas operativos", async () => {
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
                sheet: "Aplicacion_Pagos",
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
                sheet: "Aplicacion_Pagos",
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
    expect(
      await within(dialog).findByRole("heading", {
        name: "No se pudo completar",
        timeout: 8000,
      }),
    ).toBeInTheDocument();
    expect(within(dialog).getByText(/Hay 2 problemas en la revisión/)).toBeInTheDocument();
    expect(within(dialog).getByText(/Problemas operativos/)).toBeInTheDocument();
    expect(within(dialog).queryByText(/total aplicado es cero o negativo/i)).not.toBeInTheDocument();
    expect(within(dialog).queryByText(/Estado Pago está vacío/i)).not.toBeInTheDocument();
    expect(
      within(dialog).getByRole("button", { name: /Ver problemas operativos/i }),
    ).toBeInTheDocument();
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
              sheet: "Aplicacion_Pagos",
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
            links: [
              {
                rel: "review_excel",
                label: "Abrir archivo de revisión",
                path: "/review.xlsx",
                web_url: "https://sp.example/review.xlsx",
                open_mode: "sharepoint",
              },
            ],
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
    expect(screen.getByText("Fila 14")).toBeInTheDocument();
    expect(
      screen.getByText("No se pudo finalizar el archivo de revisión."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Verificar nuevamente" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Abrir archivo de revisión/i })).toBeInTheDocument();
  });
});

describe("ProcessDetailPage — CTA amortización en vuelo (active_job ausente)", () => {
  beforeEach(() => {
    mocks.fetchProcess.mockReset();
    mocks.fetchJob.mockReset();
    mocks.fetchBootstrap.mockReset();
    mocks.postAmortization.mockReset();
    mocks.useCsrfReady.mockReturnValue({ csrfReady: true, csrfPreparing: false });
  });

  it("no re-habilita Procesar amortización si load() llega sin active_job mientras el job sigue running", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const processKey = "payment-validation|banco_bogota|2026-08-01|amort-inflight";
    const readyDetail = baseDetail({
      process_key: processKey,
      operational_status: "LISTO_PARA_APLICAR",
      control_estado_proceso: "CONSOLIDADO",
      steps: [
        { name: "generate", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
        { name: "review", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
        { name: "finalize", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
        { name: "notify", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
        { name: "merge", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
        { name: "dry_run", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
        { name: "apply", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
      ],
      available_actions: {
        finalize: { allowed: false, reason: null },
        notify: { allowed: false, reason: null },
        merge: { allowed: false, reason: null },
        amortization: { allowed: true, reason: null },
      },
      amortization_readiness: {
        status: "ready",
        can_start: true,
        expected_items: 1,
        ready_items: 1,
        missing_items: [],
        warnings: [],
        user_message: "Listo.",
        next_action: "Puede procesar la amortización desde la UI.",
        checked_at: null,
      },
    });

    mocks.fetchBootstrap.mockResolvedValue(bootstrap);
    // Primer load: listo. Tras POST, refreshes sin active_job (lag de Control).
    mocks.fetchProcess.mockResolvedValue({ ...readyDetail, active_job: null });
    mocks.postAmortization.mockResolvedValue({
      accepted: true,
      action: "amortization",
      bank_code: "banco_bogota",
      process_key: processKey,
      job_id: "job-amort-inflight",
      status: "queued",
      poll_url: "/api/ui/v1/jobs/job-amort-inflight",
    });
    mocks.fetchJob.mockResolvedValue({
      job_id: "job-amort-inflight",
      type: "amortization_process",
      status: "running",
      store: "job_manager",
      process_key: processKey,
      bank_code: "banco_bogota",
      environment: "sandbox",
      created_at: "2026-08-01T10:00:00-05:00",
      started_at: "2026-08-01T10:00:00-05:00",
      finished_at: null,
      result_summary: null,
      error: null,
      user_message: null,
      next_action: null,
      progress: { phase: "validating" },
      raw_available: false,
    });

    renderProcessDetail(processKey);
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await screen.findByRole("heading", { name: "Banco de Bogotá" });

    const ctaRoot = document.querySelector(".current-phase-panel");
    expect(ctaRoot).toBeTruthy();
    const amortBtn = within(ctaRoot as HTMLElement).getByRole("button", {
      name: /^Procesar amortización$/i,
    });
    await user.click(amortBtn);
    const confirmDialog = await screen.findByRole("dialog");
    await user.click(
      within(confirmDialog).getByRole("button", { name: /^Procesar amortización$/i }),
    );

    await waitFor(() => expect(mocks.postAmortization).toHaveBeenCalled());
    // Un refresh forzado (toolbar) no debe borrar el job local en vuelo.
    await user.click(screen.getByRole("button", { name: "Actualizar estado" }));
    await waitFor(() => expect(mocks.fetchProcess.mock.calls.length).toBeGreaterThan(1));

    const panel = document.querySelector(".current-phase-panel");
    expect(panel).toBeTruthy();
    const midFlightBtn = within(panel as HTMLElement).getByRole("button", {
      name: /Procesando amortización|Sincronizando resultados|Procesar amortización/i,
    });
    expect(midFlightBtn).toBeDisabled();
    vi.useRealTimers();
  });
});

describe("ProcessDetailPage — NOTIFY_SENDING requiere verificación", () => {
  beforeEach(() => {
    mocks.fetchProcess.mockReset();
    mocks.fetchJob.mockReset();
    mocks.fetchBootstrap.mockReset();
    mocks.postNotify.mockReset();
    mocks.useCsrfReady.mockReturnValue({ csrfReady: true, csrfPreparing: false });
  });

  it("bloquea el CTA de Notify y no trata NOTIFY_SENDING| como éxito", async () => {
    const processKey = "payment-validation|banco_bogota|2026-07-30|sending-gap";
    const reason =
      "No se pudo confirmar el resultado del envío. El sistema no volverá a enviar automáticamente el correo para evitar duplicados. Requiere verificación.";
    mocks.fetchBootstrap.mockResolvedValue(bootstrap);
    mocks.fetchProcess.mockResolvedValue(
      baseDetail({
        process_key: processKey,
        operational_status: "REQUIERE_VERIFICACION",
        operational_title: "Resultado del envío no confirmado",
        operational_message: reason,
        control_estado_proceso: "FINALIZADO",
        available_actions: {
          finalize: { allowed: false, reason: null },
          notify: { allowed: false, reason },
          merge: { allowed: false, reason: null },
          amortization: { allowed: false, reason: null },
        },
        steps: [
          { name: "generate", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "review", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "finalize", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
          {
            name: "notify",
            status: "requires_verification",
            updated_at: null,
            summary: reason,
            can_retry: false,
            retry_action: null,
          },
          { name: "merge", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "dry_run", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "apply", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
        ],
        idempotency: {
          notify_idempotency_key: `NOTIFY_SENDING|${processKey}`,
          merge_idempotency_key: null,
          apply_idempotency_key: null,
        },
      }),
    );

    renderProcessDetail(processKey);
    await screen.findByRole("heading", { name: "Banco de Bogotá" });
    expect(screen.getByText(/Resultado del envío no confirmado/i)).toBeInTheDocument();
    expect(screen.queryByText(/^Correo enviado$/i)).not.toBeInTheDocument();

    const ctaRoot = document.querySelector(".current-phase-panel");
    expect(ctaRoot).toBeTruthy();
    const notifyBtn = within(ctaRoot as HTMLElement).getByRole("button", {
      name: /^Enviar correo$/i,
    });
    expect(notifyBtn).toBeDisabled();
    expect(mocks.postNotify).not.toHaveBeenCalled();
  });

  it("con job notify_mail_uncertain no muestra éxito y mantiene el CTA bloqueado", async () => {
    const processKey = "payment-validation|banco_bogota|2026-07-30|sending-job";
    const reason =
      "No se pudo confirmar el resultado del envío. El sistema no volverá a enviar automáticamente el correo para evitar duplicados. Requiere verificación.";
    mocks.fetchBootstrap.mockResolvedValue(bootstrap);
    mocks.fetchProcess.mockResolvedValue(
      baseDetail({
        process_key: processKey,
        operational_status: "REQUIERE_VERIFICACION",
        operational_title: "Resultado del envío no confirmado",
        operational_message: reason,
        control_estado_proceso: "FINALIZADO",
        available_actions: {
          finalize: { allowed: false, reason: null },
          notify: { allowed: false, reason },
          merge: { allowed: false, reason: null },
          amortization: { allowed: false, reason: null },
        },
        steps: [
          { name: "generate", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "review", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "finalize", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
          {
            name: "notify",
            status: "requires_verification",
            updated_at: null,
            summary: reason,
            can_retry: false,
            retry_action: null,
          },
          { name: "merge", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "dry_run", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "apply", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
        ],
        idempotency: {
          notify_idempotency_key: `NOTIFY_SENDING|${processKey}`,
          merge_idempotency_key: null,
          apply_idempotency_key: null,
        },
        last_attempt: {
          stage: "notify",
          job_id: "notify-uncertain",
          job_type: "notify_validar_extractos",
          status: "completed",
          outcome: "notify_mail_uncertain",
          recoverable: false,
          error_code: "notify_mail_uncertain",
          severity: "warning",
          user_message: reason,
          next_action: "Verifique en el buzón si el correo llegó. No reenvíe desde la UI.",
          started_at: "2026-07-30T10:00:00-05:00",
          finished_at: "2026-07-30T10:00:05-05:00",
          progress: null,
          technical_reference: null,
        },
      }),
    );

    renderProcessDetail(processKey);
    await screen.findByRole("heading", { name: "Banco de Bogotá" });
    expect(screen.getByText(/Resultado del envío no confirmado/i)).toBeInTheDocument();
    expect(screen.getAllByText(/Requiere verificación/i).length).toBeGreaterThan(0);
    expect(screen.queryByText(/^Correo enviado$/i)).not.toBeInTheDocument();
    const notifyBtn = within(document.querySelector(".current-phase-panel") as HTMLElement).getByRole(
      "button",
      { name: /^Enviar correo$/i },
    );
    expect(notifyBtn).toBeDisabled();
    expect(mocks.postNotify).not.toHaveBeenCalled();
  });

  it("tras Actualizar estado sigue incierto y no habilita retry de envío", async () => {
    const processKey = "payment-validation|banco_bogota|2026-07-30|sending-refresh";
    const reason =
      "No se pudo confirmar el resultado del envío. El sistema no volverá a enviar automáticamente el correo para evitar duplicados. Requiere verificación.";
    const uncertain = baseDetail({
      process_key: processKey,
      operational_status: "REQUIERE_VERIFICACION",
      operational_title: "Resultado del envío no confirmado",
      operational_message: reason,
      control_estado_proceso: "FINALIZADO",
      available_actions: {
        finalize: { allowed: false, reason: null },
        notify: { allowed: false, reason },
        merge: { allowed: false, reason: null },
        amortization: { allowed: false, reason: null },
      },
      steps: [
        { name: "generate", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
        { name: "review", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
        { name: "finalize", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
        {
          name: "notify",
          status: "requires_verification",
          updated_at: null,
          summary: reason,
          can_retry: false,
          retry_action: null,
        },
        { name: "merge", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
        { name: "dry_run", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
        { name: "apply", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
      ],
      idempotency: {
        notify_idempotency_key: `NOTIFY_SENDING|${processKey}`,
        merge_idempotency_key: null,
        apply_idempotency_key: null,
      },
    });
    mocks.fetchBootstrap.mockResolvedValue(bootstrap);
    mocks.fetchProcess.mockResolvedValue(uncertain);

    renderProcessDetail(processKey);
    await screen.findByRole("heading", { name: "Banco de Bogotá" });
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Actualizar estado" }));
    await screen.findByText(/Resultado del envío no confirmado/i);
    expect(screen.queryByText(/^Correo enviado$/i)).not.toBeInTheDocument();
    const notifyBtn = within(document.querySelector(".current-phase-panel") as HTMLElement).getByRole(
      "button",
      { name: /^Enviar correo$/i },
    );
    expect(notifyBtn).toBeDisabled();
    expect(mocks.postNotify).not.toHaveBeenCalled();
    expect(mocks.fetchProcess.mock.calls.length).toBeGreaterThan(1);
  });
});
