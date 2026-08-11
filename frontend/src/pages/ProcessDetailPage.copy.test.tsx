import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import type { UiBootstrapResponse, UiProcessDetail } from "../types/contract";

const mocks = vi.hoisted(() => ({
  fetchProcess: vi.fn(),
  fetchJob: vi.fn(),
  fetchBootstrap: vi.fn(),
  fetchNotifyRecipientsPreview: vi.fn(),
  fetchIbrPreview: vi.fn(),
  postFinalize: vi.fn(),
  postNotify: vi.fn(),
  postMerge: vi.fn(),
  postAmortization: vi.fn(),
  postJobReloadDelaysFor: vi.fn(),
}));

vi.mock("../api/client", () => ({
  fetchProcess: mocks.fetchProcess,
  fetchJob: mocks.fetchJob,
  fetchBootstrap: mocks.fetchBootstrap,
  fetchNotifyRecipientsPreview: mocks.fetchNotifyRecipientsPreview,
  fetchIbrPreview: mocks.fetchIbrPreview,
  postFinalize: mocks.postFinalize,
  postNotify: mocks.postNotify,
  postMerge: mocks.postMerge,
  postAmortization: mocks.postAmortization,
  postGenerate: vi.fn(),
  postCancelLote: vi.fn(),
  postSoftClose: vi.fn(),
}));

vi.mock("../domain/jobProjectionSync", async () => {
  const actual = await vi.importActual<typeof import("../domain/jobProjectionSync")>(
    "../domain/jobProjectionSync",
  );
  return {
    ...actual,
    postJobReloadDelaysFor: mocks.postJobReloadDelaysFor,
  };
});

import { ProcessDetailPage } from "./ProcessDetailPage";
import { POST_JOB_RELOAD_DELAYS_MS } from "../domain/jobProjectionSync";

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
        rel: "bank_input",
        label: "Abrir Excel del banco",
        path: null,
        web_url: "https://example.com/BANCO.xlsx",
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

function renderDetail(processKey: string, initialSearch = "") {
  return render(
    <MemoryRouter
      initialEntries={[`/processes/${encodeURIComponent(processKey)}${initialSearch}`]}
    >
      <Routes>
        <Route path="/processes/:processKey" element={<ProcessDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ProcessDetailPage — lenguaje operativo y fases", () => {
  beforeEach(() => {
    mocks.postJobReloadDelaysFor.mockReset();
    // En tests: delays cortos por defecto (amortización real es ~30s).
    mocks.postJobReloadDelaysFor.mockReturnValue(POST_JOB_RELOAD_DELAYS_MS);
    mocks.fetchNotifyRecipientsPreview.mockResolvedValue({
      ok: true,
      source_path: "CTL/CORREOS.xlsx",
      sheet: "CORREOS",
      emisor: "ops@hbi.test",
      receptores: ["dest@hbi.test"],
      receptores_raw_count: 1,
      file_last_modified: "2026-08-11T12:00:00Z",
      warnings: ["Si acabas de editar CORREOS.xlsx en Excel Online, espera unos segundos."],
      user_message: "Se enviará desde ops@hbi.test a dest@hbi.test.",
    });
    mocks.fetchIbrPreview.mockResolvedValue({
      ok: true,
      source_path: "CTL/IBR_DIARIO.xlsx",
      process_key: "payment-validation|banco_bogota|2026-07-31|abc-1",
      process_date: "2026-07-31",
      rate: 0.1058,
      rate_pct: 10.58,
      rate_status: "found",
      ranges: [{ inicio: "2026-01-01", fin: "2026-12-31", valor: 0.1058, valor_pct: 10.58 }],
      file_last_modified: "2026-08-11T12:00:00Z",
      warnings: ["Si acabas de editar IBR_DIARIO.xlsx en Excel Online, espera unos segundos."],
      user_message: "IBR de referencia para 2026-07-31: 10.58000%.",
    });
  });

  it("muestra Cancelar proceso después del correo cuando backend lo autoriza", async () => {
    const processKey = "payment-validation|banco_bogota|2026-07-31|abc-1";
    mocks.fetchBootstrap.mockResolvedValue(bootstrap);
    mocks.fetchProcess.mockResolvedValue(
      baseDetail({
        process_key: processKey,
        control_estado_proceso: "PENDIENTE_ASIENTOS",
        operational_status: "ESPERANDO_SOPORTES",
        steps: [
          { name: "generate", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "review", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "finalize", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "notify", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "merge", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "dry_run", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "apply", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
        ],
        available_actions: {
          finalize: { allowed: false, reason: null },
          notify: { allowed: false, reason: null },
          merge: { allowed: false, reason: null },
          amortization: { allowed: false, reason: null },
          regenerate: { allowed: false, reason: null },
          cancel_lote: { allowed: true, reason: null },
          soft_close: { allowed: false, reason: null },
        },
      }),
    );

    renderDetail(processKey);
    const cancel = await screen.findByRole("button", { name: "Cancelar proceso" });
    await userEvent.click(cancel);

    expect(screen.getByText(/correo ya enviado se conservará como evidencia/i)).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Cancelar proceso" })).toHaveLength(2);
  });

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
    const bankExcel = screen.getByRole("link", { name: /Abrir Excel del banco/i });
    expect(bankExcel).toHaveAttribute("href", "https://example.com/BANCO.xlsx");
    expect(screen.getByText("Recursos por fase")).toBeInTheDocument();
    expect(screen.queryByText(/Solo consulta: vuelve a detectar/i)).not.toBeInTheDocument();
    expect(screen.getByText(/Fase 1 de 4 · Revisión de archivo/i)).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "Revisión de archivo" })).toBeInTheDocument();
    const back = screen.getByRole("link", { name: /Volver al panel/i });
    expect(back).toHaveClass("back-link");
    expect(back).toHaveAttribute("href", "/");
    expect(back.textContent).toMatch(/</);
    // Refresh fijo arriba a la derecha; sin «Actualizar documentos» ni Excel duplicado en la fase.
    expect(screen.getByRole("button", { name: "Actualizar estado" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Actualizar documentos" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Abrir Excel de revisión/i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Finalizar revisión" })).toBeInTheDocument();
  });

  it("con ?phase=review abre Revisión de archivo con CTA Finalizar (fase unificada)", async () => {
    const processKey = "payment-validation|banco_bogota|2026-07-31|abc-1";
    mocks.fetchBootstrap.mockResolvedValue(bootstrap);
    mocks.fetchProcess.mockResolvedValue(baseDetail({ process_key: processKey }));

    renderDetail(processKey, "?phase=review");
    await screen.findByText("Banco de Bogotá");

    expect(screen.getByText(/Fase 1 de 4 · Revisión de archivo/i)).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "Revisión de archivo" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Finalizar revisión" })).toBeInTheDocument();
    expect(screen.queryByText(/Consulta solamente/i)).not.toBeInTheDocument();
  });

  it("el icono de actualizar reconsulta GET y refresca mensajes", async () => {
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
      merge_readiness: {
        status: "incomplete",
        expected_groups: 1,
        ready_groups: 0,
        missing_groups: 1,
        missing_items: [],
        folder_links: [],
        user_message: "Aún faltan documentos contables.",
        next_action: "Cargue el asiento y actualice.",
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
    expect(screen.getByText(/Aún faltan documentos contables/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Actualizar documentos" })).not.toBeInTheDocument();

    const callsBeforeClick = mocks.fetchProcess.mock.calls.length;
    mocks.fetchProcess.mockResolvedValue(afterRefresh);
    screen.getByRole("button", { name: "Actualizar estado" }).click();

    expect(await screen.findByText("Documentos detectados; puede generar el PDF.")).toBeInTheDocument();
    expect(screen.getByText("Listo para consolidar")).toBeInTheDocument();
    const listoPill = screen.getByText("Listo para consolidar");
    expect(listoPill.className).toMatch(/status-pill/);
    expect(listoPill.className).toMatch(/\bok\b/);
    expect(listoPill.className).not.toMatch(/\bwarn\b/);
    expect(screen.getByText(/Documentos listos para consolidar/i)).toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /Ir a Enviar correo/i }));
    expect(screen.getByRole("link", { name: /Ver correo enviado/i })).toHaveAttribute(
      "href",
      "https://example.com/correo.pdf",
    );
    expect(mocks.fetchProcess.mock.calls.length).toBeGreaterThan(callsBeforeClick);
    expect(mocks.postMerge).not.toHaveBeenCalled();
  });

  it("en Enviar correo ofrece Revisar destinatarios desde CORREOS.xlsx", async () => {
    const processKey = "payment-validation|banco_bancolombia|2026-08-01|notify-cfg";
    mocks.fetchBootstrap.mockResolvedValue(bootstrap);
    mocks.fetchProcess.mockResolvedValue(
      baseDetail({
        process_key: processKey,
        bank_code: "banco_bancolombia",
        bank_name: "Bancolombia",
        environment: "sandbox",
        operational_status: "LISTO_PARA_NOTIFICAR",
        control_estado_proceso: "FINALIZADO",
        steps: [
          { name: "generate", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "review", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "finalize", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "notify", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "merge", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "dry_run", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "apply", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
        ],
        available_actions: {
          finalize: { allowed: false, reason: null },
          notify: { allowed: true, reason: null },
          merge: { allowed: false, reason: null },
          amortization: { allowed: false, reason: null },
        },
        links: [
          {
            rel: "correos",
            label: "Revisar destinatarios",
            path: null,
            web_url: "https://example.com/CORREOS.xlsx",
            open_mode: "sharepoint",
          },
        ],
      }),
    );

    renderDetail(processKey);
    await screen.findByText("Bancolombia");
    expect(screen.getByRole("heading", { level: 2, name: "Enviar correo" })).toBeInTheDocument();
    const destinatarios = screen.getByRole("link", { name: "Revisar destinatarios" });
    expect(destinatarios).toHaveAttribute("href", "https://example.com/CORREOS.xlsx");
    expect(destinatarios).toHaveClass("btn", "secondary");
    expect(screen.getByText(/igual que Power Automate/i)).toBeInTheDocument();
    expect(await screen.findByText(/Emisor:\s*ops@hbi\.test/i)).toBeInTheDocument();
    expect(screen.getByText(/Destinatarios:\s*dest@hbi\.test/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Actualizar lectura/i })).toBeInTheDocument();
    const docsSection = document.getElementById("process-documents");
    expect(docsSection?.textContent).not.toMatch(/Revisar destinatarios/);

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /^Enviar correo$/i }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/Emisor:/i)).toBeInTheDocument();
    expect(within(dialog).getByText(/ops@hbi\.test/i)).toBeInTheDocument();
    expect(within(dialog).getByText(/dest@hbi\.test/i)).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: /Actualizar lectura/i })).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: /Confirmar envío/i })).toBeInTheDocument();
  });

  it("en Procesar amortización ofrece Actualizar IBR sin romper el CTA ni missing_items", async () => {
    const processKey = "payment-validation|banco_bancolombia|2026-08-01|amort-ibr";
    mocks.fetchBootstrap.mockResolvedValue(bootstrap);
    mocks.fetchProcess.mockResolvedValue(
      baseDetail({
        process_key: processKey,
        bank_code: "banco_bancolombia",
        bank_name: "Bancolombia",
        environment: "sandbox",
        operational_status: "LISTO_PARA_APLICAR",
        control_estado_proceso: "CONSOLIDADO",
        steps: [
          { name: "generate", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "review", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "finalize", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "notify", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "merge", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "dry_run", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "apply", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
        ],
        available_actions: {
          finalize: { allowed: false, reason: null },
          notify: { allowed: false, reason: null },
          merge: { allowed: false, reason: null },
          amortization: { allowed: true, reason: null },
        },
        amortization_readiness: {
          status: "incomplete",
          can_start: false,
          expected_items: 2,
          ready_items: 1,
          missing_items: [
            {
              credito: "215",
              id_pago: "pago-1",
              error_code: "asiento_contable_not_found",
            },
          ],
          warnings: [],
          checked_at: "2026-08-03T12:00:00-05:00",
          user_message: "Faltan asientos contables o el manifiesto de consolidación está incompleto.",
          next_action: "Complete la consolidación de asientos contables antes de procesar la amortización.",
        },
        links: [
          {
            rel: "ibr",
            label: "Actualizar IBR",
            path: null,
            web_url: "https://example.com/IBR_DIARIO.xlsx",
            open_mode: "sharepoint",
          },
        ],
      }),
    );

    renderDetail(processKey);
    await screen.findByText("Bancolombia");
    expect(screen.getByRole("heading", { level: 2, name: "Procesar amortización" })).toBeInTheDocument();
    const ibrLink = screen.getByRole("link", { name: "Actualizar IBR" });
    expect(ibrLink).toHaveAttribute("href", "https://example.com/IBR_DIARIO.xlsx");
    expect(ibrLink).toHaveClass("btn", "secondary");
    expect(screen.getByText(/Crédito 215/i)).toBeInTheDocument();
    expect(screen.getByText(/Ítems listos: 1 de 2/i)).toBeInTheDocument();
    expect(
      document.querySelector(".amort-readiness-panel .merge-groups-progress.is-pending"),
    ).toBeTruthy();
    expect(await screen.findByText(/IBR de referencia/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Actualizar lectura IBR/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Procesar amortización$/i })).toBeInTheDocument();
    expect(document.getElementById("process-documents")).toBeNull();
  });

  it("en Procesar amortización no muestra Actualizar IBR sin web_url", async () => {
    const processKey = "payment-validation|banco_bancolombia|2026-08-01|amort-no-ibr";
    mocks.fetchBootstrap.mockResolvedValue(bootstrap);
    mocks.fetchProcess.mockResolvedValue(
      baseDetail({
        process_key: processKey,
        bank_code: "banco_bancolombia",
        bank_name: "Bancolombia",
        environment: "sandbox",
        operational_status: "LISTO_PARA_APLICAR",
        control_estado_proceso: "CONSOLIDADO",
        steps: [
          { name: "generate", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "review", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "finalize", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "notify", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "merge", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "dry_run", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
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
          checked_at: "2026-08-03T12:00:00-05:00",
          user_message: "La información está disponible para iniciar la validación y aplicación.",
          next_action: "Puede procesar la amortización desde la UI.",
        },
        links: [],
      }),
    );

    renderDetail(processKey);
    await screen.findByText("Bancolombia");
    expect(screen.getByRole("heading", { level: 2, name: "Procesar amortización" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Actualizar IBR" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Procesar amortización$/i })).toBeInTheDocument();
  });

  it("agrupa varios PDFs consolidados en Documentos por fase al consultar Merge", async () => {
    const processKey = "payment-validation|banco_bancolombia|2026-08-01|multi-pdf";
    mocks.fetchBootstrap.mockResolvedValue(bootstrap);
    mocks.fetchProcess.mockResolvedValue(
      baseDetail({
        process_key: processKey,
        bank_code: "banco_bancolombia",
        bank_name: "Bancolombia",
        operational_status: "LISTO_PARA_APLICAR",
        control_estado_proceso: "CONSOLIDADO",
        steps: [
          { name: "generate", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "review", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "finalize", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "notify", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "merge", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "dry_run", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "apply", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
        ],
        links: [
          {
            rel: "merge_pdf:0",
            label: "Abrir PDF consolidado · Crédito 265",
            path: "merge/a.pdf",
            web_url: "https://example.com/a.pdf",
            open_mode: "sharepoint",
          },
          {
            rel: "merge_pdf:1",
            label: "Abrir PDF consolidado · Crédito 310",
            path: "merge/b.pdf",
            web_url: "https://example.com/b.pdf",
            open_mode: "sharepoint",
          },
        ],
        document_groups: [
          {
            id: "merge_pdfs",
            title: "PDFs consolidados",
            count: 2,
            links: [
              {
                rel: "merge_pdf:0",
                label: "Abrir PDF consolidado · Crédito 265",
                path: "merge/a.pdf",
                web_url: "https://example.com/a.pdf",
                open_mode: "sharepoint",
              },
              {
                rel: "merge_pdf:1",
                label: "Abrir PDF consolidado · Crédito 310",
                path: "merge/b.pdf",
                web_url: "https://example.com/b.pdf",
                open_mode: "sharepoint",
              },
            ],
          },
        ],
      }),
    );

    renderDetail(processKey);
    await screen.findByText("Bancolombia");
    // Fase viva amortización: sin Documentos por fase ni Archivos (proceso aún vivo).
    expect(screen.queryByText("Recursos por fase")).not.toBeInTheDocument();
    expect(screen.queryByText("Archivos del proceso")).not.toBeInTheDocument();

    await userEvent.setup().click(
      screen.getByRole("button", { name: /Ir a Generar PDF consolidado/i }),
    );
    expect(screen.getByText("Recursos por fase")).toBeInTheDocument();
    expect(screen.queryByText("Archivos del proceso")).not.toBeInTheDocument();
    const openCatalog = screen.getAllByRole("button", { name: /PDFs consolidados \(2\)/i })[0];
    expect(openCatalog).toBeInTheDocument();
    openCatalog.click();
    const openLinks = await screen.findAllByRole("link", { name: "Abrir" });
    expect(openLinks).toHaveLength(2);
    expect(openLinks[0]).toHaveAttribute("href", "https://example.com/a.pdf");
    expect(openLinks[1]).toHaveAttribute("href", "https://example.com/b.pdf");
    expect(screen.getByText(/Crédito 265/i)).toBeInTheDocument();
    expect(screen.getByText(/Crédito 310/i)).toBeInTheDocument();
    expect(screen.queryByText(/\(no disponible\)/i)).not.toBeInTheDocument();
  });

  it("en COMPLETADO muestra Archivos solo en amortización y Documentos en fases anteriores", async () => {
    const processKey = "payment-validation|banco_bogota|2026-08-01|done-files";
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
            rel: "email_pdf",
            label: "Ver correo enviado",
            path: "correo/x.pdf",
            web_url: "https://example.com/correo.pdf",
            open_mode: "sharepoint",
          },
          {
            rel: "merge_pdf",
            label: "Abrir PDF consolidado",
            path: "merge/m.pdf",
            web_url: "https://example.com/m.pdf",
            open_mode: "sharepoint",
          },
        ],
        document_groups: [
          {
            id: "amortization_tables",
            title: "Tablas de amortización",
            count: 1,
            links: [
              {
                rel: "amort_table:0",
                label: "Tabla cliente A",
                path: "clientes/a.xlsx",
                web_url: "https://example.com/a.xlsx",
                open_mode: "sharepoint",
              },
            ],
          },
          {
            id: "merge_pdfs",
            title: "PDFs consolidados",
            count: 1,
            links: [
              {
                rel: "merge_pdf",
                label: "Abrir PDF consolidado",
                path: "merge/m.pdf",
                web_url: "https://example.com/m.pdf",
                open_mode: "sharepoint",
              },
            ],
          },
        ],
      }),
    );

    renderDetail(processKey);
    await screen.findByText("Banco de Bogotá");
    expect(screen.queryByText("Recursos por fase")).not.toBeInTheDocument();
    expect(screen.getByText("Archivos del proceso")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Tabla cliente A/i })).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /Abrir PDF consolidado/i }),
    ).toBeInTheDocument();
    // P8: correo / artefactos del lote también en Archivos (no solo Documentos por fase).
    expect(screen.getByRole("link", { name: /Ver correo enviado/i })).toBeInTheDocument();

    await userEvent.setup().click(screen.getByRole("button", { name: /Ir a Enviar correo/i }));
    expect(screen.getByText("Recursos por fase")).toBeInTheDocument();
    expect(screen.queryByText("Archivos del proceso")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Ver correo enviado/i })).toBeInTheDocument();
  });

  it("en fase Merge muestra carpetas ASIENTOS solo en Documentos por fase", async () => {
    const processKey = "payment-validation|banco_bancolombia|2026-08-01|folder-missing";
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
        merge_readiness: {
          status: "incomplete",
          expected_groups: 1,
          ready_groups: 0,
          missing_groups: 1,
          missing_items: [
            {
              credito: "265",
              document_type: "ASIENTO_CONTABLE",
              error_code: "asiento_contable_not_found",
              id_pago: "P1",
            },
          ],
          folder_links: [
            {
              rel: "asientos",
              label: "Carpeta ASIENTOS",
              path: "clientes/265/ASIENTOS",
              web_url: "https://example.com/asientos",
              credito: "265",
            },
          ],
          user_message: "Aún faltan documentos contables.",
          next_action: "Cargue el asiento y actualice.",
          checked_at: null,
        },
        links: [],
      }),
    );

    renderDetail(processKey);
    await screen.findByText("Bancolombia");
    expect(screen.getByRole("heading", { level: 2, name: "Generar PDF consolidado" })).toBeInTheDocument();
    // Documentos por fase → drawer (estado + refresh al abrir); no botón 1:1 inline.
    const docsSection = document.getElementById("process-documents");
    expect(docsSection?.textContent).toMatch(/ASIENTOS/i);
    expect(docsSection?.querySelector('a[href="https://example.com/asientos"]')).toBeNull();
    // Indicador listos/pendientes en el panel (chip); sin lista inline de faltantes.
    expect(screen.getByText(/Grupos listos: 0 de 1 · 1 pendientes/i)).toBeInTheDocument();
    expect(document.querySelector(".merge-readiness-panel .merge-missing-list")).toBeNull();
    expect(
      document.querySelector(".merge-readiness-panel .merge-groups-progress.is-pending"),
    ).toBeTruthy();
    // Primera entrada: sin banner de problemas (aún no verificó).
    expect(document.getElementById("merge-support-errors-banner-title")).toBeNull();
    const openAsientos = screen.getByRole("button", { name: /Ver carpeta ASIENTOS/i });
    expect(openAsientos).toBeInTheDocument();
    const callsBeforeOpen = mocks.fetchProcess.mock.calls.length;
    openAsientos.click();
    expect(await screen.findByRole("heading", { name: /Carpetas ASIENTOS \(1\)/i })).toBeInTheDocument();
    // Mismo indicador dentro del drawer ASIENTOS.
    expect(screen.getAllByText(/Grupos listos: 0 de 1 · 1 pendientes/i).length).toBeGreaterThanOrEqual(2);
    // Abrir carpetas verifica → ya muestra faltante.
    expect(document.querySelector(".link-catalog-status.is-missing")).toHaveTextContent(/Falta documento/i);
    expect(screen.getByRole("link", { name: "Abrir" })).toHaveAttribute(
      "href",
      "https://example.com/asientos",
    );
    // Refresh GET al abrir (no solo el toolbar Actualizar).
    expect(mocks.fetchProcess.mock.calls.length).toBeGreaterThan(callsBeforeOpen);
    expect(screen.getByText(/Aún faltan documentos contables/i)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Actualizar \/ verificar asientos contables/i }),
    ).toBeInTheDocument();
  });

  it("muestra faltantes solo tras verificar asientos contables (banner inline en fase)", async () => {
    const processKey = "payment-validation|banco_bancolombia|2026-08-01|merge-missing-detail";
    const incomplete = baseDetail({
      process_key: processKey,
      bank_code: "banco_bancolombia",
      bank_name: "Bancolombia",
      operational_status: "ESPERANDO_SOPORTES",
      operational_message: "Esperando documentos contables.",
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
      available_actions: {
        finalize: { allowed: false, reason: null },
        notify: { allowed: false, reason: null },
        merge: { allowed: false, reason: "Faltan asientos contables." },
        amortization: { allowed: false, reason: null },
      },
      merge_readiness: {
        status: "incomplete",
        expected_groups: 2,
        ready_groups: 0,
        missing_groups: 2,
        missing_items: [
          {
            credito: "100",
            document_type: "ASIENTO_CONTABLE",
            error_code: "asiento_contable_not_found",
            id_pago: "P1",
          },
          {
            credito: "200",
            document_type: "ASIENTO_CONTABLE",
            error_code: "asiento_contable_credit_mismatch",
            id_pago: "P2",
          },
        ],
        folder_links: [
          {
            rel: "asientos",
            label: "Carpeta ASIENTOS",
            path: "clientes/100/ASIENTOS",
            web_url: "https://example.com/asientos/100",
            credito: "100",
          },
          {
            rel: "asientos",
            label: "Carpeta ASIENTOS",
            path: "clientes/200/ASIENTOS",
            web_url: "https://example.com/asientos/200",
            credito: "200",
          },
        ],
        user_message: "Faltan asientos contables o hay nombres de PDF que no coinciden con el crédito.",
        next_action: "Cargue o corrija los archivos pendientes y verifique los asientos contables.",
        checked_at: null,
      },
      links: [],
    });
    const ready = {
      ...incomplete,
      operational_status: "ESPERANDO_SOPORTES" as const,
      operational_message: "Soportes listos.",
      available_actions: {
        ...incomplete.available_actions!,
        merge: { allowed: true, reason: null },
      },
      merge_readiness: {
        status: "ready" as const,
        expected_groups: 2,
        ready_groups: 2,
        missing_groups: 0,
        missing_items: [],
        folder_links: incomplete.merge_readiness!.folder_links,
        user_message: "Los asientos contables están listos para consolidar.",
        next_action: "Puede generar el PDF consolidado desde la UI.",
        checked_at: null,
      },
      steps: incomplete.steps.map((s) =>
        s.name === "merge"
          ? { ...s, status: "not_started" as const }
          : s,
      ),
    };

    mocks.fetchBootstrap.mockResolvedValue(bootstrap);
    // Carga inicial + GET al abrir drawer ASIENTOS → incomplete; verify → ready.
    mocks.fetchProcess
      .mockResolvedValueOnce(incomplete)
      .mockResolvedValueOnce(incomplete)
      .mockResolvedValue(ready);

    renderDetail(processKey);
    await screen.findByRole("heading", { level: 2, name: "Generar PDF consolidado" });

    // Panel: chip pendiente + verificar; sin lista inline ni links «Abrir carpeta ASIENTOS · N».
    expect(screen.getByText(/Grupos listos: 0 de 2 · 2 pendientes/i)).toBeInTheDocument();
    expect(
      document.querySelector(".merge-readiness-panel .merge-groups-progress.is-pending"),
    ).toBeTruthy();
    expect(document.querySelector(".merge-readiness-panel .merge-missing-list")).toBeNull();
    expect(
      screen.queryByRole("link", { name: /Abrir carpeta ASIENTOS · 100/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: /Abrir carpeta ASIENTOS · 200/i }),
    ).not.toBeInTheDocument();
    // No triplicar el reason genérico del CTA debajo del panel detallado.
    const phasePanel = document.querySelector(".current-phase-panel");
    const faltanMatches = phasePanel?.textContent?.match(/Faltan asientos contables\./g) ?? [];
    expect(faltanMatches.length).toBeLessThanOrEqual(1);

    // Primera entrada tras Notify: sin alerta de problemas (aún no verificó).
    expect(document.getElementById("merge-support-errors-banner-title")).toBeNull();
    expect(
      screen.queryByRole("button", { name: /Ver problemas de asientos contables/i }),
    ).not.toBeInTheDocument();

    // Drawer pre-verificar vía botón de fase: aún «Sin verificar» hasta el GET de apertura.
    // Abrir carpetas fuerza GET → marca verificado y muestra faltantes por fila.
    await userEvent.setup().click(
      screen.getByRole("button", { name: /Ver carpetas ASIENTOS \(2\)/i }),
    );
    expect(
      await screen.findByRole("heading", { name: /Carpetas ASIENTOS \(2\)/i }),
    ).toBeInTheDocument();
    expect(screen.getAllByText(/Grupos listos: 0 de 2 · 2 pendientes/i).length).toBeGreaterThanOrEqual(2);
    expect(document.querySelector(".merge-groups-progress.is-pending")).toBeTruthy();
    expect(screen.getByText(/Falta el PDF del asiento contable/i)).toBeInTheDocument();
    expect(screen.getByText(/nombre no coincide/i)).toBeInTheDocument();
    expect(document.querySelectorAll(".link-catalog-status.is-missing").length).toBe(2);
    const openLinks = screen.getAllByRole("link", { name: "Abrir" });
    expect(openLinks).toHaveLength(2);
    expect(openLinks.map((a) => a.getAttribute("href"))).toEqual(
      expect.arrayContaining([
        "https://example.com/asientos/100",
        "https://example.com/asientos/200",
      ]),
    );
    await userEvent.setup().click(screen.getByRole("button", { name: /^Cerrar$/i }));

    // Tras abrir (verificar), el banner vive DENTRO del panel de fase (mismo patrón Errores).
    const supportBanner = document.getElementById("merge-support-errors-banner-title");
    expect(supportBanner).toBeTruthy();
    expect(phasePanel?.contains(supportBanner)).toBe(true);
    expect(supportBanner?.textContent).toMatch(/2 problema\(s\) con los documentos contables/i);
    await userEvent.setup().click(
      screen.getByRole("button", { name: /Ver problemas de asientos contables/i }),
    );
    expect(
      await screen.findByRole("heading", { name: /Problemas de asientos contables \(2\)/i }),
    ).toBeInTheDocument();
    expect(screen.getByText(/Falta el PDF del asiento contable/i)).toBeInTheDocument();
    expect(screen.getByText(/nombre no coincide/i)).toBeInTheDocument();
    const modalOpenLinks = screen.getAllByRole("link", { name: /Abrir carpeta ASIENTOS/i });
    expect(modalOpenLinks).toHaveLength(2);
    expect(modalOpenLinks.map((a) => a.getAttribute("href"))).toEqual(
      expect.arrayContaining([
        "https://example.com/asientos/100",
        "https://example.com/asientos/200",
      ]),
    );
    await userEvent.setup().click(screen.getByRole("button", { name: /^Cerrar$/i }));

    const verifyBtn = screen.getByRole("button", {
      name: /Actualizar \/ verificar asientos contables/i,
    });
    const callsBefore = mocks.fetchProcess.mock.calls.length;
    await userEvent.setup().click(verifyBtn);
    expect(mocks.fetchProcess.mock.calls.length).toBeGreaterThan(callsBefore);

    expect(
      await screen.findByRole("button", { name: /^Generar PDF consolidado$/i }),
    ).toBeEnabled();
    expect(screen.getByText("Listo para consolidar")).toBeInTheDocument();
    const listoPill = screen.getByText("Listo para consolidar");
    expect(listoPill.className).toMatch(/\bok\b/);
    expect(listoPill.className).not.toMatch(/\bwarn\b/);
    expect(screen.getByText(/Los asientos contables están listos para consolidar/i)).toBeInTheDocument();
    expect(screen.getByText(/Grupos listos: 2 de 2/i)).toBeInTheDocument();
    expect(document.querySelector(".merge-groups-progress.is-complete")).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: /Actualizar \/ verificar asientos contables/i }),
    ).not.toBeInTheDocument();
    // Happy path: sin banner de errores de asientos contables cuando ready.
    expect(document.getElementById("merge-support-errors-banner-title")).toBeNull();
    expect(
      screen.queryByRole("button", { name: /Ver problemas de asientos contables/i }),
    ).not.toBeInTheDocument();
  });

  it("en readiness unknown muestra mensaje corto y verificar sin listado largo", async () => {
    const processKey = "payment-validation|banco_bancolombia|2026-08-01|merge-unknown";
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
        available_actions: {
          finalize: { allowed: false, reason: null },
          notify: { allowed: false, reason: null },
          merge: {
            allowed: false,
            reason: "No se pudo verificar si los asientos contables están completos. Actualice e intente nuevamente.",
          },
          amortization: { allowed: false, reason: null },
        },
        merge_readiness: {
          status: "unknown",
          expected_groups: 1,
          ready_groups: 0,
          missing_groups: 1,
          missing_items: [],
          folder_links: [],
          user_message:
            "No se pudo verificar si los asientos contables están completos. Actualice e intente nuevamente.",
          next_action: "Actualice el detalle del proceso e intente nuevamente.",
          checked_at: null,
        },
        links: [],
      }),
    );

    renderDetail(processKey);
    await screen.findByRole("heading", { level: 2, name: "Generar PDF consolidado" });
    expect(screen.getByText(/No se pudo verificar si los asientos contables están completos/i)).toBeInTheDocument();
    expect(document.querySelector(".merge-missing-list")).toBeNull();
    // Sin missing_items → no banner de errores de asientos contables.
    expect(document.getElementById("merge-support-errors-banner-title")).toBeNull();
    expect(
      screen.getByRole("button", { name: /Actualizar \/ verificar asientos contables/i }),
    ).toBeInTheDocument();
  });

  it("en COMPLETADO mantiene el refresh fijo, oculta la tarjeta de amortización y muestra cierre", async () => {
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
            rel: "merge_pdf",
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
    const refresh = screen.getByRole("button", { name: "Actualizar estado" });
    expect(refresh).toBeInTheDocument();
    expect(refresh.closest(".process-detail-toolbar")).toBeTruthy();
    expect(refresh.closest(".status-summary-card")).toBeNull();
    expect(screen.queryByRole("button", { name: "Actualizar documentos" })).not.toBeInTheDocument();
    expect(document.querySelector(".current-phase-panel")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /^Procesar amortización$/i }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Proceso completado" })).toBeInTheDocument();
    expect(screen.getByText(/Ya no hay acciones pendientes/i)).toBeInTheDocument();
    expect(screen.getByText(/Proceso completo/i)).toBeInTheDocument();
  });

  it("en revisión sana ofrece Regenerar opcional sin forzar corrección", async () => {
    const processKey = "payment-validation|banco_bogota|2026-08-02|ok-rev";
    mocks.fetchBootstrap.mockResolvedValue(bootstrap);
    mocks.fetchProcess.mockResolvedValue(
      baseDetail({
        process_key: processKey,
        process_date: "2026-08-02",
        operational_status: "EN_REVISION",
        operational_title: "En revisión",
        control_estado_proceso: "REVISION_CREADA",
        available_actions: {
          finalize: { allowed: true, reason: null },
          notify: { allowed: false, reason: null },
          merge: { allowed: false, reason: null },
          amortization: { allowed: false, reason: null },
          regenerate: { allowed: true, reason: null },
        },
        operational_issues: [],
      }),
    );

    renderDetail(processKey);
    await screen.findByText("Banco de Bogotá");
    expect(screen.queryByRole("heading", { name: "Casos en la hoja Errores" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Falta el archivo de revisión" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Regenerar archivo de revisión/i })).toBeInTheDocument();
  });

  it("con Excel de revisión ausente ofrece Regenerar en la fase actual", async () => {
    const processKey = "payment-validation|banco_bogota|2026-08-02|missing";
    mocks.fetchBootstrap.mockResolvedValue(bootstrap);
    mocks.fetchProcess.mockResolvedValue(
      baseDetail({
        process_key: processKey,
        process_date: "2026-08-02",
        operational_status: "CORRECCION_REQUERIDA",
        operational_title: "Requiere corrección",
        operational_message: "El archivo de revisión ya no está en SharePoint.",
        control_estado_proceso: "REVISION_CREADA",
        available_actions: {
          finalize: { allowed: false, reason: "Falta el archivo" },
          notify: { allowed: false, reason: null },
          merge: { allowed: false, reason: null },
          amortization: { allowed: false, reason: null },
          regenerate: { allowed: true, reason: null },
        },
        steps: [
          {
            name: "generate",
            status: "failed_business",
            updated_at: null,
            summary: "Control indica revisión pero el archivo no existe.",
            can_retry: true,
            retry_action: "retry_generate",
          },
          { name: "review", status: "blocked", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "finalize", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "notify", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "merge", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "dry_run", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "apply", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
        ],
        operational_issues: [
          {
            issue_id: "review-file-missing",
            stage: "generate",
            category: "correction_required",
            severity: "business",
            recoverable: true,
            title: "Falta el archivo de revisión",
            user_message: "El Excel de revisión no está disponible en SharePoint.",
            location: null,
            value_found: null,
            expected_values: [],
            next_action: "Regenere el archivo.",
            retry: {
              allowed: true,
              action: "regenerate",
              label: "Regenerar archivo de revisión",
            },
            links: [],
            technical_reference: "review_file_missing",
          },
        ],
        links: [
          {
            rel: "review_excel",
            label: "Abrir archivo de revisión",
            path: "revision/x.xlsx",
            web_url: null,
            open_mode: "sharepoint",
          },
        ],
      }),
    );

    renderDetail(processKey);
    await screen.findByText("Banco de Bogotá");
    expect(screen.getByRole("heading", { name: "Falta el archivo de revisión" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Casos en la hoja Errores" })).not.toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /Regenerar archivo de revisión/i })).toHaveLength(1);
    expect(screen.getByText(/Use el botón Regenerar de la fase actual/i)).toBeInTheDocument();
    expect(screen.getByText(/Fase 1 de 4 · Revisión de archivo/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Enviar correo \(bloqueada\)/i })).toBeDisabled();
    const phase = document.querySelector(".current-phase-panel");
    const status = document.querySelector(".status-summary-card");
    expect(phase).toBeTruthy();
    expect(status).toBeTruthy();
    // Tarjeta de estado va justo tras el stepper, antes del CTA de fase.
    expect(
      status!.compareDocumentPosition(phase!) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("con hoja Errores muestra un solo Regenerar en el CTA de fase", async () => {
    const processKey = "payment-validation|banco_bogota|2026-08-02|err";
    mocks.fetchBootstrap.mockResolvedValue(bootstrap);
    mocks.fetchProcess.mockResolvedValue(
      baseDetail({
        process_key: processKey,
        process_date: "2026-08-02",
        operational_status: "CORRECCION_REQUERIDA",
        operational_title: "Requiere corrección",
        control_estado_proceso: "REVISION_CREADA",
        available_actions: {
          finalize: { allowed: false, reason: "Hay casos en Errores" },
          notify: { allowed: false, reason: null },
          merge: { allowed: false, reason: null },
          amortization: { allowed: false, reason: null },
          regenerate: { allowed: true, reason: null },
        },
        operational_issues: [
          {
            issue_id: "review-errores-1",
            stage: "generate",
            category: "correction_required",
            severity: "business",
            recoverable: true,
            title: "Caso en Errores",
            user_message: "Falta carpeta de crédito.",
            location: {
              sheet: "Errores",
              file_name: null,
              row: 2,
              column: null,
              credit: "37",
              payment_id: null,
              client_name: null,
            },
            value_found: null,
            expected_values: [],
            next_action: "Corrija y regenere.",
            retry: {
              allowed: true,
              action: "regenerate",
              label: "Regenerar archivo de revisión",
            },
            links: [],
            technical_reference: null,
          },
        ],
      }),
    );

    renderDetail(processKey);
    await screen.findByText("Banco de Bogotá");
    const phasePanel = document.querySelector(".current-phase-panel");
    expect(phasePanel).toBeTruthy();
    const alertStrip = phasePanel!.querySelector(".phase-operational-alert");
    expect(alertStrip).toBeTruthy();
    expect(within(alertStrip as HTMLElement).getByText(/1 caso\(s\) en la hoja Errores/i)).toBeInTheDocument();
    expect(
      within(alertStrip as HTMLElement).queryByText(/Corrija y regenere antes de completar/i),
    ).not.toBeInTheDocument();
    expect(
      within(alertStrip as HTMLElement).queryByRole("link", {
        name: /Abrir archivo de revisión/i,
      }),
    ).not.toBeInTheDocument();
    const openIssues = within(alertStrip as HTMLElement).getByRole("button", {
      name: /Ver problemas operativos/i,
    });
    expect(openIssues).toHaveClass("btn", "secondary");
    expect(screen.queryByRole("heading", { name: "Problemas operativos" })).not.toBeInTheDocument();
    expect(document.getElementById("operational-issues")).toBeNull();
    expect(document.querySelector(".review-errores-banner.panel")).toBeNull();

    const user = userEvent.setup();
    // Cerrar intro automático de Errores para poder abrir el modal de detalle.
    const entendido = await screen.findByRole("button", { name: "Entendido" });
    await user.click(entendido);
    await user.click(openIssues);
    expect(
      await screen.findByRole("heading", { name: /Problemas operativos \(1\)/i }),
    ).toBeInTheDocument();
    expect(screen.getByText("Falta carpeta de crédito.")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Casos en la hoja Errores" })).not.toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /Regenerar archivo de revisión/i })).toHaveLength(1);
    expect(screen.queryByRole("button", { name: "Finalizar revisión" })).not.toBeInTheDocument();
    // Stepper: fase viva = Revisión; Enviar correo+ bloqueadas.
    expect(screen.getByText(/Fase 1 de 4 · Revisión de archivo/i)).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "Revisión de archivo" })).toBeInTheDocument();
    const lockedNotify = screen.getByRole("button", {
      name: /Enviar correo \(bloqueada\)/i,
    });
    expect(lockedNotify).toBeDisabled();
    expect(lockedNotify).toHaveAttribute(
      "title",
      "Corrija los casos en Errores y regenere antes de continuar",
    );
    expect(screen.queryByRole("button", { name: /Ir a Enviar correo/i })).not.toBeInTheDocument();
  });

  it("con Errores ignora ?phase=notify y mantiene Revisión de archivo", async () => {
    const processKey = "payment-validation|banco_bogota|2026-08-02|err-phase";
    mocks.fetchBootstrap.mockResolvedValue(bootstrap);
    mocks.fetchProcess.mockResolvedValue(
      baseDetail({
        process_key: processKey,
        process_date: "2026-08-02",
        operational_status: "CORRECCION_REQUERIDA",
        operational_title: "Requiere corrección",
        control_estado_proceso: "REVISION_CREADA",
        available_actions: {
          finalize: { allowed: false, reason: "Hay casos en Errores" },
          notify: { allowed: false, reason: null },
          merge: { allowed: false, reason: null },
          amortization: { allowed: false, reason: null },
          regenerate: { allowed: true, reason: null },
        },
        operational_issues: [
          {
            issue_id: "review-errores-1",
            stage: "generate",
            category: "correction_required",
            severity: "business",
            recoverable: true,
            title: "Caso en Errores",
            user_message: "Falta carpeta de crédito.",
            location: {
              sheet: "Errores",
              file_name: null,
              row: 2,
              column: null,
              credit: "37",
              payment_id: null,
              client_name: null,
            },
            value_found: null,
            expected_values: [],
            next_action: "Corrija y regenere.",
            retry: {
              allowed: true,
              action: "regenerate",
              label: "Regenerar archivo de revisión",
            },
            links: [],
            technical_reference: null,
          },
        ],
      }),
    );

    renderDetail(processKey, "?phase=notify");
    await screen.findByText("Banco de Bogotá");
    expect(screen.getByText(/Fase 1 de 4 · Revisión de archivo/i)).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "Revisión de archivo" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { level: 2, name: "Enviar correo" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Enviar correo \(bloqueada\)/i })).toBeDisabled();
  });

  it("sin Errores muestra Revisión de archivo con CTA Finalizar (happy path)", async () => {
    const processKey = "payment-validation|banco_bogota|2026-07-31|abc-1";
    mocks.fetchBootstrap.mockResolvedValue(bootstrap);
    mocks.fetchProcess.mockResolvedValue(baseDetail({ process_key: processKey }));

    renderDetail(processKey);
    await screen.findByText("Banco de Bogotá");

    expect(screen.getByText(/Fase 1 de 4 · Revisión de archivo/i)).toBeInTheDocument();
    const goReview = screen.getByRole("button", { name: /Ir a Revisión de archivo/i });
    expect(goReview).toBeEnabled();
    expect(screen.getByRole("button", { name: "Finalizar revisión" })).toBeInTheDocument();
  });

  it("permite ver una fase completada sin re-disparar su acción y filtra documentos", async () => {
    const processKey = "payment-validation|banco_bogota|2026-08-02|nav";
    mocks.fetchBootstrap.mockResolvedValue(bootstrap);
    mocks.fetchProcess.mockResolvedValue(
      baseDetail({
        process_key: processKey,
        process_date: "2026-08-02",
        operational_status: "ESPERANDO_SOPORTES",
        operational_title: "Esperando documentos",
        control_estado_proceso: "PENDIENTE_ASIENTOS",
        available_actions: {
          finalize: { allowed: false, reason: "Ya finalizado" },
          notify: { allowed: false, reason: "Ya fue enviado" },
          merge: { allowed: true, reason: null },
          amortization: { allowed: false, reason: null },
        },
        steps: [
          { name: "generate", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "review", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "finalize", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "notify", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "merge", status: "blocked", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "dry_run", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "apply", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
        ],
        links: [
          {
            rel: "review_excel",
            label: "Abrir archivo de revisión",
            path: "revision/x.xlsx",
            web_url: "https://example.com/x.xlsx",
            open_mode: "sharepoint",
          },
          {
            rel: "email_pdf",
            label: "Ver correo enviado",
            path: "email/e.pdf",
            web_url: "https://example.com/e.pdf",
            open_mode: "sharepoint",
          },
          {
            rel: "historical",
            label: "Abrir histórico",
            path: "hist/h.xlsx",
            web_url: "https://example.com/h.xlsx",
            open_mode: "sharepoint",
          },
        ],
        idempotency: {
          notify_idempotency_key: "n1",
          merge_idempotency_key: null,
          apply_idempotency_key: null,
        },
      }),
    );

    renderDetail(processKey);
    await screen.findByText("Banco de Bogotá");
    expect(document.querySelector(".process-phase-header")).toBeTruthy();
    expect(
      screen.getByRole("button", { name: /^Generar PDF consolidado$/i }),
    ).toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /Ir a Enviar correo \(completada\)/i }));

    expect(screen.getByRole("heading", { level: 2, name: "Enviar correo" })).toBeInTheDocument();
    expect(screen.getByText(/Esta fase ya está completa/i)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /^Enviar correo$/i }),
    ).not.toBeInTheDocument();

    const docsPanel = document.getElementById("process-documents");
    expect(docsPanel).toBeTruthy();
    expect(
      within(docsPanel!).getByRole("link", { name: /Ver correo enviado/i }),
    ).toBeInTheDocument();
    expect(
      within(docsPanel!).queryByRole("link", { name: /Abrir archivo de revisión/i }),
    ).not.toBeInTheDocument();
    expect(
      within(docsPanel!).queryByRole("link", { name: /Abrir histórico/i }),
    ).not.toBeInTheDocument();
  });

  it("con job en curso muestra Spinner en la tarjeta de estado (P3)", async () => {
    const processKey = "payment-validation|banco_bogota|2026-08-03|job-run";
    mocks.fetchBootstrap.mockResolvedValue(bootstrap);
    mocks.fetchProcess.mockResolvedValue(
      baseDetail({
        process_key: processKey,
        operational_status: "FINALIZANDO",
        operational_title: "Cerrando la revisión",
        control_estado_proceso: "FINALIZANDO",
        active_job: {
          job_id: "job-finalize-1",
          type: "finalize",
          status: "running",
          store: "job_manager",
          poll_path_graph: null,
          poll_path_ui: "/api/ui/v1/jobs/job-finalize-1",
          started_at: "2026-08-03T10:00:00-05:00",
          progress: null,
        },
        available_actions: {
          finalize: { allowed: false, reason: "Hay una operación en curso." },
          notify: { allowed: false, reason: null },
          merge: { allowed: false, reason: null },
          amortization: { allowed: false, reason: null },
        },
      }),
    );
    mocks.fetchJob.mockResolvedValue({
      job_id: "job-finalize-1",
      type: "finalize",
      status: "running",
      store: "job_manager",
      process_key: processKey,
      bank_code: "banco_bogota",
      environment: "sandbox",
      created_at: "2026-08-03T10:00:00-05:00",
      started_at: "2026-08-03T10:00:00-05:00",
      finished_at: null,
      result_summary: null,
      error: null,
      progress: null,
      raw_available: false,
    });

    renderDetail(processKey);
    await screen.findByText("Banco de Bogotá");

    const statusCard = document.querySelector(".status-summary-card");
    expect(statusCard).toBeTruthy();
    const processing = statusCard!.querySelector(".status-summary-processing");
    expect(processing).toBeTruthy();
    expect(processing!.querySelector(".spinner")).toBeTruthy();
    expect(processing!.textContent).toMatch(/Verificando revisión/);
  });

  it("tras Notify OK muestra el link al PDF del correo en el modal de éxito", async () => {
    const processKey = "payment-validation|banco_bancolombia|2026-08-01|notify-ok";
    const initial = baseDetail({
      process_key: processKey,
      bank_code: "banco_bancolombia",
      bank_name: "Bancolombia",
      operational_status: "LISTO_PARA_NOTIFICAR",
      control_estado_proceso: "FINALIZADO",
      steps: [
        { name: "generate", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
        { name: "review", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
        { name: "finalize", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
        { name: "notify", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
        { name: "merge", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
        { name: "dry_run", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
        { name: "apply", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
      ],
      available_actions: {
        finalize: { allowed: false, reason: null },
        notify: { allowed: true, reason: null },
        merge: { allowed: false, reason: null },
        amortization: { allowed: false, reason: null },
      },
    });
    const afterNotify = baseDetail({
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
        { name: "merge", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
        { name: "dry_run", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
        { name: "apply", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
      ],
      available_actions: {
        finalize: { allowed: false, reason: null },
        notify: { allowed: false, reason: null },
        merge: { allowed: false, reason: null },
        amortization: { allowed: false, reason: null },
      },
      files: {
        validation_file_path: null,
        historical_file_path: null,
        secretary_file_path: null,
        email_pdf_path: "correo/ABONOS.pdf",
        merge_manifest_path: null,
        control_file_path: null,
        execution_log_path: null,
      },
      links: [
        {
          rel: "email_pdf",
          label: "Ver correo enviado",
          path: "correo/ABONOS.pdf",
          web_url: "https://example.com/correo.pdf",
          open_mode: "sharepoint",
        },
      ],
    });

    mocks.fetchBootstrap.mockResolvedValue(bootstrap);
    mocks.fetchProcess.mockResolvedValueOnce(initial).mockResolvedValue(afterNotify);
    mocks.postNotify.mockResolvedValue({
      accepted: true,
      action: "notify",
      bank_code: "banco_bancolombia",
      process_key: processKey,
      job_id: "job-notify-1",
      status: "queued",
      poll_url: "/api/ui/v1/jobs/job-notify-1",
    });
    mocks.fetchJob.mockResolvedValue({
      job_id: "job-notify-1",
      type: "notify_validar_extractos",
      status: "completed",
      store: "job_manager",
      process_key: processKey,
      bank_code: "banco_bancolombia",
      environment: "sandbox",
      created_at: "2026-08-01T10:00:00-05:00",
      started_at: "2026-08-01T10:00:00-05:00",
      finished_at: "2026-08-01T10:00:05-05:00",
      result_summary: {
        email_pdf_path: "correo/ABONOS.pdf",
        email_pdf_links: [
          {
            rel: "email_pdf",
            label: "Ver correo enviado",
            path: "correo/ABONOS.pdf",
            web_url: "https://example.com/correo.pdf",
          },
        ],
      },
      error: null,
      user_message: null,
      next_action: null,
      progress: null,
      raw_available: false,
    });

    renderDetail(processKey);
    await screen.findByText("Bancolombia");
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /^Enviar correo$/i }));
    await user.click(screen.getByRole("button", { name: /Confirmar envío/i }));

    expect(await screen.findByText("Correo enviado")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Ver correo enviado/i })).toHaveAttribute(
      "href",
      "https://example.com/correo.pdf",
    );
  });

  it("tras Finalize OK muestra enlaces al histórico y al soporte de asientos", async () => {
    const processKey = "payment-validation|banco_bancolombia|2026-08-01|finalize-ok";
    const initial = baseDetail({
      process_key: processKey,
      bank_code: "banco_bancolombia",
      bank_name: "Bancolombia",
      operational_status: "EN_REVISION",
      control_estado_proceso: "REVISION_CREADA",
      steps: [
        { name: "generate", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
        { name: "review", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
        { name: "finalize", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
        { name: "notify", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
        { name: "merge", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
        { name: "dry_run", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
        { name: "apply", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
      ],
      available_actions: {
        finalize: { allowed: true, reason: null },
        notify: { allowed: false, reason: null },
        merge: { allowed: false, reason: null },
        amortization: { allowed: false, reason: null },
      },
      links: [
        {
          rel: "review_excel",
          label: "Abrir archivo de revisión",
          path: "rev.xlsx",
          web_url: "https://example.com/review.xlsx",
          open_mode: "sharepoint",
        },
      ],
    });
    const afterFinalize = baseDetail({
      process_key: processKey,
      bank_code: "banco_bancolombia",
      bank_name: "Bancolombia",
      operational_status: "PENDIENTE_NOTIFICACION",
      control_estado_proceso: "FINALIZADO",
      steps: [
        { name: "generate", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
        { name: "review", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
        { name: "finalize", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
        { name: "notify", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
        { name: "merge", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
        { name: "dry_run", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
        { name: "apply", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
      ],
      available_actions: {
        finalize: { allowed: false, reason: null },
        notify: { allowed: true, reason: null },
        merge: { allowed: false, reason: null },
        amortization: { allowed: false, reason: null },
      },
      files: {
        validation_file_path: "rev.xlsx",
        historical_file_path: "hist/cartera.xlsx",
        secretary_file_path: "hist/asientos.xlsx",
        email_pdf_path: null,
        merge_manifest_path: null,
        control_file_path: null,
        execution_log_path: null,
      },
      links: [
        {
          rel: "review_excel",
          label: "Abrir archivo de revisión",
          path: "rev.xlsx",
          web_url: "https://example.com/review.xlsx",
          open_mode: "sharepoint",
        },
        {
          rel: "historical",
          label: "Abrir histórico",
          path: "hist/cartera.xlsx",
          web_url: "https://example.com/hist.xlsx",
          open_mode: "sharepoint",
        },
        {
          rel: "secretary_file",
          label: "Abrir asientos pendientes",
          path: "hist/asientos.xlsx",
          web_url: "https://example.com/sec.xlsx",
          open_mode: "sharepoint",
        },
      ],
    });

    mocks.fetchBootstrap.mockResolvedValue(bootstrap);
    mocks.fetchProcess.mockResolvedValueOnce(initial).mockResolvedValue(afterFinalize);
    mocks.postJobReloadDelaysFor.mockReturnValue([0, 1, 1]);
    mocks.postFinalize.mockResolvedValue({
      accepted: true,
      action: "finalize",
      bank_code: "banco_bancolombia",
      process_key: processKey,
      job_id: "job-finalize-ok-1",
      status: "queued",
      poll_url: "/api/ui/v1/jobs/job-finalize-ok-1",
    });
    mocks.fetchJob.mockResolvedValue({
      job_id: "job-finalize-ok-1",
      type: "finalize",
      status: "completed",
      store: "job_manager",
      process_key: processKey,
      bank_code: "banco_bancolombia",
      environment: "sandbox",
      created_at: "2026-08-01T10:00:00-05:00",
      started_at: "2026-08-01T10:00:00-05:00",
      finished_at: "2026-08-01T10:00:05-05:00",
      result_summary: {
        historical_file_path: "hist/cartera.xlsx",
        historical_file_url: "https://example.com/hist.xlsx",
        secretary_file_path: "hist/asientos.xlsx",
        secretary_file_url: "https://example.com/sec.xlsx",
      },
      error: null,
      user_message:
        "Se finalizó la revisión correctamente. Se guardó el histórico del día y el archivo para cargar los asientos contables.",
      next_action: null,
      progress: null,
      raw_available: false,
    });

    renderDetail(processKey);
    await screen.findByText("Bancolombia");
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /^Finalizar revisión$/i }));
    await user.click(screen.getByRole("button", { name: /Confirmar finalización/i }));

    expect(await screen.findByText("Revisión finalizada")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Abrir histórico/i })).toHaveAttribute(
      "href",
      "https://example.com/hist.xlsx",
    );
    expect(screen.getByRole("link", { name: /Abrir asientos pendientes/i })).toHaveAttribute(
      "href",
      "https://example.com/sec.xlsx",
    );
  });

  it("tras Merge OK con un PDF muestra link directo en el modal de éxito", async () => {
    const processKey = "payment-validation|banco_bancolombia|2026-08-01|merge-ok-1";
    const initial = baseDetail({
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
        { name: "merge", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
        { name: "dry_run", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
        { name: "apply", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
      ],
      available_actions: {
        finalize: { allowed: false, reason: null },
        notify: { allowed: false, reason: null },
        merge: { allowed: true, reason: null },
        amortization: { allowed: false, reason: null },
      },
      merge_readiness: {
        status: "ready",
        expected_groups: 1,
        ready_groups: 1,
        missing_groups: 0,
        missing_items: [],
        folder_links: [],
        user_message: "Los asientos contables están listos para consolidar.",
        next_action: "Puede generar el PDF consolidado desde la UI.",
        checked_at: null,
      },
    });
    const afterMerge = baseDetail({
      process_key: processKey,
      bank_code: "banco_bancolombia",
      bank_name: "Bancolombia",
      operational_status: "LISTO_PARA_APLICAR",
      control_estado_proceso: "CONSOLIDADO",
      steps: [
        { name: "generate", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
        { name: "review", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
        { name: "finalize", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
        { name: "notify", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
        { name: "merge", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
        { name: "dry_run", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
        { name: "apply", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
      ],
      available_actions: {
        finalize: { allowed: false, reason: null },
        notify: { allowed: false, reason: null },
        merge: { allowed: false, reason: null },
        amortization: { allowed: true, reason: null },
      },
      links: [
        {
          rel: "merge_pdf",
          label: "Abrir PDF consolidado · Crédito 265",
          path: "merge/a.pdf",
          web_url: "https://example.com/a.pdf",
          open_mode: "sharepoint",
        },
      ],
      document_groups: [
        {
          id: "merge_pdfs",
          title: "PDFs consolidados",
          count: 1,
          links: [
            {
              rel: "merge_pdf",
              label: "Abrir PDF consolidado · Crédito 265",
              path: "merge/a.pdf",
              web_url: "https://example.com/a.pdf",
              open_mode: "sharepoint",
            },
          ],
        },
      ],
    });

    mocks.fetchBootstrap.mockResolvedValue(bootstrap);
    mocks.fetchProcess.mockResolvedValueOnce(initial).mockResolvedValue(afterMerge);
    mocks.postMerge.mockResolvedValue({
      accepted: true,
      action: "merge",
      bank_code: "banco_bancolombia",
      process_key: processKey,
      job_id: "job-merge-1",
      status: "queued",
      poll_url: "/api/ui/v1/jobs/job-merge-1",
    });
    mocks.fetchJob.mockResolvedValue({
      job_id: "job-merge-1",
      type: "merge_pdf",
      status: "completed",
      store: "job_manager",
      process_key: processKey,
      bank_code: "banco_bancolombia",
      environment: "sandbox",
      created_at: "2026-08-01T10:00:00-05:00",
      started_at: "2026-08-01T10:00:00-05:00",
      finished_at: "2026-08-01T10:00:05-05:00",
      result_summary: {
        merge_pdf_links: [
          {
            rel: "merge_pdf",
            label: "Abrir PDF consolidado · Crédito 265",
            path: "merge/a.pdf",
            web_url: "https://example.com/a.pdf",
          },
        ],
      },
      error: null,
      user_message: null,
      next_action: null,
      progress: null,
      raw_available: false,
    });

    renderDetail(processKey);
    await screen.findByText("Bancolombia");
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /^Generar PDF consolidado$/i }));
    const confirmDialog = await screen.findByRole("dialog");
    await user.click(
      within(confirmDialog).getByRole("button", { name: /^Generar PDF consolidado$/i }),
    );

    expect(await screen.findByText("PDF consolidado listo")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /Abrir PDF consolidado · Crédito 265/i }),
    ).toHaveAttribute("href", "https://example.com/a.pdf");
    expect(screen.queryByRole("button", { name: /PDFs consolidados \(/i })).not.toBeInTheDocument();
  });

  it("tras Merge OK con varios PDFs abre el catálogo desde el CTA del modal", async () => {
    const processKey = "payment-validation|banco_bancolombia|2026-08-01|merge-ok-n";
    const initial = baseDetail({
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
        { name: "merge", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
        { name: "dry_run", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
        { name: "apply", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
      ],
      available_actions: {
        finalize: { allowed: false, reason: null },
        notify: { allowed: false, reason: null },
        merge: { allowed: true, reason: null },
        amortization: { allowed: false, reason: null },
      },
      merge_readiness: {
        status: "ready",
        expected_groups: 2,
        ready_groups: 2,
        missing_groups: 0,
        missing_items: [],
        folder_links: [],
        user_message: "Los asientos contables están listos para consolidar.",
        next_action: "Puede generar el PDF consolidado desde la UI.",
        checked_at: null,
      },
    });
    const afterMerge = baseDetail({
      process_key: processKey,
      bank_code: "banco_bancolombia",
      bank_name: "Bancolombia",
      operational_status: "LISTO_PARA_APLICAR",
      control_estado_proceso: "CONSOLIDADO",
      steps: [
        { name: "generate", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
        { name: "review", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
        { name: "finalize", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
        { name: "notify", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
        { name: "merge", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
        { name: "dry_run", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
        { name: "apply", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
      ],
      available_actions: {
        finalize: { allowed: false, reason: null },
        notify: { allowed: false, reason: null },
        merge: { allowed: false, reason: null },
        amortization: { allowed: true, reason: null },
      },
      links: [
        {
          rel: "merge_pdf:0",
          label: "Abrir PDF consolidado · Crédito 265",
          path: "merge/a.pdf",
          web_url: "https://example.com/a.pdf",
          open_mode: "sharepoint",
        },
        {
          rel: "merge_pdf:1",
          label: "Abrir PDF consolidado · Crédito 310",
          path: "merge/b.pdf",
          web_url: "https://example.com/b.pdf",
          open_mode: "sharepoint",
        },
      ],
      document_groups: [
        {
          id: "merge_pdfs",
          title: "PDFs consolidados",
          count: 2,
          links: [
            {
              rel: "merge_pdf:0",
              label: "Abrir PDF consolidado · Crédito 265",
              path: "merge/a.pdf",
              web_url: "https://example.com/a.pdf",
              open_mode: "sharepoint",
            },
            {
              rel: "merge_pdf:1",
              label: "Abrir PDF consolidado · Crédito 310",
              path: "merge/b.pdf",
              web_url: "https://example.com/b.pdf",
              open_mode: "sharepoint",
            },
          ],
        },
      ],
    });

    mocks.fetchBootstrap.mockResolvedValue(bootstrap);
    mocks.fetchProcess.mockResolvedValueOnce(initial).mockResolvedValue(afterMerge);
    mocks.postMerge.mockResolvedValue({
      accepted: true,
      action: "merge",
      bank_code: "banco_bancolombia",
      process_key: processKey,
      job_id: "job-merge-n",
      status: "queued",
      poll_url: "/api/ui/v1/jobs/job-merge-n",
    });
    mocks.fetchJob.mockResolvedValue({
      job_id: "job-merge-n",
      type: "merge_pdf",
      status: "completed",
      store: "job_manager",
      process_key: processKey,
      bank_code: "banco_bancolombia",
      environment: "sandbox",
      created_at: "2026-08-01T10:00:00-05:00",
      started_at: "2026-08-01T10:00:00-05:00",
      finished_at: "2026-08-01T10:00:05-05:00",
      result_summary: {
        merge_pdf_links: [
          {
            rel: "merge_pdf:0",
            label: "Abrir PDF consolidado · Crédito 265",
            path: "merge/a.pdf",
            web_url: "https://example.com/a.pdf",
          },
          {
            rel: "merge_pdf:1",
            label: "Abrir PDF consolidado · Crédito 310",
            path: "merge/b.pdf",
            web_url: "https://example.com/b.pdf",
          },
        ],
      },
      error: null,
      user_message: null,
      next_action: null,
      progress: null,
      raw_available: false,
    });

    renderDetail(processKey);
    await screen.findByText("Bancolombia");
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /^Generar PDF consolidado$/i }));
    const confirmDialog = await screen.findByRole("dialog");
    await user.click(
      within(confirmDialog).getByRole("button", { name: /^Generar PDF consolidado$/i }),
    );

    expect(await screen.findByText("PDF consolidado listo")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Crédito 265/i })).not.toBeInTheDocument();
    const catalogCta = screen.getByRole("button", { name: "PDFs consolidados (2)" });
    await user.click(catalogCta);

    expect(screen.queryByText("PDF consolidado listo")).not.toBeInTheDocument();
    const openLinks = await screen.findAllByRole("link", { name: "Abrir" });
    expect(openLinks).toHaveLength(2);
    expect(openLinks[0]).toHaveAttribute("href", "https://example.com/a.pdf");
    expect(openLinks[1]).toHaveAttribute("href", "https://example.com/b.pdf");
    expect(screen.getByText(/Crédito 265/i)).toBeInTheDocument();
    expect(screen.getByText(/Crédito 310/i)).toBeInTheDocument();
  });

  it("tras Amortización OK (evidencia en job) muestra Proceso completado y links de tablas", async () => {
    const processKey = "payment-validation|banco_bogota|2026-08-01|amort-ok";
    const initial = baseDetail({
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
        user_message: "Listo para amortizar.",
        next_action: "Procesar amortización",
        checked_at: null,
      },
    });
    const afterApply = baseDetail({
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
      available_actions: {
        finalize: { allowed: false, reason: null },
        notify: { allowed: false, reason: null },
        merge: { allowed: false, reason: null },
        amortization: { allowed: false, reason: null },
      },
      document_groups: [
        {
          id: "amortization_tables",
          title: "Tablas de amortización",
          count: 1,
          links: [
            {
              rel: "amort_table:0",
              label: "Tabla cliente A",
              path: "clientes/a.xlsx",
              web_url: "https://example.com/tabla-a.xlsx",
              open_mode: "sharepoint",
            },
          ],
        },
      ],
    });

    mocks.fetchBootstrap.mockResolvedValue(bootstrap);
    mocks.fetchProcess.mockResolvedValueOnce(initial).mockResolvedValue(afterApply);
    mocks.postAmortization.mockResolvedValue({
      accepted: true,
      action: "amortization",
      bank_code: "banco_bogota",
      process_key: processKey,
      job_id: "job-amort-1",
      status: "queued",
      poll_url: "/api/ui/v1/jobs/job-amort-1",
    });
    mocks.fetchJob.mockResolvedValue({
      job_id: "job-amort-1",
      type: "amortization_process",
      status: "completed",
      store: "job_manager",
      process_key: processKey,
      bank_code: "banco_bogota",
      environment: "sandbox",
      created_at: "2026-08-01T10:00:00-05:00",
      started_at: "2026-08-01T10:00:00-05:00",
      finished_at: "2026-08-01T10:00:05-05:00",
      result_summary: {
        outcome: "applied",
        process_control_estado: "AMORTIZACION_APLICADA",
        process_control_updated: true,
      },
      error: null,
      user_message: null,
      next_action: null,
      progress: null,
      raw_available: false,
    });

    renderDetail(processKey);
    await screen.findByText("Banco de Bogotá");
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /^Procesar amortización$/i }));
    const confirmDialog = await screen.findByRole("dialog");
    await user.click(
      within(confirmDialog).getByRole("button", { name: /^Procesar amortización$/i }),
    );

    const successDialog = await screen.findByRole("dialog", { name: "Proceso completado" });
    expect(within(successDialog).getByText(/amortización se aplicó|finalizado/i)).toBeInTheDocument();
    expect(screen.queryByText(/Sincronización incompleta/i)).not.toBeInTheDocument();
    expect(within(successDialog).getByRole("link", { name: /Tabla cliente A/i })).toHaveAttribute(
      "href",
      "https://example.com/tabla-a.xlsx",
    );
  });

  it("tras Amortización OK con N≥2 tablas abre catálogo (sin volcar links inline ni chips)", async () => {
    const processKey = "payment-validation|banco_bogota|2026-08-01|amort-n";
    const initial = baseDetail({
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
        expected_items: 2,
        ready_items: 2,
        missing_items: [],
        warnings: [],
        user_message: "Listo para amortizar.",
        next_action: "Procesar amortización",
        checked_at: null,
      },
    });
    const afterApply = baseDetail({
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
      available_actions: {
        finalize: { allowed: false, reason: null },
        notify: { allowed: false, reason: null },
        merge: { allowed: false, reason: null },
        amortization: { allowed: false, reason: null },
      },
      document_groups: [
        {
          id: "amortization_tables",
          title: "Tablas de amortización",
          count: 2,
          links: [
            {
              rel: "amort_table:0",
              label: "Tabla cliente A",
              path: "clientes/a.xlsx",
              web_url: "https://example.com/tabla-a.xlsx",
              open_mode: "sharepoint",
            },
            {
              rel: "amort_table:1",
              label: "Tabla cliente B",
              path: "clientes/b.xlsx",
              web_url: "https://example.com/tabla-b.xlsx",
              open_mode: "sharepoint",
            },
          ],
        },
      ],
    });

    mocks.fetchBootstrap.mockResolvedValue(bootstrap);
    mocks.fetchProcess.mockResolvedValueOnce(initial).mockResolvedValue(afterApply);
    mocks.postAmortization.mockResolvedValue({
      accepted: true,
      action: "amortization",
      bank_code: "banco_bogota",
      process_key: processKey,
      job_id: "job-amort-n",
      status: "queued",
      poll_url: "/api/ui/v1/jobs/job-amort-n",
    });
    mocks.fetchJob.mockResolvedValue({
      job_id: "job-amort-n",
      type: "amortization_process",
      status: "completed",
      store: "job_manager",
      process_key: processKey,
      bank_code: "banco_bogota",
      environment: "sandbox",
      created_at: "2026-08-01T10:00:00-05:00",
      started_at: "2026-08-01T10:00:00-05:00",
      finished_at: "2026-08-01T10:00:05-05:00",
      result_summary: {
        outcome: "applied",
        process_control_estado: "AMORTIZACION_APLICADA",
        process_control_updated: true,
      },
      error: null,
      user_message: null,
      next_action: null,
      progress: null,
      raw_available: false,
    });

    renderDetail(processKey);
    await screen.findByText("Banco de Bogotá");
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /^Procesar amortización$/i }));
    const confirmDialog = await screen.findByRole("dialog");
    await user.click(
      within(confirmDialog).getByRole("button", { name: /^Procesar amortización$/i }),
    );

    const successDialog = await screen.findByRole("dialog", { name: "Proceso completado" });
    expect(within(successDialog).getByText(/amortización se aplicó|finalizado/i)).toBeInTheDocument();
    expect(within(successDialog).queryByRole("link", { name: /Tabla cliente/i })).not.toBeInTheDocument();
    await user.click(within(successDialog).getByRole("button", { name: "Tablas de amortización (2)" }));

    expect(await screen.findByRole("heading", { name: /Tablas de amortización \(2\)/i })).toBeInTheDocument();
    expect(document.querySelector(".merge-groups-progress")).toBeNull();
    expect(document.querySelector(".link-catalog-status")).toBeNull();
    const openLinks = screen.getAllByRole("link", { name: "Abrir" });
    expect(openLinks).toHaveLength(2);
    expect(openLinks[0]).toHaveAttribute("href", "https://example.com/tabla-a.xlsx");
    expect(openLinks[1]).toHaveAttribute("href", "https://example.com/tabla-b.xlsx");
  });

  it("tras Amortización completed con requires_correction muestra resumen, CTA y banner", async () => {
    const processKey = "payment-validation|banco_bogota|2026-08-01|amort-corr";
    const initial = baseDetail({
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
        user_message: "Listo para amortizar.",
        next_action: "Procesar amortización",
        checked_at: null,
      },
    });

    mocks.fetchBootstrap.mockResolvedValue(bootstrap);
    mocks.fetchProcess.mockResolvedValue(initial);
    mocks.postAmortization.mockResolvedValue({
      accepted: true,
      action: "amortization",
      bank_code: "banco_bogota",
      process_key: processKey,
      job_id: "job-amort-corr",
      status: "queued",
      poll_url: "/api/ui/v1/jobs/job-amort-corr",
    });
    mocks.fetchJob.mockResolvedValue({
      job_id: "job-amort-corr",
      type: "amortization_process",
      status: "completed",
      store: "job_manager",
      process_key: processKey,
      bank_code: "banco_bogota",
      environment: "sandbox",
      created_at: "2026-08-01T10:00:00-05:00",
      started_at: "2026-08-01T10:00:00-05:00",
      finished_at: "2026-08-01T10:00:05-05:00",
      result_summary: {
        outcome: "requires_correction",
        user_message: "Debe corregir la tabla de amortización antes de reintentar.",
        next_action: "Abra la tabla y corrija los datos marcados.",
        operational_issues: [
          {
            issue_id: "amort-capital-1",
            stage: "amortization",
            category: "correction_required",
            severity: "business",
            recoverable: true,
            title: "Capital inválido",
            user_message: "El capital no puede ser negativo en la fila 3.",
            location: null,
            value_found: null,
            expected_values: [],
            next_action: null,
            retry: null,
            links: [],
            technical_reference: "invalid_capital",
          },
        ],
      },
      error: null,
      user_message: null,
      next_action: null,
      progress: null,
      raw_available: false,
    });

    renderDetail(processKey);
    await screen.findByText("Banco de Bogotá");
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /^Procesar amortización$/i }));
    const confirmDialog = await screen.findByRole("dialog");
    await user.click(
      within(confirmDialog).getByRole("button", { name: /^Procesar amortización$/i }),
    );

    const reviewDialog = await screen.findByRole("dialog", { name: "Revisión requerida" });
    expect(
      within(reviewDialog).getByText(/Se encontró 1 problema de amortización/i),
    ).toBeInTheDocument();
    expect(
      within(reviewDialog).getByRole("button", {
        name: /Ver problemas de amortización/i,
      }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Sincronización incompleta/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "Proceso completado" })).not.toBeInTheDocument();
    expect(reviewDialog.querySelector(".job-status-modal-result.is-warning")).toBeTruthy();

    await user.click(
      within(reviewDialog).getByRole("button", {
        name: /Ver problemas de amortización/i,
      }),
    );
    expect(
      await screen.findByRole("heading", { name: /Problemas de amortización \(1\)/i }),
    ).toBeInTheDocument();
    expect(screen.getByText(/El capital no puede ser negativo/i)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^Cerrar$/i }));

    const amortBanner = document.getElementById("amortization-issues-banner-title");
    expect(amortBanner).toBeTruthy();
    expect(amortBanner?.textContent).toMatch(/1 problema\(s\) de amortización/i);
    expect(
      screen.getByRole("button", { name: /Ver problemas de amortización/i }),
    ).toBeInTheDocument();
  });

  it("tras timeout de sync de amortización muestra warning con Actualizar estado (no error duro)", async () => {
    const processKey = "payment-validation|banco_bogota|2026-08-01|amort-stale";
    const ready = baseDetail({
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
        user_message: "Listo para amortizar.",
        next_action: "Procesar amortización",
        checked_at: null,
      },
    });
    const stale = baseDetail({
      process_key: processKey,
      operational_status: "SINCRONIZANDO",
      control_estado_proceso: "CONSOLIDADO",
      steps: [
        { name: "generate", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
        { name: "review", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
        { name: "finalize", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
        { name: "notify", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
        { name: "merge", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
        { name: "dry_run", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
        { name: "apply", status: "sync_pending", updated_at: null, summary: null, can_retry: false, retry_action: null },
      ],
      available_actions: {
        finalize: { allowed: false, reason: null },
        notify: { allowed: false, reason: null },
        merge: { allowed: false, reason: null },
        amortization: { allowed: false, reason: null },
      },
    });
    // Delays mínimos para agotar sync sin esperar ~30s reales.
    mocks.postJobReloadDelaysFor.mockReturnValue([0, 1, 1]);

    mocks.fetchBootstrap.mockResolvedValue(bootstrap);
    mocks.fetchProcess.mockResolvedValueOnce(ready).mockResolvedValue(stale);
    mocks.postAmortization.mockResolvedValue({
      accepted: true,
      action: "amortization",
      bank_code: "banco_bogota",
      process_key: processKey,
      job_id: "job-amort-stale",
      status: "queued",
      poll_url: "/api/ui/v1/jobs/job-amort-stale",
    });
    mocks.fetchJob.mockResolvedValue({
      job_id: "job-amort-stale",
      type: "amortization_process",
      status: "completed",
      store: "job_manager",
      process_key: processKey,
      bank_code: "banco_bogota",
      environment: "sandbox",
      created_at: "2026-08-01T10:00:00-05:00",
      started_at: "2026-08-01T10:00:00-05:00",
      finished_at: "2026-08-01T10:00:05-05:00",
      // Sin process_control_* ni outcome applied: obliga a esperar proyección.
      result_summary: null,
      error: null,
      user_message: null,
      next_action: null,
      progress: null,
      raw_available: false,
    });

    renderDetail(processKey);
    await screen.findByText("Banco de Bogotá");
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /^Procesar amortización$/i }));
    const confirmDialog = await screen.findByRole("dialog");
    await user.click(
      within(confirmDialog).getByRole("button", { name: /^Procesar amortización$/i }),
    );

    // Sin evidencia en result_summary → predicado exige proyección; stale agota delays.
    const pendingDialog = await screen.findByRole("dialog", {
      name: "Estado pendiente de confirmar",
    });
    expect(screen.queryByText(/Sincronización incompleta/i)).not.toBeInTheDocument();
    expect(pendingDialog.querySelector(".job-status-modal-result.is-error")).toBeNull();
    expect(pendingDialog.querySelector(".job-status-modal-result.is-warning")).toBeTruthy();
    expect(within(pendingDialog).getByRole("button", { name: "Actualizar estado" })).toBeInTheDocument();
    expect(within(pendingDialog).getByText(/La amortización ya terminó/i)).toBeInTheDocument();
  });

  it("en revisión muestra Cancelar lote lejos del CTA principal", async () => {
    const processKey = "payment-validation|banco_bogota|2026-08-02|cancel-lote";
    mocks.fetchBootstrap.mockResolvedValue(bootstrap);
    mocks.fetchProcess.mockResolvedValue(
      baseDetail({
        process_key: processKey,
        process_date: "2026-08-02",
        operational_status: "EN_REVISION",
        control_estado_proceso: "REVISION_CREADA",
        available_actions: {
          finalize: { allowed: true, reason: null },
          notify: { allowed: false, reason: null },
          merge: { allowed: false, reason: null },
          amortization: { allowed: false, reason: null },
          regenerate: { allowed: true, reason: null },
          cancel_lote: { allowed: true, reason: null },
          soft_close: { allowed: false, reason: "No aplica en revisión" },
        },
      }),
    );

    renderDetail(processKey);
    await screen.findByText("Banco de Bogotá");

    const cancelBtn = screen.getByRole("button", { name: /^Cancelar proceso$/i });
    expect(cancelBtn).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Cerrar sin amortizar$/i })).not.toBeInTheDocument();
    expect(cancelBtn.closest(".process-escape-footer")).toBeTruthy();
    expect(cancelBtn.closest(".current-phase-panel")).toBeNull();
    expect(cancelBtn.closest(".panel")).toBeNull();
    expect(screen.queryByRole("heading", { name: "Más acciones" })).not.toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(cancelBtn);
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/artefactos reversibles/i)).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: /^Cancelar proceso$/i })).toBeDisabled();
  });

  it("en consolidado separa Cancelar proceso de Cerrar sin amortizar", async () => {
    const processKey = "payment-validation|banco_bogota|2026-08-02|soft-close";
    mocks.fetchBootstrap.mockResolvedValue(bootstrap);
    mocks.fetchProcess.mockResolvedValue(
      baseDetail({
        process_key: processKey,
        process_date: "2026-08-02",
        operational_status: "LISTO_PARA_APLICAR",
        control_estado_proceso: "CONSOLIDADO",
        available_actions: {
          finalize: { allowed: false, reason: null },
          notify: { allowed: false, reason: null },
          merge: { allowed: false, reason: null },
          amortization: { allowed: true, reason: null },
          cancel_lote: { allowed: true, reason: null },
          soft_close: { allowed: true, reason: null },
        },
        steps: [
          { name: "generate", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "review", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "finalize", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "notify", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "merge", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "dry_run", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "apply", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
        ],
      }),
    );

    renderDetail(processKey);
    await screen.findByText("Banco de Bogotá");

    expect(screen.getByText(/Fase .* · Procesar amortización/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Cancelar proceso$/i })).toBeInTheDocument();
    const softBtn = screen.getByRole("button", { name: /^Cerrar sin amortizar$/i });
    expect(softBtn.closest(".process-escape-footer")).toBeTruthy();
    expect(softBtn.closest(".panel")).toBeNull();
    expect(screen.queryByRole("heading", { name: "Más acciones" })).not.toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(softBtn);
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/se conservan/i)).toBeInTheDocument();
    expect(within(dialog).getByText(/Procesados/i)).toBeInTheDocument();
    expect(within(dialog).getByText(/ASIENTOS/i)).toBeInTheDocument();
    expect(within(dialog).queryByLabelText(/Motivo/i)).not.toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: /Confirmar cierre/i })).toBeDisabled();
    expect(within(dialog).getByPlaceholderText("CANCELAR")).toBeInTheDocument();
  });

  it("en fase Merge no muestra Cerrar sin amortizar aunque el pie exista en amortización", async () => {
    const processKey = "payment-validation|banco_bogota|2026-08-02|merge-no-soft";
    mocks.fetchBootstrap.mockResolvedValue(bootstrap);
    mocks.fetchProcess.mockResolvedValue(
      baseDetail({
        process_key: processKey,
        process_date: "2026-08-02",
        operational_status: "ESPERANDO_SOPORTES",
        control_estado_proceso: "PENDIENTE_ASIENTOS",
        available_actions: {
          finalize: { allowed: false, reason: null },
          notify: { allowed: false, reason: null },
          merge: { allowed: true, reason: null },
          amortization: { allowed: false, reason: null },
          cancel_lote: { allowed: true, reason: null },
          soft_close: { allowed: false, reason: "Solo en amortización" },
        },
        steps: [
          { name: "generate", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "review", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "finalize", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "notify", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "merge", status: "in_progress", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "dry_run", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
          { name: "apply", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
        ],
      }),
    );

    renderDetail(processKey);
    await screen.findByText("Banco de Bogotá");
    expect(screen.getByRole("heading", { level: 2, name: "Generar PDF consolidado" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Cerrar sin amortizar$/i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Cancelar proceso$/i })).toBeInTheDocument();
  });

  it("recovery formato: CTA modal → fase merge con Reconsolidar PDF", async () => {
    const processKey = "payment-validation|banco_bogota|2026-08-01|amort-fmt";
    const detail = baseDetail({
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
        merge: { allowed: false, reason: "Los asientos contables de este proceso ya fueron consolidados." },
        amortization: { allowed: true, reason: null },
      },
      merge_readiness: {
        status: "already_merged",
        expected_groups: 1,
        ready_groups: 1,
        missing_groups: 0,
        missing_items: [],
        folder_links: [
          {
            rel: "asientos",
            label: "Carpeta ASIENTOS",
            path: "clientes/X/ASIENTOS",
            web_url: "https://example.com/asientos",
            credito: "264",
            list_ok: true,
            observed_pdfs: [
              {
                name: "asiento-264.pdf",
                size: 100,
                etag: '"old"',
                last_modified: "2026-08-01T10:00:00Z",
              },
            ],
          },
        ],
        checked_at: null,
        user_message: "Ya consolidado.",
        next_action: "",
      },
      amortization_readiness: {
        status: "ready",
        can_start: true,
        expected_items: 1,
        ready_items: 1,
        missing_items: [],
        warnings: [],
        user_message: "Listo para amortizar.",
        next_action: "Procesar amortización",
        checked_at: null,
      },
      links: [
        {
          rel: "merge_pdf",
          label: "Abrir PDF consolidado · Crédito 264",
          path: "merge/consolidado-264.pdf",
          web_url: "https://example.com/consolidado-264.pdf",
          open_mode: "sharepoint",
        },
      ],
      operational_issues: [
        {
          issue_id: "amort-ACCOUNTING_PARSE_FAILED-264-0",
          stage: "amortization",
          category: "correction_required",
          severity: "business",
          recoverable: true,
          title: "Documento contable · Crédito 264",
          user_message: "El PDF no tiene el formato de asiento contable esperado.",
          location: {
            file_name: "asiento-264.pdf",
            sheet: null,
            row: null,
            column: null,
            credit: "264",
            payment_id: "P1",
            client_name: null,
          },
          value_found: null,
          expected_values: [],
          next_action: "Corrija el PDF, reconsolide y procese la amortización.",
          retry: null,
          links: [
            {
              rel: "asientos",
              label: "Abrir carpeta ASIENTOS",
              path: "clientes/X/ASIENTOS",
              web_url: "https://example.com/asientos",
              open_mode: "sharepoint",
            },
          ],
          technical_reference: "ACCOUNTING_PARSE_FAILED",
        },
      ],
    });

    mocks.fetchBootstrap.mockResolvedValue(bootstrap);
    mocks.fetchProcess.mockResolvedValue(detail);

    renderDetail(processKey);
    await screen.findByText("Banco de Bogotá");
    const user = userEvent.setup();

    expect(
      screen.getByText(/Tras corregir los asientos en SharePoint/i),
    ).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: /Ver problemas de amortización/i }),
    );
    expect(
      await screen.findByRole("heading", { name: /Problemas de amortización \(1\)/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Corrija primero los PDF en SharePoint/i),
    ).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", {
        name: /Ya corregí los asientos — ir a reconsolidar/i,
      }),
    );

    expect(
      await screen.findByText(/Está aquí para reconsolidar/i),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Actualizar \/ verificar asientos contables/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /^Reconsolidar PDF$/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Ver carpeta ASIENTOS/i }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: /Abrir PDF consolidado/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Abrir PDF consolidado/i }),
    ).not.toBeInTheDocument();
  });

  it("muestra banner de amortización al cargar detalle con last_amortization_attempt", async () => {
    const processKey = "payment-validation|banco_bogota|2026-08-01|amort-persist";
    const detail = baseDetail({
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
      operational_issues: [],
      last_amortization_attempt: {
        attempt_id: "job-persisted-refresh",
        outcome: "requires_correction",
        created_at: "2026-08-01T10:00:00-05:00",
        operational_issues: [
          {
            issue_id: "amort-capital-persisted",
            stage: "amortization",
            category: "correction_required",
            severity: "business",
            recoverable: true,
            title: "Capital inválido",
            user_message: "El capital no puede ser negativo en la fila 3.",
            location: {
              file_name: null,
              sheet: null,
              row: null,
              column: null,
              credit: "264",
              payment_id: "P1",
              client_name: "Cliente Demo",
            },
            value_found: null,
            expected_values: [],
            next_action: null,
            retry: null,
            links: [],
            technical_reference: "invalid_capital",
          },
        ],
        affected_payment_ids: ["P1"],
        user_message: "La amortización encontró 1 problema(s).",
        next_action: "Revise cada punto.",
      },
      amortization_readiness: {
        status: "ready",
        can_start: true,
        expected_items: 1,
        ready_items: 1,
        missing_items: [],
        warnings: [],
        user_message: "Listo para amortizar.",
        next_action: "Procesar amortización",
        checked_at: null,
      },
    });

    mocks.fetchBootstrap.mockResolvedValue(bootstrap);
    mocks.fetchProcess.mockResolvedValue(detail);

    renderDetail(processKey, "?phase=amortization");
    await screen.findByText("Banco de Bogotá");

    const amortBanner = document.getElementById("amortization-issues-banner-title");
    expect(amortBanner).toBeTruthy();
    expect(amortBanner?.textContent).toMatch(/1 problema\(s\) de amortización/i);
    expect(
      screen.getByRole("button", { name: /Ver problemas de amortización/i }),
    ).toBeInTheDocument();
  });
});
