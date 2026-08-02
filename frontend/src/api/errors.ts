/** Error tipado de la API UI: preserva el `detail` estructurado que emite FastAPI. */

export type UiApiErrorSeverity =
  | "info"
  | "warning"
  | "recoverable"
  | "business"
  | "fatal";

/** Forma laxa: el backend aún no emite `issues`/`technical_reference` en
 * todos los 4xx/5xx, pero el tipo queda listo para cuando los incluya. */
export interface UiApiErrorIssue {
  issue_id?: string;
  stage?: string | null;
  title?: string;
  user_message?: string;
  next_action?: string | null;
  [key: string]: unknown;
}

export interface UiApiErrorInit {
  status: number;
  errorCode?: string | null;
  userMessage: string;
  nextAction?: string | null;
  severity?: UiApiErrorSeverity | null;
  issues?: UiApiErrorIssue[];
  technicalReference?: string | null;
}

const KNOWN_SEVERITIES: ReadonlySet<string> = new Set([
  "info",
  "warning",
  "recoverable",
  "business",
  "fatal",
]);

export class UiApiError extends Error {
  readonly status: number;
  readonly errorCode: string | null;
  readonly userMessage: string;
  readonly nextAction: string | null;
  readonly severity: UiApiErrorSeverity | null;
  readonly issues: UiApiErrorIssue[];
  readonly technicalReference: string | null;

  constructor(init: UiApiErrorInit) {
    super(init.userMessage);
    this.name = "UiApiError";
    this.status = init.status;
    this.errorCode = init.errorCode ?? null;
    this.userMessage = init.userMessage;
    this.nextAction = init.nextAction ?? null;
    this.severity = init.severity ?? null;
    this.issues = init.issues ?? [];
    this.technicalReference = init.technicalReference ?? null;
  }
}

/** Fallos de red/gateway que no implican que el job de negocio haya fallado. */
export function isTransientPollError(error: unknown): boolean {
  if (error instanceof UiApiError) {
    return (
      error.status === 408 ||
      error.status === 429 ||
      error.status === 502 ||
      error.status === 503 ||
      error.status === 504
    );
  }
  if (error instanceof TypeError) {
    return true;
  }
  if (error instanceof Error) {
    const raw = error.message || "";
    return (
      /Error HTTP\s*(408|429|502|503|504)\b/i.test(raw) ||
      /\bHTTP\s*(408|429|502|503|504)\b/i.test(raw) ||
      /Failed to fetch|NetworkError|Load failed|network/i.test(raw)
    );
  }
  return false;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function pickString(record: Record<string, unknown>, key: string): string | null {
  const value = record[key];
  return typeof value === "string" && value.trim() ? value : null;
}

function pickSeverity(record: Record<string, unknown>): UiApiErrorSeverity | null {
  const value = record.severity;
  return typeof value === "string" && KNOWN_SEVERITIES.has(value)
    ? (value as UiApiErrorSeverity)
    : null;
}

function pickIssues(record: Record<string, unknown>): UiApiErrorIssue[] {
  const value = record.issues ?? record.operational_issues;
  if (!Array.isArray(value)) return [];
  return value.filter(isRecord) as UiApiErrorIssue[];
}

/** Extrae el objeto `detail` de FastAPI, o el body plano si no viene envuelto. */
function extractDetail(body: unknown): Record<string, unknown> {
  if (!isRecord(body)) return {};
  const detail = body.detail;
  return isRecord(detail) ? detail : body;
}

/** Mensaje amigable cuando el backend no envía `user_message` (p. ej. HTML 502). */
export function fallbackMessageForHttpStatus(status: number): string {
  if (status === 401) {
    return "Su sesión expiró o no es válida. Inicie sesión de nuevo.";
  }
  if (status === 403) {
    return "No tiene permiso para esta acción o la sesión de seguridad no está lista.";
  }
  if (status === 404) {
    return "No encontramos lo que buscaba. Actualice la página e intente de nuevo.";
  }
  if (status === 409) {
    return "No se pudo completar la acción porque el proceso cambió. Actualice el estado e intente de nuevo.";
  }
  if (status === 429) {
    return "Hay demasiados intentos. Espere un momento e intente de nuevo.";
  }
  if (status >= 500) {
    return (
      "El servicio no respondió correctamente (problema temporal del servidor). " +
      "Espere unos segundos, actualice el estado e intente de nuevo."
    );
  }
  if (status >= 400) {
    return "No pudimos completar la solicitud. Revise los datos e intente de nuevo.";
  }
  return "No pudimos completar la operación. Intente de nuevo en unos momentos.";
}

export function buildUiApiError(status: number, body: unknown): UiApiError {
  const detail = extractDetail(body);
  const userMessage =
    pickString(detail, "user_message") || fallbackMessageForHttpStatus(status);
  return new UiApiError({
    status,
    errorCode: pickString(detail, "error_code"),
    userMessage,
    nextAction: pickString(detail, "next_action"),
    severity: pickSeverity(detail),
    issues: pickIssues(detail),
    technicalReference: pickString(detail, "technical_reference"),
  });
}
