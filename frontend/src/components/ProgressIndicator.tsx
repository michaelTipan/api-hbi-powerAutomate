import { progressPhaseLabel } from "../copy/labels";

export interface ProgressData {
  phase?: string | null;
  current?: number | null;
  total?: number | null;
}

/**
 * Progreso de un job en curso. La barra y el porcentaje solo se muestran
 * cuando `total` es un número conocido: nunca se inventa un porcentaje.
 */
export function ProgressIndicator({
  progress,
}: {
  progress: ProgressData | null | undefined;
}) {
  if (!progress) return null;
  const phaseText = progressPhaseLabel(progress.phase);
  const hasCurrent = typeof progress.current === "number";
  const hasTotal = typeof progress.total === "number" && progress.total! > 0;
  const pct =
    hasCurrent && hasTotal
      ? Math.min(100, Math.max(0, Math.round((progress.current! / progress.total!) * 100)))
      : null;

  if (!phaseText && !hasCurrent) return null;

  return (
    <div className="progress-indicator" role="status">
      {phaseText && <p className="meta">{phaseText}…</p>}
      {hasCurrent && (
        <p className="meta">
          {progress.current}
          {hasTotal ? ` de ${progress.total}` : ""}
        </p>
      )}
      {pct !== null && (
        <div
          className="progress-bar"
          role="progressbar"
          aria-valuenow={pct}
          aria-valuemin={0}
          aria-valuemax={100}
        >
          <div className="progress-bar-fill" style={{ width: `${pct}%` }} />
        </div>
      )}
    </div>
  );
}
