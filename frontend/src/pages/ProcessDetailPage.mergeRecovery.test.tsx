import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import type {
  UiBootstrapResponse,
  UiMergeReadiness,
  UiMergeVerification,
  UiOperationalIssue,
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
  postCancelLote: vi.fn(),
  postSoftClose: vi.fn(),
  postAmortizationExclusion: vi.fn(),
  postAmortizationExclusionUndo: vi.fn(),
  postConciliationConfirmation: vi.fn(),
  postConciliationConfirmationUndo: vi.fn(),
  mergeDecisions: {
    exclude: mocks.exclude,
    undoExclude: vi.fn(),
    confirm: vi.fn(),
    undoConfirm: vi.fn(),
    assign: vi.fn(),
    undoAssign: vi.fn(),
    markUnused: vi.fn(),
    undoUnused: vi.fn(),
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

const PROCESS_KEY = "payment-validation|banco_bogota|2026-09-30|recovery-1";

function step(name: string, status: string): UiProcessDetail["steps"][number] {
  return { name: name as never, status, updated_at: null, summary: null, can_retry: false, retry_action: null };
}

function formatIssue(credit: string): UiOperationalIssue {
  return {
    issue_id: `amort-ACCOUNTING_PARSE_FAILED-${credit}-0`,
    stage: "amortization",
    category: "correction_required",
    severity: "business",
    recoverable: true,
    title: `Documento contable · Crédito ${credit}`,
    user_message: "El PDF no tiene el formato de asiento contable esperado.",
    location: {
      file_name: "A.pdf",
      sheet: null,
      row: null,
      column: null,
      credit,
      payment_id: "P1",
      client_name: null,
    },
    value_found: null,
    expected_values: [],
    next_action: "Corrija el PDF, reconsolide y procese la amortización.",
    retry: null,
    links: [],
    technical_reference: "ACCOUNTING_PARSE_FAILED",
    reconsolidate: true,
  } as UiOperationalIssue;
}

function readiness(v: UiMergeVerification): UiMergeReadiness {
  const ready = v.credits_attention === 0 && !v.all_excluded;
  return {
    status: ready ? "ready" : "incomplete",
    expected_groups: v.groups.length,
    ready_groups: v.groups.filter((g) => g.status === "ready").length,
    missing_groups: v.groups.filter((g) => g.status === "attention").length,
    missing_items: [],
    folder_links: [],
    user_message: `${v.credits_ready} de ${v.credits_total} créditos listos para consolidar.`,
    next_action: "",
    checked_at: null,
    verification: v,
  };
}

function partialDetail(v: UiMergeVerification): UiProcessDetail {
  return {
    process_key: PROCESS_KEY,
    process_id: "recovery-1",
    bank_code: "banco_bogota",
    bank_name: "Banco de Bogotá",
    process_date: "2026-09-30",
    environment: "sandbox",
    operational_status: "FINALIZADO_PARCIALMENTE",
    control_estado_proceso: "AMORTIZACION_PARCIAL",
    is_active: true,
    steps: [
      step("generate", "completed"),
      step("review", "completed"),
      step("finalize", "completed"),
      step("notify", "completed"),
      step("merge", "completed"),
      step("dry_run", "completed"),
      step("apply", "partial"),
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
      merge: { allowed: false, reason: "Los asientos contables de este proceso ya fueron consolidados." },
      force_rebuild: { allowed: true, reason: null },
      amortization: { allowed: true, reason: null },
      soft_close: { allowed: true, reason: null },
    },
    errors: [],
    operational_issues: [formatIssue("133")],
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
      merge_idempotency_key: PROCESS_KEY,
      apply_idempotency_key: null,
    },
    trigger_source: null,
    requested_by: null,
    operator_checklist: [],
    merge_readiness: readiness(v),
    amortization_readiness: null,
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

async function goToReconsolidate() {
  const user = userEvent.setup();
  renderPage();
  await screen.findByRole("heading", { name: "Banco de Bogotá" });
  await user.click(await screen.findByRole("button", { name: /Ver problemas de amortización/i }));
  await user.click(
    await screen.findByRole("button", { name: /Ya corregí los asientos — ir a reconsolidar/i }),
  );
  await screen.findByText(/Está aquí para reconsolidar/i);
  return user;
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

describe("ProcessDetailPage — reconsolidar tras amortización parcial", () => {
  it("si la verificación pide decisiones, muestra el panel con acciones y la salida de cierre", async () => {
    const v = verification([group(), twoPaymentGroup()]);
    mocks.fetchProcess.mockResolvedValue(partialDetail(v));
    await goToReconsolidate();

    const card = document.querySelector(".merge-credits-card") as HTMLElement;
    expect(within(card).getByRole("heading", { name: "Créditos del lote" })).toBeInTheDocument();
    expect(within(card).getByRole("button", { name: "Asignar" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Reconsolidar PDF$/i })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /^Cerrar con amortización incompleta$/i }),
    ).toBeInTheDocument();
  });

  it("excluir el crédito pendiente llama al servicio de decisiones de fase 3", async () => {
    const v = verification([group(), twoPaymentGroup()]);
    const after = verification([
      group(),
      twoPaymentGroup({
        status: "excluded",
        motivos: [],
        primary_action: null,
        exclusion: { motivo: "Se aplicará manualmente", motivo_codigo: "APLICACION_MANUAL", can_undo: true },
      }),
    ]);
    mocks.fetchProcess.mockResolvedValueOnce(partialDetail(v)).mockResolvedValue(partialDetail(after));
    mocks.exclude.mockResolvedValue({ ok: true, merge_readiness: readiness(after) });
    const user = await goToReconsolidate();

    const card = document.querySelector(".merge-credits-card") as HTMLElement;
    const row = within(card).getByText("CLIENTE DOS FECHAS").closest("tr") as HTMLElement;
    await user.click(within(row).getByRole("button", { name: "Revisar" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Excluir crédito 133" }));
    await user.click(within(dialog).getByLabelText("Se aplicará manualmente"));
    await user.click(within(dialog).getByRole("button", { name: "Excluir crédito 133" }));
    await waitFor(() =>
      expect(mocks.exclude).toHaveBeenCalledWith("banco_bogota", PROCESS_KEY, "133", "APLICACION_MANUAL", ""),
    );
  });

  it("sin créditos que decidir, conserva el resumen de recuperación", async () => {
    const v = verification([group()]);
    mocks.fetchProcess.mockResolvedValue(partialDetail(v));
    await goToReconsolidate();

    expect(document.querySelector(".merge-credits-card")).toBeNull();
  });
});
