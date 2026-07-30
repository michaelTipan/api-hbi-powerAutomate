import type {
  UiEnvironmentResponse,
  UiJobView,
  UiProcessDetail,
  UiProcessListResponse,
} from "../types/contract";
import {
  mockEnvironment,
  mockGetJob,
  mockGetProcess,
  mockListProcesses,
} from "../mocks/data";

const USE_MOCKS =
  (import.meta.env.VITE_UI_USE_MOCKS as string | undefined)?.toLowerCase() !==
  "false";

const TOKEN = (import.meta.env.VITE_UI_BEARER as string | undefined) || "mock-user";

async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(path, {
    headers: {
      Authorization: `Bearer ${TOKEN}`,
      Accept: "application/json",
    },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const detail = (body as { detail?: { user_message?: string } }).detail;
    throw new Error(detail?.user_message || `Error HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export async function fetchEnvironment(): Promise<UiEnvironmentResponse> {
  if (USE_MOCKS) return mockEnvironment;
  return apiGet("/api/ui/v1/environment");
}

export async function fetchProcesses(): Promise<UiProcessListResponse> {
  if (USE_MOCKS) return mockListProcesses();
  return apiGet("/api/ui/v1/processes");
}

export async function fetchProcess(
  processKey: string,
): Promise<UiProcessDetail> {
  if (USE_MOCKS) {
    const hit = mockGetProcess(processKey);
    if (!hit) throw new Error("No se encontró el proceso solicitado.");
    return hit;
  }
  return apiGet(`/api/ui/v1/processes/${encodeURIComponent(processKey)}`);
}

export async function fetchJob(jobId: string): Promise<UiJobView> {
  if (USE_MOCKS) {
    const hit = mockGetJob(jobId);
    if (!hit) throw new Error("No se encontró el trabajo solicitado.");
    return hit;
  }
  return apiGet(`/api/ui/v1/jobs/${encodeURIComponent(jobId)}`);
}

export function isMockMode(): boolean {
  return USE_MOCKS;
}
