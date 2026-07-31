import type {
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

// Mocks solo con opt-in explícito. En Azure/prod el default debe ser API real.
const USE_MOCKS =
  (import.meta.env.VITE_UI_USE_MOCKS as string | undefined)?.toLowerCase() ===
  "true";

/** Solo desarrollo mock; no se usa con local_session. */
const DEV_TOKEN =
  (import.meta.env.VITE_UI_BEARER as string | undefined) || "mock-user";

let bootstrapCache: UiBootstrapResponse | null = null;
let accessTokenProvider: (() => Promise<string | null>) | null = null;
/** CSRF solo en memoria de proceso — nunca localStorage/sessionStorage. */
let csrfTokenMemory: string | null = null;

export type UiBankCode = "banco_bogota" | "banco_bancolombia";

export interface UiActionAvailability {
  allowed: boolean;
  reason: string | null;
}

export interface UiBankCapabilities {
  bank_code: UiBankCode;
  bank_name: string;
  available_actions: {
    generate: UiActionAvailability;
  };
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

export function getCsrfTokenMemory(): string | null {
  return csrfTokenMemory;
}

export function clearCsrfTokenMemory(): void {
  csrfTokenMemory = null;
}

function authMode(): string {
  return bootstrapCache?.auth_mode || "mock";
}

async function resolveBearer(): Promise<string | null> {
  if (authMode() === "local_session") {
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

async function apiFetch<T>(
  path: string,
  options: {
    auth: boolean;
    method?: string;
    body?: unknown;
    csrf?: boolean;
  },
): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
  }
  if (options.auth && authMode() !== "local_session") {
    const bearer = await resolveBearer();
    if (bearer) {
      headers.Authorization = `Bearer ${bearer}`;
    }
  }
  if (options.csrf && authMode() === "local_session") {
    if (!csrfTokenMemory) {
      await fetchCsrfToken();
    }
    if (csrfTokenMemory) {
      headers["X-CSRF-Token"] = csrfTokenMemory;
    }
  }
  const res = await fetch(path, {
    method: options.method || "GET",
    headers,
    credentials: "include",
    body:
      options.body === undefined ? undefined : JSON.stringify(options.body),
  });
  if (!res.ok) {
    if (res.status === 401 && authMode() === "local_session") {
      clearCsrfTokenMemory();
      clearBootstrapCache();
    }
    const body = await res.json().catch(() => ({}));
    const detail = body as {
      detail?: {
        user_message?: string;
        error_code?: string;
        next_action?: string;
      };
      user_message?: string;
      error_code?: string;
      next_action?: string;
    };
    const msg =
      detail.detail?.user_message ||
      detail.user_message ||
      `Error HTTP ${res.status}`;
    const err = new Error(msg) as Error & {
      status: number;
      errorCode?: string;
      nextAction?: string;
    };
    err.status = res.status;
    err.errorCode = detail.detail?.error_code || detail.error_code;
    err.nextAction = detail.detail?.next_action || detail.next_action;
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
  return bootstrapCache;
}

export function getCachedBootstrap(): UiBootstrapResponse | null {
  return bootstrapCache;
}

export function clearBootstrapCache(): void {
  bootstrapCache = null;
}

export async function fetchCsrfToken(): Promise<string> {
  const res = await apiFetch<{ csrf_token: string }>("/api/ui/v1/auth/csrf", {
    auth: true,
  });
  csrfTokenMemory = res.csrf_token;
  return res.csrf_token;
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
): Promise<UiGenerateAccepted> {
  return apiFetch<UiGenerateAccepted>("/api/ui/v1/processes/generate", {
    auth: true,
    method: "POST",
    body: { bank_code: bankCode },
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
): Promise<UiMergeAccepted> {
  return apiFetch<UiMergeAccepted>("/api/ui/v1/processes/merge", {
    auth: true,
    method: "POST",
    body: { bank_code: bankCode, process_key: processKey },
    csrf: true,
  });
}

export async function fetchProcesses(): Promise<UiProcessListResponse> {
  if (USE_MOCKS) return mockListProcesses();
  return apiFetch("/api/ui/v1/processes", { auth: true });
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
