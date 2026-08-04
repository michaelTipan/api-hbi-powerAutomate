import { describe, expect, it } from "vitest";
import { statusClass } from "./AppShell";

/** Compat: AppShell reexporta `statusClass`; cobertura detallada en statusTone.test. */
describe("statusClass (reexport AppShell)", () => {
  it("EN_REVISION no es éxito", () => {
    expect(statusClass("EN_REVISION")).toBe("info");
  });

  it("in_progress es procesamiento (info), no warn", () => {
    expect(statusClass("in_progress")).toBe("info");
  });

  it("CORRECCION_REQUERIDA / blocked son danger", () => {
    expect(statusClass("CORRECCION_REQUERIDA")).toBe("danger");
    expect(statusClass("blocked")).toBe("danger");
  });

  it("COMPLETADO y LISTO_PARA_CONSOLIDAR son ok", () => {
    expect(statusClass("COMPLETADO")).toBe("ok");
    expect(statusClass("LISTO_PARA_CONSOLIDAR")).toBe("ok");
  });

  it("ESPERANDO_SOPORTES es warn; ERROR_MERGE es danger", () => {
    expect(statusClass("ESPERANDO_SOPORTES")).toBe("warn");
    expect(statusClass("ERROR_MERGE")).toBe("danger");
  });
});
