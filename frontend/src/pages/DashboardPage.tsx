import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  fetchBanks,
  fetchJob,
  fetchProcesses,
  postGenerate,
  type UiBankCapabilities,
  type UiBankCode,
} from "../api/client";
import { useCsrfReady } from "../api/useCsrfReady";
import type { UiJobView, UiProcessSummary } from "../types/contract";
import { statusClass } from "../components/AppShell";
import { LoadingButton } from "../components/LoadingButton";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { CardSkeleton } from "../components/Skeleton";
import { ProgressIndicator, type ProgressData } from "../components/ProgressIndicator";
import { actionLabels, busyLabels, confirmTitles, dashboardEmptyStateMessage, operationalStatusLabel, statusLabel } from "../copy/labels";

export type DashboardBucket =
  | "atencion"
  | "soportes"
  | "parciales"
  | "finalizados"
  | "activos";

export type DashboardTab = "todos" | DashboardBucket;

const TAB_ORDER: Array<{ id: DashboardTab; label: string }> = [
  { id: "todos", label: "Todos" },
  { id: "atencion", label: "Requieren atención" },
  { id: "activos", label: "En curso" },
  { id: "soportes", label: "Esperando soportes" },
  { id: "parciales", label: "Parciales" },
  { id: "finalizados", label: "Completados" },
];

/**
 * Clasifica un proceso para las columnas del dashboard.
 *
 * `error_count > 0` se evalúa primero: un proceso puede quedar en
 * `EN_REVISION` (p. ej. Finalize fallido conserva el Excel de revisión) y
 * aun así traer avisos pendientes. Sin esta prioridad, ese caso caería en
 * "Activos" en vez de "Requieren atención".
 */
export function classifyProcessBucket(item: UiProcessSummary): DashboardBucket {
  // Se ensancha a `string`: algunos valores legado (p. ej. ESPERANDO_IBR) ya
  // no están en el enum tipado de OperationalStatus, igual que en el
  // `bucket()` original (que recibía `string`, no el literal estricto).
  const status: string = item.operational_status;
  if (
    item.error_count > 0 ||
    status.includes("ERROR") ||
    status === "CORRECCION_REQUERIDA"
  ) {
    return "atencion";
  }
  if (status === "ESPERANDO_SOPORTES") return "soportes";
  if (status === "ESPERANDO_IBR" || status === "FINALIZADO_PARCIALMENTE") return "parciales";
  if (status === "COMPLETADO") return "finalizados";
  return "activos";
}

function bankLabel(code: string): string {
  if (code === "banco_bogota") return "Banco Bogotá";
  if (code === "banco_bancolombia") return "Bancolombia";
  return code;
}

function bankExcelHint(code: UiBankCode): string {
  if (code === "banco_bogota") {
    return "Se validará la información del archivo bancario cargado para Banco Bogotá (sandbox).";
  }
  return "Se validará la información del archivo bancario cargado para Bancolombia (sandbox).";
}

type JobPanel = {
  bankCode: UiBankCode;
  jobId: string;
  status: string;
  message: string | null;
  nextAction: string | null;
  reviewUrl: string | null;
  progress: ProgressData | null;
};

/** Extrae progreso de `job.progress` sin inventar campos: solo lee lo que Generate ya emite. */
function progressFromJob(job: UiJobView): ProgressData | null {
  const raw = job.progress;
  if (!raw || typeof raw !== "object") return null;
  const done = (raw as Record<string, unknown>).bank_rows_done;
  const total = (raw as Record<string, unknown>).bank_rows_total;
  if (typeof done !== "number" && typeof total !== "number") return null;
  return {
    current: typeof done === "number" ? done : null,
    total: typeof total === "number" ? total : null,
  };
}

export function DashboardPage() {
  const [items, setItems] = useState<UiProcessSummary[]>([]);
  const [banks, setBanks] = useState<UiBankCapabilities[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [confirmBank, setConfirmBank] = useState<UiBankCode | null>(null);
  const [busyBank, setBusyBank] = useState<UiBankCode | null>(null);
  const [jobPanel, setJobPanel] = useState<JobPanel | null>(null);
  const [activeTab, setActiveTab] = useState<DashboardTab>("todos");
  const pollRef = useRef<number | null>(null);
  const { csrfReady, csrfPreparing } = useCsrfReady();

  const reload = useCallback(async () => {
    const [procs, caps] = await Promise.all([fetchProcesses(), fetchBanks()]);
    setItems(procs.items);
    setBanks(caps);
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        await reload();
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Error al cargar");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [reload]);

  useEffect(() => {
    return () => {
      if (pollRef.current !== null) window.clearInterval(pollRef.current);
    };
  }, []);

  function stopPoll() {
    if (pollRef.current !== null) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }

  function reviewLinkFromJob(job: UiJobView): string | null {
    const summary = job.result_summary;
    if (!summary || typeof summary !== "object") return null;
    const url =
      (summary as { validation_file_url?: string }).validation_file_url ||
      (summary as { review_web_url?: string }).review_web_url;
    return typeof url === "string" && url ? url : null;
  }

  function startPolling(bankCode: UiBankCode, jobId: string) {
    stopPoll();
    const tick = async () => {
      try {
        const job = await fetchJob(jobId);
        const msg =
          (job as UiJobView & { user_message?: string }).user_message ||
          (typeof job.error?.message === "string" ? job.error.message : null);
        const next =
          (job as UiJobView & { next_action?: string }).next_action || null;
        setJobPanel({
          bankCode,
          jobId,
          status: job.status,
          message: msg,
          nextAction: next,
          reviewUrl: reviewLinkFromJob(job),
          progress: progressFromJob(job),
        });
        if (job.status === "completed" || job.status === "failed") {
          stopPoll();
          setBusyBank(null);
          try {
            await reload();
          } catch {
            /* best-effort */
          }
        }
      } catch (e) {
        setJobPanel((prev) =>
          prev
            ? {
                ...prev,
                status: "failed",
                message: e instanceof Error ? e.message : "Error al consultar el estado del trabajo",
              }
            : prev,
        );
        stopPoll();
        setBusyBank(null);
      }
    };
    void tick();
    pollRef.current = window.setInterval(() => {
      void tick();
    }, 2500);
  }

  async function runGenerate(bankCode: UiBankCode) {
    if (busyBank || !csrfReady) return;
    setConfirmBank(null);
    setBusyBank(bankCode);
    setError(null);
    setJobPanel({
      bankCode,
      jobId: "…",
      status: "queued",
      message: "Preparando la validación…",
      nextAction: null,
      reviewUrl: null,
      progress: null,
    });
    try {
      const accepted = await postGenerate(bankCode);
      setJobPanel({
        bankCode,
        jobId: accepted.job_id,
        status: accepted.status,
        message: "Trabajo aceptado. Consultando progreso…",
        nextAction: null,
        reviewUrl: null,
        progress: null,
      });
      startPolling(bankCode, accepted.job_id);
    } catch (e) {
      const err = e as Error & { nextAction?: string };
      setJobPanel({
        bankCode,
        jobId: "—",
        status: "failed",
        message: err.message,
        nextAction: err.nextAction ?? null,
        reviewUrl: null,
        progress: null,
      });
      setBusyBank(null);
    }
  }

  const bucketCounts: Record<DashboardBucket, number> = {
    activos: 0,
    atencion: 0,
    soportes: 0,
    parciales: 0,
    finalizados: 0,
  };
  for (const item of items) {
    bucketCounts[classifyProcessBucket(item)] += 1;
  }

  const visibleItems = activeTab === "todos" ? items : items.filter((i) => classifyProcessBucket(i) === activeTab);

  const bankCards =
    banks.length > 0
      ? banks
      : ([
          {
            bank_code: "banco_bogota" as const,
            bank_name: "Banco Bogotá",
            available_actions: { generate: { allowed: false, reason: "Cargando…" } },
          },
          {
            bank_code: "banco_bancolombia" as const,
            bank_name: "Bancolombia",
            available_actions: { generate: { allowed: false, reason: "Cargando…" } },
          },
        ] satisfies UiBankCapabilities[]);

  return (
    <section className="panel">
      <div className="sandbox-banner" role="status">
        SANDBOX / PRUEBAS — escrituras solo con autorización explícita del backend
      </div>
      <h1 style={{ marginTop: "0.75rem", fontFamily: "var(--font-display)", fontSize: "1.35rem" }}>
        Procesos del día
      </h1>
      <p className="muted" style={{ marginTop: 0 }}>
        Inicie la validación del archivo bancario cargado para continuar con la revisión.
      </p>
      {csrfPreparing ? (
        <p className="muted" role="status" style={{ marginTop: "0.5rem" }}>
          Preparando sesión segura…
        </p>
      ) : null}

      <div className="grid grid-cards" style={{ marginTop: "1rem" }}>
        {bankCards.map((b) => {
          const allowed = b.available_actions.generate.allowed;
          const reason = b.available_actions.generate.reason;
          const code = b.bank_code;
          const busy = busyBank === code;
          return (
            <div key={code} className="process-card bank-action-card">
              <h2 style={{ fontSize: "1.05rem", margin: "0 0 0.35rem" }}>{b.bank_name || bankLabel(code)}</h2>
              <p className="meta">{bankExcelHint(code)}</p>
              {allowed ? (
                <LoadingButton
                  busy={busy}
                  busyLabel={busyLabels.generate}
                  disabled={!csrfReady || (busyBank !== null && !busy)}
                  onClick={() => setConfirmBank(code)}
                >
                  {actionLabels.generate}
                </LoadingButton>
              ) : (
                <p className="muted" style={{ fontSize: "0.85rem", margin: "0.5rem 0 0" }}>
                  Validación no disponible{reason ? `: ${reason}` : "."}
                </p>
              )}
            </div>
          );
        })}
      </div>

      {jobPanel ? (
        <div className="job-panel" style={{ marginTop: "1.25rem" }}>
          <h2 style={{ fontSize: "0.95rem", margin: "0 0 0.4rem" }}>
            Progreso de la validación — {bankLabel(jobPanel.bankCode)}
          </h2>
          <p className="meta">
            Estado:{" "}
            <span className={`status-pill ${statusClass(jobPanel.status)}`}>
              {statusLabel(jobPanel.status)}
            </span>
          </p>
          {jobPanel.message ? <p className="meta">{jobPanel.message}</p> : null}
          <ProgressIndicator progress={jobPanel.progress} />
          {jobPanel.nextAction ? (
            <p className="meta">Siguiente acción: {jobPanel.nextAction}</p>
          ) : null}
          {jobPanel.reviewUrl ? (
            <p className="meta">
              <a href={jobPanel.reviewUrl} target="_blank" rel="noreferrer">
                Abrir Excel de revisión
              </a>
            </p>
          ) : null}
        </div>
      ) : null}

      {confirmBank ? (
        <ConfirmDialog
          title={confirmTitles.generate}
          confirmLabel="Confirmar"
          busyLabel={busyLabels.generate}
          busy={busyBank === confirmBank}
          onConfirm={() => runGenerate(confirmBank)}
          onCancel={() => setConfirmBank(null)}
        >
          <p>
            Se iniciará la validación para <strong>{bankLabel(confirmBank)}</strong> en{" "}
            <strong>SANDBOX / PRUEBAS</strong>.
          </p>
          <p className="muted">{bankExcelHint(confirmBank)}</p>
        </ConfirmDialog>
      ) : null}

      {loading && (
        <div className="grid grid-cards" style={{ marginTop: "1.5rem" }}>
          <CardSkeleton />
          <CardSkeleton />
          <CardSkeleton />
        </div>
      )}
      {error && <div className="error-box">{error}</div>}
      {!loading && !error && (
        <>
          <div className="tabbar" role="tablist" aria-label="Filtrar procesos">
            {TAB_ORDER.map((tab) => (
              <button
                key={tab.id}
                type="button"
                role="tab"
                className="tab-btn"
                aria-selected={activeTab === tab.id}
                onClick={() => setActiveTab(tab.id)}
              >
                {tab.label} ({tab.id === "todos" ? items.length : bucketCounts[tab.id]})
              </button>
            ))}
          </div>

          {visibleItems.length === 0 ? (
            <p className="muted">{dashboardEmptyStateMessage}</p>
          ) : (
            <div className="grid grid-cards">
              {visibleItems.map((p) => (
                <Link
                  key={p.process_key}
                  className="process-card"
                  to={`/processes/${encodeURIComponent(p.process_key)}`}
                >
                  <h2 style={{ fontSize: "1.05rem", margin: "0 0 0.35rem" }}>{bankLabel(p.bank_code)}</h2>
                  <p className="meta">Fecha: {p.process_date ?? "—"}</p>
                  <span className={`status-pill ${statusClass(p.operational_status)}`}>
                    {operationalStatusLabel(p.operational_status)}
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
        </>
      )}
    </section>
  );
}
