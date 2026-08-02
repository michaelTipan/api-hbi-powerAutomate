import { describe, expect, it } from "vitest";
import { formatPhaseProgressSummary } from "./ProcessPhaseStepper";
import type { ResolvedOperatorPhase } from "../domain/processPhases";
import { OPERATOR_PHASES } from "../domain/processPhases";

function resolved(
  visuals: Array<"completed" | "current" | "upcoming">,
): ResolvedOperatorPhase[] {
  return OPERATOR_PHASES.map((def, i) => ({
    def,
    visual: visuals[i] ?? "upcoming",
    unlocked: (visuals[i] ?? "upcoming") !== "upcoming",
  }));
}

describe("formatPhaseProgressSummary", () => {
  it("anuncia fase N de 5 sin repetir el conteo del stepper", () => {
    const phases = resolved([
      "completed",
      "completed",
      "current",
      "upcoming",
      "upcoming",
    ]);
    expect(formatPhaseProgressSummary(phases, "Enviar correo")).toBe(
      "Fase 3 de 5 · Enviar correo",
    );
  });

  it("marca proceso completo cuando las 5 son completed", () => {
    const phases = resolved([
      "completed",
      "completed",
      "completed",
      "completed",
      "completed",
    ]);
    expect(formatPhaseProgressSummary(phases, "Procesar amortización")).toBe(
      "Proceso completo · 5 de 5 fases",
    );
  });
});
