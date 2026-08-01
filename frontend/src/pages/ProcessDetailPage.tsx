import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import {
  fetchBootstrap,
  fetchJob,
  fetchProcess,
  postAmortization,
  postFinalize,
  postMerge,
  postNotify,
  type UiBankCode,
} from "../api/client";
import type {
  StepName,
  UiBootstrapResponse,
  UiJobView,
  UiMergeReadiness,
  UiAmortizationReadiness,
  UiProcessDetail,
} from "../types/contract";
import { statusClass } from "../components/AppShell";
import { OperationalIssuePanel } from "../components/OperationalIssuePanel";
import { isTerminalUiJob, resolveDisplayedAttempt } from "../domain/resolveDisplayedAttempt";
import { LoadingButton } from "../components/LoadingButton";
import { Disclosure } from "../components/Disclosure";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { PollingStatus } from "../components/PollingStatus";
import { PageSkeleton } from "../components/Skeleton";
import { ProgressIndicator } from "../components/ProgressIndicator";
import { AttemptHistory } from "../components/AttemptHistory";
import { TechnicalDetails } from "../components/TechnicalDetails";
import {
  actionLabels,
  busyLabels,
  confirmTitles,
  operationalStatusLabel,
  stageLabel,
  statusLabel,
} from "../copy/labels";

const POLL_FAILURE_WARNING_THRESHOLD = 3;

function fileNameFromPath(path: string | null | undefined): string {
  if (!path) return "—";
  const parts = path.split("/");
  return parts[parts.length - 1] || path;
}

function MergeReadinessDetails({ readiness }: { readiness: UiMergeReadiness | null }) {
  if (!readiness) {
    return <p className="meta">Readiness de consolidación no disponible todavía.</p>;
  }
  return (
    <>
      <p className="meta">
        Esperados: {readiness.expected_groups} · Encontrados: {readiness.ready_groups} · Faltantes:{" "}
        {readiness.missing_groups}
      </p>
      {readiness.user_message && <p className="meta">{readiness.user_message}</p>}
      {readiness.next_action && <p className="meta">{readiness.next_action}</p>}
      {readiness.missing_items.length > 0 && (
        <ul style={{ margin: "0.5rem 0 0", paddingLeft: "1.25rem" }}>
          {readiness.missing_items.slice(0, 12).map((item, idx) => {
            const credito = typeof item.credito === "string" ? item.credito : null;
            const reason =
              typeof item.reason === "string"
                ? item.reason
                : typeof item.code === "string"
                  ? item.code
                  : null;
            const idPago = typeof item.id_pago === "string" ? item.id_pago : null;
            const label = [idPago, credito, reason].filter(Boolean).join(" · ");
            return (
              <li key={`${idPago ?? "m"}-${credito ?? idx}-${idx}`} className="meta" style={{ marginBottom: "0.25rem" }}>
                {label || JSON.stringify(item)}
              </li>
            );
          })}
        </ul>
      )}
      {readiness.folder_links.length > 0 && (
        <div className="actions" style={{ marginTop: "0.5rem" }}>
          {readiness.folder_links.map((fl, idx) => {
            const href = fl.web_url || null;
            const label = fl.label || (fl.credito ? `Carpeta ASIENTOS · ${fl.credito}` : "Carpeta ASIENTOS");
            if (href) {
              return (
                <a key={`${fl.path ?? fl.rel ?? "folder"}-${idx}`} className="btn secondary" href={href} target="_blank" rel="noreferrer">
                  {label}
                </a>
              );
            }
            return (
              <span key={`${fl.path ?? fl.rel ?? "folder"}-${idx}`} className="btn secondary" title={fl.path ?? undefined}>
                {label}
              </span>
            );
          })}
        </div>
      )}
    </>
  );
}

function AmortizationDetails({ readiness }: { readiness: UiAmortizationReadiness | null }) {
  if (!readiness) {
    return <p className="meta">Información de disponibilidad no cargada todavía.</p>;
  }
  return (
    <>
      <p className="meta">{readiness.user_message}</p>
      <p className="meta">
        Esperados: {readiness.expected_items} · Listos: {readiness.ready_items}
      </p>
    </>
  );
}

export function ProcessDetailPage() {
  const { processKey = "" } = useParams();
  const key = decodeURIComponent(processKey);
  const [detail, setDetail] = useState<UiProcessDetail | null>(null);
  const [job, setJob] = useState<UiJobView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmFinalize, setConfirmFinalize] = useState(false);
  const [confirmNotify, setConfirmNotify] = useState(false);
  const [confirmMerge, setConfirmMerge] = useState(false);
  const [confirmAmortization, setConfirmAmortization] = useState(false);
  const [finalizeBusy, setFinalizeBusy] = useState(false);
  const [notifyBusy, setNotifyBusy] = useState(false);
  const [mergeBusy, setMergeBusy] = useState(false);
  const [amortizationBusy, setAmortizationBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [bootstrap, setBootstrap] = useState<UiBootstrapResponse | null>(null);
  const [pollWarning, setPollWarning] = useState<string | null>(null);
  const pollRef = useRef<number | null>(null);
  const pollFailureCountRef = useRef(0);

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
        // Sin active_job confirmado por Graph/JobManager: conservar el
        // último job terminal conocido en vez de borrar el error (U4-B).
        setJob((prev) => (isTerminalUiJob(prev) ? prev : null));
      }
    } else {
      // active_job puede desaparecer de la proyección aunque el último
      // intento haya terminado en error: no lo limpiamos sin más.
      setJob((prev) => (isTerminalUiJob(prev) ? prev : null));
    }
    return p;
  }, [key]);

  useEffect(() => {
    void fetchBootstrap()
      .then(setBootstrap)
      .catch(() => setBootstrap(null));
  }, []);

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;

    const tick = async () => {
      try {
        const p = await load();
        if (cancelled) return;
        const running = ["queued", "running"].includes((p.active_job?.status || "").toLowerCase());
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

  function retryHandlerFor(action: string | null | undefined): (() => void) | undefined {
    switch (action) {
      case "finalize":
        return () => setConfirmFinalize(true);
      case "notify":
        return () => setConfirmNotify(true);
      case "merge":
        return () => setConfirmMerge(true);
      case "amortization":
        return () => setConfirmAmortization(true);
      default:
        return undefined;
    }
  }

  function reviewLink(): string | null {
    const hit = detail?.links.find((l) => l.rel === "review_excel");
    return hit?.web_url ?? null;
  }

  function reviewFileName(): string {
    return fileNameFromPath(detail?.files.validation_file_path);
  }

  function histFileName(): string {
    return fileNameFromPath(detail?.files.historical_file_path);
  }

  function emailPdfFileName(): string {
    return fileNameFromPath(detail?.files.email_pdf_path);
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

  function emailPdfLink(): string | null {
    const hit = detail?.links.find((l) => l.rel === "email_pdf");
    return hit?.web_url ?? null;
  }

  function startJobPoll(acceptedJobId: string, processKeyAccepted: string, bank: string) {
    stopPoll();
    pollFailureCountRef.current = 0;
    setPollWarning(null);
    pollRef.current = window.setInterval(async () => {
      try {
        const j = await fetchJob(acceptedJobId);
        pollFailureCountRef.current = 0;
        setPollWarning(null);
        setJob(j);
        const st = (j.status || "").toLowerCase();
        if (st === "completed" || st === "failed") {
          stopPoll();
          await load();
        }
      } catch {
        pollFailureCountRef.current += 1;
        if (pollFailureCountRef.current >= POLL_FAILURE_WARNING_THRESHOLD) {
          setPollWarning(
            "No hemos podido confirmar el estado más reciente del trabajo. " +
              "Seguimos intentando; si el problema persiste, actualice el estado manualmente.",
          );
        }
      }
    }, 2500);
    void processKeyAccepted;
    void bank;
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
      startJobPoll(accepted.job_id, accepted.process_key, accepted.bank_code);
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Error al finalizar");
    } finally {
      setFinalizeBusy(false);
    }
  }

  async function runNotify() {
    if (!detail) return;
    const bank = detail.bank_code as UiBankCode;
    if (bank !== "banco_bogota" && bank !== "banco_bancolombia") return;
    setNotifyBusy(true);
    setActionError(null);
    setConfirmNotify(false);
    try {
      const accepted = await postNotify(bank, detail.process_key);
      setJob({
        job_id: accepted.job_id,
        type: "notify_validar_extractos",
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
      startJobPoll(accepted.job_id, accepted.process_key, accepted.bank_code);
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Error al notificar");
    } finally {
      setNotifyBusy(false);
    }
  }

  async function runMerge() {
    if (!detail) return;
    const bank = detail.bank_code as UiBankCode;
    if (bank !== "banco_bogota" && bank !== "banco_bancolombia") return;
    setMergeBusy(true);
    setActionError(null);
    setConfirmMerge(false);
    try {
      const accepted = await postMerge(bank, detail.process_key);
      setJob({
        job_id: accepted.job_id,
        type: "merge_composite_validado_pdfs",
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
      startJobPoll(accepted.job_id, accepted.process_key, accepted.bank_code);
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Error al consolidar");
    } finally {
      setMergeBusy(false);
    }
  }

  async function runAmortization() {
    if (!detail) return;
    const bank = detail.bank_code as UiBankCode;
    if (bank !== "banco_bogota" && bank !== "banco_bancolombia") return;
    setAmortizationBusy(true);
    setActionError(null);
    setConfirmAmortization(false);
    try {
      const accepted = await postAmortization(bank, detail.process_key);
      setJob({
        job_id: accepted.job_id,
        type: "amortization_process",
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
        progress: { phase: "validating" },
        raw_available: false,
      });
      startJobPoll(accepted.job_id, accepted.process_key, accepted.bank_code);
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Error al procesar amortización");
    } finally {
      setAmortizationBusy(false);
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
    return <PageSkeleton rows={4} label="Cargando proceso…" />;
  }

  const displayedAttempt = resolveDisplayedAttempt({
    activeJob: detail.active_job,
    locallyPolledJob: job,
    lastAttempt: detail.last_attempt,
    latestAttemptByStage: detail.latest_attempts_by_stage,
  });

  const finalizeAction = detail.available_actions?.finalize;
  const finalizeAllowed = Boolean(finalizeAction?.allowed);
  const finalizeReason = finalizeAction?.reason;
  const notifyAction = detail.available_actions?.notify;
  const notifyAllowed = Boolean(notifyAction?.allowed);
  const notifyReason = notifyAction?.reason;
  const mergeAction = detail.available_actions?.merge;
  const mergeAllowed = Boolean(mergeAction?.allowed);
  const mergeReason = mergeAction?.reason;
  const amortizationAction = detail.available_actions?.amortization;
  const amortizationAllowed = Boolean(amortizationAction?.allowed);
  const amortizationReason = amortizationAction?.reason;
  const recipientsConfigured = Boolean(bootstrap?.notify_test_recipients_configured);
  const reviewUrl = reviewLink();
  const emailPdfUrl = emailPdfLink();
  const actionBusy = finalizeBusy || notifyBusy || mergeBusy || amortizationBusy;

  const finalizeCompleted = detail.steps.some((s) => s.name === "finalize" && s.status === "completed");
  const notifyCompleted =
    detail.steps.some((s) => s.name === "notify" && s.status === "completed") ||
    (detail.control_estado_proceso || "").toUpperCase() === "PENDIENTE_ASIENTOS" ||
    Boolean(detail.idempotency?.notify_idempotency_key) ||
    (notifyReason || "").toLowerCase().includes("ya fue enviado");
  const mergeStep = detail.steps.find((s) => s.name === "merge");
  const mergeCompleted =
    mergeStep?.status === "completed" ||
    (detail.control_estado_proceso || "").toUpperCase() === "CONSOLIDADO" ||
    Boolean(detail.idempotency?.merge_idempotency_key) ||
    (mergeReason || "").toLowerCase().includes("ya consolidado") ||
    (mergeReason || "").toLowerCase().includes("already_merged");
  const mergePartial =
    mergeStep?.status === "partial" || (detail.control_estado_proceso || "").toUpperCase() === "MERGE_PARCIAL";
  const readiness = detail.merge_readiness ?? null;
  const nextAsientos = (detail.control_estado_proceso || "").toUpperCase() === "PENDIENTE_ASIENTOS" || notifyCompleted;

  const jobSummary = job?.result_summary;
  const jobFileAction = jobSummary && typeof jobSummary.file_action === "string" ? jobSummary.file_action : null;
  const jobPdfReused = Boolean(jobSummary?.pdf_reused);
  const isMergeJob = (job?.type || detail.active_job?.type || "").includes("merge");

  const amortizationReadiness = detail.amortization_readiness ?? null;
  const amortizationCompleted =
    (detail.control_estado_proceso || "").toUpperCase() === "AMORTIZACION_APLICADA" ||
    Boolean(detail.idempotency?.apply_idempotency_key) ||
    amortizationReadiness?.status === "already_applied" ||
    (amortizationReason || "").toLowerCase().includes("ya fue aplicada");
  const amortizationPartial = (detail.control_estado_proceso || "").toUpperCase() === "AMORTIZACION_PARCIAL";
  const isAmortizationJob = (job?.type || detail.active_job?.type || "").includes("amortization");
  const jobProgress = (job?.progress || detail.active_job?.progress) as
    | { phase?: string; current?: number; total?: number }
    | null
    | undefined;
  const amortizationRunning =
    isAmortizationJob && ["queued", "running"].includes((job?.status || "").toLowerCase());
  const amortizationOutcome = jobSummary && typeof jobSummary.outcome === "string" ? jobSummary.outcome : null;

  function stepNote(stepName: StepName): ReactNode {
    switch (stepName) {
      case "notify":
        return notifyCompleted ? <p className="meta">Correo enviado.</p> : null;
      case "merge":
        return (
          <>
            {isMergeJob && (job?.status || "").toLowerCase() === "completed" && (
              <p className="meta">
                {jobFileAction === "partial" || mergePartial
                  ? "Consolidación parcial: revise los soportes faltantes y reintente."
                  : jobPdfReused
                    ? "Consolidación completada (PDFs reutilizados; sin duplicar)."
                    : "Consolidación completada."}
              </p>
            )}
            {mergePartial && !mergeCompleted && !isMergeJob && (
              <p className="meta">Consolidación parcial: corrija los archivos indicados y reintente.</p>
            )}
          </>
        );
      case "apply":
        return (
          <>
            {amortizationCompleted && <p className="meta">Este proceso ya fue aplicado a las tablas.</p>}
            {amortizationRunning && <ProgressIndicator progress={jobProgress} />}
            {amortizationOutcome === "requires_correction" && (
              <p className="meta">
                Se encontraron datos que requieren corrección. No se realizó ninguna escritura en las tablas.
              </p>
            )}
            {(amortizationOutcome === "partial" || amortizationPartial) && (
              <p className="meta">
                La amortización se aplicó parcialmente. Puede reintentar de forma segura una vez corregidos los
                pendientes.
              </p>
            )}
            {amortizationOutcome === "applied" && <p className="meta">Amortización procesada correctamente.</p>}
            {job?.user_message && isAmortizationJob && <p className="meta">{String(job.user_message)}</p>}
            {job?.next_action && isAmortizationJob && <p className="meta">{String(job.next_action)}</p>}
          </>
        );
      default:
        return null;
    }
  }

  type StepAction = {
    kind: "link" | "button";
    label: string;
    href?: string;
    onClick?: () => void;
    busy?: boolean;
    busyLabel?: string;
    disabled?: boolean;
    reason?: string | null;
    details?: ReactNode;
  };

  function stepActionFor(stepName: StepName): StepAction | null {
    switch (stepName) {
      case "review":
        return reviewUrl ? { kind: "link", label: "Abrir Excel de revisión", href: reviewUrl } : null;
      case "finalize":
        if (finalizeCompleted) return null;
        return {
          kind: "button",
          label: actionLabels.finalize,
          onClick: () => setConfirmFinalize(true),
          busy: finalizeBusy,
          busyLabel: busyLabels.finalize,
          disabled: !finalizeAllowed || actionBusy,
          reason: finalizeReason,
          details:
            histUrlFromJob(job) || secUrlFromJob(job) ? (
              <div className="actions">
                {histUrlFromJob(job) && (
                  <a className="btn secondary" href={histUrlFromJob(job)!} target="_blank" rel="noreferrer">
                    Abrir histórico
                  </a>
                )}
                {secUrlFromJob(job) && (
                  <a className="btn secondary" href={secUrlFromJob(job)!} target="_blank" rel="noreferrer">
                    Abrir soporte secretaría
                  </a>
                )}
              </div>
            ) : null,
        };
      case "notify":
        if (notifyCompleted) return null;
        return {
          kind: "button",
          label: actionLabels.notify,
          onClick: () => setConfirmNotify(true),
          busy: notifyBusy,
          busyLabel: busyLabels.notify,
          disabled: !notifyAllowed || actionBusy,
          reason: notifyReason,
          details: (
            <>
              <p className="meta">Destinatarios de prueba configurados: {recipientsConfigured ? "Sí" : "No"}</p>
              <p className="meta">Esta acción enviará un correo real a los destinatarios de prueba configurados.</p>
              {emailPdfUrl && (
                <a className="btn secondary" href={emailPdfUrl} target="_blank" rel="noreferrer">
                  Abrir PDF del correo
                </a>
              )}
            </>
          ),
        };
      case "merge":
        if (mergeCompleted) return null;
        return {
          kind: "button",
          label: actionLabels.merge,
          onClick: () => setConfirmMerge(true),
          busy: mergeBusy,
          busyLabel: busyLabels.merge,
          disabled: !mergeAllowed || actionBusy,
          reason: mergeReason,
          details: <MergeReadinessDetails readiness={readiness} />,
        };
      case "apply":
        if (amortizationCompleted) return null;
        return {
          kind: "button",
          label: actionLabels.amortization,
          onClick: () => setConfirmAmortization(true),
          busy: amortizationBusy,
          busyLabel: busyLabels.amortization,
          disabled: !amortizationAllowed || actionBusy,
          reason: amortizationReason,
          details: <AmortizationDetails readiness={amortizationReadiness} />,
        };
      default:
        return null;
    }
  }

  const primaryNextAction = detail.next_actions?.[0] ?? null;
  const secondaryNextActions = detail.next_actions?.slice(1) ?? [];

  function nextActionHandler(code: string): (() => void) | null {
    switch (code) {
      case "finalize":
      case "retry_finalize":
        return finalizeAllowed ? () => setConfirmFinalize(true) : null;
      case "notify":
      case "retry_notify":
        return notifyAllowed ? () => setConfirmNotify(true) : null;
      case "merge":
      case "retry_merge":
        return mergeAllowed ? () => setConfirmMerge(true) : null;
      case "amortization":
      case "retry_amortization":
        return amortizationAllowed ? () => setConfirmAmortization(true) : null;
      case "open_review_excel":
        return reviewUrl ? () => window.open(reviewUrl, "_blank", "noreferrer") : null;
      default:
        return null;
    }
  }

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
        <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem", alignItems: "center" }}>
          <span className={`status-pill ${statusClass(detail.operational_status)}`}>
            {detail.operational_title || operationalStatusLabel(detail.operational_status)}
          </span>
          <span className="env-badge">{detail.environment}</span>
        </div>
        {detail.operational_message && (
          <p className="meta" style={{ marginTop: "0.75rem" }}>
            {detail.operational_message}
          </p>
        )}
        {detail.operational_status === "DESCONOCIDO" && detail.technical_status_reference && (
          <p className="meta">Referencia técnica: {detail.technical_status_reference}</p>
        )}
        {displayedAttempt.kind !== "none" && (
          <p className="meta" style={{ marginTop: "0.75rem" }}>
            Último intento: {stageLabel(displayedAttempt.stage ?? displayedAttempt.jobType)} ·{" "}
            {statusLabel(displayedAttempt.status)}
          </p>
        )}
        {displayedAttempt.userMessage && (
          <p className="meta" style={{ marginTop: "0.5rem" }}>
            {displayedAttempt.userMessage}
          </p>
        )}
        {displayedAttempt.nextAction && <p className="meta">{displayedAttempt.nextAction}</p>}
        <PollingStatus message={pollWarning} />
        {actionError && <div className="error-box">{actionError}</div>}
        <div className="actions">
          <button type="button" className="btn secondary" onClick={() => void load()} disabled={actionBusy}>
            Actualizar estado
          </button>
        </div>
      </section>

      {primaryNextAction && (
        <section className="panel next-action-panel">
          <h2 className="section-title">Siguiente paso recomendado</h2>
          <p className="cta">{primaryNextAction.label}</p>
          {primaryNextAction.reason && <p className="meta">{primaryNextAction.reason}</p>}
          {primaryNextAction.enabled && nextActionHandler(primaryNextAction.code) && (
            <div className="actions">
              <button type="button" className="btn primary" onClick={nextActionHandler(primaryNextAction.code)!}>
                {primaryNextAction.label}
              </button>
            </div>
          )}
          {secondaryNextActions.length > 0 && (
            <Disclosure summary="Ver otras sugerencias">
              <ul style={{ margin: 0, paddingLeft: "1.25rem" }}>
                {secondaryNextActions.map((na) => (
                  <li key={na.code} className="meta" style={{ marginBottom: "0.35rem" }}>
                    {na.label}
                    {na.reason ? ` — ${na.reason}` : ""}
                  </li>
                ))}
              </ul>
            </Disclosure>
          )}
        </section>
      )}

      {detail.operational_issues.length > 0 && (
        <section className="panel">
          <h2 className="section-title">Problemas operativos</h2>
          {detail.operational_issues.map((issue) => (
            <OperationalIssuePanel
              key={issue.issue_id}
              issue={issue}
              onRetry={retryHandlerFor(issue.retry?.action)}
              retryBusy={actionBusy}
            />
          ))}
        </section>
      )}

      <section className="panel">
        <h2 className="section-title">Progreso de la revisión</h2>
        <ul className="timeline">
          {detail.steps.map((s) => {
            const action = stepActionFor(s.name);
            return (
              <li key={s.name}>
                <div className="step-name">{stageLabel(s.name)}</div>
                <div>
                  <span className={`status-pill ${statusClass(s.status)}`}>{statusLabel(s.status)}</span>
                  {s.summary && (
                    <p className="meta" style={{ marginTop: "0.35rem" }}>
                      {s.summary}
                    </p>
                  )}
                  {stepNote(s.name)}
                  {action && action.kind === "link" && (
                    <div className="step-actions actions">
                      <a className="btn secondary" href={action.href} target="_blank" rel="noreferrer">
                        {action.label}
                      </a>
                    </div>
                  )}
                  {action && action.kind === "button" && (
                    <>
                      <div className="step-actions actions">
                        <LoadingButton
                          busy={Boolean(action.busy)}
                          busyLabel={action.busyLabel}
                          disabled={Boolean(action.disabled)}
                          title={action.reason ?? undefined}
                          onClick={action.onClick}
                        >
                          {action.label}
                        </LoadingButton>
                      </div>
                      {action.disabled && action.reason && (
                        <p className="meta" style={{ marginTop: "0.35rem" }}>
                          {action.reason}
                        </p>
                      )}
                      {action.details && <Disclosure summary="Ver detalles">{action.details}</Disclosure>}
                    </>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
        {nextAsientos && !mergeCompleted && !mergePartial && (
          <p className="meta" style={{ marginTop: "0.75rem" }}>
            Siguiente etapa pendiente: consolidar soportes. Las etapas de amortización posteriores no están
            disponibles todavía.
          </p>
        )}
      </section>

      {detail.links.length > 0 && (
        <section className="panel">
          <h2 className="section-title">Documentos del proceso</h2>
          <div className="actions">
            {detail.links.map((l) =>
              l.web_url ? (
                <a key={l.rel} className="btn secondary" href={l.web_url} target="_blank" rel="noreferrer">
                  {l.label}
                </a>
              ) : (
                <span key={l.rel} className="btn secondary" title={l.path ?? undefined}>
                  {l.label}
                </span>
              ),
            )}
          </div>
        </section>
      )}

      {(detail.operator_checklist?.length ?? 0) > 0 && (
        <section className="panel">
          <Disclosure summary="Ayuda para completar la revisión">
            <ol style={{ margin: 0, paddingLeft: "1.25rem" }}>
              {detail.operator_checklist!.map((line) => (
                <li key={line} className="meta" style={{ marginBottom: "0.4rem" }}>
                  {line}
                </li>
              ))}
            </ol>
          </Disclosure>
        </section>
      )}

      <AttemptHistory attempts={detail.latest_attempts_by_stage} />

      <TechnicalDetails detail={detail} job={job} />

      {detail.errors.length > 0 && (
        <section className="panel">
          <h2 className="section-title">Centro de errores</h2>
          {detail.errors.map((e, idx) => (
            <div className="error-box" key={`${e.error_code}-${idx}`}>
              <strong>
                {stageLabel(e.stage)} · {e.error_code ?? e.severity}
              </strong>
              <p style={{ margin: "0.35rem 0" }}>{e.user_message}</p>
              {e.next_action && <p className="meta">{e.next_action}</p>}
            </div>
          ))}
        </section>
      )}

      {confirmFinalize && (
        <ConfirmDialog
          title={confirmTitles.finalize}
          confirmLabel="Confirmar finalización"
          busyLabel={busyLabels.finalize}
          busy={actionBusy}
          onConfirm={() => void runFinalize()}
          onCancel={() => setConfirmFinalize(false)}
        >
          <p className="meta">Banco: {detail.bank_name ?? detail.bank_code}</p>
          <p className="meta">Excel: {reviewFileName()}</p>
          <p>
            Guarde el Excel, espere la sincronización y cierre Excel Online antes de continuar. No se ejecutará el
            envío de validación ni etapas posteriores.
          </p>
        </ConfirmDialog>
      )}

      {confirmNotify && (
        <ConfirmDialog
          title={confirmTitles.notify}
          confirmLabel="Confirmar envío"
          busyLabel={busyLabels.notify}
          busy={actionBusy}
          onConfirm={() => void runNotify()}
          onCancel={() => setConfirmNotify(false)}
        >
          <p className="meta">Esta acción enviará un correo real a los destinatarios de prueba configurados.</p>
          <p className="meta">Banco: {detail.bank_name ?? detail.bank_code}</p>
          <p className="meta">Histórico: {histFileName()}</p>
          <p className="meta">Destinatarios de prueba configurados: {recipientsConfigured ? "Sí" : "No"}</p>
          <p>
            No se ejecutará consolidación ni amortización en este paso. Confirme solo si los destinatarios de
            prueba ya fueron aprobados explícitamente.
          </p>
        </ConfirmDialog>
      )}

      {confirmMerge && (
        <ConfirmDialog
          title={confirmTitles.merge}
          confirmLabel="Confirmar consolidación"
          busyLabel={busyLabels.merge}
          busy={actionBusy}
          onConfirm={() => void runMerge()}
          onCancel={() => setConfirmMerge(false)}
        >
          <p className="meta">Banco: {detail.bank_name ?? detail.bank_code}</p>
          <p className="meta">Estado: {operationalStatusLabel(detail.control_estado_proceso ?? undefined)}</p>
          <p className="meta">Histórico: {histFileName()}</p>
          <p className="meta">PDF correo: {emailPdfFileName()}</p>
          {readiness && (
            <p className="meta">
              Soportes: esperados {readiness.expected_groups} · encontrados {readiness.ready_groups} · faltantes{" "}
              {readiness.missing_groups}
            </p>
          )}
          <p>Se generarán los PDFs consolidados y se actualizará el proceso.</p>
        </ConfirmDialog>
      )}

      {confirmAmortization && (
        <ConfirmDialog
          title={confirmTitles.amortization}
          confirmLabel="Confirmar procesamiento"
          busyLabel={busyLabels.amortization}
          busy={actionBusy}
          onConfirm={() => void runAmortization()}
          onCancel={() => setConfirmAmortization(false)}
        >
          <p className="meta">Banco: {detail.bank_name ?? detail.bank_code}</p>
          <p className="meta">Estado: {operationalStatusLabel(detail.control_estado_proceso ?? undefined)}</p>
          {amortizationReadiness && (
            <p className="meta">
              Esperados: {amortizationReadiness.expected_items} · Listos: {amortizationReadiness.ready_items}
            </p>
          )}
          <p>
            Se validará la información y, si está correcta, se aplicará sobre las tablas de amortización en el
            ambiente de pruebas (sandbox). No se realizarán escrituras si se detectan datos que requieran
            corrección.
          </p>
        </ConfirmDialog>
      )}
    </div>
  );
}
