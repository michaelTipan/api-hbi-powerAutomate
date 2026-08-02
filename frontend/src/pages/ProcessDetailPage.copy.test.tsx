import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import type { UiBootstrapResponse, UiProcessDetail } from "../types/contract";

const mocks = vi.hoisted(() => ({
  fetchProcess: vi.fn(),
  fetchJob: vi.fn(),
  fetchBootstrap: vi.fn(),
  postFinalize: vi.fn(),
  postNotify: vi.fn(),
  postMerge: vi.fn(),
  postAmortization: vi.fn(),
}));

vi.mock("../api/client", () => ({
  fetchProcess: mocks.fetchProcess,
  fetchJob: mocks.fetchJob,
  fetchBootstrap: mocks.fetchBootstrap,
  postFinalize: mocks.postFinalize,
  postNotify: mocks.postNotify,
  postMerge: mocks.postMerge,
  postAmortization: mocks.postAmortization,
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
    steps: [
      { name: "generate", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
      { name: "review", status: "in_progress", updated_at: null, summary: null, can_retry: false, retry_action: null },
      { name: "finalize", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
      { name: "notify", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
      { name: "merge", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
      { name: "dry_run", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
      { name: "apply", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
    ],
    items: [],
    active_job: null,
    last_attempt: null,
    latest_attempts_by_stage: {
      generate: {
        stage: "generate",
        job_id: "j1",
        job_type: "generate",
        status: "completed",
        outcome: null,
        recoverable: false,
        error_code: null,
        severity: null,
        user_message: null,
        next_action: null,
        started_at: "2026-08-01T13:30:28-05:00",
        finished_at: "2026-08-01T13:30:28-05:00",
        progress: null,
        technical_reference: null,
      },
    },
    attempts: [],
    next_actions: [],
    available_actions: {
      finalize: { allowed: true, reason: null },
      notify: { allowed: false, reason: "Debe completarse el cierre de la revisión primero." },
      merge: { allowed: false, reason: null },
      amortization: { allowed: false, reason: null },
    },
    errors: [],
    operational_issues: [],
    links: [
      {
        rel: "review_excel",
        label: "Abrir archivo de revisión",
        path: "revision/x.xlsx",
        web_url: "https://example.com/x.xlsx",
        open_mode: "sharepoint",
      },
      {
        rel: "control",
        label: "Abrir control del proceso",
        path: "control/c.xlsx",
        web_url: "https://example.com/control.xlsx",
        open_mode: "sharepoint",
      },
    ],
    files: {
      validation_file_path: "revision/x.xlsx",
      historical_file_path: null,
      secretary_file_path: null,
      email_pdf_path: null,
      merge_manifest_path: null,
      control_file_path: "control/c.xlsx",
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

function renderDetail(processKey: string) {
  return render(
    <MemoryRouter initialEntries={[`/processes/${encodeURIComponent(processKey)}`]}>
      <Routes>
        <Route path="/processes/:processKey" element={<ProcessDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ProcessDetailPage — lenguaje operativo y fases", () => {
  it("no expone ProcessKey, jerga técnica, historial ni detalles técnicos", async () => {
    const processKey = "payment-validation|banco_bogota|2026-07-31|abc-1";
    mocks.fetchBootstrap.mockResolvedValue(bootstrap);
    mocks.fetchProcess.mockResolvedValue(baseDetail({ process_key: processKey }));

    renderDetail(processKey);

    await screen.findByText("Banco de Bogotá");
    const text = document.body.textContent || "";
    expect(text).not.toMatch(/ProcessKey/i);
    expect(text).not.toMatch(/\bGenerate\b/);
    expect(text).not.toMatch(/\bFinalize\b/);
    expect(text).not.toMatch(/secretar/i);
    expect(screen.queryByText(/Historial de intentos/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Detalles técnicos/i)).not.toBeInTheDocument();
    expect(screen.queryByText(processKey)).not.toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Progreso del proceso" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Finalizar revisión" })).toBeInTheDocument();
  });

  it("oculta el enlace de control y agrupa documentos por fase", async () => {
    const processKey = "payment-validation|banco_bogota|2026-07-31|abc-1";
    mocks.fetchBootstrap.mockResolvedValue(bootstrap);
    mocks.fetchProcess.mockResolvedValue(baseDetail({ process_key: processKey }));

    renderDetail(processKey);
    await screen.findByText("Banco de Bogotá");

    expect(screen.queryByRole("link", { name: /Abrir control del proceso/i })).not.toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: /Abrir archivo de revisión/i }).length).toBeGreaterThan(0);
    expect(screen.getByText("Documentos por fase")).toBeInTheDocument();
    expect(screen.queryByText(/Solo consulta: vuelve a detectar/i)).not.toBeInTheDocument();
    expect(screen.getByText(/Fase 1 de 5 · Generar archivo/i)).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "Generar archivo" })).toBeInTheDocument();
    const back = screen.getByRole("link", { name: "Volver al panel" });
    expect(back).toHaveClass("btn", "secondary");
    expect(back).toHaveAttribute("href", "/");
    // En revisión: recargo genérico, no el de documentos.
    expect(screen.getByRole("button", { name: "Actualizar estado" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Actualizar documentos" })).not.toBeInTheDocument();
    expect(
      screen.queryByText(/Después de cargar, reemplazar o renombrar documentos/i),
    ).not.toBeInTheDocument();
  });

  it("muestra Actualizar documentos solo cuando Merge espera soportes", async () => {
    const processKey = "payment-validation|banco_bancolombia|2026-08-01|m1";
    mocks.fetchBootstrap.mockResolvedValue(bootstrap);
    mocks.fetchProcess.mockResolvedValue(
      baseDetail({
        process_key: processKey,
        bank_code: "banco_bancolombia",
        bank_name: "Bancolombia",
        operational_status: "ESPERANDO_SOPORTES",
        control_estado_proceso: "PENDIENTE_ASIENTOS",
        steps: [
          { name: "generate", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "review", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "finalize", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "notify", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "merge", status: "blocked", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "dry_run", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "apply", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
        ],
        next_actions: [
          { code: "refresh_documents", label: "Actualizar documentos", enabled: true, reason: null },
        ],
        links: [
          {
            rel: "email_pdf",
            label: "Ver correo enviado",
            path: "correo/x.pdf",
            web_url: "https://example.com/correo.pdf",
            open_mode: "sharepoint",
          },
          {
            rel: "merge_manifest",
            label: "Abrir PDF consolidado",
            path: "merge/m.pdf",
            web_url: null,
            open_mode: "sharepoint",
          },
        ],
      }),
    );

    renderDetail(processKey);
    await screen.findByText("Bancolombia");

    expect(
      await screen.findByText(/Después de cargar, reemplazar o renombrar documentos/i),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Actualizar documentos" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Actualizar estado" })).not.toBeInTheDocument();
  });

  it("Actualizar documentos solo reconsulta GET y refresca links/readiness/mensajes", async () => {
    const processKey = "payment-validation|banco_bancolombia|2026-08-01|m2";
    const waiting = baseDetail({
      process_key: processKey,
      bank_code: "banco_bancolombia",
      bank_name: "Bancolombia",
      operational_status: "ESPERANDO_SOPORTES",
      operational_message: "Faltan documentos contables.",
      control_estado_proceso: "PENDIENTE_ASIENTOS",
      steps: [
        { name: "generate", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
        { name: "review", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
        { name: "finalize", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
        { name: "notify", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
        { name: "merge", status: "blocked", updated_at: null, summary: null, can_retry: false, retry_action: null },
        { name: "dry_run", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
        { name: "apply", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
      ],
      next_actions: [
        { code: "refresh_documents", label: "Actualizar documentos", enabled: true, reason: null },
      ],
      merge_readiness: {
        status: "incomplete",
        expected_groups: 1,
        ready_groups: 0,
        missing_groups: 1,
        missing_items: [{ credito: "215", user_message: "Falta asiento contable" }],
        folder_links: [],
        user_message: "Aún faltan documentos contables.",
        next_action: "Cargue el asiento y actualice documentos.",
        checked_at: null,
      },
      links: [
        {
          rel: "email_pdf",
          label: "Ver correo enviado",
          path: "correo/x.pdf",
          web_url: null,
          open_mode: "sharepoint",
        },
      ],
    });
    const afterRefresh = {
      ...waiting,
      operational_message: "Documentos detectados; puede generar el PDF.",
      merge_readiness: {
        status: "ready" as const,
        expected_groups: 1,
        ready_groups: 1,
        missing_groups: 0,
        missing_items: [],
        folder_links: [],
        user_message: "Documentos listos para consolidar.",
        next_action: "Genere el PDF consolidado.",
        checked_at: null,
      },
      links: [
        {
          rel: "email_pdf",
          label: "Ver correo enviado",
          path: "correo/x.pdf",
          web_url: "https://example.com/correo.pdf",
          open_mode: "sharepoint" as const,
        },
      ],
    };
    mocks.fetchBootstrap.mockResolvedValue(bootstrap);
    mocks.fetchProcess.mockResolvedValueOnce(waiting).mockResolvedValueOnce(afterRefresh);

    renderDetail(processKey);
    await screen.findByText("Faltan documentos contables.");
    expect(screen.getByText(/Ver correo enviado \(no disponible\)/i)).toBeInTheDocument();
    expect(screen.getByText(/Falta asiento contable/i)).toBeInTheDocument();
    expect(screen.getByText(/Aún faltan documentos contables/i)).toBeInTheDocument();

    const callsBeforeClick = mocks.fetchProcess.mock.calls.length;
    mocks.fetchProcess.mockResolvedValue(afterRefresh);
    screen.getByRole("button", { name: "Actualizar documentos" }).click();

    expect(await screen.findByText("Documentos detectados; puede generar el PDF.")).toBeInTheDocument();
    expect(screen.getByText(/Documentos listos para consolidar/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Ver correo enviado/i })).toHaveAttribute(
      "href",
      "https://example.com/correo.pdf",
    );
    expect(mocks.fetchProcess.mock.calls.length).toBeGreaterThan(callsBeforeClick);
    expect(mocks.postFinalize).not.toHaveBeenCalled();
    expect(mocks.postNotify).not.toHaveBeenCalled();
    expect(mocks.postMerge).not.toHaveBeenCalled();
    expect(mocks.postAmortization).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Actualizar estado" })).not.toBeInTheDocument();
  });

  it("en COMPLETADO no muestra botones de recarga si todo está disponible", async () => {
    const processKey = "payment-validation|banco_bogota|2026-08-01|done";
    mocks.fetchBootstrap.mockResolvedValue(bootstrap);
    mocks.fetchProcess.mockResolvedValue(
      baseDetail({
        process_key: processKey,
        operational_status: "COMPLETADO",
        control_estado_proceso: "AMORTIZACION_APLICADA",
        steps: [
          { name: "generate", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "review", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "finalize", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "notify", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "merge", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "dry_run", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "apply", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
        ],
        links: [
          {
            rel: "merge_manifest",
            label: "Abrir PDF consolidado",
            path: "merge/m.pdf",
            web_url: "https://example.com/m.pdf",
            open_mode: "sharepoint",
          },
        ],
      }),
    );

    renderDetail(processKey);
    await screen.findByText("Banco de Bogotá");
    expect(screen.queryByRole("button", { name: "Actualizar estado" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Actualizar documentos" })).not.toBeInTheDocument();
  });
});
