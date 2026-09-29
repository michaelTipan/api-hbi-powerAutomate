import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import type {
  UiBootstrapResponse,
  UiMergeReadiness,
  UiMergeVerification,
  UiProcessDetail,
} from "../types/contract";
import { group, twoPaymentGroup, verification } from "../mocks/mergeVerification";

const mocks = vi.hoisted(() => ({
  fetchProcess: vi.fn(),
  fetchJob: vi.fn(),
  fetchBootstrap: vi.fn(),
  fetchBanks: vi.fn(),
  fetchNotifyRecipientsPreview: vi.fn(),
  exclude: vi.fn(),
  undoExclude: vi.fn(),
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
  postAmortizationExclusion: vi.fn(),
  postAmortizationExclusionUndo: vi.fn(),
  postConciliationConfirmation: vi.fn(),
  postConciliationConfirmationUndo: vi.fn(),
  mergeDecisions: {
    exclude: mocks.exclude,
    undoExclude: mocks.undoExclude,
    confirm: vi.fn(),
    undoConfirm: vi.fn(),
    assign: vi.fn(),
    undoAssign: vi.fn(),
    markUnused: vi.fn(),
    undoUnused: vi.fn(),
    useTipo: vi.fn(),
    undoTipo: vi.fn(),
  },
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

const PROCESS_KEY = "payment-validation|banco_bogota|2026-09-30|merge-1";

function step(name: string, status: string): UiProcessDetail["steps"][number] {
  return { name: name as never, status, updated_at: null, summary: null, can_retry: false, retry_action: null };
}

function readiness(v: UiMergeVerification | null, overrides: Partial<UiMergeReadiness> = {}): UiMergeReadiness {
  const ready = v ? v.credits_attention === 0 && !v.all_excluded : false;
  return {
    status: ready ? "ready" : "incomplete",
    expected_groups: v?.groups.length ?? 0,
    ready_groups: v ? v.groups.filter((g) => g.status === "ready").length : 0,
    missing_groups: v ? v.groups.filter((g) => g.status === "attention").length : 0,
    missing_items: [],
    folder_links: [],
    user_message: ready ? "Los asientos contables están listos para consolidar." : "Faltan asientos.",
    next_action: "",
    checked_at: null,
    verification: v,
    ...overrides,
  };
}

function mergeDetail(r: UiMergeReadiness, mergeAllowed: boolean): UiProcessDetail {
  return {
    process_key: PROCESS_KEY,
    process_id: "merge-1",
    bank_code: "banco_bogota",
    bank_name: "Banco de Bogotá",
    process_date: "2026-09-30",
    environment: "sandbox",
    operational_status: "ESPERANDO_SOPORTES",
    control_estado_proceso: "PENDIENTE_ASIENTOS",
    is_active: true,
    steps: [
      step("generate", "completed"),
      step("review", "completed"),
      step("finalize", "completed"),
      step("notify", "completed"),
      step("merge", "not_started"),
      step("dry_run", "not_started"),
      step("apply", "not_started"),
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
      merge: { allowed: mergeAllowed, reason: mergeAllowed ? null : "Faltan asientos." },
      amortization: { allowed: false, reason: null },
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
    merge_readiness: r,
  };
}

function excludedTransp() {
  return group({
    group_key: "95",
    credits: ["95"],
    clientes: { "95": "TRANSPORTES SINTETICO" },
    cliente: "TRANSPORTES SINTETICO",
    status: "excluded",
    exclusion: { motivo: "Se aplicará manualmente", motivo_codigo: "APLICACION_MANUAL", can_undo: true },
  });
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

describe("ProcessDetailPage — Consolidar con verificación por crédito", () => {
  it("muestra el resumen y la tabla de atención en la fase Consolidar", async () => {
    const v = verification([group(), twoPaymentGroup()]);
    mocks.fetchProcess.mockResolvedValue(mergeDetail(readiness(v), false));
    renderPage();
    await screen.findByRole("heading", { name: "Banco de Bogotá" });
    const panel = document.querySelector(".current-phase-panel") as HTMLElement;
    expect(await within(panel).findByText("1 de 2 créditos listos para consolidar.")).toBeInTheDocument();
    expect(within(panel).getByRole("heading", { name: "Requieren atención" })).toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: "Asignar" })).toBeInTheDocument();
  });

  it("la confirmación de Consolidar indica consolidados y excluidos", async () => {
    const user = userEvent.setup();
    const v = verification([group(), group({ group_key: "250", credits: ["250"] }), excludedTransp()]);
    mocks.fetchProcess.mockResolvedValue(mergeDetail(readiness(v), true));
    renderPage();
    await screen.findByRole("heading", { name: "Banco de Bogotá" });
    await user.click(await screen.findByRole("button", { name: /^Generar PDF consolidado$/i }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Se generarán 2 consolidados. Excluidos: 1")).toBeInTheDocument();
    expect(within(dialog).getByText("crédito 95 · TRANSPORTES SINTETICO")).toBeInTheDocument();
  });

  it("excluir desde Revisar guarda la decisión y actualiza el panel", async () => {
    const user = userEvent.setup();
    const pending = twoPaymentGroup();
    const before = verification([group(), pending]);
    const excludedPending = twoPaymentGroup({
      status: "excluded",
      motivos: [],
      primary_action: null,
      exclusion: { motivo: "Se aplicará manualmente", motivo_codigo: "APLICACION_MANUAL", can_undo: true },
    });
    const after = verification([group(), excludedPending]);
    mocks.fetchProcess
      .mockResolvedValueOnce(mergeDetail(readiness(before), false))
      .mockResolvedValue(mergeDetail(readiness(after), true));
    mocks.exclude.mockResolvedValue({ ok: true, merge_readiness: readiness(after) });
    renderPage();
    await screen.findByRole("heading", { name: "Banco de Bogotá" });
    const panel = document.querySelector(".current-phase-panel") as HTMLElement;
    const row = (await within(panel).findByText("CLIENTE DOS FECHAS")).closest("tr") as HTMLElement;
    await user.click(within(row).getByRole("button", { name: "Revisar" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Excluir crédito" }));
    await user.click(within(dialog).getByLabelText("Se aplicará manualmente"));
    await user.click(within(dialog).getByRole("button", { name: "Excluir" }));
    await waitFor(() =>
      expect(mocks.exclude).toHaveBeenCalledWith(
        "banco_bogota",
        PROCESS_KEY,
        "133",
        "APLICACION_MANUAL",
        "",
      ),
    );
    expect(await within(dialog).findByText(/Excluido/)).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Deshacer" })).toBeInTheDocument();
    expect(await within(panel).findByText("1 de 2 créditos listos para consolidar.")).toBeInTheDocument();
  });

  it("error del servidor al guardar: el mensaje queda visible dentro de la ventana", async () => {
    const user = userEvent.setup();
    const v = verification([group(), twoPaymentGroup()]);
    mocks.fetchProcess.mockResolvedValue(mergeDetail(readiness(v), false));
    mocks.exclude.mockRejectedValue(new Error("fallo de red"));
    renderPage();
    await screen.findByRole("heading", { name: "Banco de Bogotá" });
    const panel = document.querySelector(".current-phase-panel") as HTMLElement;
    const row = (await within(panel).findByText("CLIENTE DOS FECHAS")).closest("tr") as HTMLElement;
    await user.click(within(row).getByRole("button", { name: "Revisar" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Excluir crédito" }));
    await user.click(within(dialog).getByLabelText("Se aplicará manualmente"));
    await user.click(within(dialog).getByRole("button", { name: "Excluir" }));
    expect(await within(dialog).findByRole("alert")).not.toBeEmptyDOMElement();
    expect(within(dialog).getByRole("button", { name: "Cerrar" })).toBeEnabled();
  });

  it("registro de decisiones ilegible: sin panel, con el mensaje de reintento", async () => {
    const msg =
      "No pudimos leer las decisiones guardadas del proceso. Verifique de nuevo en unos minutos.";
    mocks.fetchProcess.mockResolvedValue(
      mergeDetail(readiness(null, { status: "unknown", user_message: msg }), false),
    );
    renderPage();
    await screen.findByRole("heading", { name: "Banco de Bogotá" });
    const panel = document.querySelector(".current-phase-panel") as HTMLElement;
    expect(await within(panel).findByText(msg)).toBeInTheDocument();
    expect(within(panel).queryByText(/créditos listos para consolidar/)).not.toBeInTheDocument();
  });
});
