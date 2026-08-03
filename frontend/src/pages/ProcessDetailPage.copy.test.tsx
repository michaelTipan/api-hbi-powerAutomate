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
  postGenerate: vi.fn(),
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
    // Abrir revisión: una sola vez junto al CTA de fase (no en Documentos ni panel).
    expect(screen.getAllByRole("link", { name: /Abrir archivo de revisión/i })).toHaveLength(1);
    expect(screen.getByText("Documentos por fase")).toBeInTheDocument();
    expect(screen.queryByText(/Solo consulta: vuelve a detectar/i)).not.toBeInTheDocument();
    expect(screen.getByText(/Fase 2 de 5 · Finalizar revisión/i)).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "Finalizar revisión" })).toBeInTheDocument();
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
    expect(screen.getByText(/Documentos listos para consolidar/i)).toBeInTheDocument();
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
    expect(screen.getByRole("link", { name: "Revisar destinatarios" })).toHaveAttribute(
      "href",
      "https://example.com/CORREOS.xlsx",
    );
    expect(screen.getByText(/igual que Power Automate/i)).toBeInTheDocument();
    const docsSection = document.getElementById("process-documents");
    expect(docsSection?.textContent).not.toMatch(/Revisar destinatarios/);
  });

  it("agrupa varios PDFs consolidados en catálogo (sin saturar la fase)", async () => {
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
      }),
    );

    renderDetail(processKey);
    await screen.findByText("Bancolombia");
    // Resumen en página; detalle en modal de catálogo.
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

  it("en fase Merge no muestra enlaces de carpetas ASIENTOS en ninguna sección", async () => {
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
          missing_items: [],
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
        links: [
          {
            rel: "asientos_folder",
            label: "Carpeta ASIENTOS · Crédito 265",
            path: "clientes/265/ASIENTOS",
            web_url: "https://example.com/asientos",
            open_mode: "sharepoint",
          },
        ],
        document_groups: [
          {
            id: "asientos_folders",
            title: "Carpetas ASIENTOS",
            count: 1,
            links: [
              {
                rel: "asientos_folder:0",
                label: "Carpeta ASIENTOS · Crédito 265",
                path: "clientes/265/ASIENTOS",
                web_url: "https://example.com/asientos",
                open_mode: "sharepoint",
              },
            ],
          },
        ],
      }),
    );

    renderDetail(processKey);
    await screen.findByText("Bancolombia");
    expect(screen.getByRole("heading", { level: 2, name: "Generar PDF consolidado" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Carpeta ASIENTOS/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/Ver carpetas ASIENTOS/i)).not.toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/Carpeta ASIENTOS/i);
    expect(screen.getByText(/Aún faltan documentos contables/i)).toBeInTheDocument();
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
    expect(screen.queryByRole("button", { name: /Procesar amortización/i })).not.toBeInTheDocument();
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
    // Regenerar solo en el CTA de fase (no en banner ni en problemas operativos).
    expect(screen.getAllByRole("button", { name: /Regenerar archivo de revisión/i })).toHaveLength(1);
    const phase = document.querySelector(".current-phase-panel");
    const status = document.querySelector(".status-summary-card");
    expect(phase).toBeTruthy();
    expect(status).toBeTruthy();
    expect(
      phase!.compareDocumentPosition(status!) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(phase!.querySelector("button")).toHaveTextContent(/Regenerar archivo de revisión/i);
  });

  it("con hoja Errores muestra Regenerar y Abrir una sola vez en la fase", async () => {
    const processKey = "payment-validation|banco_bancolombia|2026-08-02|err";
    mocks.fetchBootstrap.mockResolvedValue(bootstrap);
    mocks.fetchProcess.mockResolvedValue(
      baseDetail({
        process_key: processKey,
        bank_code: "banco_bancolombia",
        bank_name: "Bancolombia",
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
        steps: [
          {
            name: "generate",
            status: "failed_business",
            updated_at: null,
            summary: null,
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
            issue_id: "review-errores-open",
            stage: "generate",
            category: "correction_required",
            severity: "business",
            recoverable: true,
            title: "Casos en Errores",
            user_message: "Hay filas en la hoja Errores.",
            location: null,
            value_found: null,
            expected_values: [],
            next_action: "Corrija y regenere.",
            retry: {
              allowed: true,
              action: "regenerate",
              label: "Regenerar archivo de revisión",
            },
            links: [
              {
                rel: "review_excel",
                label: "Abrir archivo de revisión",
                path: "revision/x.xlsx",
                web_url: "https://example.com/review.xlsx",
                open_mode: "sharepoint",
              },
            ],
            technical_reference: "review_errores_open",
          },
        ],
        links: [
          {
            rel: "review_excel",
            label: "Abrir archivo de revisión",
            path: "revision/x.xlsx",
            web_url: "https://example.com/review.xlsx",
            open_mode: "sharepoint",
          },
        ],
      }),
    );

    renderDetail(processKey);
    await screen.findByText("Bancolombia");
    expect(screen.getByRole("heading", { name: "Casos en la hoja Errores" })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /Regenerar archivo de revisión/i })).toHaveLength(1);
    expect(screen.getAllByRole("link", { name: /Abrir archivo de revisión/i })).toHaveLength(1);
    const phase = document.querySelector(".current-phase-panel");
    expect(phase).toBeTruthy();
    expect(phase!.textContent).toMatch(/Regenerar archivo de revisión/i);
    expect(phase!.textContent).toMatch(/Abrir archivo de revisión/i);
  });
});
