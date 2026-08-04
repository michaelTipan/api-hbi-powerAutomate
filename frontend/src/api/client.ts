import type {
  UiAmortizationAccepted,
  UiBootstrapResponse,
  UiEnvironmentResponse,
  UiJobView,
  UiMergeAccepted,
  UiProcessDetail,
  UiProcessListResponse,
} from "../types/contract";
import type { UiMeResponse } from "../types/auth";
import {
  mockBootstrap,
  mockEnvironment,
  mockGetJob,
  mockGetProcess,
  mockListProcesses,
} from "../mocks/data";
import { buildUiApiError } from "./errors";
import {
  CSRF_HEADER_NAME,
  clearCsrfTokenMemory,
  ensureCsrfToken,
  getCsrfTokenMemory,
  isLocalSessionMode,
  notifySessionExpired,
  setCsrfTokenMemory,
  setLocalSessionMode,
} from "./csrfManager";

// Mocks solo con opt-in explícito. En Azure/prod el default debe ser API real.
const USE_MOCKS =
  (import.meta.env.VITE_UI_USE_MOCKS as string | undefined)?.toLowerCase() ===
  "true";

/** Solo desarrollo mock; no se usa con local_session. */
const DEV_TOKEN =
  (import.meta.env.VITE_UI_BEARER as string | undefined) || "mock-user";

let bootstrapCache: UiBootstrapResponse | null = null;
let accessTokenProvider: (() => Promise<string | null>) | null = null;

export type UiBankCode = "banco_bogota" | "banco_bancolombia";

export interface UiActionAvailability {
  allowed: boolean;
  reason: string | null;
}

export type DashboardPrimaryAction = "generate" | "resume" | "retry_read";

export interface UiBankCapabilities {
  bank_code: UiBankCode;
  bank_name: string;
  available_actions: {
    generate: UiActionAvailability;
  };
  control_readable?: boolean;
  active_process_key?: string | null;
  active_operational_status?: string | null;
  active_control_estado?: string | null;
  dashboard_primary_action?: DashboardPrimaryAction;
  /** webUrl SharePoint del Excel de entrada del banco (plantilla de carga). */
  bank_input_web_url?: string | null;
}

export interface UiGenerateAccepted {
  accepted: boolean;
  action: string;
  bank_code: UiBankCode;
  job_id: string;
  status: string;
  poll_url: string;
}

export interface UiFinalizeAccepted {
  accepted: boolean;
  action: string;
  bank_code: UiBankCode;
  process_key: string;
  job_id: string;
  status: string;
  poll_url: string;
}

export interface UiNotifyAccepted {
  accepted: boolean;
  action: string;
  bank_code: UiBankCode;
  process_key: string;
  job_id: string;
  status: string;
  poll_url: string;
}

export function setAccessTokenProvider(
  provider: (() => Promise<string | null>) | null,
): void {
  accessTokenProvider = provider;
}

export {
  clearCsrfTokenMemory,
  getCsrfTokenMemory,
  isCsrfReady,
  isLocalSessionMode,
  setLocalSessionMode,
  subscribeCsrfReady,
  subscribeSessionExpired,
} from "./csrfManager";

function authMode(): string {
  return bootstrapCache?.auth_mode || "mock";
}

/** CSRF de cookie-session: sticky aunque bootstrapCache se limpie tras un 401. */
function usesLocalSessionCsrf(): boolean {
  return isLocalSessionMode() || authMode() === "local_session";
}

async function resolveBearer(): Promise<string | null> {
  if (usesLocalSessionCsrf()) {
    return null;
  }
  if (accessTokenProvider) {
    const token = await accessTokenProvider();
    if (token) return token;
  }
  if (authMode() === "mock" || USE_MOCKS) {
    return DEV_TOKEN;
  }
  return null;
}

async function loadCsrfFromApi(): Promise<string> {
  const res = await apiFetch<{ csrf_token: string }>(
    "/api/ui/v1/auth/csrf",
    { auth: true },
    { csrfRetried: true },
  );
  const token = res.csrf_token;
  if (typeof token !== "string" || !token.trim()) {
    throw new Error("No se pudo preparar la sesión segura.");
  }
  return token.trim();
}

async function apiFetch<T>(
  path: string,
  options: {
    auth: boolean;
    method?: string;
    body?: unknown;
    csrf?: boolean;
  },
  retryState: { csrfRetried: boolean } = { csrfRetried: false },
): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
  }
  if (options.auth && !usesLocalSessionCsrf()) {
    const bearer = await resolveBearer();
    if (bearer) {
      headers.Authorization = `Bearer ${bearer}`;
    }
  }
  if (options.csrf && usesLocalSessionCsrf()) {
    await ensureCsrfToken(loadCsrfFromApi);
    const token = getCsrfTokenMemory();
    if (!token) {
      throw buildUiApiError(403, {
        detail: {
          error_code: "invalid_csrf_token",
          user_message: "La sesión de seguridad expiró o no es válida.",
          next_action: "Actualice la página e intente la acción nuevamente.",
          severity: "fatal",
        },
      });
    }
    headers[CSRF_HEADER_NAME] = token;
  }
  const res = await fetch(path, {
    method: options.method || "GET",
    headers,
    credentials: "include",
    body:
      options.body === undefined ? undefined : JSON.stringify(options.body),
  });
  if (!res.ok) {
    if (res.status === 401 && usesLocalSessionCsrf()) {
      clearCsrfTokenMemory();
      clearBootstrapCache();
      notifySessionExpired();
    }
    const body = await res.json().catch(() => ({}));
    const err = buildUiApiError(res.status, body);
    if (
      options.csrf &&
      usesLocalSessionCsrf() &&
      res.status === 403 &&
      err.errorCode === "invalid_csrf_token" &&
      !retryState.csrfRetried
    ) {
      clearCsrfTokenMemory();
      await ensureCsrfToken(loadCsrfFromApi, { force: true });
      return apiFetch<T>(path, options, { csrfRetried: true });
    }
    throw err;
  }
  if (res.status === 204) {
    return undefined as T;
  }
  return res.json() as Promise<T>;
}

export async function fetchBootstrap(): Promise<UiBootstrapResponse> {
  if (USE_MOCKS) {
    bootstrapCache = mockBootstrap;
    return mockBootstrap;
  }
  if (bootstrapCache) return bootstrapCache;
  bootstrapCache = await apiFetch<UiBootstrapResponse>("/api/ui/v1/bootstrap", {
    auth: false,
  });
  if (bootstrapCache.auth_mode === "local_session") {
    setLocalSessionMode(true);
  }
  return bootstrapCache;
}

export function getCachedBootstrap(): UiBootstrapResponse | null {
  return bootstrapCache;
}

export function clearBootstrapCache(): void {
  bootstrapCache = null;
}

export async function fetchCsrfToken(): Promise<string> {
  const token = await ensureCsrfToken(loadCsrfFromApi, { force: true });
  setCsrfTokenMemory(token);
  return token;
}

export async function loginLocal(
  username: string,
  password: string,
): Promise<void> {
  await apiFetch("/api/ui/v1/auth/login", {
    auth: false,
    method: "POST",
    body: { username, password },
  });
  setLocalSessionMode(true);
  clearCsrfTokenMemory();
  await fetchCsrfToken();
}

export async function logoutLocal(): Promise<void> {
  try {
    await apiFetch("/api/ui/v1/auth/logout", {
      auth: false,
      method: "POST",
      body: {},
      csrf: true,
    });
  } finally {
    clearCsrfTokenMemory();
    clearBootstrapCache();
    setLocalSessionMode(false);
  }
}

export async function fetchMe(): Promise<UiMeResponse> {
  return apiFetch("/api/ui/v1/auth/me", { auth: true });
}

export async function fetchEnvironment(): Promise<UiEnvironmentResponse> {
  if (USE_MOCKS) return mockEnvironment;
  return apiFetch("/api/ui/v1/environment", { auth: true });
}

export async function fetchBanks(): Promise<UiBankCapabilities[]> {
  if (USE_MOCKS) {
    return [
      {
        bank_code: "banco_bogota",
        bank_name: "Banco Bogotá",
        available_actions: { generate: { allowed: false, reason: "Mocks" } },
      },
      {
        bank_code: "banco_bancolombia",
        bank_name: "Bancolombia",
        available_actions: { generate: { allowed: false, reason: "Mocks" } },
      },
    ];
  }
  return apiFetch<UiBankCapabilities[]>("/api/ui/v1/banks", { auth: true });
}

export async function postGenerate(
  bankCode: UiBankCode,
  options?: { forceRegenerate?: boolean; processDate?: string | null },
): Promise<UiGenerateAccepted> {
  const body: {
    bank_code: UiBankCode;
    force_regenerate?: boolean;
    process_date?: string;
  } = { bank_code: bankCode };
  if (options?.forceRegenerate) {
    body.force_regenerate = true;
  }
  if (options?.processDate) {
    body.process_date = options.processDate;
  }
  return apiFetch<UiGenerateAccepted>("/api/ui/v1/processes/generate", {
    auth: true,
    method: "POST",
    body,
    csrf: true,
  });
}

export async function postFinalize(
  bankCode: UiBankCode,
  processKey: string,
): Promise<UiFinalizeAccepted> {
  return apiFetch<UiFinalizeAccepted>("/api/ui/v1/processes/finalize", {
    auth: true,
    method: "POST",
    body: { bank_code: bankCode, process_key: processKey },
    csrf: true,
  });
}

export async function postNotify(
  bankCode: UiBankCode,
  processKey: string,
): Promise<UiNotifyAccepted> {
  return apiFetch<UiNotifyAccepted>("/api/ui/v1/processes/notify", {
    auth: true,
    method: "POST",
    body: { bank_code: bankCode, process_key: processKey },
    csrf: true,
  });
}

export async function postMerge(
  bankCode: UiBankCode,
  processKey: string,
  options?: { forceRebuild?: boolean },
): Promise<UiMergeAccepted> {
  const body: {
    bank_code: UiBankCode;
    process_key: string;
    force_rebuild?: boolean;
  } = { bank_code: bankCode, process_key: processKey };
  if (options?.forceRebuild) {
    body.force_rebuild = true;
  }
  return apiFetch<UiMergeAccepted>("/api/ui/v1/processes/merge", {
    auth: true,
    method: "POST",
    body,
    csrf: true,
  });
}

export async function postAmortization(
  bankCode: UiBankCode,
  processKey: string,
): Promise<UiAmortizationAccepted> {
  return apiFetch<UiAmortizationAccepted>("/api/ui/v1/processes/amortization", {
    auth: true,
    method: "POST",
    body: { bank_code: bankCode, process_key: processKey },
    csrf: true,
  });
}

export interface UiCancelLoteAccepted {
  accepted: boolean;
  action: "cancel_lote";
  bank_code: string;
  process_key: string;
  job_id: string;
  status: string;
  poll_url: string;
}

export interface UiSoftCloseAccepted {
  accepted: boolean;
  action: "soft_close";
  bank_code: string;
  process_key: string;
  job_id: string;
  status: string;
  poll_url: string;
}

export async function postCancelLote(
  bankCode: UiBankCode,
  processKey: string,
): Promise<UiCancelLoteAccepted> {
  return apiFetch<UiCancelLoteAccepted>("/api/ui/v1/processes/cancel-lote", {
    auth: true,
    method: "POST",
    body: { bank_code: bankCode, process_key: processKey },
    csrf: true,
  });
}

export async function postSoftClose(
  bankCode: UiBankCode,
  processKey: string,
  reason: string = "",
): Promise<UiSoftCloseAccepted> {
  return apiFetch<UiSoftCloseAccepted>("/api/ui/v1/processes/soft-close", {
    auth: true,
    method: "POST",
    body: { bank_code: bankCode, process_key: processKey, reason },
    csrf: true,
  });
}

export async function fetchProcesses(): Promise<UiProcessListResponse> {
  if (USE_MOCKS) return mockListProcesses();
  return apiFetch("/api/ui/v1/processes", { auth: true });
}

export interface UiHistoryItem {
  process_key: string;
  bank_code: string;
  bank_name?: string | null;
  process_date: string | null;
  environment: string;
  operational_status: string;
  operational_title?: string;
  operational_message?: string;
  control_estado_proceso: string | null;
  source: "active" | "archive";
  read_only: boolean;
  closed_at?: string | null;
  archive_reason?: string | null;
  review_excel_web_url?: string | null;
  historical_web_url?: string | null;
}

export interface UiHistoryListResponse {
  environment: string;
  items: UiHistoryItem[];
  unavailable_banks?: string[];
}

export interface UiHistoryDetail {
  process_key: string;
  process_id?: string | null;
  bank_code: string;
  bank_name?: string | null;
  process_date: string | null;
  environment: string;
  operational_status: string;
  operational_title?: string;
  operational_message?: string;
  control_estado_proceso: string | null;
  source: "active" | "archive";
  read_only: boolean;
  closed_at?: string | null;
  archive_reason?: string | null;
  archive_path?: string | null;
  links: Array<{
    rel: string;
    label: string;
    path?: string | null;
    web_url?: string | null;
    open_mode?: string;
  }>;
  document_groups?: Array<{
    id: string;
    title: string;
    count: number;
    links: Array<{
      rel: string;
      label: string;
      path?: string | null;
      web_url?: string | null;
      open_mode?: string;
    }>;
  }>;
  paths: Record<string, string | null>;
}

export async function fetchProcessHistory(
  bankCode?: string,
): Promise<UiHistoryListResponse> {
  if (USE_MOCKS) {
    const live = await mockListProcesses();
    return {
      environment: live.environment,
      items: live.items.map((p) => ({
        ...p,
        source: "active" as const,
        read_only: false,
      })),
      unavailable_banks: live.unavailable_banks,
    };
  }
  const q =
    bankCode && bankCode.trim()
      ? `?bank_code=${encodeURIComponent(bankCode.trim())}`
      : "";
  return apiFetch(`/api/ui/v1/process-history${q}`, { auth: true });
}

export async function fetchProcessHistoryDetail(
  processKey: string,
): Promise<UiHistoryDetail> {
  if (USE_MOCKS) {
    throw new Error("Detalle histórico no disponible en modo demo.");
  }
  return apiFetch(
    `/api/ui/v1/process-history/${encodeURIComponent(processKey)}`,
    { auth: true },
  );
}

export async function fetchProcess(
  processKey: string,
): Promise<UiProcessDetail> {
  if (USE_MOCKS) {
    const hit = mockGetProcess(processKey);
    if (!hit) throw new Error("No se encontró el proceso solicitado.");
    return hit;
  }
  return apiFetch(`/api/ui/v1/processes/${encodeURIComponent(processKey)}`, {
    auth: true,
  });
}

export async function fetchJob(jobId: string): Promise<UiJobView> {
  if (USE_MOCKS) {
    const hit = mockGetJob(jobId);
    if (!hit) throw new Error("No se encontró el trabajo solicitado.");
    return hit;
  }
  return apiFetch(`/api/ui/v1/jobs/${encodeURIComponent(jobId)}`, {
    auth: true,
  });
}

export function isMockMode(): boolean {
  return USE_MOCKS;
}

/** Guardrail: la SPA no debe usar storage para tokens/credenciales. */
export function assertNoCredentialStorage(): void {
  if (typeof window === "undefined") return;
  const keys = [
    ...Object.keys(window.localStorage || {}),
    ...Object.keys(window.sessionStorage || {}),
  ];
  const banned = keys.filter((k) =>
    /password|token|session|api.?key|secret|bearer|csrf/i.test(k),
  );
  if (banned.length > 0) {
    throw new Error(`Storage de credenciales prohibido: ${banned.join(",")}`);
  }
}
