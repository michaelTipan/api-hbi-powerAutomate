import type { ResolvedOperatorPhase } from "../domain/processPhases";

/**
 * Resumen breve: el stepper ya comunica completadas/pendientes visualmente
 * (forma + color + número/✓). Solo anuncia posición y nombre de la fase.
 */
export function formatPhaseProgressSummary(
  phases: readonly ResolvedOperatorPhase[],
  currentTitle: string,
): string {
  const total = phases.length;
  const completed = phases.filter((p) => p.visual === "completed").length;
  const hasCurrent = phases.some((p) => p.visual === "current");
  const currentIndex = phases.findIndex((p) => p.visual === "current");
  const currentOrdinal = currentIndex >= 0 ? currentIndex + 1 : total;

  if (!hasCurrent && completed === total) {
    return `Proceso completo · ${total} de ${total} fases`;
  }

  return `Fase ${currentOrdinal} de ${total} · ${currentTitle}`;
}

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
  return (
    <nav className="phase-stepper" aria-label="Progreso del proceso">
      <p className="phase-stepper-summary meta">
        {formatPhaseProgressSummary(phases, currentTitle)}
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
