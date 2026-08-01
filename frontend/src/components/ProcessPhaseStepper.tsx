import type { ResolvedOperatorPhase } from "../domain/processPhases";

/**
 * Stepper permanente: indica en qué fase está el operador y cuántas le faltan.
 * Completadas → visto verde; actual → resaltada; futuras → atenuadas.
 */
export function ProcessPhaseStepper({
  phases,
  currentTitle,
}: {
  phases: readonly ResolvedOperatorPhase[];
  currentTitle: string;
}) {
  const completed = phases.filter((p) => p.visual === "completed").length;
  const total = phases.length;
  const remaining = Math.max(0, total - completed - (phases.some((p) => p.visual === "current") ? 1 : 0));

  return (
    <nav className="phase-stepper" aria-label="Progreso del proceso">
      <p className="phase-stepper-summary meta">
        {phases.every((p) => p.visual === "completed")
          ? `Proceso completo · ${total} de ${total} fases`
          : `Fase actual: ${currentTitle} · ${completed} completada${completed === 1 ? "" : "s"} · ${remaining} pendiente${remaining === 1 ? "" : "s"}`}
      </p>
      <ol className="phase-stepper-list">
        {phases.map((phase, index) => {
          const { def, visual } = phase;
          return (
            <li
              key={def.id}
              className={`phase-step phase-step--${visual}`}
              aria-current={visual === "current" ? "step" : undefined}
            >
              <span className="phase-step-marker" aria-hidden="true">
                {visual === "completed" ? "✓" : index + 1}
              </span>
              <span className="phase-step-label">{def.shortLabel}</span>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
