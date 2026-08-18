import { describe, expect, it } from "vitest";
import { classifyProcessBucket, shouldPollDashboardProcesses } from "./DashboardPage";
import type { UiBankCapabilities } from "../api/client";
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

  it("clasifica REQUIERE_VERIFICACION como 'Requieren atención'", () => {
    expect(
      classifyProcessBucket(summary({ operational_status: "REQUIERE_VERIFICACION" })),
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

describe("shouldPollDashboardProcesses", () => {
  const bank = (reason: string | null): UiBankCapabilities =>
    ({
      bank_code: "banco_bancolombia",
      bank_name: "Bancolombia",
      available_actions: { generate: { allowed: !reason, reason } },
      dashboard_primary_action: reason ? "generate" : "generate",
      control_readable: true,
      active_process_key: null,
    }) as UiBankCapabilities;

  it("sondea cuando un proceso está GENERANDO", () => {
    expect(
      shouldPollDashboardProcesses(
        [summary({ operational_status: "GENERANDO" })],
        [bank(null)],
      ),
    ).toBe(true);
  });

  it("sondea cuando el lock de mutación está tomado aunque el lote parezca cancelado", () => {
    expect(
      shouldPollDashboardProcesses(
        [summary({ operational_status: "CANCELADO" })],
        [bank("Ya hay una operación en curso. Espere a que termine antes de iniciar otra.")],
      ),
    ).toBe(true);
  });

  it("no sondea en revisión quieta sin lock", () => {
    expect(
      shouldPollDashboardProcesses(
        [summary({ operational_status: "EN_REVISION" })],
        [bank(null)],
      ),
    ).toBe(false);
  });
});
