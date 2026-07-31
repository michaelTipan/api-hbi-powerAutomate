import type { UiLastAttempt } from "../types/contract";
import { Disclosure } from "./Disclosure";
import { stageLabel, statusLabel } from "../copy/labels";

/** Historial de intentos por etapa, plegado por defecto. */
export function AttemptHistory({
  attempts,
}: {
  attempts: Record<string, UiLastAttempt> | null | undefined;
}) {
  const entries = Object.entries(attempts ?? {});
  if (entries.length === 0) return null;
  return (
    <section className="panel">
      <Disclosure summary={`Historial de intentos (${entries.length})`}>
        {entries.map(([stageKey, attempt]) => (
          <div key={stageKey} className="attempt-history-item">
            <p style={{ margin: 0, fontWeight: 600 }}>
              {stageLabel(attempt.stage || stageKey)} · {statusLabel(attempt.status)}
            </p>
            {attempt.user_message && <p className="meta">{attempt.user_message}</p>}
            {attempt.next_action && <p className="meta">{attempt.next_action}</p>}
            <p className="meta">{attempt.finished_at ?? attempt.started_at ?? "Fecha no disponible"}</p>
          </div>
        ))}
      </Disclosure>
    </section>
  );
}
