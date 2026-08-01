import { describe, expect, it } from "vitest";

import type { UiProcessSummary } from "../types/contract";
import { classifyProcessBucket } from "./DashboardPage";

function summary(partial: Partial<UiProcessSummary>): UiProcessSummary {
  return {
    process_key: "pk",
    bank_code: "banco_bancolombia",
    process_date: "2026-07-31",
    environment: "sandbox",
    operational_status: "EN_REVISION",
    control_estado_proceso: null,
    is_active: true,
    error_count: 0,
    next_actions: [],
    ...partial,
  };
}

describe("classifyProcessBucket · PENDIENTE_NOTIFICACION", () => {
  it("clasifica FINALIZADO pendiente de Notify como activos (en curso)", () => {
    expect(
      classifyProcessBucket(summary({ operational_status: "PENDIENTE_NOTIFICACION" })),
    ).toBe("activos");
  });

  it("no clasifica pendiente de Notify como finalizados ni atención", () => {
    const bucket = classifyProcessBucket(
      summary({ operational_status: "PENDIENTE_NOTIFICACION", error_count: 0 }),
    );
    expect(bucket).not.toBe("finalizados");
    expect(bucket).not.toBe("atencion");
  });
});
