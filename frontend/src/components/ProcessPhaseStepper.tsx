import type { OperatorPhaseId, ResolvedOperatorPhase } from "../domain/processPhases";

/**
 * Resumen breve: el stepper ya comunica completadas/pendientes visualmente
 * (forma + color + número/✓). Anuncia posición de la fase vista (o la viva).
 */
export function formatPhaseProgressSummary(
  phases: readonly ResolvedOperatorPhase[],
  currentTitle: string,
  selectedId?: OperatorPhaseId,
): string {
  const total = phases.length;
  const completed = phases.filter((p) => p.visual === "completed").length;
  const hasCurrent = phases.some((p) => p.visual === "current");
  const selectedIndex =
    selectedId != null ? phases.findIndex((p) => p.def.id === selectedId) : -1;
  const currentIndex = phases.findIndex((p) => p.visual === "current");
  const currentOrdinal =
    selectedIndex >= 0 ? selectedIndex + 1 : currentIndex >= 0 ? currentIndex + 1 : total;

  if (!hasCurrent && completed === total) {
    return `Proceso completo · ${total} de ${total} fases`;
  }

  return `Fase ${currentOrdinal} de ${total} · ${currentTitle}`;
}

/**
 * Header de fases: permite navegar a fases ya alcanzadas (completadas o actual).
 * Las futuras / bloqueadas permanecen no seleccionables.
 */
export function ProcessPhaseStepper({
  phases,
  currentTitle,
  selectedId,
  onSelectPhase,
}: {
  phases: readonly ResolvedOperatorPhase[];
  currentTitle: string;
  selectedId?: OperatorPhaseId;
  onSelectPhase?: (id: OperatorPhaseId) => void;
}) {
  return (
    <nav className="phase-stepper" aria-label="Progreso del proceso">
      <p className="phase-stepper-summary meta">
        {formatPhaseProgressSummary(phases, currentTitle, selectedId)}
      </p>
      <ol className="phase-stepper-list">
        {phases.map((phase, index) => {
          const { def, visual, unlocked, lockReason } = phase;
          const isSelected = selectedId === def.id;
          const className = [
            "phase-step",
            `phase-step--${visual}`,
            isSelected ? "phase-step--selected" : "",
            !unlocked && lockReason ? "phase-step--locked" : "",
          ]
            .filter(Boolean)
            .join(" ");
          const marker = visual === "completed" ? "✓" : index + 1;
          const label = def.shortLabel;

          if (unlocked && onSelectPhase) {
            const stateHint =
              visual === "completed"
                ? "completada"
                : visual === "current"
                  ? "fase actual"
                  : "alcanzada";
            return (
              <li key={def.id} className={className}>
                <button
                  type="button"
                  className="phase-step-button"
                  aria-current={isSelected ? "step" : undefined}
                  aria-label={`Ir a ${label} (${stateHint})`}
                  onClick={() => onSelectPhase(def.id)}
                >
                  <span className="phase-step-marker" aria-hidden="true">
                    {marker}
                  </span>
                  <span className="phase-step-label">{label}</span>
                </button>
              </li>
            );
          }

          if (lockReason) {
            return (
              <li key={def.id} className={className}>
                <button
                  type="button"
                  className="phase-step-button"
                  disabled
                  aria-disabled="true"
                  title={lockReason}
                  aria-label={`${label} (bloqueada). ${lockReason}`}
                >
                  <span className="phase-step-marker" aria-hidden="true">
                    {marker}
                  </span>
                  <span className="phase-step-label">{label}</span>
                </button>
              </li>
            );
          }

          return (
            <li
              key={def.id}
              className={className}
              aria-current={isSelected ? "step" : undefined}
            >
              <span className="phase-step-marker" aria-hidden="true">
                {marker}
              </span>
              <span className="phase-step-label">{label}</span>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
