import { describe, expect, it } from "vitest";
import { statusClass } from "./AppShell";

describe("statusClass — semántica de color por estado", () => {
  it("EN_REVISION es un estado neutral de espera, no un éxito (verde)", () => {
    expect(statusClass("EN_REVISION")).not.toBe("ok");
    expect(statusClass("EN_REVISION")).toBe("info");
  });

  it("in_progress no es éxito", () => {
    expect(statusClass("in_progress")).not.toBe("ok");
    expect(statusClass("in_progress")).toBe("warn");
  });

  it("CORRECCION_REQUERIDA es un problema (danger), nunca éxito", () => {
    expect(statusClass("CORRECCION_REQUERIDA")).toBe("danger");
    expect(statusClass("CORRECCION_REQUERIDA")).not.toBe("ok");
  });

  it("COMPLETADO / completed sí son éxito", () => {
    expect(statusClass("COMPLETADO")).toBe("ok");
    expect(statusClass("completed")).toBe("ok");
  });

  it("estados de espera/parciales son advertencia", () => {
    expect(statusClass("ESPERANDO_SOPORTES")).toBe("warn");
    expect(statusClass("partial")).toBe("warn");
    expect(statusClass("blocked")).toBe("warn");
  });

  it("estados con ERROR o failed son danger", () => {
    expect(statusClass("ERROR_MERGE")).toBe("danger");
    expect(statusClass("failed")).toBe("danger");
  });
});
