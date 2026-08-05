import type {
  UiBootstrapResponse,
  UiEnvironmentResponse,
  UiJobView,
  UiProcessDetail,
  UiProcessListResponse,
  UiProcessSummary,
} from "../../src/types/contract";
import type { UiMeResponse } from "../../src/types/auth";

export const E2E_CSRF = "e2e-csrf-token-fixed";
export const E2E_USERNAME = "operador.pruebas";
export const E2E_PASSWORD = "Pruebas123!";

export const bootstrapEnabled: UiBootstrapResponse = {
  ui_enabled: true,
  writes_allowed: true,
  finalize_allowed: true,
  notify_allowed: true,
  merge_allowed: true,
  amortization_allowed: true,
  notify_test_recipients_configured: true,
  active_environment: "sandbox",
  display_label: "Entorno de validación (E2E)",
  auth_mode: "local_session",
  login_required: true,
  entra_authority: "",
  entra_spa_client_id: "",
  entra_api_scope: "",
};

export const environmentSandbox: UiEnvironmentResponse = {
  environment: "sandbox",
  display_label: "Entorno de validación (E2E)",
  ui_enabled: true,
  ui_write_enabled: true,
  ui_auth_mode: "local_session",
};

export const meOperator: UiMeResponse = {
  authenticated: true,
  username: E2E_USERNAME,
  role: "operator",
  auth_mode: "local_session",
  expires_at: "2099-12-31T23:59:59-05:00",
};

export const reviewProcessKey =
  "payment-validation|banco_bancolombia|2026-08-05|e2e-review";

export const notifyProcessKey =
  "payment-validation|banco_bogota|2026-08-05|e2e-notify";

export const mergeProcessKey =
  "payment-validation|banco_bancolombia|2026-08-04|e2e-merge";

export const amortRecoveryProcessKey =
  "payment-validation|banco_bogota|2026-08-03|e2e-amort-recovery";

function baseProcess(
  overrides: Partial<UiProcessDetail> & Pick<UiProcessDetail, "process_key">,
): UiProcessDetail {
  return {
    process_id: overrides.process_key.split("|").pop() ?? "e2e",
    bank_code: "banco_bancolombia",
    bank_name: "Bancolombia",
    process_date: "2026-08-05",
    environment: "sandbox",
    operational_status: "EN_REVISION",
    control_estado_proceso: "REVISION_CREADA",
    is_active: true,
    steps: [
      {
        name: "generate",
        status: "completed",
        updated_at: null,
        summary: "Excel de revisión disponible.",
        can_retry: false,
        retry_action: null,
      },
      {
        name: "review",
        status: "in_progress",
        updated_at: null,
        summary: "Pendiente revisión humana.",
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
    next_actions: [],
    available_actions: {
      finalize: { allowed: true, reason: null },
      notify: { allowed: false, reason: "Complete la revisión primero." },
      merge: { allowed: false, reason: null },
      amortization: { allowed: false, reason: null },
    },
    operator_checklist: ["Abra el Excel de revisión y marque Procesar=SI."],
    errors: [],
    operational_issues: [],
    links: [
      {
        rel: "review_excel",
        label: "Abrir archivo de revisión",
        path: "02 VALIDACION PAGOS/01 REVISION/demo.xlsx",
        web_url: "https://example.sharepoint.com/review",
        open_mode: "sharepoint",
      },
    ],
    files: {
      validation_file_path: "02 VALIDACION PAGOS/01 REVISION/demo.xlsx",
      historical_file_path: null,
      secretary_file_path: null,
      email_pdf_path: null,
      merge_manifest_path: null,
      control_file_path: "control.xlsx",
      execution_log_path: null,
    },
    idempotency: {
      notify_idempotency_key: null,
      merge_idempotency_key: null,
      apply_idempotency_key: null,
    },
    merge_readiness: null,
    amortization_readiness: null,
    last_amortization_attempt: null,
    trigger_source: null,
    requested_by: null,
    ...overrides,
  };
}

export const reviewProcess = baseProcess({
  process_key: reviewProcessKey,
  bank_code: "banco_bancolombia",
  bank_name: "Bancolombia",
  operational_status: "EN_REVISION",
  available_actions: {
    finalize: { allowed: true, reason: null },
    notify: { allowed: false, reason: "Finalice la revisión primero." },
  },
});

export const finalizeReadyProcess = baseProcess({
  process_key: reviewProcessKey,
  operational_status: "EN_REVISION",
  available_actions: {
    finalize: { allowed: true, reason: null },
  },
});

export const notifyReadyProcess = baseProcess({
  process_key: notifyProcessKey,
  bank_code: "banco_bogota",
  bank_name: "Banco de Bogotá",
  operational_status: "PENDIENTE_NOTIFICACION",
  control_estado_proceso: "REVISION_FINALIZADA",
  available_actions: {
    notify: { allowed: true, reason: null },
    finalize: { allowed: false, reason: null },
  },
  steps: reviewProcess.steps.map((s) => {
    if (s.name === "review" || s.name === "finalize") {
      return { ...s, status: "completed" as const, summary: "Revisión finalizada." };
    }
    if (s.name === "notify") {
      return { ...s, status: "not_started" as const };
    }
    return s;
  }),
});

export const mergeReadyProcess = baseProcess({
  process_key: mergeProcessKey,
  process_date: "2026-08-04",
  operational_status: "ESPERANDO_SOPORTES",
  control_estado_proceso: "NOTIFICACION_ENVIADA",
  available_actions: {
    merge: { allowed: true, reason: null },
    notify: { allowed: false, reason: null },
  },
  steps: reviewProcess.steps.map((s) => {
    if (s.name === "review" || s.name === "finalize" || s.name === "notify") {
      return { ...s, status: "completed" as const, summary: "Completado." };
    }
    if (s.name === "merge") {
      return { ...s, status: "not_started" as const };
    }
    return s;
  }),
  merge_readiness: {
    status: "ready",
    expected_groups: 2,
    ready_groups: 2,
    missing_groups: 0,
    missing_items: [],
    folder_links: [],
    user_message: "Todos los soportes están listos.",
    next_action: "Puede consolidar.",
    checked_at: "2026-08-04T10:00:00-05:00",
  },
});

export const amortRecoveryProcess = baseProcess({
  process_key: amortRecoveryProcessKey,
  bank_code: "banco_bogota",
  bank_name: "Banco de Bogotá",
  process_date: "2026-08-03",
  operational_status: "CORRECCION_REQUERIDA",
  control_estado_proceso: "AMORTIZACION_REQUIERE_CORRECCION",
  available_actions: {
    amortization: { allowed: true, reason: null },
    merge: { allowed: true, reason: null },
  },
  steps: reviewProcess.steps.map((s) => {
    if (s.name === "apply" || s.name === "dry_run") {
      return { ...s, status: "not_started" as const };
    }
    if (s.name === "merge") {
      return { ...s, status: "completed" as const, summary: "PDF consolidado." };
    }
    return { ...s, status: "completed" as const, summary: "Completado." };
  }),
  last_amortization_attempt: {
    attempt_id: "attempt-e2e-1",
    outcome: "requires_correction",
    created_at: "2026-08-03T14:00:00-05:00",
    operational_issues: [
      {
        issue_id: "issue-format-1",
        stage: "apply",
        category: "correction_required",
        severity: "business",
        recoverable: true,
        title: "Formato de asiento incorrecto",
        user_message: "El asiento del crédito 12345 no cumple el formato esperado.",
        location: {
          file_name: "Asientos.xlsx",
          sheet: "ASIENTOS",
          row: 12,
          column: "MONTO",
          credit: "12345",
          payment_id: "PAY-001",
          client_name: "Cliente Demo",
        },
        value_found: "ABC",
        expected_values: ["numérico"],
        next_action: "Corrija el asiento y vuelva a procesar.",
        retry: { allowed: true, action: "amortization", label: "Procesar amortización" },
        links: [],
        technical_reference: "ACCOUNTING_PARSE_FAILED",
      },
    ],
    affected_payment_ids: ["PAY-001"],
    user_message: "Corrija los asientos señalados antes de reintentar.",
    next_action: "Revise los problemas de amortización.",
  },
  amortization_readiness: {
    status: "incomplete",
    can_start: false,
    expected_items: 1,
    ready_items: 0,
    missing_items: [{ credit: "12345" }],
    warnings: [],
    user_message: "Hay correcciones pendientes.",
    next_action: "Corrija los asientos.",
    checked_at: "2026-08-03T14:05:00-05:00",
  },
});

const processByKey: Record<string, UiProcessDetail> = {
  [reviewProcessKey]: reviewProcess,
  [notifyProcessKey]: notifyReadyProcess,
  [mergeProcessKey]: mergeReadyProcess,
  [amortRecoveryProcessKey]: amortRecoveryProcess,
};

export function summaryFromDetail(p: UiProcessDetail): UiProcessSummary {
  return {
    process_key: p.process_key,
    bank_code: p.bank_code,
    process_date: p.process_date,
    environment: p.environment,
    operational_status: p.operational_status,
    control_estado_proceso: p.control_estado_proceso,
    is_active: p.is_active,
    error_count: p.errors.length + p.operational_issues.length,
    next_actions: p.next_actions.slice(0, 3),
  };
}

export function mockProcessList(): UiProcessListResponse {
  return {
    environment: "sandbox",
    items: Object.values(processByKey).map(summaryFromDetail),
    unavailable_banks: [],
  };
}

export function getProcessDetail(processKey: string): UiProcessDetail | null {
  return processByKey[processKey] ?? null;
}

export function completedJob(
  jobId: string,
  processKey: string,
  type: string,
): UiJobView {
  return {
    job_id: jobId,
    type,
    status: "completed",
    store: "job_manager",
    process_key: processKey,
    bank_code: processKey.includes("banco_bogota") ? "banco_bogota" : "banco_bancolombia",
    environment: "sandbox",
    created_at: "2026-08-05T08:00:00-05:00",
    started_at: "2026-08-05T08:00:01-05:00",
    finished_at: "2026-08-05T08:05:00-05:00",
    result_summary: { process_key: processKey },
    error: null,
    raw_available: true,
  };
}

export const banksCapabilities = [
  {
    bank_code: "banco_bogota" as const,
    bank_name: "Banco Bogotá",
    available_actions: { generate: { allowed: true, reason: null } },
    dashboard_primary_action: "generate" as const,
  },
  {
    bank_code: "banco_bancolombia" as const,
    bank_name: "Bancolombia",
    available_actions: { generate: { allowed: true, reason: null } },
    dashboard_primary_action: "generate" as const,
  },
];

export const historyItems = [
  {
    process_key: mergeProcessKey,
    bank_code: "banco_bancolombia",
    bank_name: "Bancolombia",
    process_date: "2026-08-04",
    environment: "sandbox",
    operational_status: "COMPLETADO",
    control_estado_proceso: "AMORTIZACION_APLICADA",
    source: "archive" as const,
    read_only: true,
    closed_at: "2026-08-04T18:00:00-05:00",
    archive_reason: "amortization_applied",
  },
];
