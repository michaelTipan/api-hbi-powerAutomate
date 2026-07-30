import type {
  UiBootstrapResponse,
  UiEnvironmentResponse,
  UiJobView,
  UiProcessDetail,
  UiProcessListResponse,
} from "../types/contract";
import {
  mockBootstrap,
  mockEnvironment,
  mockGetJob,
  mockGetProcess,
  mockListProcesses,
} from "../mocks/data";

const USE_MOCKS =
  (import.meta.env.VITE_UI_USE_MOCKS as string | undefined)?.toLowerCase() !==
  "false";

/** Solo desarrollo mock; en Azure el Bearer lo aportará MSAL tras bootstrap. */
const DEV_TOKEN =
  (import.meta.env.VITE_UI_BEARER as string | undefined) || "mock-user";

let bootstrapCache: UiBootstrapResponse | null = null;
let accessTokenProvider: (() => Promise<string | null>) | null = null;

export function setAccessTokenProvider(
  provider: (() => Promise<string | null>) | null,
): void {
  accessTokenProvider = provider;
}

async function resolveBearer(): Promise<string> {
  if (accessTokenProvider) {
    const token = await accessTokenProvider();
    if (token) return token;
  }
  return DEV_TOKEN;
}

async function apiGet<T>(
  path: string,
  options: { auth: boolean },
): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (options.auth) {
    headers.Authorization = `Bearer ${await resolveBearer()}`;
  }
  const res = await fetch(path, { headers });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const detail = (body as { detail?: { user_message?: string }; user_message?: string });
    const msg =
      detail.detail?.user_message ||
      detail.user_message ||
      `Error HTTP ${res.status}`;
    throw new Error(msg);
  }
  return res.json() as Promise<T>;
}

/** Config runtime pública (sin Bearer). Fuente de Entra SPA — no hardcodear en TS. */
export async function fetchBootstrap(): Promise<UiBootstrapResponse> {
  if (USE_MOCKS) {
    bootstrapCache = mockBootstrap;
    return mockBootstrap;
  }
  if (bootstrapCache) return bootstrapCache;
  bootstrapCache = await apiGet<UiBootstrapResponse>("/api/ui/v1/bootstrap", {
    auth: false,
  });
  return bootstrapCache;
}

export function getCachedBootstrap(): UiBootstrapResponse | null {
  return bootstrapCache;
}

export async function fetchEnvironment(): Promise<UiEnvironmentResponse> {
  if (USE_MOCKS) return mockEnvironment;
  return apiGet("/api/ui/v1/environment", { auth: true });
}

export async function fetchProcesses(): Promise<UiProcessListResponse> {
  if (USE_MOCKS) return mockListProcesses();
  return apiGet("/api/ui/v1/processes", { auth: true });
}

export async function fetchProcess(
  processKey: string,
): Promise<UiProcessDetail> {
  if (USE_MOCKS) {
    const hit = mockGetProcess(processKey);
    if (!hit) throw new Error("No se encontró el proceso solicitado.");
    return hit;
  }
  return apiGet(`/api/ui/v1/processes/${encodeURIComponent(processKey)}`, {
    auth: true,
  });
}

export async function fetchJob(jobId: string): Promise<UiJobView> {
  if (USE_MOCKS) {
    const hit = mockGetJob(jobId);
    if (!hit) throw new Error("No se encontró el trabajo solicitado.");
    return hit;
  }
  return apiGet(`/api/ui/v1/jobs/${encodeURIComponent(jobId)}`, { auth: true });
}

export function isMockMode(): boolean {
  return USE_MOCKS;
}
