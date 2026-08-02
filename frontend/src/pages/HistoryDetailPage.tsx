import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { fetchProcessHistoryDetail, type UiHistoryDetail } from "../api/client";
import { operatorErrorMessage } from "../domain/jobMessages";
import { statusClass } from "../components/AppShell";
import { CardSkeleton } from "../components/Skeleton";
import { actionLabels, operationalStatusLabel } from "../copy/labels";

function bankLabel(code: string): string {
  if (code === "banco_bogota") return "Banco Bogotá";
  if (code === "banco_bancolombia") return "Bancolombia";
  return code;
}

/** Detalle solo lectura de un proceso archivado (Fase 2). */
export function HistoryDetailPage() {
  const { processKey: rawKey } = useParams();
  const processKey = rawKey ? decodeURIComponent(rawKey) : "";
  const [detail, setDetail] = useState<UiHistoryDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!processKey) {
        setError("Proceso no indicado.");
        setLoading(false);
        return;
      }
      try {
        const d = await fetchProcessHistoryDetail(processKey);
        if (!cancelled) setDetail(d);
      } catch (e) {
        if (!cancelled) {
          setError(
            operatorErrorMessage(e, "No pudimos cargar el detalle histórico.").message,
          );
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [processKey]);

  return (
    <div className="process-detail">
      <div className="process-detail-toolbar">
        <Link className="back-link" to="/historial">
          <span aria-hidden="true">&lt;</span> Volver al historial
        </Link>
      </div>

      {loading ? <CardSkeleton /> : null}
      {error ? <div className="error-box">{error}</div> : null}

      {detail ? (
        <>
          <section className="panel" aria-labelledby="history-detail-title">
            <p className="meta" style={{ marginTop: 0 }}>
              Solo lectura · archivo histórico
            </p>
            <h1 id="history-detail-title" className="page-title" style={{ marginTop: "0.35rem" }}>
              {detail.bank_name || bankLabel(detail.bank_code)}
            </h1>
            <p className="meta">Fecha: {detail.process_date ?? "—"}</p>
            <span className={`status-pill ${statusClass(detail.operational_status)}`}>
              {detail.operational_title || operationalStatusLabel(detail.operational_status)}
            </span>
            {detail.operational_message ? (
              <p className="meta" style={{ marginTop: "0.65rem" }}>
                {detail.operational_message}
              </p>
            ) : null}
            {detail.closed_at ? (
              <p className="meta">Archivado: {detail.closed_at}</p>
            ) : null}
          </section>

          <section className="panel" aria-labelledby="history-docs-title">
            <h2 id="history-docs-title" className="section-title">
              Documentos del proceso
            </h2>
            {detail.links.length === 0 ? (
              <p className="muted">No hay enlaces disponibles para este archivo.</p>
            ) : (
              <div className="actions">
                {detail.links.map((l) =>
                  l.web_url ? (
                    <a
                      key={l.rel}
                      className="btn secondary"
                      href={l.web_url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {l.label}
                    </a>
                  ) : (
                    <span key={l.rel} className="meta">
                      {l.label} (no disponible)
                    </span>
                  ),
                )}
              </div>
            )}
            <p className="meta" style={{ marginTop: "1rem" }}>
              Este proceso ya no está en el Control activo. Para operar un lote nuevo use el{" "}
              <Link to="/">{actionLabels.back_to_dashboard.toLowerCase()}</Link>.
            </p>
          </section>
        </>
      ) : null}
    </div>
  );
}
