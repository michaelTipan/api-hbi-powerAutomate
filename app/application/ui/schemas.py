"""DTOs del contrato UI v1 (Pydantic). Fase U1: lectura."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

OperationalStatus = Literal[
    "NUEVO",
    "GENERANDO",
    "EN_REVISION",
    "FINALIZANDO",
    "PENDIENTE_NOTIFICACION",
    "NOTIFICANDO",
    "ESPERANDO_SOPORTES",
    "CONSOLIDANDO",
    "VALIDANDO_AMORTIZACION",
    "LISTO_PARA_APLICAR",
    "APLICANDO",
    "COMPLETADO",
    "FINALIZADO_PARCIALMENTE",
    "SINCRONIZANDO",
    "ERROR_RECUPERABLE",
    "CORRECCION_REQUERIDA",
    "REVISION_MANUAL",
    "CANCELADO",
    "DESCONOCIDO",
]

StepName = Literal[
    "generate",
    "review",
    "finalize",
    "notify",
    "merge",
    "dry_run",
    "apply",
]

StepStatus = Literal[
    "not_started",
    "in_progress",
    "completed",
    "failed_retryable",
    "failed_business",
    "sync_pending",
    "blocked",
    "skipped",
    "partial",
]

# Estados de negocio por pago/crédito.
# Canónicos de Excel (EstadoPago en review_schema): NORMAL, ATRASADO, ADELANTADO,
# REVISION_MANUAL. Estados de pago retirados del flujo no se incluyen aquí.
# Operativos propios de la proyección UI: ESPERANDO_*, COMPLETADO, ERROR_CORREGIBLE.
BusinessStatus = Literal[
    "NORMAL",
    "ATRASADO",
    "ADELANTADO",
    "REVISION_MANUAL",
    "ESPERANDO_IBR",
    "ESPERANDO_SOPORTE",
    "COMPLETADO",
    "ERROR_CORREGIBLE",
    "DESCONOCIDO",
]

ErrorSeverity = Literal["info", "warning", "recoverable", "business", "fatal"]
JobStore = Literal["job_manager", "sharepoint_memory", "none"]
TriggerSource = Literal["power_automate", "web_ui", "admin"]


class UiLink(BaseModel):
    rel: str
    label: str
    path: str | None = None
    web_url: str | None = None
    open_mode: Literal["sharepoint", "external"] = "sharepoint"


class UiDocumentGroup(BaseModel):
    """Conjunto N de enlaces (PDFs consolidados, tablas amort.) para drawer UI."""

    id: str
    title: str
    count: int = 0
    links: list[UiLink] = Field(default_factory=list)


class UiReviewPagoRow(BaseModel):
    """Fila Distribucion_Pagos (R0 solo lectura)."""

    row_key: str
    excel_row: int
    id_pago: str
    cliente: str = ""
    credito: str = ""
    monto_banco: float | None = None
    fecha_banco: str | None = None
    fecha_limite: str | None = None
    dias_mora: int | None = None
    valor_extracto: float | None = None
    aplicar_a_extracto: float | None = None
    mora_a_aplicar: float | None = None
    abono_a_capital: float | None = None
    otros_valores: float | None = None
    total_aplicado: float | None = None
    saldo_por_asignar: float | None = None
    estado_pago: str | None = None
    validar_pago: str | None = None
    observacion: str | None = None
    tipo_aplicacion_original: str | None = None
    editable_fields: list[str] = Field(default_factory=list)
    links: list[UiLink] = Field(default_factory=list)


class UiReviewAbonoRow(BaseModel):
    """Fila Distribucion_Abonos (R0 solo lectura)."""

    row_key: str
    excel_row: int
    id_pago: str
    cliente: str = ""
    credito: str = ""
    monto_banco: float | None = None
    fecha_banco: str | None = None
    validar_abono: str | None = None
    observacion: str | None = None
    origen_credito: str | None = None
    tipo_aplicacion_original: str | None = None
    editable_fields: list[str] = Field(default_factory=list)
    links: list[UiLink] = Field(default_factory=list)


class UiReviewErrorItem(BaseModel):
    """Fila hoja Errores navegable desde la UI."""

    row_key: str
    excel_row: int
    id_pago: str = ""
    cliente: str = ""
    credito: str = ""
    tipo_caso: str = ""
    descripcion: str = ""
    que_debe_hacer: str = ""
    codigo_tecnico: str | None = None
    requires_regeneration: bool = True
    links: list[UiLink] = Field(default_factory=list)


class UiReviewResponse(BaseModel):
    """GET /processes/{key}/review — R0 read-only."""

    process_key: str
    bank_code: str
    validation_file_path: str | None = None
    review_excel: UiLink | None = None
    etag: str | None = None
    schema_version: int | None = None
    pagos: list[UiReviewPagoRow] = Field(default_factory=list)
    abonos: list[UiReviewAbonoRow] = Field(default_factory=list)
    errors: list[UiReviewErrorItem] = Field(default_factory=list)
    requires_regeneration: bool = False
    read_only: bool = True
    summary: dict[str, int] = Field(default_factory=dict)


class UiReviewRowPatch(BaseModel):
    """Cambio parcial de una fila (identidad estable row_key)."""

    row_key: str
    fields: dict[str, str | float | int | None] = Field(default_factory=dict)


class UiReviewPatchRequest(BaseModel):
    """PATCH review — borrador; no exige cuadre de negocio completo."""

    changes: list[UiReviewRowPatch] = Field(default_factory=list)


class UiReviewPatchResponse(BaseModel):
    process_key: str
    etag: str | None = None
    updated_row_keys: list[str] = Field(default_factory=list)
    review: UiReviewResponse


class UiReviewPreflightIssue(BaseModel):
    error_code: str
    sheet: str | None = None
    excel_row: int | None = None
    id_pago: str | None = None
    credito: str | None = None
    field: str | None = None
    value_found: str | None = None
    user_message: str | None = None


class UiReviewPreflightResponse(BaseModel):
    process_key: str
    etag: str | None = None
    ok: bool
    issue_count: int = 0
    issues: list[UiReviewPreflightIssue] = Field(default_factory=list)
    requires_regeneration: bool = False


class UiReviewFinalizeRequest(BaseModel):
    """POST .../review/finalize — cambios opcionales + cierre atómico."""

    changes: list[UiReviewRowPatch] = Field(default_factory=list)


class UiReviewFinalizeAccepted(BaseModel):
    accepted: bool = True
    action: Literal["finalize"] = "finalize"
    bank_code: str
    process_key: str
    job_id: str
    status: str = "queued"
    poll_url: str
    etag: str | None = None
    updated_row_keys: list[str] = Field(default_factory=list)


class UiError(BaseModel):
    stage: StepName | str | None = None
    severity: ErrorSeverity = "business"
    error_code: str | None = None
    user_message: str
    next_action: str | None = None
    payment_id: str | None = None
    client_name: str | None = None
    credit: str | None = None
    link: UiLink | None = None


class UiStepState(BaseModel):
    name: StepName
    status: StepStatus
    updated_at: str | None = None
    summary: str | None = None
    can_retry: bool = False
    retry_action: str | None = None


class UiActiveJob(BaseModel):
    job_id: str
    type: str
    status: str
    store: JobStore
    poll_path_graph: str | None = None
    poll_path_ui: str
    started_at: str | None = None
    progress: dict[str, Any] | None = None


class UiNextAction(BaseModel):
    code: str
    label: str
    enabled: bool = True
    reason: str | None = None


class UiProcessItem(BaseModel):
    payment_id: str | None = None
    client_name: str | None = None
    credit: str | None = None
    application_type: str | None = None
    business_status: BusinessStatus = "DESCONOCIDO"
    # Valor histórico no canónico (p. ej. texto retirado) preservado sin remapear.
    legacy_state: str | None = None
    legacy_warning: str | None = None
    stage_hint: StepName | None = None
    observation: str | None = None
    links: list[UiLink] = Field(default_factory=list)


class UiProcessFiles(BaseModel):
    validation_file_path: str | None = None
    historical_file_path: str | None = None
    secretary_file_path: str | None = None
    email_pdf_path: str | None = None
    merge_manifest_path: str | None = None
    control_file_path: str | None = None
    execution_log_path: str | None = None


class UiIdempotencyKeys(BaseModel):
    notify_idempotency_key: str | None = None
    merge_idempotency_key: str | None = None
    apply_idempotency_key: str | None = None


class UiAttempt(BaseModel):
    stage: StepName | str
    attempt_number: int = 1
    status: str | None = None
    at: str | None = None
    trigger_source: TriggerSource | None = None
    requested_by: str | None = None
    job_id: str | None = None


class UiLastAttempt(BaseModel):
    """Último intento relevante (puede ser terminal). No confundir con active_job."""

    stage: StepName | str
    job_id: str
    job_type: str
    status: str
    outcome: str | None = None
    recoverable: bool = False
    error_code: str | None = None
    severity: ErrorSeverity | None = None
    user_message: str | None = None
    next_action: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    progress: dict[str, Any] | None = None
    technical_reference: str | None = None


class UiIssueLocation(BaseModel):
    file_name: str | None = None
    sheet: str | None = None
    row: int | None = None
    column: str | None = None
    credit: str | None = None
    payment_id: str | None = None
    client_name: str | None = None


class UiIssueRetry(BaseModel):
    allowed: bool = False
    action: str | None = None
    label: str | None = None


IssueCategory = Literal[
    "correction_required",
    "temporary_failure",
    "system_failure",
    "warning",
    "partial_result",
]


class UiOperationalIssue(BaseModel):
    issue_id: str
    stage: StepName | str | None = None
    category: IssueCategory
    severity: ErrorSeverity = "warning"
    recoverable: bool = True
    title: str
    user_message: str
    location: UiIssueLocation | None = None
    value_found: str | None = None
    expected_values: list[str] = Field(default_factory=list)
    next_action: str | None = None
    retry: UiIssueRetry | None = None
    links: list[UiLink] = Field(default_factory=list)
    technical_reference: str | None = None


class UiProcessDetail(BaseModel):
    process_key: str
    process_id: str | None = None
    bank_code: str
    bank_name: str | None = None
    process_date: str | None = None
    environment: str
    operational_status: OperationalStatus
    operational_title: str = ""
    operational_message: str = ""
    control_estado_proceso: str | None = None
    is_active: bool = False
    steps: list[UiStepState]
    items: list[UiProcessItem] = Field(default_factory=list)
    active_job: UiActiveJob | None = None
    last_attempt: UiLastAttempt | None = None
    latest_attempts_by_stage: dict[str, UiLastAttempt] = Field(default_factory=dict)
    attempts: list[UiAttempt] = Field(default_factory=list)
    next_actions: list[UiNextAction] = Field(default_factory=list)
    available_actions: dict[str, UiActionAvailability] = Field(default_factory=dict)
    errors: list[UiError] = Field(default_factory=list)
    operational_issues: list[UiOperationalIssue] = Field(default_factory=list)
    technical_status_reference: str | None = None
    links: list[UiLink] = Field(default_factory=list)
    # Aditivo: grupos N para drawer (no reemplaza `links` 1:1 del lote).
    document_groups: list[UiDocumentGroup] = Field(default_factory=list)
    files: UiProcessFiles
    idempotency: UiIdempotencyKeys
    trigger_source: TriggerSource | None = None
    requested_by: str | None = None
    operator_checklist: list[str] = Field(default_factory=list)
    merge_readiness: UiMergeReadiness | None = None
    amortization_readiness: UiAmortizationReadiness | None = None


class UiProcessSummary(BaseModel):
    process_key: str
    bank_code: str
    process_date: str | None = None
    environment: str
    operational_status: OperationalStatus
    operational_title: str = ""
    operational_message: str = ""
    control_estado_proceso: str | None = None
    is_active: bool = False
    error_count: int = 0
    next_actions: list[UiNextAction] = Field(default_factory=list)
    # Aditivo Fase 1 UI: enlace directo al Excel de revisión en el Panel.
    review_excel_web_url: str | None = None


class UiProcessListResponse(BaseModel):
    environment: str
    items: list[UiProcessSummary]
    # Bancos cuyo Control no se pudo leer o proyectar: la lista vacía no debe
    # confundirse con "no hay procesos".
    unavailable_banks: list[str] = Field(default_factory=list)


HistoryItemSource = Literal["active", "archive"]


class UiHistoryItem(BaseModel):
    """Fila de historial: Control activo o snapshot en 04 ARCHIVO PROCESOS."""

    process_key: str
    bank_code: str
    bank_name: str | None = None
    process_date: str | None = None
    environment: str
    operational_status: OperationalStatus
    operational_title: str = ""
    operational_message: str = ""
    control_estado_proceso: str | None = None
    source: HistoryItemSource
    read_only: bool = False
    closed_at: str | None = None
    archive_reason: str | None = None
    review_excel_web_url: str | None = None
    historical_web_url: str | None = None


class UiHistoryListResponse(BaseModel):
    environment: str
    items: list[UiHistoryItem]
    unavailable_banks: list[str] = Field(default_factory=list)


class UiHistoryDetail(BaseModel):
    """Detalle solo lectura de un proceso archivado (snapshot JSON)."""

    process_key: str
    process_id: str | None = None
    bank_code: str
    bank_name: str | None = None
    process_date: str | None = None
    environment: str
    operational_status: OperationalStatus
    operational_title: str = ""
    operational_message: str = ""
    control_estado_proceso: str | None = None
    source: HistoryItemSource = "archive"
    read_only: bool = True
    closed_at: str | None = None
    archive_reason: str | None = None
    archive_path: str | None = None
    links: list[UiLink] = Field(default_factory=list)
    document_groups: list[UiDocumentGroup] = Field(default_factory=list)
    paths: dict[str, str | None] = Field(default_factory=dict)


class UiEnvironmentResponse(BaseModel):
    environment: str
    display_label: str
    ui_enabled: bool
    ui_write_enabled: bool
    ui_auth_mode: str


class UiBootstrapResponse(BaseModel):
    """Config runtime pública para la SPA. Sin secretos ni rutas Graph."""

    ui_enabled: bool
    writes_allowed: bool
    finalize_allowed: bool = False
    notify_allowed: bool = False
    # True cuando Notify UI está habilitado en sandbox: destinatarios vía CORREOS.xlsx.
    notify_test_recipients_configured: bool = False
    merge_allowed: bool = False
    amortization_allowed: bool = False
    review_edit_allowed: bool = False
    active_environment: str
    display_label: str
    auth_mode: str
    login_required: bool = False
    # Solo modo entra (migración futura). Vacío en local_session.
    entra_authority: str = ""
    entra_spa_client_id: str = ""
    entra_api_scope: str = ""


class UiLoginRequest(BaseModel):
    username: str
    password: str


class UiLoginResponse(BaseModel):
    authenticated: bool = True
    username: str
    role: str
    auth_mode: str = "local_session"


class UiMeResponse(BaseModel):
    authenticated: bool
    username: str
    role: str
    auth_mode: str
    expires_at: str


class UiLogoutResponse(BaseModel):
    ok: bool = True


class UiJobView(BaseModel):
    job_id: str
    type: str | None = None
    status: str
    store: JobStore
    process_key: str | None = None
    bank_code: str | None = None
    environment: str
    created_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    result_summary: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    user_message: str | None = None
    next_action: str | None = None
    severity: str | None = None
    progress: dict[str, Any] | None = None
    raw_available: bool = True


class UiErrorBody(BaseModel):
    error_code: str
    user_message: str
    next_action: str | None = None
    severity: ErrorSeverity = "business"


# ─── U3-A: CSRF + Generate desde la UI ──────────────────────────────────────

UiBankCode = Literal["banco_bogota", "banco_bancolombia"]


class UiCsrfResponse(BaseModel):
    csrf_token: str


class UiGenerateRequest(BaseModel):
    """Body de POST /processes/generate.

    ``force_regenerate``: cancela el lote pre-Finalize y genera un Excel nuevo
    (misma fecha de ProcessKey). Disponible en revisión aunque no haya Errores
    (p. ej. tras actualizar el Excel del banco). Solo UI autenticada.
    """

    model_config = {"extra": "forbid"}

    bank_code: UiBankCode
    force_regenerate: bool = False
    process_date: str | None = None


class UiGenerateAccepted(BaseModel):
    """202 sin process_key (aún no se conoce al momento de encolar)."""

    accepted: bool = True
    action: Literal["generate"] = "generate"
    bank_code: str
    job_id: str
    status: str = "queued"
    poll_url: str


class UiFinalizeRequest(BaseModel):
    """Body de POST /processes/finalize. Solo bank_code + process_key."""

    model_config = {"extra": "forbid"}

    bank_code: UiBankCode
    process_key: str


class UiFinalizeAccepted(BaseModel):
    accepted: bool = True
    action: Literal["finalize"] = "finalize"
    bank_code: str
    process_key: str
    job_id: str
    status: str = "queued"
    poll_url: str


class UiNotifyRequest(BaseModel):
    """Body de POST /processes/notify. Solo bank_code + process_key (sin to/cc)."""

    model_config = {"extra": "forbid"}

    bank_code: UiBankCode
    process_key: str


class UiNotifyAccepted(BaseModel):
    accepted: bool = True
    action: Literal["notify"] = "notify"
    bank_code: str
    process_key: str
    job_id: str
    status: str = "queued"
    poll_url: str


class UiMergeRequest(BaseModel):
    """Body de POST /processes/merge. Solo bank_code + process_key (sin paths)."""

    model_config = {"extra": "forbid"}

    bank_code: UiBankCode
    process_key: str


class UiMergeAccepted(BaseModel):
    accepted: bool = True
    action: Literal["merge"] = "merge"
    bank_code: str
    process_key: str
    job_id: str
    status: str = "queued"
    poll_url: str


class UiMergeReadiness(BaseModel):
    """Resumen operativo de soportes antes de consolidar."""

    status: Literal["ready", "incomplete", "unknown", "already_merged"]
    expected_groups: int = 0
    ready_groups: int = 0
    missing_groups: int = 0
    missing_items: list[dict[str, Any]] = Field(default_factory=list)
    folder_links: list[dict[str, Any]] = Field(default_factory=list)
    checked_at: str | None = None
    user_message: str = ""
    next_action: str = ""


class UiAmortizationRequest(BaseModel):
    """Body de POST /processes/amortization. Solo bank_code + process_key."""

    model_config = {"extra": "forbid"}

    bank_code: UiBankCode
    process_key: str


class UiAmortizationAccepted(BaseModel):
    accepted: bool = True
    action: Literal["amortization"] = "amortization"
    bank_code: str
    process_key: str
    job_id: str
    status: str = "queued"
    poll_url: str


class UiAmortizationReadiness(BaseModel):
    """Resumen operativo liviano antes de procesar amortización."""

    status: Literal["ready", "incomplete", "unknown", "already_applied"]
    can_start: bool = False
    expected_items: int = 0
    ready_items: int = 0
    missing_items: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    checked_at: str | None = None
    user_message: str = ""
    next_action: str = ""


class UiActionAvailability(BaseModel):
    allowed: bool
    reason: str | None = None


DashboardPrimaryAction = Literal["generate", "resume", "retry_read"]


class UiBankCapabilities(BaseModel):
    bank_code: str
    bank_name: str | None = None
    available_actions: dict[str, UiActionAvailability]
    # Continuidad R3.3: el dashboard decide Iniciar / Retomar / Volver a intentar
    # a partir del Control, no solo del lock en memoria.
    control_readable: bool = True
    active_process_key: str | None = None
    active_operational_status: str | None = None
    active_control_estado: str | None = None
    dashboard_primary_action: DashboardPrimaryAction = "generate"
    # Aditivo Fase 1 UI: Excel de entrada del banco (BANCO_*.xlsx) para abrir desde el Panel.
    bank_input_web_url: str | None = None
