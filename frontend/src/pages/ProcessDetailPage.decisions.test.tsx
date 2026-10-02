import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import type {
  UiAmortizationDecisions,
  UiBootstrapResponse,
  UiExcludedCredit,
  UiOperationalIssue,
  UiProcessDetail,
} from "../types/contract";

const mocks = vi.hoisted(() => ({
  fetchProcess: vi.fn(),
  fetchJob: vi.fn(),
  fetchBootstrap: vi.fn(),
  fetchBanks: vi.fn(),
  fetchNotifyRecipientsPreview: vi.fn(),
  postAmortizationExclusion: vi.fn(),
  postAmortizationExclusionUndo: vi.fn(),
  postConciliationConfirmation: vi.fn(),
  postConciliationConfirmationUndo: vi.fn(),
  postSoftClose: vi.fn(),
  useCsrfReady: vi.fn(),
}));

vi.mock("../api/client", () => ({
  fetchProcess: mocks.fetchProcess,
  fetchJob: mocks.fetchJob,
  fetchBootstrap: mocks.fetchBootstrap,
  fetchBanks: mocks.fetchBanks,
  fetchNotifyRecipientsPreview: mocks.fetchNotifyRecipientsPreview,
  postFinalize: vi.fn(),
  postNotify: vi.fn(),
  postMerge: vi.fn(),
  postAmortization: vi.fn(),
  postGenerate: vi.fn(),
  postAmortizationExclusion: mocks.postAmortizationExclusion,
  postAmortizationExclusionUndo: mocks.postAmortizationExclusionUndo,
  postConciliationConfirmation: mocks.postConciliationConfirmation,
  postConciliationConfirmationUndo: mocks.postConciliationConfirmationUndo,
  postSoftClose: mocks.postSoftClose,
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

const PROCESS_KEY = "payment-validation|banco_bogota|2026-08-01|decisions-1";

const completedSteps: UiProcessDetail["steps"] = [
  "generate",
  "review",
  "finalize",
  "notify",
  "merge",
  "dry_run",
].map((name) => ({
  name,
  status: "completed",
  updated_at: null,
  summary: null,
  can_retry: false,
  retry_action: null,
}));

function conciliationIssue(credit: string, group: string[]): UiOperationalIssue {
  return {
    issue_id: `amort-CONCILIACION_ASIENTOS_MAYOR_BANCO-${credit}-0`,
    stage: "amortization",
    category: "correction_required",
    severity: "business",
    recoverable: true,
    title: `Consignación · Crédito ${credit}`,
    user_message: "Los asientos suman más que la consignación del banco.",
    location: {
      file_name: null,
      sheet: null,
      row: null,
      column: null,
      credit,
      payment_id: "P1",
      client_name: `CLIENTE ${credit}`,
    },
    value_found: "Asientos $1.200",
    expected_values: ["Banco $1.000"],
    next_action: "Corrija el asiento o excluya el crédito.",
    retry: null,
    links: [],
    technical_reference: "CONCILIACION_ASIENTOS_MAYOR_BANCO",
    decision: {
      excludable: true,
      group_credits: group,
      group_key: group.join("+"),
      confirmable: false,
      conciliation_key: null,
      fecha_banco: "2026-08-01",
      bank_amount: 1000,
      asientos_amount: 1200,
      unapplied_amount: null,
    },
  };
}

function excludedRow(overrides: Partial<UiExcludedCredit> = {}): UiExcludedCredit {
  return {
    credit: "133",
    client_name: "CLIENTE 133",
    motivo: "Falta el asiento de Contabilidad",
    motivo_codigo: "FALTA_ASIENTO",
    nota: null,
    group_credits: ["133"],
    exclusion_id: "e1",
    can_undo: true,
    table_link: null,
    ...overrides,
  };
}

function decisions(overrides: Partial<UiAmortizationDecisions> = {}): UiAmortizationDecisions {
  return {
    available: true,
    user_message: null,
    excluded: [],
    confirmations: [],
    planned_lines: null,
    planned_tables: null,
    credits_not_amortized: [],
    ...overrides,
  };
}

function amortDetail(overrides: Partial<UiProcessDetail> = {}): UiProcessDetail {
  return {
    process_key: PROCESS_KEY,
    process_id: "decisions-1",
    bank_code: "banco_bogota",
    bank_name: "Banco de Bogotá",
    process_date: "2026-08-01",
    environment: "sandbox",
    operational_status: "LISTO_PARA_APLICAR",
    control_estado_proceso: "CONSOLIDADO",
    is_active: true,
    steps: [
      ...completedSteps,
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
    next_actions: [],
    available_actions: {
      finalize: { allowed: false, reason: null },
      notify: { allowed: false, reason: null },
      merge: { allowed: false, reason: null },
      amortization: { allowed: true, reason: null },
    },
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
    amortization_readiness: {
      status: "ready",
      can_start: true,
      expected_items: 2,
      ready_items: 2,
      missing_items: [],
      warnings: [],
      user_message: "Listo.",
      next_action: "Puede procesar la amortización desde la UI.",
      checked_at: null,
    },
    last_amortization_attempt: {
      attempt_id: "att-1",
      outcome: "requires_correction",
      created_at: "2026-08-01T10:00:00-05:00",
      operational_issues: [
        conciliationIssue("133", ["133"]),
        conciliationIssue("250", ["250"]),
      ],
      affected_payment_ids: ["P1"],
      user_message: "Hay problemas por resolver.",
      next_action: null,
    },
    ...overrides,
  };
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={[`/processes/${encodeURIComponent(PROCESS_KEY)}`]}>
      <Routes>
        <Route path="/processes/:processKey" element={<ProcessDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.useRealTimers();
  for (const fn of Object.values(mocks)) fn.mockReset();
  mocks.fetchBanks.mockResolvedValue([]);
  mocks.fetchBootstrap.mockResolvedValue(bootstrap);
  mocks.fetchNotifyRecipientsPreview.mockResolvedValue({
    ok: true,
    source_path: "CTL/CORREOS.xlsx",
    sheet: "CORREOS",
    emisor: "ops@hbi.test",
    receptores: ["dest@hbi.test"],
    receptores_raw_count: 1,
    file_last_modified: null,
    warnings: [],
    user_message: "Listo.",
  });
  mocks.useCsrfReady.mockReturnValue({ csrfReady: true, csrfPreparing: false });
});

describe("ProcessDetailPage — decisiones de amortización", () => {
  it("fase de amortización: línea de excluido, resumen de escrituras y franja sin contar excluidos", async () => {
    mocks.fetchProcess.mockResolvedValue(
      amortDetail({
        amortization_decisions: decisions({
          excluded: [excludedRow()],
          planned_lines: 3,
          planned_tables: 2,
        }),
      }),
    );
    renderPage();
    await screen.findByRole("heading", { name: "Banco de Bogotá" });
    const panel = document.querySelector(".current-phase-panel") as HTMLElement;
    expect(panel).toBeTruthy();
    expect(
      await within(panel).findByText("Excluido: crédito 133 · CLIENTE 133"),
    ).toBeInTheDocument();
    expect(within(panel).getByText("Se registrarán 3 líneas en 2 tablas")).toBeInTheDocument();
    const banner = document.getElementById("amortization-issues-banner-title");
    expect(banner?.textContent).toMatch(/\b1\b/);
    expect(document.body.textContent).not.toContain("FALTA_ASIENTO");
  });

  it("Deshacer en la tarjeta de fase llama al endpoint y actualiza sin recargar", async () => {
    const user = userEvent.setup();
    mocks.fetchProcess.mockResolvedValue(
      amortDetail({
        amortization_decisions: decisions({
          excluded: [excludedRow()],
          planned_lines: 3,
          planned_tables: 2,
        }),
      }),
    );
    mocks.postAmortizationExclusionUndo.mockResolvedValue({
      ok: true,
      decisions: decisions(),
    });
    renderPage();
    await screen.findByRole("heading", { name: "Banco de Bogotá" });
    const panel = document.querySelector(".current-phase-panel") as HTMLElement;
    await within(panel).findByText("Excluido: crédito 133 · CLIENTE 133");
    await user.click(within(panel).getByRole("button", { name: "Deshacer" }));
    await waitFor(() =>
      expect(mocks.postAmortizationExclusionUndo).toHaveBeenCalledWith(
        "banco_bogota",
        PROCESS_KEY,
        "133",
      ),
    );
    await waitFor(() =>
      expect(within(panel).queryByText(/Excluido: crédito 133/)).not.toBeInTheDocument(),
    );
  });

  it("modal: excluir desde el problema llama al endpoint y el modal sigue abierto", async () => {
    const user = userEvent.setup();
    mocks.fetchProcess.mockResolvedValue(amortDetail({ amortization_decisions: decisions() }));
    mocks.postAmortizationExclusion.mockResolvedValue({
      ok: true,
      decisions: decisions({
        excluded: [excludedRow({ motivo: "Se aplicará manualmente" })],
        planned_lines: 1,
        planned_tables: 1,
      }),
    });
    renderPage();
    await screen.findByRole("heading", { name: "Banco de Bogotá" });
    const bannerBtn = await screen.findByRole("button", { name: /Ver problemas/i });
    await user.click(bannerBtn);
    const dialog = await screen.findByRole("dialog");
    const excludeButtons = within(dialog).getAllByRole("button", { name: /^Excluir crédito \d+$/ });
    expect(excludeButtons.map((b) => b.textContent)).toEqual([
      "Excluir crédito 133",
      "Excluir crédito 250",
    ]);
    const card133 = excludeButtons[0].closest(".error-box") as HTMLElement;
    expect(card133).toHaveAttribute("data-issue-id", "amort-CONCILIACION_ASIENTOS_MAYOR_BANCO-133-0");
    await user.click(excludeButtons[0]);
    expect(
      within(card133).getByRole("group", { name: "Excluir crédito 133 · CLIENTE 133" }),
    ).toBeInTheDocument();
    await user.click(within(card133).getByLabelText("Se aplicará manualmente"));
    await user.click(within(card133).getByRole("button", { name: "Excluir crédito 133" }));
    await waitFor(() =>
      expect(mocks.postAmortizationExclusion).toHaveBeenCalledWith(
        "banco_bogota",
        PROCESS_KEY,
        "133",
        "APLICACION_MANUAL",
        "",
      ),
    );
    expect(await within(dialog).findByText(/Excluido · Se aplicará manualmente/)).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    const panel = document.querySelector(".current-phase-panel") as HTMLElement;
    expect(within(panel).getByText("Se registrarán 1 línea en 1 tabla")).toBeInTheDocument();
  });

  it("la confirmación de cierre enumera los créditos excluidos", async () => {
    const user = userEvent.setup();
    mocks.fetchProcess.mockResolvedValue(
      amortDetail({
        operational_status: "AMORTIZACION_PARCIAL",
        control_estado_proceso: "AMORTIZACION_PARCIAL",
        available_actions: {
          amortization: { allowed: true, reason: null },
          soft_close: { allowed: true, reason: null },
        },
        last_amortization_attempt: {
          attempt_id: "att-2",
          outcome: "partial",
          created_at: "2026-08-01T11:00:00-05:00",
          operational_issues: [],
          affected_payment_ids: [],
          user_message: null,
          next_action: null,
        },
        amortization_decisions: decisions({
          excluded: [
            excludedRow({ can_undo: false }),
            excludedRow({ credit: "102", client_name: "CLIENTE 102", can_undo: false }),
          ],
        }),
      }),
    );
    renderPage();
    await screen.findByRole("heading", { name: "Banco de Bogotá" });
    await user.click(
      await screen.findByRole("button", { name: /Cerrar con amortización incompleta/i }),
    );
    const dialog = await screen.findByRole("dialog");
    expect(
      within(dialog).getByText(
        "El proceso se cerrará con 2 créditos sin amortizar: 133 · CLIENTE 133, 102 · CLIENTE 102.",
      ),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByText(
        "Ya hay tablas de amortización aplicadas en este proceso; esas escrituras se conservan. Los créditos pendientes no se aplicarán automáticamente; deberán aplicarse de forma manual. Los asientos usados se moverán a Procesados y el banco quedará libre para un nuevo lote.",
      ),
    ).toBeInTheDocument();
    expect(dialog.textContent).not.toMatch(/\bAPI\b/);
    expect(within(dialog).queryByRole("textbox")).toBeNull();
    expect(within(dialog).getByRole("button", { name: "Volver" })).toBeEnabled();
    mocks.postSoftClose.mockRejectedValue(new Error("sin red"));
    await user.click(within(dialog).getByRole("button", { name: "Confirmar cierre" }));
    await waitFor(() =>
      expect(mocks.postSoftClose).toHaveBeenCalledWith("banco_bogota", PROCESS_KEY),
    );
  });

  function partialDetail(
    decisionsOverrides: Partial<UiAmortizationDecisions>,
    issues: UiOperationalIssue[] = [],
  ): UiProcessDetail {
    return amortDetail({
      operational_status: "FINALIZADO_PARCIALMENTE",
      operational_message: "Hay avances parciales; revise lo pendiente y continúe.",
      control_estado_proceso: "AMORTIZACION_PARCIAL",
      available_actions: {
        amortization: { allowed: true, reason: null },
        soft_close: { allowed: true, reason: null },
      },
      last_amortization_attempt: {
        attempt_id: "att-3",
        outcome: "partial",
        created_at: "2026-08-01T12:00:00-05:00",
        operational_issues: issues,
        affected_payment_ids: [],
        user_message: null,
        next_action: null,
      },
      amortization_decisions: decisions(decisionsOverrides),
    });
  }

  it("parcial sin nada pendiente: sin Procesar, mensaje de cierre y un solo botón de cierre", async () => {
    mocks.fetchProcess.mockResolvedValue(
      partialDetail({
        excluded: [excludedRow({ can_undo: false })],
        planned_lines: 0,
        planned_tables: 0,
        applied_credits: ["250"],
      }),
    );
    renderPage();
    await screen.findByRole("heading", { name: "Banco de Bogotá" });
    const panel = document.querySelector(".current-phase-panel") as HTMLElement;
    expect(
      await within(panel).findByText(
        "No quedan créditos por procesar. Para terminar, use Cerrar con amortización incompleta.",
      ),
    ).toBeInTheDocument();
    expect(within(panel).getByText("Ya quedó registrado 1 crédito en su tabla.")).toBeInTheDocument();
    expect(within(panel).queryByRole("button", { name: "Procesar amortización" })).toBeNull();
    expect(within(panel).queryByText(/Se registrarán/)).toBeNull();
    expect(within(panel).queryByText("No hay acciones pendientes en esta fase.")).toBeNull();
    expect(within(panel).queryByText("Puede procesar la amortización desde la UI.")).toBeNull();
    expect(document.body.textContent).not.toContain("Hay avances parciales");
    expect(
      screen.getAllByRole("button", { name: /Cerrar con amortización incompleta/i }),
    ).toHaveLength(1);
  });

  it("parcial con problemas abiertos conserva Procesar y cuenta solo lo pendiente", async () => {
    mocks.fetchProcess.mockResolvedValue(
      partialDetail(
        { planned_lines: 2, planned_tables: 1, applied_credits: ["250"] },
        [conciliationIssue("133", ["133"])],
      ),
    );
    renderPage();
    await screen.findByRole("heading", { name: "Banco de Bogotá" });
    const panel = document.querySelector(".current-phase-panel") as HTMLElement;
    expect(
      await within(panel).findByRole("button", { name: "Procesar amortización" }),
    ).toBeInTheDocument();
    expect(within(panel).getByText("Quedan 2 líneas por registrar en 1 tabla.")).toBeInTheDocument();
    expect(within(panel).queryByText(/No quedan créditos por procesar/)).toBeNull();
    expect(within(panel).queryByText(/Se registrarán/)).toBeNull();
  });

  it("amortización interrumpida por reinicio: ofrece Procesar y Cerrar con amortización incompleta", async () => {
    const user = userEvent.setup();
    mocks.fetchProcess.mockResolvedValue(
      amortDetail({
        operational_status: "ERROR_RECUPERABLE",
        operational_title: "Amortización interrumpida",
        operational_message:
          "La amortización se interrumpió antes de terminar (por ejemplo, por un reinicio del servidor). Vuelva a procesar la amortización: lo que ya quedó registrado en las tablas no se duplica. Si no va a continuar, use Cerrar con amortización incompleta.",
        control_estado_proceso: "APLICANDO_AMORTIZACION",
        steps: [
          ...completedSteps,
          {
            name: "apply",
            status: "failed_retryable",
            updated_at: null,
            summary: "La amortización se interrumpió antes de terminar.",
            can_retry: true,
            retry_action: "retry_apply",
          },
        ],
        available_actions: {
          amortization: { allowed: true, reason: null },
          soft_close: { allowed: true, reason: null },
        },
        last_amortization_attempt: null,
        amortization_decisions: decisions(),
      }),
    );
    renderPage();
    await screen.findByRole("heading", { name: "Banco de Bogotá" });
    expect(await screen.findByText("Amortización interrumpida")).toBeInTheDocument();
    expect(screen.getByText(/se interrumpió antes de terminar/)).toBeInTheDocument();
    const panel = document.querySelector(".current-phase-panel") as HTMLElement;
    const process = within(panel).getByRole("button", { name: "Procesar amortización" });
    expect(process).toBeEnabled();
    const close = screen.getAllByRole("button", { name: /Cerrar con amortización incompleta/i });
    expect(close).toHaveLength(1);
    await user.click(close[0]);
    const dialog = await screen.findByRole("dialog");
    expect(
      within(dialog).getByText(/La amortización se interrumpió antes de terminar y pudo dejar tablas/),
    ).toBeInTheDocument();
  });

  it.each([
    ["CERRADO_AMORTIZACION_INCOMPLETA", "CERRADO_AMORTIZACION_INCOMPLETA"],
    ["CERRADO_SIN_AMORTIZAR", "CERRADO_SIN_AMORTIZAR"],
    ["CANCELADO", "CANCELADO"],
  ])(
    "proceso %s: no muestra como vigentes los problemas del último intento ni Excluir crédito",
    async (operational, control) => {
      mocks.fetchProcess.mockResolvedValue(
        amortDetail({
          operational_status: operational,
          control_estado_proceso: control,
          is_active: false,
          available_actions: {},
          operational_issues: [conciliationIssue("151", ["151"])],
          amortization_decisions: decisions(),
        }),
      );
      renderPage();
      await screen.findByRole("heading", { name: "Banco de Bogotá" });
      await waitFor(() =>
        expect(document.querySelector("[aria-labelledby='process-soft-closed-title'], [aria-labelledby='process-completed-title']")).toBeTruthy(),
      );
      expect(document.getElementById("amortization-issues-banner-title")).toBeNull();
      expect(document.body.textContent).not.toMatch(/problema\(s\) de amortización/);
      expect(screen.queryByRole("button", { name: /Ver problemas/i })).toBeNull();
      expect(screen.queryByRole("button", { name: /Excluir crédito/i })).toBeNull();
    },
  );

  it("proceso cerrado con amortización incompleta lista los créditos sin amortizar", async () => {
    mocks.fetchProcess.mockResolvedValue(
      amortDetail({
        operational_status: "CERRADO_AMORTIZACION_INCOMPLETA",
        control_estado_proceso: "CERRADO_AMORTIZACION_INCOMPLETA",
        is_active: false,
        available_actions: {},
        last_amortization_attempt: null,
        amortization_decisions: decisions({
          credits_not_amortized: [
            excludedRow({
              can_undo: false,
              table_link: {
                rel: "amortization_table",
                label: "Abrir tabla",
                path: "clientes/X/tabla.xlsx",
                web_url: "https://example.com/tabla-133.xlsx",
                open_mode: "sharepoint",
              },
            }),
            excludedRow({
              credit: "148",
              client_name: "INVERSIONES FLOREZ",
              motivo: "Se aplicará manualmente",
              can_undo: false,
              table_link: null,
            }),
          ],
        }),
      }),
    );
    renderPage();
    await screen.findByRole("heading", { name: "Banco de Bogotá" });
    expect(await screen.findByText("Créditos sin amortizar")).toBeInTheDocument();
    const table = screen.getByRole("table", { name: "Créditos sin amortizar" });
    expect(
      within(table)
        .getAllByRole("columnheader")
        .map((th) => th.textContent),
    ).toEqual(["Crédito", "Cliente", "Motivo", "Tabla"]);
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(2);
    expect(
      within(rows[0])
        .getAllByRole("cell")
        .map((td) => td.textContent),
    ).toEqual(["133", "CLIENTE 133", "Falta el asiento de Contabilidad", "Abrir tabla"]);
    const tableLink = within(rows[0]).getByRole("link", {
      name: "Abrir tabla de amortización del crédito 133",
    });
    expect(tableLink).toHaveAttribute("href", "https://example.com/tabla-133.xlsx");
    expect(tableLink).toHaveClass("card-link");
    expect(tableLink.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
    expect(
      within(rows[1])
        .getAllByRole("cell")
        .map((td) => td.textContent),
    ).toEqual(["148", "INVERSIONES FLOREZ", "Se aplicará manualmente", "—"]);
    expect(document.body.textContent).not.toContain("133 · CLIENTE 133 — ");
  });
});
