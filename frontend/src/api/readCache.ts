import type { UiBankCapabilities } from "./client";
import type { UiProcessDetail, UiProcessSummary } from "../types/contract";

const PANEL_KEY = "ui-read-cache:panel";
const DETAIL_PREFIX = "ui-read-cache:detail:";

export type PanelCachePayload = {
  items: UiProcessSummary[];
  banks: UiBankCapabilities[];
  unavailable_banks: string[];
  ts: number;
};

export type DetailCachePayload = {
  key: string;
  detail: UiProcessDetail;
  ts: number;
};

function readJson<T>(key: string): T | null {
  if (typeof window === "undefined" || !window.sessionStorage) return null;
  try {
    const raw = window.sessionStorage.getItem(key);
    if (!raw) return null;
    return JSON.parse(raw) as T;
  } catch {
    return null;
  }
}

function writeJson(key: string, value: unknown): void {
  if (typeof window === "undefined" || !window.sessionStorage) return;
  try {
    window.sessionStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* quota / private mode */
  }
}

export function readPanelCache(): PanelCachePayload | null {
  return readJson<PanelCachePayload>(PANEL_KEY);
}

export function writePanelCache(
  items: UiProcessSummary[],
  banks: UiBankCapabilities[],
  unavailable_banks: string[],
): void {
  writeJson(PANEL_KEY, {
    items,
    banks,
    unavailable_banks,
    ts: Date.now(),
  });
}

export function readDetailCache(processKey: string): DetailCachePayload | null {
  const key = (processKey || "").trim();
  if (!key) return null;
  return readJson<DetailCachePayload>(`${DETAIL_PREFIX}${key}`);
}

export function writeDetailCache(processKey: string, detail: UiProcessDetail): void {
  const key = (processKey || "").trim();
  if (!key) return;
  writeJson(`${DETAIL_PREFIX}${key}`, {
    key,
    detail,
    ts: Date.now(),
  });
}

export function invalidateReadCache(
  scope: "panel" | "detail" | "all" = "all",
  processKey?: string,
): void {
  if (typeof window === "undefined" || !window.sessionStorage) return;
  if (scope === "panel" || scope === "all") {
    window.sessionStorage.removeItem(PANEL_KEY);
  }
  if (scope === "detail" || scope === "all") {
    const pk = (processKey || "").trim();
    if (pk) {
      window.sessionStorage.removeItem(`${DETAIL_PREFIX}${pk}`);
    } else if (scope === "all") {
      for (let i = 0; i < window.sessionStorage.length; i += 1) {
        const k = window.sessionStorage.key(i);
        if (k?.startsWith(DETAIL_PREFIX)) {
          window.sessionStorage.removeItem(k);
        }
      }
    }
  }
}
