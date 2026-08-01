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
import { useCsrfReady } from "../api/useCsrfReady";
import type {
  StepName,
  UiBootstrapResponse,
  UiJobView,
  UiLink,
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
import { ProcessPhaseStepper } from "../components/ProcessPhaseStepper";
import {
  documentSectionsForUnlockedPhases,
  documentsForPhase,
  operatorDocumentLabel,
  resolveOperatorPhases,
  type OperatorPhaseId,
} from "../domain/processPhases";
import {
  actionExplanations,
  actionLabels,
  busyLabels,
  confirmTitles,
  operationalStatusLabel,
  stageLabel,
} from "../copy/labels";

const POLL_FAILURE_WARNING_THRESHOLD = 3;

function fileNameFromPath(path: string | null | undefined): string {
  if (!path) return "—";
  const parts = path.split("/");
  return parts[parts.length - 1] || path;
}

function MergeReadinessDetails({ readiness }: { readiness: UiMergeReadiness | null }) {
  if (!readiness) {
    return <p className="meta">La verificación de documentos aún no está disponible.</p>;
  }
  return (
    <>
      <p className="meta">
        Grupos verificados por el sistema: {readiness.ready_groups} listos de {readiness.expected_groups}
        {readiness.missing_groups > 0
          ? ` · ${readiness.missing_groups} aún no listos según esa verificación`
          : ""}
        .
      </p>
      {readiness.user_message && <p className="meta">{readiness.user_message}</p>}
      {readiness.next_action && <p className="meta">{readiness.next_action}</p>}
      {readiness.missing_items.length > 0 && (
        <ul style={{ margin: "0.5rem 0 0", paddingLeft: "1.25rem" }}>
          {readiness.missing_items.slice(0, 12).map((item, idx) => {
            const credito = typeof item.credito === "string" ? item.credito : null;
            const client =
              typeof item.client_name === "string"
                ? item.client_name
                : typeof item.cliente === "string"
                  ? item.cliente
                  : null;
            const appType =
              typeof item.application_type === "string"
                ? item.application_type
                : typeof item.tipo_aplicacion === "string"
                  ? item.tipo_aplicacion
                  : null;
            const reason =
              typeof item.reason === "string" && !/^[a-z][a-z0-9_]+$/.test(item.reason)
                ? item.reason
                : typeof item.user_message === "string"
                  ? item.user_message
                  : null;
            const label = [client, credito, appType, reason].filter(Boolean).join(" · ");
            return (
              <li key={`${credito ?? "m"}-${idx}`} className="meta" style={{ marginBottom: "0.25rem" }}>
                {label || "Documento detectado sin detalle adicional"}
              </li>
            );
          })}
        </ul>
      )}
      {readiness.folder_links.length > 0 && (
        <div className="actions" style={{ marginTop: "0.5rem" }}>
          {readiness.folder_links.map((fl, idx) => {
            const href = fl.web_url || null;
            const label = fl.label || (fl.credito ? `Carpeta de documentos · ${fl.credito}` : "Abrir carpeta de documentos");
            if (href) {
              return (
                <a key={`${fl.path ?? fl.rel ?? "folder"}-${idx}`} className="btn secondary" href={href} target="_blank" rel="noreferrer">
                  {label}
                </a>
              );
            }
            return (
              <span key={`${fl.path ?? fl.rel ?? "folder"}-${idx}`} className="btn secondary" title={fl.path ?? undefined}>
                {label} (no disponible)
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
  const [docsRefreshing, setDocsRefreshing] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [bootstrap, setBootstrap] = useState<UiBootstrapResponse | null>(null);
  const [pollWarning, setPollWarning] = useState<string | null>(null);
  const pollRef = useRef<number | null>(null);
  const pollFailureCountRef = useRef(0);
  const { csrfReady, csrfPreparing } = useCsrfReady();

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

  async function refreshDocuments() {
    // Solo lectura: reconsulta el detalle (Graph GET de webUrl/existencia).
    setDocsRefreshing(true);
    setActionError(null);
    try {
      await load();
    } catch (e) {
      setActionError(
        e instanceof Error ? e.message : "No pudimos actualizar la lista de documentos.",
      );
    } finally {
      setDocsRefreshing(false);
    }
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
          disabled: !csrfReady || !finalizeAllowed || actionBusy,
          reason: csrfPreparing ? "Preparando sesión segura…" : finalizeReason,
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
                    Abrir asientos pendientes
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
          disabled: !csrfReady || !notifyAllowed || actionBusy,
          reason: csrfPreparing ? "Preparando sesión segura…" : notifyReason,
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
          disabled: !csrfReady || !mergeAllowed || actionBusy,
          reason: csrfPreparing ? "Preparando sesión segura…" : mergeReason,
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
          disabled: !csrfReady || !amortizationAllowed || actionBusy,
          reason: csrfPreparing ? "Preparando sesión segura…" : amortizationReason,
          details: <AmortizationDetails readiness={amortizationReadiness} />,
        };
      default:
        return null;
    }
  }

  const { phases: resolvedPhases, currentId } = resolveOperatorPhases(detail.steps);
  const currentPhase = resolvedPhases.find((p) => p.def.id === currentId)?.def;
  const currentPhaseDocs = currentPhase ? documentsForPhase(detail.links, currentPhase) : [];
  const documentSections = documentSectionsForUnlockedPhases(detail.links, resolvedPhases);

  function actionsForPhase(phaseId: OperatorPhaseId): StepAction[] {
    const out: StepAction[] = [];
    if (phaseId === "review") {
      const review = stepActionFor("review");
      if (review) out.push(review);
      const fin = stepActionFor("finalize");
      if (fin) out.push(fin);
    } else if (phaseId === "finalize") {
      const fin = stepActionFor("finalize");
      if (fin) out.push(fin);
    } else if (phaseId === "notify") {
      const n = stepActionFor("notify");
      if (n) out.push(n);
    } else if (phaseId === "merge") {
      const m = stepActionFor("merge");
      if (m) out.push(m);
    } else if (phaseId === "amortization") {
      const a = stepActionFor("apply");
      if (a) out.push(a);
    }
    return out;
  }

  const currentActions = actionsForPhase(currentId);

  function renderDocLink(l: UiLink) {
    const label = operatorDocumentLabel(l);
    if (l.web_url) {
      return (
        <a key={l.rel} className="btn secondary" href={l.web_url} target="_blank" rel="noreferrer">
          {label}
        </a>
      );
    }
    return (
      <span
        key={l.rel}
        className="btn secondary"
        title={l.path ?? undefined}
        aria-disabled="true"
        style={{ opacity: 0.65, cursor: "not-allowed" }}
      >
        {label} (no disponible)
      </span>
    );
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
        {displayedAttempt.kind !== "none" && displayedAttempt.userMessage && (
          <p className="meta" style={{ marginTop: "0.75rem" }}>
            {displayedAttempt.userMessage}
          </p>
        )}
        {displayedAttempt.nextAction && <p className="meta">{displayedAttempt.nextAction}</p>}
        {nextAsientos && !mergeCompleted && currentId === "merge" && (
          <div className="info-box" style={{ marginTop: "0.75rem" }}>
            <p style={{ margin: 0 }}>{actionExplanations.pending_asientos}</p>
          </div>
        )}
        <PollingStatus message={pollWarning} />
        {csrfPreparing ? (
          <p className="muted" role="status">
            Preparando sesión segura…
          </p>
        ) : null}
        {actionError && <div className="error-box">{actionError}</div>}
        <div className="actions">
          <button type="button" className="btn secondary" onClick={() => void load()} disabled={actionBusy}>
            Actualizar estado
          </button>
        </div>
      </section>

      <section className="panel">
        <ProcessPhaseStepper
          phases={resolvedPhases}
          currentTitle={currentPhase?.title ?? "Proceso"}
        />
      </section>

      {currentPhase && (
        <section className="panel current-phase-panel" aria-labelledby="current-phase-title">
          <h2 id="current-phase-title" className="section-title">
            {currentPhase.title}
          </h2>
          <p className="meta">{currentPhase.guidance}</p>
          {currentPhase.stepNames.map((name) => {
            const s = detail.steps.find((st) => st.name === name);
            if (!s?.summary) return null;
            return (
              <p key={name} className="meta">
                {s.summary}
              </p>
            );
          })}
          {currentPhase.stepNames.map((name) => (
            <div key={`note-${name}`}>{stepNote(name)}</div>
          ))}
          {currentActions.length > 0 && (
            <div className="actions" style={{ marginTop: "0.75rem" }}>
              {currentActions.map((action) =>
                action.kind === "link" ? (
                  <a
                    key={action.label}
                    className="btn secondary"
                    href={action.href}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {action.label}
                  </a>
                ) : (
                  <LoadingButton
                    key={action.label}
                    busy={Boolean(action.busy)}
                    busyLabel={action.busyLabel}
                    disabled={Boolean(action.disabled)}
                    title={action.reason ?? undefined}
                    onClick={action.onClick}
                  >
                    {action.label}
                  </LoadingButton>
                ),
              )}
            </div>
          )}
          {currentActions
            .filter((a) => a.kind === "button" && a.disabled && a.reason)
            .map((a) => (
              <p key={`reason-${a.label}`} className="meta" style={{ marginTop: "0.35rem" }}>
                {a.reason}
              </p>
            ))}
          {currentActions
            .filter((a) => a.details)
            .map((a) => (
              <div key={`details-${a.label}`} style={{ marginTop: "0.75rem" }}>
                {a.details}
              </div>
            ))}
          {currentId === "merge" && !currentActions.some((a) => a.details) && (
            <div style={{ marginTop: "0.75rem" }}>
              <MergeReadinessDetails readiness={readiness} />
            </div>
          )}
          {currentId === "amortization" && !currentActions.some((a) => a.details) && (
            <div style={{ marginTop: "0.75rem" }}>
              <AmortizationDetails readiness={amortizationReadiness} />
            </div>
          )}
          {currentPhaseDocs.length > 0 && (
            <div className="phase-docs" style={{ marginTop: "1rem" }}>
              <h3 className="phase-docs-title">Documentos de esta fase</h3>
              <div className="actions" style={{ flexWrap: "wrap" }}>
                {currentPhaseDocs.map(renderDocLink)}
              </div>
            </div>
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

      {detail.errors.length > 0 && (
        <section className="panel">
          <h2 className="section-title">Avisos del proceso</h2>
          {detail.errors.map((e, idx) => (
            <div className="error-box" key={`${e.error_code ?? "err"}-${idx}`}>
              <strong>{stageLabel(e.stage)}</strong>
              <p style={{ margin: "0.35rem 0" }}>{e.user_message}</p>
              {e.next_action && <p className="meta">{e.next_action}</p>}
            </div>
          ))}
        </section>
      )}

      <section className="panel" id="process-documents">
        <h2 className="section-title">Sus documentos por fase</h2>
        <p className="meta">{actionExplanations.refresh_documents}</p>
        {documentSections.length === 0 ? (
          <p className="muted">
            Aún no hay documentos disponibles para las fases que ya alcanzó. Use «Actualizar documentos» si acaba de
            generar o editar un archivo.
          </p>
        ) : (
          documentSections.map(({ phase, links }) => (
            <div key={phase.id} className="phase-docs-section">
              <h3 className="phase-docs-title">{phase.title}</h3>
              <div className="actions" style={{ flexWrap: "wrap" }}>
                {links.map(renderDocLink)}
              </div>
            </div>
          ))
        )}
        <div className="actions" style={{ marginTop: "0.75rem" }}>
          <LoadingButton
            busy={docsRefreshing}
            busyLabel="Actualizando documentos…"
            disabled={docsRefreshing || actionBusy}
            variant="secondary"
            onClick={() => void refreshDocuments()}
          >
            {actionLabels.refresh_documents}
          </LoadingButton>
        </div>
      </section>

      {(detail.operator_checklist?.length ?? 0) > 0 && currentId === "review" && (
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
          confirmLabel="Generar PDF consolidado"
          busyLabel={busyLabels.merge}
          busy={actionBusy}
          onConfirm={() => void runMerge()}
          onCancel={() => setConfirmMerge(false)}
        >
          <p>{actionExplanations.merge}</p>
          <p className="meta">Banco: {detail.bank_name ?? detail.bank_code}</p>
          <p className="meta">Histórico: {histFileName()}</p>
          <p className="meta">PDF correo: {emailPdfFileName()}</p>
          {readiness && (
            <p className="meta">
              Documentos detectados por el sistema: {readiness.ready_groups} de {readiness.expected_groups} grupos
              listos
              {readiness.missing_groups > 0
                ? ` · ${readiness.missing_groups} grupo(s) aún no listos según la verificación`
                : ""}
              .
            </p>
          )}
          <p className="meta">No se ejecutará la amortización en este paso.</p>
        </ConfirmDialog>
      )}

      {confirmAmortization && (
        <ConfirmDialog
          title={confirmTitles.amortization}
          confirmLabel="Procesar amortización"
          busyLabel={busyLabels.amortization}
          busy={actionBusy}
          onConfirm={() => void runAmortization()}
          onCancel={() => setConfirmAmortization(false)}
        >
          <p>{actionExplanations.amortization}</p>
          <p className="meta">Banco: {detail.bank_name ?? detail.bank_code}</p>
          {amortizationReadiness && (
            <p className="meta">
              Ítems verificados: {amortizationReadiness.ready_items} de {amortizationReadiness.expected_items} listos
              según la verificación del sistema.
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
