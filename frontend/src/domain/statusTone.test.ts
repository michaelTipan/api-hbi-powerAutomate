import { describe, expect, it } from "vitest";
import {
  LISTO_PARA_CONSOLIDAR,
  resolveProcessBadgeStatus,
  statusClass,
  statusTone,
} from "./statusTone";

describe("statusTone — semántica de color por estado", () => {
  it("EN_REVISION es espera de acción humana (azul), no éxito", () => {
    expect(statusTone("EN_REVISION")).toBe("info");
    expect(statusClass("EN_REVISION")).toBe("info");
  });

  it("in_progress / running son procesamiento (azul), no advertencia", () => {
    expect(statusTone("in_progress")).toBe("info");
    expect(statusTone("running")).toBe("info");
    expect(statusClass("in_progress")).toBe("info");
  });

  it("REQUIERE_VERIFICACION y requires_verification son danger, no éxito", () => {
    expect(statusTone("REQUIERE_VERIFICACION")).toBe("danger");
    expect(statusTone("requires_verification")).toBe("danger");
    expect(statusClass("REQUIERE_VERIFICACION")).toBe("danger");
  });

  it("COMPLETADO / completed / LISTO_* son éxito (verde)", () => {
    expect(statusTone("COMPLETADO")).toBe("ok");
    expect(statusTone("completed")).toBe("ok");
    expect(statusTone("LISTO_PARA_APLICAR")).toBe("ok");
    expect(statusTone(LISTO_PARA_CONSOLIDAR)).toBe("ok");
    expect(statusTone("LISTO_PARA_NOTIFICAR")).toBe("ok");
    expect(statusClass("COMPLETADO")).toBe("ok");
  });

  it("CONSOLIDADO y AMORTIZACION_APLICADA son éxito", () => {
    expect(statusTone("CONSOLIDADO")).toBe("ok");
    expect(statusTone("AMORTIZACION_APLICADA")).toBe("ok");
  });

  it("ESPERANDO / parciales son advertencia (ámbar)", () => {
    expect(statusTone("ESPERANDO_SOPORTES")).toBe("warn");
    expect(statusTone("partial")).toBe("warn");
    expect(statusTone("FINALIZADO_PARCIALMENTE")).toBe("warn");
    expect(statusClass("ESPERANDO_SOPORTES")).toBe("warn");
  });

  it("ERROR_* / failed son danger", () => {
    expect(statusTone("ERROR_MERGE")).toBe("danger");
    expect(statusTone("failed")).toBe("danger");
  });

  it("busy operativos (GENERANDO, SINCRONIZANDO) son info", () => {
    expect(statusTone("GENERANDO")).toBe("info");
    expect(statusTone("SINCRONIZANDO")).toBe("info");
    expect(statusTone("CONSOLIDANDO")).toBe("info");
  });
});

describe("resolveProcessBadgeStatus", () => {
  it("con ESPERANDO_SOPORTES + merge ready usa LISTO_PARA_CONSOLIDAR (verde)", () => {
    expect(
      resolveProcessBadgeStatus({
        operationalStatus: "ESPERANDO_SOPORTES",
        mergeReadinessStatus: "ready",
      }),
    ).toBe(LISTO_PARA_CONSOLIDAR);
    expect(
      statusClass(
        resolveProcessBadgeStatus({
          operationalStatus: "ESPERANDO_SOPORTES",
          mergeReadinessStatus: "ready",
        }),
      ),
    ).toBe("ok");
  });

  it("con ESPERANDO_SOPORTES + incomplete conserva espera (ámbar)", () => {
    expect(
      resolveProcessBadgeStatus({
        operationalStatus: "ESPERANDO_SOPORTES",
        mergeReadinessStatus: "incomplete",
      }),
    ).toBe("ESPERANDO_SOPORTES");
    expect(statusClass("ESPERANDO_SOPORTES")).toBe("warn");
  });
});
