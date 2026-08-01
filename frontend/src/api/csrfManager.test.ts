import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  clearCsrfTokenMemory,
  ensureCsrfToken,
  getCsrfTokenMemory,
  isCsrfReady,
  resetCsrfManagerForTests,
  setCsrfTokenMemory,
  setLocalSessionMode,
  subscribeCsrfReady,
} from "./csrfManager";

describe("csrfManager", () => {
  beforeEach(() => {
    resetCsrfManagerForTests();
  });

  afterEach(() => {
    resetCsrfManagerForTests();
  });

  it("sin local_session el gate está listo", () => {
    expect(isCsrfReady()).toBe(true);
  });

  it("con local_session exige token en memoria", () => {
    setLocalSessionMode(true);
    expect(isCsrfReady()).toBe(false);
    setCsrfTokenMemory("token-vigente-abc");
    expect(isCsrfReady()).toBe(true);
    expect(getCsrfTokenMemory()).toBe("token-vigente-abc");
  });

  it("rechaza token vacío", () => {
    expect(() => setCsrfTokenMemory("   ")).toThrow(/vacío/);
  });

  it("logout/clear limpia memoria y desactiva ready", () => {
    setLocalSessionMode(true);
    setCsrfTokenMemory("token-vigente-abc");
    clearCsrfTokenMemory();
    expect(getCsrfTokenMemory()).toBeNull();
    expect(isCsrfReady()).toBe(false);
  });

  it("ensureCsrfToken comparte una sola renovación concurrente", async () => {
    setLocalSessionMode(true);
    let calls = 0;
    const loader = vi.fn(async () => {
      calls += 1;
      await new Promise((r) => setTimeout(r, 30));
      return `csrf-${calls}`;
    });
    const [a, b, c] = await Promise.all([
      ensureCsrfToken(loader),
      ensureCsrfToken(loader),
      ensureCsrfToken(loader),
    ]);
    expect(loader).toHaveBeenCalledTimes(1);
    expect(a).toBe(b);
    expect(b).toBe(c);
    expect(getCsrfTokenMemory()).toBe(a);
  });

  it("notifica listeners al cambiar ready", () => {
    setLocalSessionMode(true);
    const spy = vi.fn();
    const unsub = subscribeCsrfReady(spy);
    setCsrfTokenMemory("nuevo");
    expect(spy).toHaveBeenCalled();
    unsub();
  });
});
