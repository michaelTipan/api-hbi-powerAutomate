import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { fetchProcesses } from "../api/client";
import type { UiProcessSummary } from "../types/contract";
import { statusClass } from "../components/AppShell";

function bucket(status: string): string {
  if (status.includes("ERROR") || status === "CORRECCION_REQUERIDA") return "errores";
  if (status === "ESPERANDO_SOPORTES") return "soportes";
  if (status === "ESPERANDO_IBR" || status === "FINALIZADO_PARCIALMENTE") return "parciales";
  if (status === "COMPLETADO") return "finalizados";
  return "activos";
}

export function DashboardPage() {
  const [items, setItems] = useState<UiProcessSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetchProcesses();
        if (!cancelled) setItems(res.items);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Error al cargar");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const groups = {
    activos: items.filter((i) => bucket(i.operational_status) === "activos"),
    errores: items.filter((i) => bucket(i.operational_status) === "errores"),
    soportes: items.filter((i) => bucket(i.operational_status) === "soportes"),
    parciales: items.filter((i) => bucket(i.operational_status) === "parciales"),
    finalizados: items.filter((i) => bucket(i.operational_status) === "finalizados"),
  };

  return (
    <section className="panel">
      <h1 style={{ marginTop: 0, fontFamily: "var(--font-display)", fontSize: "1.35rem" }}>
        Procesos del día
      </h1>
      <p className="muted" style={{ marginTop: 0 }}>
        Solo consulta (U1). Las acciones de escritura se habilitarán después.
      </p>
      {loading && <p className="muted">Cargando…</p>}
      {error && <div className="error-box">{error}</div>}
      {!loading && !error && (
        <div className="grid" style={{ gap: "1.5rem", marginTop: "1rem" }}>
          {(
            [
              ["Activos / en curso", groups.activos],
              ["Errores recuperables", groups.errores],
              ["Esperando soportes", groups.soportes],
              ["Parciales / IBR", groups.parciales],
              ["Finalizados", groups.finalizados],
            ] as const
          ).map(([title, list]) => (
            <div key={title}>
              <h2 style={{ fontSize: "0.95rem", margin: "0 0 0.6rem", color: "var(--muted)" }}>
                {title} ({list.length})
              </h2>
              {list.length === 0 ? (
                <p className="muted" style={{ margin: 0, fontSize: "0.85rem" }}>
                  Ninguno
                </p>
              ) : (
                <div className="grid grid-cards">
                  {list.map((p) => (
                    <Link
                      key={p.process_key}
                      className="process-card"
                      to={`/processes/${encodeURIComponent(p.process_key)}`}
                    >
                      <h3>{p.bank_code.replace("banco_", "Banco ").replace("_", " ")}</h3>
                      <p className="meta">Fecha: {p.process_date ?? "—"}</p>
                      <p className="meta">Control: {p.control_estado_proceso ?? "—"}</p>
                      <span className={`status-pill ${statusClass(p.operational_status)}`}>
                        {p.operational_status}
                      </span>
                      {p.error_count > 0 && (
                        <p className="meta" style={{ marginTop: "0.5rem" }}>
                          {p.error_count} aviso(s)
                        </p>
                      )}
                    </Link>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
