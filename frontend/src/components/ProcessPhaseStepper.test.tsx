import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { formatPhaseProgressSummary, ProcessPhaseStepper } from "./ProcessPhaseStepper";
import type { ResolvedOperatorPhase } from "../domain/processPhases";
import {
  buildPhaseStepperModel,
  OPERATOR_PHASES,
  REGENERATE_FOCUS_LOCK_REASON,
  resolveOperatorPhases,
} from "../domain/processPhases";
import type { UiStepState } from "../types/contract";

function resolved(
  visuals: Array<"completed" | "current" | "upcoming">,
): ResolvedOperatorPhase[] {
  return OPERATOR_PHASES.map((def, i) => ({
    def,
    visual: visuals[i] ?? "upcoming",
    unlocked: (visuals[i] ?? "upcoming") !== "upcoming",
  }));
}

function step(name: UiStepState["name"], status: UiStepState["status"]): UiStepState {
  return { name, status, updated_at: null, summary: null, can_retry: false, retry_action: null };
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

  it("con selectedId anuncia la fase consultada, no solo la viva", () => {
    const phases = resolved([
      "completed",
      "completed",
      "current",
      "upcoming",
      "upcoming",
    ]);
    expect(formatPhaseProgressSummary(phases, "Generar archivo", "review")).toBe(
      "Fase 1 de 5 · Generar archivo",
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

describe("ProcessPhaseStepper — bloqueo por regeneración", () => {
  it("no permite seleccionar Finalizar cuando está locked", async () => {
    const { phases } = resolveOperatorPhases([
      step("generate", "completed"),
      step("review", "in_progress"),
      step("finalize", "not_started"),
      step("notify", "not_started"),
      step("merge", "not_started"),
      step("dry_run", "not_started"),
      step("apply", "not_started"),
    ]);
    const model = buildPhaseStepperModel(phases, true);
    const onSelect = vi.fn();
    const user = userEvent.setup();

    render(
      <ProcessPhaseStepper
        phases={model}
        currentTitle="Generar archivo"
        selectedId="review"
        onSelectPhase={onSelect}
      />,
    );

    const locked = screen.getByRole("button", {
      name: new RegExp(`Finalizar revisión \\(bloqueada\\).*${REGENERATE_FOCUS_LOCK_REASON}`),
    });
    expect(locked).toBeDisabled();
    expect(locked).toHaveAttribute("title", REGENERATE_FOCUS_LOCK_REASON);
    await user.click(locked);
    expect(onSelect).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: /Ir a Generar archivo/i }));
    expect(onSelect).toHaveBeenCalledWith("review");
  });

  it("permite seleccionar Finalizar en el happy path", async () => {
    const { phases } = resolveOperatorPhases([
      step("generate", "completed"),
      step("review", "in_progress"),
      step("finalize", "not_started"),
      step("notify", "not_started"),
      step("merge", "not_started"),
      step("dry_run", "not_started"),
      step("apply", "not_started"),
    ]);
    const model = buildPhaseStepperModel(phases, false);
    const onSelect = vi.fn();
    const user = userEvent.setup();

    render(
      <ProcessPhaseStepper
        phases={model}
        currentTitle="Finalizar revisión"
        selectedId="finalize"
        onSelectPhase={onSelect}
      />,
    );

    const finalize = screen.getByRole("button", { name: /Ir a Finalizar revisión/i });
    expect(finalize).toBeEnabled();
    await user.click(finalize);
    expect(onSelect).toHaveBeenCalledWith("finalize");
  });
});
