import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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
  display_label: "SANDBOX / PRUEBAS",
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
    latest_attempts_by_stage: {},
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

function renderDetail(processKey: string) {
  return render(
    <MemoryRouter initialEntries={[`/processes/${encodeURIComponent(processKey)}`]}>
      <Routes>
        <Route path="/processes/:processKey" element={<ProcessDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ProcessDetailPage — lenguaje operativo", () => {
  it("no expone ProcessKey ni jerga técnica (Generate/Finalize) fuera de Detalles técnicos", async () => {
    const processKey = "payment-validation|banco_bogota|2026-07-31|abc-1";
    mocks.fetchBootstrap.mockResolvedValue(bootstrap);
    mocks.fetchProcess.mockResolvedValue(baseDetail({ process_key: processKey }));

    renderDetail(processKey);

    await screen.findByText("Banco de Bogotá");
    const text = document.body.textContent || "";
    expect(text).not.toMatch(/ProcessKey/i);
    expect(text).not.toMatch(/\bGenerate\b/);
    expect(text).not.toMatch(/\bFinalize\b/);
    expect(screen.getByText("Cierre de la revisión")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Finalizar revisión" })).toBeInTheDocument();
  });

  it("muestra el ProcessKey solo dentro de Detalles técnicos, plegado por defecto", async () => {
    const processKey = "payment-validation|banco_bogota|2026-07-31|abc-1";
    mocks.fetchBootstrap.mockResolvedValue(bootstrap);
    mocks.fetchProcess.mockResolvedValue(baseDetail({ process_key: processKey }));

    renderDetail(processKey);
    await screen.findByText("Banco de Bogotá");

    expect(screen.queryByText(processKey)).not.toBeInTheDocument();

    const trigger = screen.getByRole("button", { name: /Detalles técnicos/ });
    expect(trigger).toHaveAttribute("aria-expanded", "false");

    const user = userEvent.setup();
    await user.click(trigger);

    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText(processKey)).toBeInTheDocument();
  });
});
