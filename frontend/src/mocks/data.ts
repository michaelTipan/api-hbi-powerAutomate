import type {
  UiBootstrapResponse,
  UiEnvironmentResponse,
  UiJobView,
  UiProcessDetail,
  UiProcessListResponse,
} from "../types/contract";

export const mockBootstrap: UiBootstrapResponse = {
  ui_enabled: true,
  writes_allowed: false,
  active_environment: "sandbox",
  display_label: "SANDBOX / PRUEBAS",
  auth_mode: "mock",
  login_required: false,
  entra_authority: "",
  entra_spa_client_id: "",
  entra_api_scope: "",
};

const reviewProcess: UiProcessDetail = {
  process_key: "payment-validation|banco_bancolombia|2026-07-29|abc-123",
  process_id: "abc-123",
  bank_code: "banco_bancolombia",
  bank_name: "Bancolombia",
  process_date: "2026-07-29",
  environment: "sandbox",
  operational_status: "EN_REVISION",
  control_estado_proceso: "REVISION_CREADA",
  is_active: true,
  steps: [
    { name: "generate", status: "completed", updated_at: null, summary: "Excel de revisión disponible.", can_retry: false, retry_action: null },
    { name: "review", status: "in_progress", updated_at: null, summary: "Pendiente revisión humana en SharePoint.", can_retry: false, retry_action: null },
    { name: "finalize", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
    { name: "notify", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
    { name: "merge", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
    { name: "dry_run", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
    { name: "apply", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
  ],
  items: [],
  active_job: null,
  attempts: [],
  next_actions: [
    {
      code: "open_review_excel",
      label: "Abrir Excel de revisión en SharePoint",
      enabled: true,
      reason: null,
    },
  ],
  errors: [],
  links: [
    {
      rel: "review_excel",
      label: "Abrir Excel de revisión",
      path: "02 VALIDACION PAGOS/01 REVISION/validacion_pagos_demo.xlsx",
      web_url: "https://gecolsacat.sharepoint.com/sites/OperacionesHBICapital",
      open_mode: "sharepoint",
    },
  ],
  files: {
    validation_file_path: "02 VALIDACION PAGOS/01 REVISION/validacion_pagos_demo.xlsx",
    historical_file_path: null,
    secretary_file_path: null,
    email_pdf_path: null,
    merge_manifest_path: null,
    control_file_path: "02 VALIDACION PAGOS/90 ACCESO RESTRINGIDO/03 CONTROL TECNICO/control.xlsx",
    execution_log_path: null,
  },
  idempotency: {
    notify_idempotency_key: null,
    merge_idempotency_key: null,
    apply_idempotency_key: null,
  },
  trigger_source: null,
  requested_by: null,
};

const notifyFailed: UiProcessDetail = {
  ...reviewProcess,
  process_key: "payment-validation|banco_bogota|2026-07-28|def-456",
  process_id: "def-456",
  bank_code: "banco_bogota",
  bank_name: "Banco de Bogotá",
  process_date: "2026-07-28",
  operational_status: "ERROR_RECUPERABLE",
  control_estado_proceso: "ERROR_NOTIFY",
  steps: [
    { name: "generate", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
    { name: "review", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
    { name: "finalize", status: "completed", updated_at: null, summary: "Histórico formalizado.", can_retry: false, retry_action: null },
    {
      name: "notify",
      status: "failed_retryable",
      updated_at: null,
      summary: "Correo no enviado; Finalize se conserva.",
      can_retry: true,
      retry_action: "retry_notify",
    },
    { name: "merge", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
    { name: "dry_run", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
    { name: "apply", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
  ],
  next_actions: [
    {
      code: "retry_notify",
      label: "Reintentar correo (Notify)",
      enabled: false,
      reason: "Mutaciones no habilitadas en Fase U1 (solo lectura).",
    },
  ],
  errors: [
    {
      stage: "notify",
      severity: "recoverable",
      error_code: "ERROR_NOTIFY",
      user_message:
        "El correo de pagos no quedó confirmado. La finalización del Excel se conserva.",
      next_action:
        "Corrija destinatarios o el fallo de envío y reintente solo Notify cuando las mutaciones estén habilitadas.",
      payment_id: null,
      client_name: null,
      credit: null,
      link: null,
    },
  ],
  links: [
    {
      rel: "historical",
      label: "Abrir histórico del día",
      path: "02 VALIDACION PAGOS/03 HISTORICO/cartera.xlsx",
      web_url: "https://gecolsacat.sharepoint.com/sites/OperacionesHBICapital",
      open_mode: "sharepoint",
    },
  ],
  files: {
    ...reviewProcess.files,
    validation_file_path: null,
    historical_file_path: "02 VALIDACION PAGOS/03 HISTORICO/cartera.xlsx",
  },
};

const mergePartial: UiProcessDetail = {
  ...notifyFailed,
  process_key: "payment-validation|banco_bancolombia|2026-07-27|ghi-789",
  process_id: "ghi-789",
  bank_code: "banco_bancolombia",
  bank_name: "Bancolombia",
  process_date: "2026-07-27",
  operational_status: "FINALIZADO_PARCIALMENTE",
  control_estado_proceso: "MERGE_PARCIAL",
  steps: [
    { name: "generate", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
    { name: "review", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
    { name: "finalize", status: "completed", updated_at: null, summary: null, can_retry: false, retry_action: null },
    { name: "notify", status: "completed", updated_at: null, summary: "Correo registrado en control.", can_retry: false, retry_action: null },
    {
      name: "merge",
      status: "partial",
      updated_at: null,
      summary: "Consolidación parcial; faltan soportes.",
      can_retry: true,
      retry_action: "retry_merge",
    },
    {
      name: "dry_run",
      status: "blocked",
      updated_at: null,
      summary: "Bloqueado hasta completar Merge.",
      can_retry: false,
      retry_action: null,
    },
    { name: "apply", status: "not_started", updated_at: null, summary: null, can_retry: false, retry_action: null },
  ],
  next_actions: [
    {
      code: "open_asientos_pendientes",
      label: "Revisar asientos / soportes pendientes",
      enabled: true,
      reason: null,
    },
    {
      code: "retry_merge",
      label: "Reintentar consolidación (Merge)",
      enabled: false,
      reason: "Mutaciones no habilitadas en Fase U1 (solo lectura).",
    },
  ],
  errors: [
    {
      stage: "merge",
      severity: "business",
      error_code: "MERGE_PARCIAL",
      user_message:
        "La consolidación quedó parcial: faltan soportes en uno o más créditos.",
      next_action: "Complete asientos/extractos faltantes y reintente Merge.",
      payment_id: null,
      client_name: null,
      credit: null,
      link: null,
    },
  ],
  links: [
    {
      rel: "secretary_file",
      label: "Abrir Asientos_Pendientes",
      path: "historico/Asientos_Pendientes.xlsx",
      web_url: "https://gecolsacat.sharepoint.com/sites/OperacionesHBICapital",
      open_mode: "sharepoint",
    },
  ],
  files: {
    ...notifyFailed.files,
    secretary_file_path: "historico/Asientos_Pendientes.xlsx",
    email_pdf_path: "correos/ABONOS.pdf",
    merge_manifest_path: "trazabilidad/manifest.json",
  },
  idempotency: {
    notify_idempotency_key: "payment-validation|banco_bancolombia|2026-07-27|ghi-789",
    merge_idempotency_key: null,
    apply_idempotency_key: null,
  },
};

const byKey: Record<string, UiProcessDetail> = {
  [reviewProcess.process_key]: reviewProcess,
  [notifyFailed.process_key]: notifyFailed,
  [mergePartial.process_key]: mergePartial,
};

export const mockEnvironment: UiEnvironmentResponse = {
  environment: "sandbox",
  display_label: "SANDBOX / PRUEBAS",
  ui_enabled: true,
  ui_write_enabled: false,
  ui_auth_mode: "mock",
};

export function mockListProcesses(): UiProcessListResponse {
  return {
    environment: "sandbox",
    items: Object.values(byKey).map((p) => ({
      process_key: p.process_key,
      bank_code: p.bank_code,
      process_date: p.process_date,
      environment: p.environment,
      operational_status: p.operational_status,
      control_estado_proceso: p.control_estado_proceso,
      is_active: p.is_active,
      error_count: p.errors.length,
      next_actions: p.next_actions.slice(0, 3),
    })),
  };
}

export function mockGetProcess(processKey: string): UiProcessDetail | null {
  return byKey[processKey] ?? null;
}

export function mockGetJob(jobId: string): UiJobView | null {
  if (jobId !== "demo-job-1") return null;
  return {
    job_id: jobId,
    type: "generate",
    status: "completed",
    store: "job_manager",
    process_key: reviewProcess.process_key,
    bank_code: "banco_bancolombia",
    environment: "sandbox",
    created_at: "2026-07-29T08:00:00-05:00",
    started_at: "2026-07-29T08:00:01-05:00",
    finished_at: "2026-07-29T08:08:00-05:00",
    result_summary: { already_generated: false },
    error: null,
    raw_available: true,
  };
}
