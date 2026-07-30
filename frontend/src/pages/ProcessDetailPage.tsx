import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  fetchJob,
  fetchProcess,
  postFinalize,
  type UiBankCode,
} from "../api/client";
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
  const [confirmFinalize, setConfirmFinalize] = useState(false);
  const [finalizeBusy, setFinalizeBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const pollRef = useRef<number | null>(null);

  const stopPoll = useCallback(() => {
    if (pollRef.current !== null) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const load = useCallback(async () => {
    const p = await fetchProcess(key);
    setDetail(p);
    setError(null);
    if (p.active_job?.job_id) {
      try {
        const j = await fetchJob(p.active_job.job_id);
        setJob(j);
      } catch {
        setJob(null);
      }
    } else {
      setJob(null);
    }
    return p;
  }, [key]);

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;

    const tick = async () => {
      try {
        const p = await load();
        if (cancelled) return;
        const running = ["queued", "running"].includes(
          (p.active_job?.status || "").toLowerCase(),
        );
        if (running) {
          timer = window.setTimeout(tick, 4000);
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Error");
      }
    };

    void tick();
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
      stopPoll();
    };
  }, [load, stopPoll]);

  function reviewLink(): string | null {
    const hit = detail?.links.find((l) => l.rel === "review_excel");
    return hit?.web_url ?? null;
  }

  function reviewFileName(): string {
    const path = detail?.files.validation_file_path;
    if (!path) return "—";
    const parts = path.split("/");
    return parts[parts.length - 1] || path;
  }

  function histUrlFromJob(j: UiJobView | null): string | null {
    const s = j?.result_summary;
    if (!s) return null;
    const url = s.historical_file_url;
    return typeof url === "string" && url ? url : null;
  }

  function secUrlFromJob(j: UiJobView | null): string | null {
    const s = j?.result_summary;
    if (!s) return null;
    const url = s.secretary_file_url;
    return typeof url === "string" && url ? url : null;
  }

  async function runFinalize() {
    if (!detail) return;
    const bank = detail.bank_code as UiBankCode;
    if (bank !== "banco_bogota" && bank !== "banco_bancolombia") return;
    setFinalizeBusy(true);
    setActionError(null);
    setConfirmFinalize(false);
    try {
      const accepted = await postFinalize(bank, detail.process_key);
      setJob({
        job_id: accepted.job_id,
        type: "finalize",
        status: accepted.status,
        store: "job_manager",
        process_key: accepted.process_key,
        bank_code: accepted.bank_code,
        environment: detail.environment,
        created_at: null,
        started_at: null,
        finished_at: null,
        result_summary: null,
        error: null,
        user_message: null,
        next_action: null,
        raw_available: false,
      });
      stopPoll();
      pollRef.current = window.setInterval(async () => {
        try {
          const j = await fetchJob(accepted.job_id);
          setJob(j);
          const st = (j.status || "").toLowerCase();
          if (st === "completed" || st === "failed") {
            stopPoll();
            await load();
          }
        } catch {
          /* keep polling */
        }
      }, 2500);
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Error al finalizar");
    } finally {
      setFinalizeBusy(false);
    }
  }

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

  const finalizeAction = detail.available_actions?.finalize;
  const finalizeAllowed = Boolean(finalizeAction?.allowed);
  const finalizeReason = finalizeAction?.reason;
  const reviewUrl = reviewLink();

  return (
    <div className="grid" style={{ gap: "1rem" }}>
      <section className="panel">
        <Link className="back" to="/">
          ← Dashboard
        </Link>
        <h1
          style={{
            margin: "0 0 0.35rem",
            fontFamily: "var(--font-display)",
            fontSize: "1.4rem",
          }}
        >
          {detail.bank_name ?? detail.bank_code}
        </h1>
        <p className="meta">Fecha: {detail.process_date ?? "—"}</p>
        <p className="meta" style={{ wordBreak: "break-all" }}>
          process_key: {detail.process_key}
        </p>
        <span
          className={`status-pill ${statusClass(detail.operational_status)}`}
        >
          {detail.operational_status}
        </span>
        <p className="meta" style={{ marginTop: "0.75rem" }}>
          Estado control: {detail.control_estado_proceso ?? "—"}
        </p>
        {(detail.active_job || job) && (
          <p className="meta">
            Job: {(job || detail.active_job)?.type} ·{" "}
            {(job || detail.active_job)?.status}
            {job?.job_id ? ` · ${job.job_id}` : ""}
          </p>
        )}
        {job?.user_message && (
          <p className="meta" style={{ marginTop: "0.5rem" }}>
            {String(job.user_message)}
          </p>
        )}
        {job?.next_action && (
          <p className="meta">{String(job.next_action)}</p>
        )}
        {actionError && <div className="error-box">{actionError}</div>}
      </section>

      <section className="panel">
        <h2 style={{ marginTop: 0, fontSize: "1.05rem" }}>Progreso por etapa</h2>
        <ul className="timeline">
          {detail.steps.map((s) => (
            <li key={s.name}>
              <div className="step-name">{STEP_LABEL[s.name] ?? s.name}</div>
              <div>
                <span className={`status-pill ${statusClass(s.status)}`}>
                  {s.status}
                </span>
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
        <h2 style={{ marginTop: 0, fontSize: "1.05rem" }}>
          Finalize / revisión
        </h2>
        <div className="actions">
          {reviewUrl ? (
            <a
              className="btn primary"
              href={reviewUrl}
              target="_blank"
              rel="noreferrer"
            >
              Abrir Excel de revisión
            </a>
          ) : (
            <button type="button" className="btn" disabled>
              Abrir Excel de revisión
            </button>
          )}
          <button
            type="button"
            className="btn"
            onClick={() => void load()}
            disabled={finalizeBusy}
          >
            Actualizar estado
          </button>
          <button
            type="button"
            className="btn primary"
            disabled={!finalizeAllowed || finalizeBusy}
            title={finalizeReason ?? undefined}
            onClick={() => setConfirmFinalize(true)}
          >
            Finalizar validación
          </button>
        </div>
        {!finalizeAllowed && finalizeReason && (
          <p className="meta" style={{ marginTop: "0.75rem" }}>
            {finalizeReason}
          </p>
        )}
        {(histUrlFromJob(job) || secUrlFromJob(job)) && (
          <div className="actions" style={{ marginTop: "1rem" }}>
            {histUrlFromJob(job) && (
              <a
                className="btn"
                href={histUrlFromJob(job)!}
                target="_blank"
                rel="noreferrer"
              >
                Abrir histórico
              </a>
            )}
            {secUrlFromJob(job) && (
              <a
                className="btn"
                href={secUrlFromJob(job)!}
                target="_blank"
                rel="noreferrer"
              >
                Abrir soporte secretaría
              </a>
            )}
          </div>
        )}
      </section>

      {(detail.operator_checklist?.length ?? 0) > 0 && (
        <section className="panel">
          <h2 style={{ marginTop: 0, fontSize: "1.05rem" }}>
            Checklist del operador
          </h2>
          <ol style={{ margin: 0, paddingLeft: "1.25rem" }}>
            {detail.operator_checklist!.map((line) => (
              <li key={line} className="meta" style={{ marginBottom: "0.4rem" }}>
                {line}
              </li>
            ))}
          </ol>
        </section>
      )}

      <section className="panel">
        <h2 style={{ marginTop: 0, fontSize: "1.05rem" }}>Enlaces</h2>
        <div className="actions">
          {detail.links.map((l) =>
            l.web_url ? (
              <a
                key={l.rel}
                className="btn"
                href={l.web_url}
                target="_blank"
                rel="noreferrer"
              >
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
          <h2 style={{ marginTop: 0, fontSize: "1.05rem" }}>
            Centro de errores
          </h2>
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

      {confirmFinalize && (
        <div className="modal-backdrop" role="dialog" aria-modal="true">
          <div className="panel modal-card">
            <h2 style={{ marginTop: 0 }}>Confirmar Finalize</h2>
            <p className="meta">Banco: {detail.bank_name ?? detail.bank_code}</p>
            <p className="meta" style={{ wordBreak: "break-all" }}>
              ProcessKey: {detail.process_key}
            </p>
            <p className="meta">Excel: {reviewFileName()}</p>
            <p>
              Guarde el Excel, espere la sincronización y cierre Excel Online
              antes de continuar. No se ejecutará Notify ni etapas posteriores.
            </p>
            <div className="actions">
              <button
                type="button"
                className="btn primary"
                disabled={finalizeBusy}
                onClick={() => void runFinalize()}
              >
                Confirmar Finalize
              </button>
              <button
                type="button"
                className="btn"
                disabled={finalizeBusy}
                onClick={() => setConfirmFinalize(false)}
              >
                Cancelar
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
