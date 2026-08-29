import { describe, expect, it, beforeEach } from "vitest";
import {
  invalidateReadCache,
  readDetailCache,
  readPanelCache,
  writeDetailCache,
  writePanelCache,
} from "./readCache";
import type { UiProcessDetail } from "../types/contract";

const minimalDetail = (key: string): UiProcessDetail =>
  ({
    process_key: key,
    bank_code: "banco_bogota",
    environment: "sandbox",
    operational_status: "EN_REVISION",
    operational_title: "",
    operational_message: "",
    control_estado_proceso: "REVISION_CREADA",
    is_active: true,
    steps: [],
    items: [],
    active_job: null,
    last_attempt: null,
    latest_attempts_by_stage: {},
    attempts: [],
    next_actions: [],
    available_actions: {},
    errors: [],
    operational_issues: [],
    links: [],
    document_groups: [],
    files: {},
    idempotency: {},
    operator_checklist: [],
  }) as UiProcessDetail;

describe("readCache", () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  it("guarda y lee caché del panel", () => {
    writePanelCache(
      [{ process_key: "pk-1", bank_code: "banco_bogota", environment: "sandbox", operational_status: "EN_REVISION", operational_title: "", operational_message: "", is_active: true, error_count: 0, next_actions: [] }],
      [{ bank_code: "banco_bogota", bank_name: "Bogotá", available_actions: { generate: { allowed: true, reason: null } } }],
      [],
    );
    const hit = readPanelCache();
    expect(hit?.items[0].process_key).toBe("pk-1");
    expect(hit?.banks.length).toBe(1);
  });

  it("invalida panel tras mutación", () => {
    writePanelCache([], [], []);
    invalidateReadCache("panel");
    expect(readPanelCache()).toBeNull();
  });

  it("invalida detalle por process_key", () => {
    const key = "payment-validation|banco_bogota|2026-01-01|abc";
    writeDetailCache(key, minimalDetail(key));
    invalidateReadCache("detail", key);
    expect(readDetailCache(key)).toBeNull();
  });

  it("invalidate all limpia panel y detalles", () => {
    const key = "payment-validation|banco_bogota|2026-01-01|abc";
    writePanelCache([], [], []);
    writeDetailCache(key, minimalDetail(key));
    invalidateReadCache("all");
    expect(readPanelCache()).toBeNull();
    expect(readDetailCache(key)).toBeNull();
  });
});
