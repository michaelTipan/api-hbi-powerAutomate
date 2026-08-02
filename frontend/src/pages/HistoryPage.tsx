import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { fetchProcesses } from "../api/client";
import { operatorErrorMessage } from "../domain/jobMessages";
import type { UiProcessSummary } from "../types/contract";
import { statusClass } from "../components/AppShell";
import { CardSkeleton } from "../components/Skeleton";
import {
  actionLabels,
  historyEmptyStateMessage,
  operationalStatusLabel,
} from "../copy/labels";

function bankLabel(code: string): string {
  if (code === "banco_bogota") return "Banco Bogotá";
  if (code === "banco_bancolombia") return "Bancolombia";
  return code;
}

/**
 * Historial Fase 1: solo procesos del Control activo (0–2 filas).
 * Sin crear proceso; consulta y acceso al detalle.
 */
export function HistoryPage() {
  const [items, setItems] = useState<UiProcessSummary[]>([]);
  const [unavailableBanks, setUnavailableBanks] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const reload = useCallback(async () => {
    const procs = await fetchProcesses();
    setItems(procs.items);
    setUnavailableBanks(procs.unavailable_banks ?? []);
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        await reload();
      } catch (e) {
        if (!cancelled) {
          setError(
            operatorErrorMessage(e, "No pudimos cargar el historial. Intente de nuevo.")
              .message,
          );
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [reload]);

  return (
    <section className="panel history-page">
      <header className="page-header">
        <div>
          <h1 className="page-title">Historial</h1>
          <p className="muted page-lead">
            Consulte los procesos registrados en el Control activo (hasta uno por banco).
          </p>
        </div>
      </header>

      {unavailableBanks.length > 0 ? (
        <div className="error-box" role="alert">
          No pudimos leer el estado de {unavailableBanks.map(bankLabel).join(" y ")}.
        </div>
      ) : null}
      {error ? <div className="error-box">{error}</div> : null}

      {loading ? (
        <div className="grid grid-cards" style={{ marginTop: "1rem" }}>
          <CardSkeleton />
          <CardSkeleton />
        </div>
      ) : null}

      {!loading && !error && items.length === 0 ? (
        <p className="muted">{historyEmptyStateMessage}</p>
      ) : null}

      {!loading && items.length > 0 ? (
        <div className="history-table-wrap" role="region" aria-label="Procesos del Control">
          <table className="history-table">
            <thead>
              <tr>
                <th scope="col">Banco</th>
                <th scope="col">Fecha</th>
                <th scope="col">Estado</th>
                <th scope="col">Etapa / resumen</th>
                <th scope="col">Acción</th>
              </tr>
            </thead>
            <tbody>
              {items.map((p) => {
                const completed = p.operational_status === "COMPLETADO";
                const actionLabel = completed
                  ? actionLabels.view_detail
                  : actionLabels.continue_process;
                return (
                  <tr key={p.process_key}>
                    <td>{bankLabel(p.bank_code)}</td>
                    <td>{p.process_date ?? "—"}</td>
                    <td>
                      <span className={`status-pill ${statusClass(p.operational_status)}`}>
                        {p.operational_title || operationalStatusLabel(p.operational_status)}
                      </span>
                    </td>
                    <td className="history-summary-cell">
                      {p.operational_message || "—"}
                    </td>
                    <td>
                      <Link
                        className="btn secondary btn-compact"
                        to={`/processes/${encodeURIComponent(p.process_key)}`}
                      >
                        {actionLabel}
                      </Link>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}
