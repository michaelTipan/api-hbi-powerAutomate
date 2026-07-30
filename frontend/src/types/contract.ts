/** Tipos alineados al contrato docs/ui-api-contract-v1.md */

export type OperationalStatus =
  | "NUEVO"
  | "GENERANDO"
  | "EN_REVISION"
  | "FINALIZANDO"
  | "NOTIFICANDO"
  | "ESPERANDO_SOPORTES"
  | "CONSOLIDANDO"
  | "VALIDANDO_AMORTIZACION"
  | "LISTO_PARA_APLICAR"
  | "APLICANDO"
  | "COMPLETADO"
  | "FINALIZADO_PARCIALMENTE"
  | "ERROR_RECUPERABLE"
  | "CORRECCION_REQUERIDA"
  | "REVISION_MANUAL"
  | "CANCELADO"
  | "DESCONOCIDO";

export type StepName =
  | "generate"
  | "review"
  | "finalize"
  | "notify"
  | "merge"
  | "dry_run"
  | "apply";

export type StepStatus =
  | "not_started"
  | "in_progress"
  | "completed"
  | "failed_retryable"
  | "failed_business"
  | "blocked"
  | "skipped"
  | "partial";

export interface UiLink {
  rel: string;
  label: string;
  path: string | null;
  web_url: string | null;
  open_mode: "sharepoint" | "external";
}

export interface UiError {
  stage: string | null;
  severity: string;
  error_code: string | null;
  user_message: string;
  next_action: string | null;
  payment_id: string | null;
  client_name: string | null;
  credit: string | null;
  link: UiLink | null;
}

export interface UiStepState {
  name: StepName;
  status: StepStatus;
  updated_at: string | null;
  summary: string | null;
  can_retry: boolean;
  retry_action: string | null;
}

export interface UiActiveJob {
  job_id: string;
  type: string;
  status: string;
  store: "job_manager" | "sharepoint_memory" | "none";
  poll_path_graph: string | null;
  poll_path_ui: string;
  started_at: string | null;
  progress: Record<string, unknown> | null;
}

export interface UiNextAction {
  code: string;
  label: string;
  enabled: boolean;
  reason: string | null;
}

export interface UiProcessFiles {
  validation_file_path: string | null;
  historical_file_path: string | null;
  secretary_file_path: string | null;
  email_pdf_path: string | null;
  merge_manifest_path: string | null;
  control_file_path: string | null;
  execution_log_path: string | null;
}

export interface UiProcessDetail {
  process_key: string;
  process_id: string | null;
  bank_code: string;
  bank_name: string | null;
  process_date: string | null;
  environment: string;
  operational_status: OperationalStatus;
  control_estado_proceso: string | null;
  is_active: boolean;
  steps: UiStepState[];
  items: unknown[];
  active_job: UiActiveJob | null;
  attempts: unknown[];
  next_actions: UiNextAction[];
  available_actions?: Record<string, { allowed: boolean; reason: string | null }>;
  operator_checklist?: string[];
  errors: UiError[];
  links: UiLink[];
  files: UiProcessFiles;
  idempotency: {
    notify_idempotency_key: string | null;
    merge_idempotency_key: string | null;
    apply_idempotency_key: string | null;
  };
  trigger_source: string | null;
  requested_by: string | null;
}

export interface UiProcessSummary {
  process_key: string;
  bank_code: string;
  process_date: string | null;
  environment: string;
  operational_status: OperationalStatus;
  control_estado_proceso: string | null;
  is_active: boolean;
  error_count: number;
  next_actions: UiNextAction[];
}

export interface UiEnvironmentResponse {
  environment: string;
  display_label: string;
  ui_enabled: boolean;
  ui_write_enabled: boolean;
  ui_auth_mode: string;
}

/** Respuesta pública de GET /api/ui/v1/bootstrap (sin secretos). */
export interface UiBootstrapResponse {
  ui_enabled: boolean;
  writes_allowed: boolean;
  finalize_allowed?: boolean;
  active_environment: string;
  display_label: string;
  auth_mode: string;
  login_required: boolean;
  entra_authority?: string;
  entra_spa_client_id?: string;
  entra_api_scope?: string;
}

export interface UiProcessListResponse {
  environment: string;
  items: UiProcessSummary[];
}

export interface UiJobView {
  job_id: string;
  type: string | null;
  status: string;
  store: string;
  process_key: string | null;
  bank_code: string | null;
  environment: string;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  result_summary: Record<string, unknown> | null;
  error: Record<string, unknown> | null;
  user_message?: string | null;
  next_action?: string | null;
  severity?: string | null;
  raw_available: boolean;
}
