import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
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
import { bankDisplayName } from "../domain/bankDisplay";
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
import {
  actionLabels,
  busyLabels,
  confirmTitles,
  dashboardEmptyStateMessage,
  isOperationalStatusBusy,
  operationalStatusLabel,
  statusLabel,
  FALLBACK_OPERATOR_MESSAGE,
} from "../copy/labels";
import { Spinner } from "../components/Spinner";

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

/**
 * Clasifica un proceso (badges / Historial futuro).
 * Fase 1: el Panel ya no filtra por chips; el estado se muestra en cada tarjeta.
 *
 * `error_count > 0` se evalúa primero: un proceso puede quedar en
 * `EN_REVISION` (p. ej. Finalize fallido conserva el Excel de revisión) y
 * aun así traer avisos pendientes.
 */
export function classifyProcessBucket(item: UiProcessSummary): DashboardBucket {
  // Se ensancha a `string`: algunos valores legado (p. ej. ESPERANDO_IBR) ya
  // no están en el enum tipado de OperationalStatus, igual que en el
  // `bucket()` original (que recibía `string`, no el literal estricto).
  const status: string = item.operational_status;
  if (
    item.error_count > 0 ||
    status.includes("ERROR") ||
    status === "CORRECCION_REQUERIDA" ||
    status === "REQUIERE_VERIFICACION"
  ) {
    return "atencion";
  }
  if (status === "ESPERANDO_SOPORTES") return "soportes";
  if (status === "ESPERANDO_IBR" || status === "FINALIZADO_PARCIALMENTE") return "parciales";
  if (status === "COMPLETADO" || status === "CERRADO_SIN_AMORTIZAR" || status === "CANCELADO") {
    return "finalizados";
  }
  return "activos";
}

/**
 * «Procesos activos» del Panel: solo lotes reanudables o recién completados
 * (Ver detalle). Cancelado / cerrado sin amortizar no deben ocupar tarjeta
 * ni CTA «Continuar» — el operador inicia uno nuevo.
 *
 * Regenerar: mientras generate está en curso la proyección pinta GENERANDO
 * (no CANCELADO), así la tarjeta sigue visible durante el progreso.
 */
export function shouldShowProcessOnDashboardPanel(item: UiProcessSummary): boolean {
  const status: string = item.operational_status;
  if (status === "CANCELADO" || status === "CERRADO_SIN_AMORTIZAR") {
    return false;
  }
  return true;
}

/** Panel: seguir el job si hay fase en curso o el lock de mutación está tomado. */
export function shouldPollDashboardProcesses(
  items: readonly UiProcessSummary[],
  banks: readonly UiBankCapabilities[],
): boolean {
  if (items.some((p) => isOperationalStatusBusy(p.operational_status))) {
    return true;
  }
  return banks.some((b) => {
    const reason = (b.available_actions?.generate?.reason || "").toLowerCase();
    return reason.includes("en curso");
  });
}

function bankLabel(code: string): string {
  return bankDisplayName(code);
}

function bankExcelHint(code: UiBankCode): string {
  if (code === "banco_bogota") {
    return "Se validará la información del archivo bancario cargado para Bogotá.";
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

/** Clave de proceso tras Generate OK: job → result_summary → lista por banco. */
export function resolveGenerateProcessKey(
  job: UiJobView,
  items: readonly UiProcessSummary[],
  bankCode: UiBankCode,
): string | null {
  const fromJob = (job.process_key || "").trim();
  if (fromJob) return fromJob;
  const summary = job.result_summary;
  if (summary && typeof summary === "object") {
    const raw = (summary as { process_key?: unknown }).process_key;
    if (typeof raw === "string" && raw.trim()) return raw.trim();
  }
  const bank = bankCode.trim().toLowerCase();
  const hit = items.find((i) => (i.bank_code || "").toLowerCase() === bank);
  const fromList = (hit?.process_key || "").trim();
  return fromList || null;
}

/** Ruta de detalle en Revisión de archivo tras Generate exitoso. */
export function processDetailPathAfterGenerate(processKey: string): string {
  return `/processes/${encodeURIComponent(processKey)}?phase=review`;
}

/**
 * Extrae progreso de `job.progress` sin inventar campos: solo lee lo que Generate ya emite.
 * Oculta «0 de N» al inicio (sin avance real); mantiene la barra cuando `bank_rows_done` > 0.
 */
export function progressFromJob(job: UiJobView): ProgressData | null {
  const raw = job.progress;
  if (!raw || typeof raw !== "object") return null;
  const done = (raw as Record<string, unknown>).bank_rows_done;
  const total = (raw as Record<string, unknown>).bank_rows_total;
  if (typeof done !== "number" && typeof total !== "number") return null;
  // Sin filas procesadas aún: «0 de N» no aporta; oculta la barra vacía.
  if (typeof done !== "number" || done <= 0) {
    return null;
  }
  return {
    current: done,
    total: typeof total === "number" ? total : null,
  };
}

export function DashboardPage() {
  const navigate = useNavigate();
  const [items, setItems] = useState<UiProcessSummary[]>([]);
  const [banks, setBanks] = useState<UiBankCapabilities[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [confirmBank, setConfirmBank] = useState<UiBankCode | null>(null);
  const [busyBank, setBusyBank] = useState<UiBankCode | null>(null);
  const [jobPanel, setJobPanel] = useState<JobPanel | null>(null);
  const [selectedBank, setSelectedBank] = useState<UiBankCode | "">("");
  const [unavailableBanks, setUnavailableBanks] = useState<string[]>([]);
  const [retryingBank, setRetryingBank] = useState<UiBankCode | null>(null);
  const pollRef = useRef<number | null>(null);
  const pollFailureCountRef = useRef(0);
  const pollInFlightRef = useRef(false);
  const { csrfReady, csrfPreparing } = useCsrfReady();
  const panelProcessItems = items.filter(shouldShowProcessOnDashboardPanel);

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
    if (!shouldPollDashboardProcesses(items, banks)) return;
    const timer = window.setInterval(() => {
      void reload().catch(() => {
        /* el siguiente tick reintenta */
      });
    }, 2500);
    return () => window.clearInterval(timer);
  }, [items, banks, reload]);

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
            const { synced, data: syncedItems } = await reloadUntilProjectionMatchesJob(
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
            const processKey = resolveGenerateProcessKey(job, syncedItems, bankCode);
            // Happy path: con clave de proceso, ir al detalle en Revisión de archivo.
            if (processKey) {
              navigate(processDetailPathAfterGenerate(processKey));
              return;
            }
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

  const bankCards: UiBankCapabilities[] =
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

  const selectedCap = selectedBank
    ? bankCards.find((b) => b.bank_code === selectedBank) ?? null
    : null;
  const selectedPrimary =
    selectedCap?.dashboard_primary_action ??
    (selectedCap?.available_actions.generate.allowed ? "generate" : "generate");
  const selectedCanGenerate =
    Boolean(selectedCap?.available_actions.generate.allowed) && selectedPrimary === "generate";
  const selectedTemplateUrl = selectedCap?.bank_input_web_url ?? null;
  const selectedBusy = selectedBank !== "" && busyBank === selectedBank;

  return (
    <section className="panel dashboard-page">
      <header className="page-header">
        <div>
          <h1 className="page-title">Panel</h1>
          <p className="muted page-lead">
            Inicie la validación del archivo bancario cargado para continuar con la revisión.
          </p>
        </div>
      </header>
      {csrfPreparing ? (
        <p className="muted" role="status">
          Preparando sesión segura…
        </p>
      ) : null}
      {unavailableBanks.length > 0 ? (
        <div className="error-box" role="alert">
          No pudimos leer el estado de {unavailableBanks.map(bankLabel).join(" y ")}. Use «Volver a
          intentar» (solo lectura) antes de iniciar una validación nueva.
          <div className="actions" style={{ marginTop: "0.5rem" }}>
            {unavailableBanks.map((code) => (
              <LoadingButton
                key={code}
                busy={retryingBank === code}
                busyLabel={busyLabels.retry_read}
                disabled={retryingBank !== null && retryingBank !== code}
                onClick={() => void retryBankRead(code as UiBankCode)}
              >
                {actionLabels.retry_read} — {bankLabel(code)}
              </LoadingButton>
            ))}
          </div>
        </div>
      ) : null}

      <section className="panel nested-panel new-process-panel" aria-labelledby="new-process-title">
        <h2 id="new-process-title" className="section-title" style={{ marginTop: 0 }}>
          Nuevo proceso
        </h2>
        <p className="meta">
          Seleccione el banco, abra el archivo bancario si necesita completar filas y luego inicie la
          validación.
        </p>
        <div className="new-process-row">
          <label className="field-label" htmlFor="new-process-bank">
            Banco
          </label>
          <select
            id="new-process-bank"
            className="field-select"
            value={selectedBank}
            onChange={(e) => setSelectedBank(e.target.value as UiBankCode | "")}
          >
            <option value="">Seleccionar banco</option>
            {bankCards.map((b) => (
              <option key={b.bank_code} value={b.bank_code}>
                {bankDisplayName(b.bank_code, b.bank_name)}
              </option>
            ))}
          </select>
          {selectedTemplateUrl ? (
            <a
              className="btn secondary"
              href={selectedTemplateUrl}
              target="_blank"
              rel="noreferrer"
            >
              {actionLabels.open_bank_template}
            </a>
          ) : (
            <button type="button" className="btn secondary" disabled title="Seleccione un banco con archivo disponible">
              {actionLabels.open_bank_template}
            </button>
          )}
          {selectedPrimary === "resume" && selectedCap?.active_process_key ? null : selectedPrimary === "retry_read" ? (
            <LoadingButton
              busy={retryingBank === selectedBank}
              busyLabel={busyLabels.retry_read}
              disabled={!selectedBank || (retryingBank !== null && retryingBank !== selectedBank)}
              onClick={() => selectedBank && void retryBankRead(selectedBank)}
            >
              {actionLabels.retry_read}
            </LoadingButton>
          ) : (
            <LoadingButton
              busy={selectedBusy}
              busyLabel={busyLabels.generate}
              disabled={!selectedBank || !selectedCanGenerate || !csrfReady || busyBank !== null}
              title={
                selectedCap && !selectedCanGenerate
                  ? selectedCap.available_actions.generate.reason ?? undefined
                  : undefined
              }
              onClick={() => selectedBank && setConfirmBank(selectedBank)}
            >
              {actionLabels.generate}
            </LoadingButton>
          )}
        </div>
        {selectedBank && selectedPrimary === "resume" ? (
          <p className="meta" style={{ marginTop: "0.65rem" }}>
            Este banco ya tiene un proceso en curso
            {selectedCap?.active_operational_status
              ? ` (${operationalStatusLabel(selectedCap.active_operational_status)})`
              : ""}
            . Continúe desde la tarjeta de procesos activos.
          </p>
        ) : null}
        {selectedBank && selectedCanGenerate ? (
          <p className="meta" style={{ marginTop: "0.65rem" }}>
            {bankExcelHint(selectedBank)}
          </p>
        ) : null}
      </section>

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
          {jobPanel.status === "completed" || jobPanel.reviewUrl ? (
            <p className="meta">
              Continúe desde la tarjeta de procesos activos.
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

      <section className="active-processes-section" aria-labelledby="active-processes-title">
        <h2 id="active-processes-title" className="section-title">
          Procesos activos
        </h2>
        {loading && (
          <div className="grid grid-cards">
            <CardSkeleton />
            <CardSkeleton />
          </div>
        )}
        {error && <div className="error-box">{error}</div>}
        {!loading && !error && panelProcessItems.length === 0 ? (
          <p className="muted">{dashboardEmptyStateMessage}</p>
        ) : null}
        {!loading && panelProcessItems.length > 0 ? (
          <div className="grid grid-cards">
            {panelProcessItems.map((p) => {
              const bucket = classifyProcessBucket(p);
              const attention = bucket === "atencion";
              const processing = isOperationalStatusBusy(p.operational_status);
              const statusText =
                p.operational_title || operationalStatusLabel(p.operational_status);
              const detailCta =
                p.operational_status === "COMPLETADO"
                  ? actionLabels.view_detail
                  : actionLabels.continue_process;
              return (
                <article
                  key={p.process_key}
                  className={`process-card active-process-card${attention ? " needs-attention" : ""}`}
                >
                  <h3 className="active-process-title">{bankLabel(p.bank_code)}</h3>
                  <p className="meta">Fecha: {p.process_date ?? "—"}</p>
                  <div
                    className={`active-process-status${processing ? " is-processing" : ""}`}
                    {...(processing
                      ? { role: "status", "aria-live": "polite", "aria-busy": "true" }
                      : {})}
                  >
                    {processing ? <Spinner size="sm" label={statusText || "Procesando…"} /> : null}
                    <span className={`status-pill ${statusClass(p.operational_status)}`}>
                      {statusText}
                    </span>
                  </div>
                  {p.operational_message ? (
                    <p className="meta" style={{ marginTop: "0.5rem" }}>
                      {p.operational_message}
                    </p>
                  ) : null}
                  {p.error_count > 0 ? (
                    <p className="meta" style={{ marginTop: "0.35rem" }}>
                      {p.error_count} aviso(s)
                    </p>
                  ) : null}
                  <div className="actions active-process-actions">
                    <Link
                      className="btn"
                      to={`/processes/${encodeURIComponent(p.process_key)}`}
                      aria-label={`${detailCta} — ${bankLabel(p.bank_code)}`}
                    >
                      {detailCta}
                    </Link>
                  </div>
                </article>
              );
            })}
          </div>
        ) : null}
      </section>
    </section>
  );
}
