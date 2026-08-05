/** Tipos alineados al contrato docs/ui-api-contract-v1.md */

export type OperationalStatus =
  | "NUEVO"
  | "GENERANDO"
  | "EN_REVISION"
  | "FINALIZANDO"
  | "PENDIENTE_NOTIFICACION"
  | "NOTIFICANDO"
  | "ESPERANDO_SOPORTES"
  | "CONSOLIDANDO"
  | "VALIDANDO_AMORTIZACION"
  | "LISTO_PARA_APLICAR"
  | "APLICANDO"
  | "COMPLETADO"
  | "FINALIZADO_PARCIALMENTE"
  | "SINCRONIZANDO"
  | "ERROR_RECUPERABLE"
  | "CORRECCION_REQUERIDA"
  | "REVISION_MANUAL"
  | "CANCELADO"
  | "CERRADO_SIN_AMORTIZAR"
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
  | "sync_pending"
  | "blocked"
  | "skipped"
  | "partial";

export type ErrorSeverity =
  | "info"
  | "warning"
  | "recoverable"
  | "business"
  | "fatal";

export interface UiLink {
  rel: string;
  label: string;
  path: string | null;
  web_url: string | null;
  open_mode: "sharepoint" | "external";
}

/** Conjunto N de enlaces para drawer (PDFs consolidados, tablas amort.). */
export interface UiDocumentGroup {
  id: string;
  title: string;
  count: number;
  links: UiLink[];
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

/** Resumen operativo de soportes antes de consolidar (GET proceso). */
export interface UiMergeReadiness {
  status: "ready" | "incomplete" | "unknown" | "already_merged";
  expected_groups: number;
  ready_groups: number;
  missing_groups: number;
  missing_items: Array<Record<string, unknown>>;
  folder_links: Array<{
    rel?: string;
    label?: string;
    path?: string | null;
    web_url?: string | null;
    credito?: string | null;
  }>;
  user_message: string;
  next_action: string;
  checked_at: string | null;
}

/** Respuesta 202 de POST /api/ui/v1/processes/merge. */
export interface UiMergeAccepted {
  accepted: boolean;
  action: "merge" | string;
  bank_code: string;
  process_key: string;
  job_id: string;
  status: string;
  poll_url: string;
}

/** Resumen operativo liviano antes de procesar amortización (GET proceso). */
export interface UiAmortizationReadiness {
  status: "ready" | "incomplete" | "unknown" | "already_applied";
  can_start: boolean;
  expected_items: number;
  ready_items: number;
  missing_items: Array<Record<string, unknown>>;
  warnings: string[];
  user_message: string;
  next_action: string;
  checked_at: string | null;
}

/** Respuesta 202 de POST /api/ui/v1/processes/amortization. */
export interface UiAmortizationAccepted {
  accepted: boolean;
  action: "amortization" | string;
  bank_code: string;
  process_key: string;
  job_id: string;
  status: string;
  poll_url: string;
}

/** Último intento relevante por etapa (puede ser terminal). No confundir con active_job. */
export interface UiLastAttempt {
  stage: StepName | string;
  job_id: string;
  job_type: string;
  status: string;
  outcome: string | null;
  recoverable: boolean;
  error_code: string | null;
  severity: ErrorSeverity | null;
  user_message: string | null;
  next_action: string | null;
  started_at: string | null;
  finished_at: string | null;
  progress: Record<string, unknown> | null;
  technical_reference: string | null;
}

export interface UiIssueLocation {
  file_name: string | null;
  sheet: string | null;
  row: number | null;
  column: string | null;
  credit: string | null;
  payment_id: string | null;
  client_name: string | null;
}

export interface UiIssueRetry {
  allowed: boolean;
  action: string | null;
  label: string | null;
}

export type IssueCategory =
  | "correction_required"
  | "temporary_failure"
  | "system_failure"
  | "warning"
  | "partial_result";

export interface UiOperationalIssue {
  issue_id: string;
  stage: StepName | string | null;
  category: IssueCategory;
  severity: ErrorSeverity;
  recoverable: boolean;
  title: string;
  user_message: string;
  location: UiIssueLocation | null;
  value_found: string | null;
  expected_values: string[];
  next_action: string | null;
  retry: UiIssueRetry | null;
  links: UiLink[];
  technical_reference: string | null;
}

export interface UiLastAmortizationAttempt {
  attempt_id: string;
  outcome:
    | "requires_correction"
    | "failed"
    | "partial"
    | "applied"
    | "already_applied";
  created_at: string | null;
  operational_issues: UiOperationalIssue[];
  affected_payment_ids: string[];
  user_message: string | null;
  next_action: string | null;
}

export interface UiProcessDetail {
  process_key: string;
  process_id: string | null;
  bank_code: string;
  bank_name: string | null;
  process_date: string | null;
  environment: string;
  operational_status: OperationalStatus;
  operational_title?: string;
  operational_message?: string;
  control_estado_proceso: string | null;
  is_active: boolean;
  steps: UiStepState[];
  items: unknown[];
  active_job: UiActiveJob | null;
  last_attempt: UiLastAttempt | null;
  latest_attempts_by_stage: Record<string, UiLastAttempt>;
  attempts: unknown[];
  next_actions: UiNextAction[];
  /** Puede incluir generate, finalize, notify, merge, amortization. */
  available_actions?: Record<string, { allowed: boolean; reason: string | null }>;
  operator_checklist?: string[];
  errors: UiError[];
  operational_issues: UiOperationalIssue[];
  technical_status_reference?: string | null;
  links: UiLink[];
  /** Aditivo: grupos N para catálogo/drawer (no reemplaza links 1:1). */
  document_groups?: UiDocumentGroup[];
  files: UiProcessFiles;
  idempotency: {
    notify_idempotency_key: string | null;
    merge_idempotency_key: string | null;
    apply_idempotency_key: string | null;
  };
  merge_readiness?: UiMergeReadiness | null;
  amortization_readiness?: UiAmortizationReadiness | null;
  last_amortization_attempt?: UiLastAmortizationAttempt | null;
  trigger_source: string | null;
  requested_by: string | null;
}

export interface UiProcessSummary {
  process_key: string;
  bank_code: string;
  process_date: string | null;
  environment: string;
  operational_status: OperationalStatus;
  operational_title?: string;
  operational_message?: string;
  control_estado_proceso: string | null;
  is_active: boolean;
  error_count: number;
  next_actions: UiNextAction[];
  /** webUrl del Excel de revisión (si Graph lo resolvió). */
  review_excel_web_url?: string | null;
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
  notify_allowed?: boolean;
  merge_allowed?: boolean;
  amortization_allowed?: boolean;
  notify_test_recipients_configured?: boolean;
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
  /** Bancos cuyo Control no se pudo leer: lista vacía ≠ "no hay procesos". */
  unavailable_banks?: string[];
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
  progress?: Record<string, unknown> | null;
  raw_available: boolean;
}
