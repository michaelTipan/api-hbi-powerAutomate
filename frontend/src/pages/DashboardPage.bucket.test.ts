import { describe, expect, it } from "vitest";
import { classifyProcessBucket } from "./DashboardPage";
import type { UiProcessSummary } from "../types/contract";

function summary(overrides: Partial<UiProcessSummary> = {}): UiProcessSummary {
  return {
    process_key: "payment-validation|banco_bogota|2026-07-31|abc",
    bank_code: "banco_bogota",
    process_date: "2026-07-31",
    environment: "sandbox",
    operational_status: "EN_REVISION",
    control_estado_proceso: "REVISION_CREADA",
    is_active: true,
    error_count: 0,
    next_actions: [],
    ...overrides,
  };
}

describe("classifyProcessBucket", () => {
  it("clasifica CORRECCION_REQUERIDA como 'Requieren atención'", () => {
    expect(
      classifyProcessBucket(summary({ operational_status: "CORRECCION_REQUERIDA" })),
    ).toBe("atencion");
  });

  it("clasifica ERROR_RECUPERABLE como 'Requieren atención'", () => {
    expect(
      classifyProcessBucket(summary({ operational_status: "ERROR_RECUPERABLE" })),
    ).toBe("atencion");
  });

  it("clasifica cualquier estado con error_count > 0 como 'Requieren atención', aunque el estado sea EN_REVISION", () => {
    // Caso del bug U4-B: Finalize fallido puede dejar operational_status=EN_REVISION
    // (el Excel de revisión se conserva) pero con avisos pendientes.
    const result = classifyProcessBucket(
      summary({ operational_status: "EN_REVISION", error_count: 1 }),
    );
    expect(result).toBe("atencion");
    expect(result).not.toBe("activos");
  });

  it("un proceso EN_REVISION sin errores va a 'Activos / en curso'", () => {
    expect(
      classifyProcessBucket(summary({ operational_status: "EN_REVISION", error_count: 0 })),
    ).toBe("activos");
  });

  it("clasifica ESPERANDO_SOPORTES", () => {
    expect(
      classifyProcessBucket(summary({ operational_status: "ESPERANDO_SOPORTES" })),
    ).toBe("soportes");
  });

  it("clasifica FINALIZADO_PARCIALMENTE como parciales", () => {
    expect(
      classifyProcessBucket(summary({ operational_status: "FINALIZADO_PARCIALMENTE" })),
    ).toBe("parciales");
  });

  it("clasifica COMPLETADO como finalizados", () => {
    expect(
      classifyProcessBucket(summary({ operational_status: "COMPLETADO" })),
    ).toBe("finalizados");
  });
});
