import type {
  UiBootstrapResponse,
  UiEnvironmentResponse,
  UiJobView,
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

export function setAccessTokenProvider(
  provider: (() => Promise<string | null>) | null,
): void {
  accessTokenProvider = provider;
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
  const res = await fetch(path, {
    method: options.method || "GET",
    headers,
    credentials: "include",
    body:
      options.body === undefined ? undefined : JSON.stringify(options.body),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const detail = body as {
      detail?: { user_message?: string; error_code?: string };
      user_message?: string;
      error_code?: string;
    };
    const msg =
      detail.detail?.user_message ||
      detail.user_message ||
      `Error HTTP ${res.status}`;
    const err = new Error(msg) as Error & {
      status: number;
      errorCode?: string;
    };
    err.status = res.status;
    err.errorCode = detail.detail?.error_code || detail.error_code;
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

export async function loginLocal(
  username: string,
  password: string,
): Promise<void> {
  await apiFetch("/api/ui/v1/auth/login", {
    auth: false,
    method: "POST",
    body: { username, password },
  });
}

export async function logoutLocal(): Promise<void> {
  await apiFetch("/api/ui/v1/auth/logout", {
    auth: false,
    method: "POST",
    body: {},
  });
}

export async function fetchMe(): Promise<UiMeResponse> {
  return apiFetch("/api/ui/v1/auth/me", { auth: true });
}

export async function fetchEnvironment(): Promise<UiEnvironmentResponse> {
  if (USE_MOCKS) return mockEnvironment;
  return apiFetch("/api/ui/v1/environment", { auth: true });
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
    /password|token|session|api.?key|secret|bearer/i.test(k),
  );
  if (banned.length > 0) {
    throw new Error(`Storage de credenciales prohibido: ${banned.join(",")}`);
  }
}
