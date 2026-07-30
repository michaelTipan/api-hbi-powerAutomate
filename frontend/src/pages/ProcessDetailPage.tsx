import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { fetchJob, fetchProcess } from "../api/client";
import type { UiJobView, UiProcessDetail } from "../types/contract";
import { statusClass } from "../components/AppShell";

const STEP_LABEL: Record<string, string> = {
  generate: "Generate",
  review: "Revisión",
  finalize: "Finalize",
  notify: "Notify / correo",
  merge: "Merge PDF",
  dry_run: "Dry-run",
  apply: "Apply",
};

export function ProcessDetailPage() {
  const { processKey = "" } = useParams();
  const key = decodeURIComponent(processKey);
  const [detail, setDetail] = useState<UiProcessDetail | null>(null);
  const [job, setJob] = useState<UiJobView | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;

    const load = async () => {
      try {
        const p = await fetchProcess(key);
        if (cancelled) return;
        setDetail(p);
        setError(null);
        if (p.active_job?.job_id) {
          try {
            const j = await fetchJob(p.active_job.job_id);
            if (!cancelled) setJob(j);
          } catch {
            if (!cancelled) setJob(null);
          }
          const running = ["queued", "running"].includes(
            (p.active_job.status || "").toLowerCase(),
          );
          if (running) {
            timer = window.setTimeout(load, 4000);
          }
        } else {
          setJob(null);
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Error");
      }
    };

    void load();
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [key]);

  if (error) {
    return (
      <section className="panel">
        <Link className="back" to="/">
          ← Volver
        </Link>
        <div className="error-box">{error}</div>
      </section>
    );
  }

  if (!detail) {
    return (
      <section className="panel">
        <p className="muted">Cargando proceso…</p>
      </section>
    );
  }

  return (
    <div className="grid" style={{ gap: "1rem" }}>
      <section className="panel">
        <Link className="back" to="/">
          ← Dashboard
        </Link>
        <h1 style={{ margin: "0 0 0.35rem", fontFamily: "var(--font-display)", fontSize: "1.4rem" }}>
          {detail.bank_name ?? detail.bank_code}
        </h1>
        <p className="meta">Fecha: {detail.process_date ?? "—"}</p>
        <p className="meta" style={{ wordBreak: "break-all" }}>
          process_key: {detail.process_key}
        </p>
        <span className={`status-pill ${statusClass(detail.operational_status)}`}>
          {detail.operational_status}
        </span>
        <p className="meta" style={{ marginTop: "0.75rem" }}>
          Estado control: {detail.control_estado_proceso ?? "—"}
        </p>
        {detail.active_job && (
          <p className="meta">
            Job activo: {detail.active_job.type} · {detail.active_job.status}
            {job ? ` · store ${job.store}` : ""}
          </p>
        )}
      </section>

      <section className="panel">
        <h2 style={{ marginTop: 0, fontSize: "1.05rem" }}>Progreso por etapa</h2>
        <ul className="timeline">
          {detail.steps.map((s) => (
            <li key={s.name}>
              <div className="step-name">{STEP_LABEL[s.name] ?? s.name}</div>
              <div>
                <span className={`status-pill ${statusClass(s.status)}`}>{s.status}</span>
                {s.summary && (
                  <p className="meta" style={{ marginTop: "0.35rem" }}>
                    {s.summary}
                  </p>
                )}
              </div>
            </li>
          ))}
        </ul>
      </section>

      <section className="panel">
        <h2 style={{ marginTop: 0, fontSize: "1.05rem" }}>Siguiente acción</h2>
        {detail.next_actions.length === 0 ? (
          <p className="muted">Sin acciones sugeridas.</p>
        ) : (
          <div className="actions">
            {detail.next_actions.map((a) => {
              const link = detail.links.find(
                (l) =>
                  (a.code === "open_review_excel" && l.rel === "review_excel") ||
                  (a.code === "open_asientos_pendientes" && l.rel === "secretary_file"),
              );
              if (link?.web_url && a.enabled) {
                return (
                  <a
                    key={a.code}
                    className="btn primary"
                    href={link.web_url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {a.label}
                  </a>
                );
              }
              return (
                <button key={a.code} className="btn" type="button" disabled title={a.reason ?? undefined}>
                  {a.label}
                </button>
              );
            })}
          </div>
        )}
        <div className="actions" style={{ marginTop: "1rem" }}>
          {detail.links.map((l) =>
            l.web_url ? (
              <a key={l.rel} className="btn" href={l.web_url} target="_blank" rel="noreferrer">
                {l.label}
              </a>
            ) : (
              <span key={l.rel} className="btn" title={l.path ?? undefined}>
                {l.label}
              </span>
            ),
          )}
        </div>
      </section>

      {detail.errors.length > 0 && (
        <section className="panel">
          <h2 style={{ marginTop: 0, fontSize: "1.05rem" }}>Centro de errores</h2>
          {detail.errors.map((e, idx) => (
            <div className="error-box" key={`${e.error_code}-${idx}`}>
              <strong>
                {e.stage ?? "proceso"} · {e.error_code ?? e.severity}
              </strong>
              <p style={{ margin: "0.35rem 0" }}>{e.user_message}</p>
              {e.next_action && <p className="meta">{e.next_action}</p>}
            </div>
          ))}
        </section>
      )}
    </div>
  );
}
