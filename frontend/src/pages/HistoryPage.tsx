import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { fetchProcessHistory, type UiHistoryItem } from "../api/client";
import { operatorErrorMessage } from "../domain/jobMessages";
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

type BankFilter = "" | "banco_bogota" | "banco_bancolombia";
type SourceFilter = "all" | "active" | "archive";

/**
 * Historial Fase 2: Control activo + snapshots en 04 ARCHIVO PROCESOS.
 * Sin crear proceso.
 */
export function HistoryPage() {
  const [items, setItems] = useState<UiHistoryItem[]>([]);
  const [unavailableBanks, setUnavailableBanks] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [bankFilter, setBankFilter] = useState<BankFilter>("");
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>("all");

  const reload = useCallback(async () => {
    const procs = await fetchProcessHistory(bankFilter || undefined);
    setItems(procs.items);
    setUnavailableBanks(procs.unavailable_banks ?? []);
  }, [bankFilter]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    (async () => {
      try {
        await reload();
        if (!cancelled) setError(null);
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

  const visible = useMemo(() => {
    if (sourceFilter === "all") return items;
    return items.filter((i) => i.source === sourceFilter);
  }, [items, sourceFilter]);

  return (
    <section className="panel history-page">
      <header className="page-header">
        <div>
          <h1 className="page-title">Historial</h1>
          <p className="muted page-lead">
            Consulte procesos activos del Control y lotes archivados al cerrar.
          </p>
        </div>
      </header>

      <div className="history-filters new-process-row" style={{ marginTop: 0 }}>
        <div>
          <label className="field-label" htmlFor="history-bank-filter">
            Banco
          </label>
          <select
            id="history-bank-filter"
            className="field-select"
            value={bankFilter}
            onChange={(e) => setBankFilter(e.target.value as BankFilter)}
          >
            <option value="">Todos</option>
            <option value="banco_bogota">Banco Bogotá</option>
            <option value="banco_bancolombia">Bancolombia</option>
          </select>
        </div>
        <div>
          <label className="field-label" htmlFor="history-source-filter">
            Origen
          </label>
          <select
            id="history-source-filter"
            className="field-select"
            value={sourceFilter}
            onChange={(e) => setSourceFilter(e.target.value as SourceFilter)}
          >
            <option value="all">Todos</option>
            <option value="active">En Control (activos)</option>
            <option value="archive">Archivados</option>
          </select>
        </div>
      </div>

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

      {!loading && !error && visible.length === 0 ? (
        <p className="muted">{historyEmptyStateMessage}</p>
      ) : null}

      {!loading && visible.length > 0 ? (
        <div className="history-table-wrap" role="region" aria-label="Historial de procesos">
          <table className="history-table">
            <thead>
              <tr>
                <th scope="col">Banco</th>
                <th scope="col">Fecha</th>
                <th scope="col">Estado</th>
                <th scope="col">Origen</th>
                <th scope="col">Resumen</th>
                <th scope="col">Acción</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((p) => {
                const archived = p.source === "archive";
                const completed = p.operational_status === "COMPLETADO";
                const actionLabel = archived
                  ? actionLabels.view_detail
                  : completed
                    ? actionLabels.view_detail
                    : actionLabels.continue_process;
                const href = archived
                  ? `/historial/${encodeURIComponent(p.process_key)}`
                  : `/processes/${encodeURIComponent(p.process_key)}`;
                return (
                  <tr key={`${p.source}-${p.process_key}`}>
                    <td>{p.bank_name || bankLabel(p.bank_code)}</td>
                    <td>{p.process_date ?? "—"}</td>
                    <td>
                      <span className={`status-pill ${statusClass(p.operational_status)}`}>
                        {p.operational_title || operationalStatusLabel(p.operational_status)}
                      </span>
                    </td>
                    <td>
                      <span className="meta">
                        {archived ? "Archivo" : "Activo"}
                      </span>
                    </td>
                    <td className="history-summary-cell">
                      {p.operational_message || "—"}
                    </td>
                    <td>
                      <Link className="btn secondary btn-compact" to={href}>
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
