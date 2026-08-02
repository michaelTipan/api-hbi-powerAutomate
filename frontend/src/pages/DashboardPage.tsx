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
import { isTransientPollError } from "../api/errors";
import { jobNextAction, jobUserMessage, operatorErrorMessage } from "../domain/jobMessages";
import {
  SYNC_RESULTS_MESSAGE,
  SYNC_TIMEOUT_MESSAGE,
  processListReflectsGenerateJob,
  reloadUntilProjectionMatchesJob,
} from "../domain/jobProjectionSync";
import type { UiJobView, UiProcessSummary } from "../types/contract";
import { statusClass } from "../components/AppShell";
import { LoadingButton } from "../components/LoadingButton";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { ProcessingBanner } from "../components/ProcessingBanner";
import { CardSkeleton } from "../components/Skeleton";
import { ProgressIndicator, type ProgressData } from "../components/ProgressIndicator";
import { actionLabels, busyLabels, confirmTitles, dashboardEmptyStateMessage, operationalStatusLabel, statusLabel } from "../copy/labels";
import { FALLBACK_OPERATOR_MESSAGE } from "../copy/labels";

/** Aviso al operador tras varios fallos de poll consecutivos (~7.5 s). */
const POLL_FAILURE_WARNING_THRESHOLD = 3;
/**
 * Dejar de sondear solo tras ~2 min de fallos seguidos.
 * Un 502 aislado no debe marcar la validación como fallida.
 */
const POLL_FAILURE_GIVE_UP_THRESHOLD = 48;
const POLL_INTERVAL_MS = 2500;

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
  { id: "soportes", label: "Esperando documentos" },
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
    return "Se validará la información del archivo bancario cargado para Banco Bogotá.";
  }
  return "Se validará la información del archivo bancario cargado para Bancolombia.";
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
  // «0 de 1» sin avance real no aporta al operador: oculta la barra vacía.
  if (typeof total === "number" && total <= 1 && (typeof done !== "number" || done <= 0)) {
    return null;
  }
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
  const [unavailableBanks, setUnavailableBanks] = useState<string[]>([]);
  const [retryingBank, setRetryingBank] = useState<UiBankCode | null>(null);
  const pollRef = useRef<number | null>(null);
  const pollFailureCountRef = useRef(0);
  const pollInFlightRef = useRef(false);
  const { csrfReady, csrfPreparing } = useCsrfReady();

  const reload = useCallback(async () => {
    const [procs, caps] = await Promise.all([fetchProcesses(), fetchBanks()]);
    setItems(procs.items);
    setUnavailableBanks(procs.unavailable_banks ?? []);
    setBanks(caps);
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        await reload();
      } catch (e) {
        if (!cancelled) setError(operatorErrorMessage(e, "No pudimos cargar el panel. Intente de nuevo.").message);
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
    pollFailureCountRef.current = 0;
    pollInFlightRef.current = false;
    const tick = async () => {
      if (pollInFlightRef.current) return;
      pollInFlightRef.current = true;
      try {
        const job = await fetchJob(jobId);
        pollFailureCountRef.current = 0;
        const msg = jobUserMessage(job);
        const next = jobNextAction(job);
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
          if (job.status === "failed") {
            try {
              await reload();
            } catch {
              /* best-effort */
            }
            return;
          }
          setJobPanel((prev) =>
            prev
              ? {
                  ...prev,
                  status: job.status,
                  message: SYNC_RESULTS_MESSAGE,
                  nextAction: null,
                  reviewUrl: reviewLinkFromJob(job) ?? prev.reviewUrl,
                  progress: progressFromJob(job),
                }
              : prev,
          );
          try {
            const { synced } = await reloadUntilProjectionMatchesJob(
              async () => {
                const [procs, caps] = await Promise.all([
                  fetchProcesses(),
                  fetchBanks(),
                ]);
                setItems(procs.items);
                setUnavailableBanks(procs.unavailable_banks ?? []);
                setBanks(caps);
                return procs.items;
              },
              job,
              processListReflectsGenerateJob,
            );
            setJobPanel((prev) =>
              prev
                ? {
                    ...prev,
                    status: job.status,
                    message: synced
                      ? jobUserMessage(job)
                      : SYNC_TIMEOUT_MESSAGE,
                    nextAction: synced ? jobNextAction(job) : "Actualice la página en unos segundos.",
                    reviewUrl: reviewLinkFromJob(job) ?? prev.reviewUrl,
                    progress: null,
                  }
                : prev,
            );
          } catch {
            setJobPanel((prev) =>
              prev
                ? {
                    ...prev,
                    message: SYNC_TIMEOUT_MESSAGE,
                    nextAction: "Actualice la página en unos segundos.",
                  }
                : prev,
            );
          }
        }
      } catch (e) {
        pollFailureCountRef.current += 1;
        const failures = pollFailureCountRef.current;
        const sessionLost =
          e !== null &&
          typeof e === "object" &&
          "status" in e &&
          (e as { status: number }).status === 401;

        if (sessionLost) {
          const human = operatorErrorMessage(
            e,
            "Su sesión expiró. Vuelva a iniciar sesión para ver el avance.",
          );
          setJobPanel((prev) =>
            prev
              ? {
                  ...prev,
                  message: human.message,
                  nextAction: human.nextAction,
                }
              : prev,
          );
          stopPoll();
          setBusyBank(null);
          return;
        }

        // Un 502/corte puntual no significa que Generate haya fallado.
        if (failures < POLL_FAILURE_GIVE_UP_THRESHOLD) {
          if (failures >= POLL_FAILURE_WARNING_THRESHOLD || isTransientPollError(e)) {
            setJobPanel((prev) =>
              prev
                ? {
                    ...prev,
                    status:
                      prev.status === "failed" || prev.status === "completed"
                        ? prev.status
                        : prev.status || "running",
                    message:
                      "La validación sigue en curso. Reintentando conexión con el servidor…",
                    nextAction:
                      "No cierre esta pantalla; si el aviso persiste, actualice la página.",
                  }
                : prev,
            );
          }
          return;
        }

        setJobPanel((prev) =>
          prev
            ? {
                ...prev,
                status:
                  prev.status === "completed" || prev.status === "failed"
                    ? prev.status
                    : "running",
                message:
                  "No pudimos confirmar el avance de la validación por un problema temporal de conexión.",
                nextAction:
                  "Actualice la página: si la validación terminó, verá el proceso listo. No vuelva a iniciar otra sin revisar el estado.",
                progress: null,
              }
            : prev,
        );
        stopPoll();
        setBusyBank(null);
      } finally {
        pollInFlightRef.current = false;
      }
    };
    void tick();
    pollRef.current = window.setInterval(() => {
      void tick();
    }, POLL_INTERVAL_MS);
  }

  async function runGenerate(bankCode: UiBankCode) {
    if (busyBank || !csrfReady) return;
    setBusyBank(bankCode);
    setError(null);
    try {
      const accepted = await postGenerate(bankCode);
      setConfirmBank(null);
      setJobPanel({
        bankCode,
        jobId: accepted.job_id,
        status: accepted.status,
        message: "Validación iniciada. Estamos preparando el archivo de revisión…",
        nextAction: null,
        reviewUrl: null,
        progress: null,
      });
      startPolling(bankCode, accepted.job_id);
    } catch (e) {
      const human = operatorErrorMessage(e, FALLBACK_OPERATOR_MESSAGE);
      setJobPanel({
        bankCode,
        jobId: "—",
        status: "failed",
        message: human.message,
        nextAction: human.nextAction,
        reviewUrl: null,
        progress: null,
      });
      setBusyBank(null);
    }
  }

  async function retryBankRead(bankCode: UiBankCode) {
    if (retryingBank) return;
    setRetryingBank(bankCode);
    setError(null);
    try {
      await reload();
    } catch (e) {
      setError(operatorErrorMessage(e, "No pudimos volver a consultar el estado.").message);
    } finally {
      setRetryingBank(null);
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
      <h1 style={{ marginTop: 0, fontFamily: "var(--font-display)", fontSize: "1.35rem" }}>
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
      {unavailableBanks.length > 0 ? (
        <div className="error-box" role="alert" style={{ marginTop: "0.75rem" }}>
          No pudimos leer el estado de {unavailableBanks.map(bankLabel).join(" y ")}. No se muestra como vacío:
          use «Volver a intentar» en la tarjeta del banco (solo lectura) antes de iniciar una validación nueva.
        </div>
      ) : null}

      <div className="grid grid-cards" style={{ marginTop: "1rem" }}>
        {bankCards.map((b) => {
          const code = b.bank_code;
          const busy = busyBank === code;
          const primary = b.dashboard_primary_action ?? (b.available_actions.generate.allowed ? "generate" : "generate");
          const reason = b.available_actions.generate.reason;
          const resumeKey = b.active_process_key;
          const statusHint = b.active_operational_status
            ? operationalStatusLabel(b.active_operational_status)
            : null;

          return (
            <div key={code} className="process-card bank-action-card">
              <h2 style={{ fontSize: "1.05rem", margin: "0 0 0.35rem" }}>{b.bank_name || bankLabel(code)}</h2>
              {primary === "resume" && resumeKey ? (
                <>
                  <p className="meta">
                    Hay una validación en curso
                    {statusHint ? `: ${statusHint}` : ""}. Continúe desde el último paso completado.
                  </p>
                  <Link
                    className="btn"
                    to={`/processes/${encodeURIComponent(resumeKey)}`}
                    aria-label={`${actionLabels.resume} — ${bankLabel(code)}`}
                  >
                    {actionLabels.resume}
                  </Link>
                </>
              ) : primary === "retry_read" ? (
                <>
                  <p className="meta">
                    {reason ||
                      "No pudimos consultar el estado de este banco. La consulta es de solo lectura."}
                  </p>
                  <LoadingButton
                    busy={retryingBank === code}
                    busyLabel={busyLabels.retry_read}
                    disabled={retryingBank !== null && retryingBank !== code}
                    onClick={() => void retryBankRead(code)}
                  >
                    {actionLabels.retry_read}
                  </LoadingButton>
                </>
              ) : b.available_actions.generate.allowed ? (
                <>
                  <p className="meta">{bankExcelHint(code)}</p>
                  <LoadingButton
                    busy={busy}
                    busyLabel={busyLabels.generate}
                    disabled={!csrfReady || (busyBank !== null && !busy)}
                    onClick={() => setConfirmBank(code)}
                  >
                    {actionLabels.generate}
                  </LoadingButton>
                </>
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
        <div className="job-panel" style={{ marginTop: "1.25rem" }} role="status">
          <h2 style={{ fontSize: "0.95rem", margin: "0 0 0.4rem" }}>
            Seguimiento — {bankLabel(jobPanel.bankCode)}
          </h2>
          {["queued", "running"].includes((jobPanel.status || "").toLowerCase()) ||
          jobPanel.message === SYNC_RESULTS_MESSAGE ? (
            <ProcessingBanner
              title={
                jobPanel.message === SYNC_RESULTS_MESSAGE
                  ? "Sincronizando resultados…"
                  : busyLabels.generate
              }
              message={
                jobPanel.message === SYNC_RESULTS_MESSAGE
                  ? "La validación terminó; estamos sincronizando el estado del proceso."
                  : jobPanel.message ||
                    "El sistema está trabajando. No cierre esta pantalla hasta ver el resultado."
              }
            />
          ) : null}
          <p className="meta">
            Estado:{" "}
            <span className={`status-pill ${statusClass(jobPanel.status)}`}>
              {statusLabel(jobPanel.status)}
            </span>
          </p>
          {jobPanel.message &&
          jobPanel.message !== SYNC_RESULTS_MESSAGE &&
          !["queued", "running"].includes((jobPanel.status || "").toLowerCase()) ? (
            <p className="meta">{jobPanel.message}</p>
          ) : null}
          <ProgressIndicator progress={jobPanel.progress} />
          {jobPanel.nextAction ? (
            <p className="meta">Qué puede hacer: {jobPanel.nextAction}</p>
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
            Se iniciará la validación para <strong>{bankLabel(confirmBank)}</strong>.
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
                  aria-label={`${actionLabels.resume} — ${bankLabel(p.bank_code)}${
                    p.process_date ? ` (${p.process_date})` : ""
                  }`}
                >
                  <h2 style={{ fontSize: "1.05rem", margin: "0 0 0.35rem" }}>{bankLabel(p.bank_code)}</h2>
                  <p className="meta">Fecha: {p.process_date ?? "—"}</p>
                  <span className={`status-pill ${statusClass(p.operational_status)}`}>
                    {p.operational_title || operationalStatusLabel(p.operational_status)}
                  </span>
                  {p.operational_message ? (
                    <p className="meta" style={{ marginTop: "0.5rem" }}>
                      {p.operational_message}
                    </p>
                  ) : null}
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
