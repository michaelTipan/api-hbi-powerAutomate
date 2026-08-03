import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  fetchBootstrap,
  fetchJob,
  fetchProcess,
  postAmortization,
  postFinalize,
  postGenerate,
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
import { ConfirmDialog } from "../components/ConfirmDialog";
import { JobStatusModal, type JobStatusModalView } from "../components/JobStatusModal";
import { LinkCatalogDrawer } from "../components/LinkCatalogDrawer";
import { ReviewReadPanel } from "../components/ReviewReadPanel";
import { PageSkeleton } from "../components/Skeleton";
import { ProcessPhaseStepper } from "../components/ProcessPhaseStepper";
import { Modal } from "../components/Modal";
import {
  catalogGroupTitle,
  partitionLinksForPhaseCard,
  resolveDocumentGroups,
  shouldOpenCatalogDrawer,
} from "../domain/documentCatalog";
import {
  asientosFolderDocumentLinks,
  documentSectionsForUnlockedPhases,
  operatorDocumentLabel,
  resolveOperatorPhases,
  type OperatorPhaseId,
} from "../domain/processPhases";
import { jobNextAction, jobUserMessage, operatorErrorMessage } from "../domain/jobMessages";
import {
  SYNC_RESULTS_MESSAGE,
  SYNC_TIMEOUT_MESSAGE,
  projectionReflectsTerminalJob,
  reloadUntilProjectionMatchesJob,
} from "../domain/jobProjectionSync";
import {
  actionExplanations,
  actionLabels,
  busyLabels,
  confirmTitles,
  jobSuccessCopy,
  operationalStatusLabel,
  stageLabel,
} from "../copy/labels";

const POLL_FAILURE_WARNING_THRESHOLD = 3;

function MergeReadinessSummary({ readiness }: { readiness: UiMergeReadiness | null }) {
  if (!readiness) {
    return <p className="meta">La verificación de documentos aún no está disponible.</p>;
  }
  return (
    <>
      <p className="meta">
        Grupos listos: {readiness.ready_groups} de {readiness.expected_groups}
        {readiness.missing_groups > 0 ? ` · ${readiness.missing_groups} pendientes` : ""}.
      </p>
      {readiness.user_message ? <p className="meta">{readiness.user_message}</p> : null}
    </>
  );
}

function AmortizationSummary({ readiness }: { readiness: UiAmortizationReadiness | null }) {
  if (!readiness) {
    return <p className="meta">Información de disponibilidad no cargada todavía.</p>;
  }
  return (
    <>
      {readiness.user_message ? <p className="meta">{readiness.user_message}</p> : null}
      <p className="meta">
        Esperados: {readiness.expected_items} · Listos: {readiness.ready_items}
      </p>
    </>
  );
}

export function ProcessDetailPage() {
  const { processKey = "" } = useParams();
  const key = decodeURIComponent(processKey);
  const navigate = useNavigate();
  const reviewErroresTitleId = useId();
  const reviewErroresDescId = useId();
  const [detail, setDetail] = useState<UiProcessDetail | null>(null);
  const [job, setJob] = useState<UiJobView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmFinalize, setConfirmFinalize] = useState(false);
  const [confirmNotify, setConfirmNotify] = useState(false);
  const [confirmMerge, setConfirmMerge] = useState(false);
  const [confirmAmortization, setConfirmAmortization] = useState(false);
  const [confirmRegenerate, setConfirmRegenerate] = useState(false);
  const [catalogDrawer, setCatalogDrawer] = useState<{
    title: string;
    links: UiLink[];
  } | null>(null);
  const [reviewErroresIntroOpen, setReviewErroresIntroOpen] = useState(false);
  const [finalizeBusy, setFinalizeBusy] = useState(false);
  const [notifyBusy, setNotifyBusy] = useState(false);
  const [mergeBusy, setMergeBusy] = useState(false);
  const [amortizationBusy, setAmortizationBusy] = useState(false);
  const [regenerateBusy, setRegenerateBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [bootstrap, setBootstrap] = useState<UiBootstrapResponse | null>(null);
  const [pollWarning, setPollWarning] = useState<string | null>(null);
  const [jobModal, setJobModal] = useState<JobStatusModalView | null>(null);
  const [statusCardNote, setStatusCardNote] = useState<string | null>(null);
  /** El operador cerró el modal de progreso; el job sigue y el resultado se muestra al terminar. */
  const jobModalBackgroundRef = useRef(false);
  const pollRef = useRef<number | null>(null);
  const pollFailureCountRef = useRef(0);
  const pollInFlightRef = useRef(false);
  const reviewErroresIntroShownRef = useRef(false);
  const regenerateNavigateRef = useRef(false);
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
        setJob((prev) => (isTerminalUiJob(prev) ? prev : null));
      }
    } else {
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
    if (!detail) return;
    const hasErrores = detail.operational_issues.some(
      (issue) =>
        issue.issue_id.startsWith("review-errores-") ||
        (issue.location?.sheet || "").toLowerCase() === "errores",
    );
    const tracked = job ?? detail.active_job;
    const st = (tracked?.status || "").toLowerCase();
    const inFlight = st === "queued" || st === "running";
    if (!hasErrores || reviewErroresIntroShownRef.current || inFlight) return;
    reviewErroresIntroShownRef.current = true;
    setReviewErroresIntroOpen(true);
  }, [detail, job]);

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
        if (!cancelled) {
          setError(operatorErrorMessage(e, "No pudimos cargar el proceso. Intente de nuevo.").message);
        }
      }
    };

    void tick();
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
      stopPoll();
    };
  }, [load, stopPoll]);

  function processingTitleForJob(j: { type?: string | null } | null | undefined): string {
    const t = (j?.type || "").toLowerCase();
    if (t.includes("finalize")) return busyLabels.finalize;
    if (t.includes("notify")) return busyLabels.notify;
    if (t.includes("merge")) return busyLabels.merge;
    if (t.includes("amortization") || t.includes("apply")) return busyLabels.amortization;
    if (t.includes("generate")) {
      return regenerateNavigateRef.current ? busyLabels.regenerate : busyLabels.generate;
    }
    return "Procesando…";
  }

  function showProcessingModal(
    title: string,
    message?: string,
    options?: { dismissible?: boolean },
  ) {
    const dismissible = Boolean(options?.dismissible);
    if (!dismissible) {
      jobModalBackgroundRef.current = false;
    }
    setStatusCardNote("Procesando…");
    if (dismissible && jobModalBackgroundRef.current) {
      // Modal cerrado a propósito: no reabrir mientras el job sigue.
      return;
    }
    setJobModal({
      kind: "processing",
      title,
      message:
        message ||
        (dismissible
          ? "El sistema está trabajando. Puede cerrar este aviso; el estado se actualizará en la tarjeta."
          : "El sistema está aceptando la solicitud. Espere un momento…"),
      dismissible,
      dismissLabel: dismissible ? "Seguir en segundo plano" : undefined,
    });
  }

  function showResultModal(outcome: "success" | "error", title: string, message: string) {
    jobModalBackgroundRef.current = false;
    setJobModal({ kind: outcome, title, message });
    setStatusCardNote(message);
  }

  function dismissJobModal() {
    if (jobModal?.kind === "processing" && jobModal.dismissible) {
      jobModalBackgroundRef.current = true;
      setStatusCardNote("Procesando…");
    }
    setJobModal(null);
  }

  async function refreshAll() {
    setRefreshing(true);
    try {
      await load();
    } catch (e) {
      const msg = operatorErrorMessage(e, "No pudimos actualizar el estado.").message;
      showResultModal("error", "No se pudo actualizar", msg);
    } finally {
      setRefreshing(false);
    }
  }

  async function syncProjectionAfterJob(terminalJob: UiJobView) {
    const st = (terminalJob.status || "").toLowerCase();
    if (st !== "completed") {
      await load();
      return { synced: true as const };
    }
    setPollWarning(SYNC_RESULTS_MESSAGE);
    showProcessingModal(
      "Sincronizando resultados…",
      "La acción terminó; estamos actualizando el estado del proceso.",
      { dismissible: true },
    );
    const { synced } = await reloadUntilProjectionMatchesJob(
      load,
      terminalJob,
      projectionReflectsTerminalJob,
    );
    setPollWarning(synced ? null : SYNC_TIMEOUT_MESSAGE);
    return { synced };
  }

  function startJobPoll(acceptedJobId: string, title: string) {
    stopPoll();
    pollFailureCountRef.current = 0;
    pollInFlightRef.current = false;
    setPollWarning(null);
    // Tras aceptar el POST el modal deja de bloquear toda la pantalla.
    showProcessingModal(title, undefined, { dismissible: true });

    const tick = async () => {
      if (pollInFlightRef.current) return;
      pollInFlightRef.current = true;
      try {
        const j = await fetchJob(acceptedJobId);
        pollFailureCountRef.current = 0;
        setJob(j);
        const st = (j.status || "").toLowerCase();
        if (st === "queued" || st === "running") {
          showProcessingModal(
            processingTitleForJob(j),
            st === "queued"
              ? "La solicitud fue aceptada y está en cola."
              : "El sistema está trabajando. Puede cerrar este aviso sin cancelar la operación.",
            { dismissible: true },
          );
        }
        if (st === "completed" || st === "failed") {
          stopPoll();
          if (st === "failed") {
            regenerateNavigateRef.current = false;
            const msg =
              jobUserMessage(j) ||
              "No pudimos completar la operación. Revise el estado e inténtelo de nuevo.";
            const next = jobNextAction(j);
            showResultModal("error", "No se pudo completar", next ? `${msg} ${next}` : msg);
            return;
          }
          if (regenerateNavigateRef.current) {
            regenerateNavigateRef.current = false;
            const newKey =
              (j.process_key || "").trim() ||
              String(
                (j.result_summary &&
                  typeof j.result_summary.process_key === "string" &&
                  j.result_summary.process_key) ||
                  "",
              ).trim();
            if (newKey && newKey !== key) {
              showResultModal(
                "success",
                "Archivo regenerado",
                "Se generó un archivo de revisión nuevo. Abra la hoja Errores si aún aparecen casos, o continúe con la distribución.",
              );
              navigate(`/processes/${encodeURIComponent(newKey)}`, { replace: true });
              return;
            }
            // Misma clave o aún no proyectada: recargar detalle actual.
            await load();
            showResultModal(
              "success",
              "Archivo regenerado",
              jobUserMessage(j) || "Se generó un archivo de revisión nuevo.",
            );
            return;
          }
          const sync = await syncProjectionAfterJob(j);
          if (!sync.synced) {
            showResultModal(
              "error",
              "Sincronización incompleta",
              SYNC_TIMEOUT_MESSAGE,
            );
            return;
          }
          const jobType = (j.type || "").toLowerCase();
          if (jobType.includes("amortization") || jobType.includes("apply")) {
            showResultModal(
              "success",
              jobSuccessCopy.amortization.title,
              jobUserMessage(j) || jobSuccessCopy.amortization.message,
            );
            return;
          }
          const msg = jobUserMessage(j) || jobSuccessCopy.default.message;
          showResultModal("success", jobSuccessCopy.default.title, msg);
        }
      } catch {
        pollFailureCountRef.current += 1;
        if (pollFailureCountRef.current >= POLL_FAILURE_WARNING_THRESHOLD) {
          showProcessingModal(
            title,
            "No hemos podido confirmar el estado más reciente. Seguimos intentando…",
            { dismissible: true },
          );
        }
      } finally {
        pollInFlightRef.current = false;
      }
    };
    void tick();
    pollRef.current = window.setInterval(() => {
      void tick();
    }, 2500);
  }

  async function runFinalize() {
    if (!detail) return;
    const bank = detail.bank_code as UiBankCode;
    if (bank !== "banco_bogota" && bank !== "banco_bancolombia") return;
    setFinalizeBusy(true);
    setConfirmFinalize(false);
    showProcessingModal(busyLabels.finalize);
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
      startJobPoll(accepted.job_id, busyLabels.finalize);
    } catch (e) {
      const msg = operatorErrorMessage(e, "No pudimos finalizar la revisión.").message;
      showResultModal("error", "No se pudo finalizar", msg);
    } finally {
      setFinalizeBusy(false);
    }
  }

  async function runNotify() {
    if (!detail) return;
    const bank = detail.bank_code as UiBankCode;
    if (bank !== "banco_bogota" && bank !== "banco_bancolombia") return;
    setNotifyBusy(true);
    setConfirmNotify(false);
    showProcessingModal(busyLabels.notify);
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
      startJobPoll(accepted.job_id, busyLabels.notify);
    } catch (e) {
      const msg = operatorErrorMessage(e, "No pudimos enviar la validación.").message;
      showResultModal("error", "No se pudo enviar", msg);
    } finally {
      setNotifyBusy(false);
    }
  }

  async function runMerge() {
    if (!detail) return;
    const bank = detail.bank_code as UiBankCode;
    if (bank !== "banco_bogota" && bank !== "banco_bancolombia") return;
    setMergeBusy(true);
    setConfirmMerge(false);
    showProcessingModal(busyLabels.merge);
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
      startJobPoll(accepted.job_id, busyLabels.merge);
    } catch (e) {
      const msg = operatorErrorMessage(e, "No pudimos generar el PDF consolidado.").message;
      showResultModal("error", "No se pudo generar el PDF", msg);
    } finally {
      setMergeBusy(false);
    }
  }

  async function runAmortization() {
    if (!detail) return;
    const bank = detail.bank_code as UiBankCode;
    if (bank !== "banco_bogota" && bank !== "banco_bancolombia") return;
    setAmortizationBusy(true);
    setConfirmAmortization(false);
    showProcessingModal(busyLabels.amortization);
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
      startJobPoll(accepted.job_id, busyLabels.amortization);
    } catch (e) {
      const msg = operatorErrorMessage(e, "No pudimos procesar la amortización.").message;
      showResultModal("error", "No se pudo procesar", msg);
    } finally {
      setAmortizationBusy(false);
    }
  }

  async function runRegenerate() {
    if (!detail) return;
    const bank = detail.bank_code as UiBankCode;
    if (bank !== "banco_bogota" && bank !== "banco_bancolombia") return;
    setRegenerateBusy(true);
    setConfirmRegenerate(false);
    setReviewErroresIntroOpen(false);
    regenerateNavigateRef.current = true;
    showProcessingModal(busyLabels.regenerate);
    try {
      const accepted = await postGenerate(bank, {
        forceRegenerate: true,
        processDate: detail.process_date,
      });
      setJob({
        job_id: accepted.job_id,
        type: "generate",
        status: accepted.status,
        store: "job_manager",
        process_key: null,
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
      startJobPoll(accepted.job_id, busyLabels.regenerate);
    } catch (e) {
      regenerateNavigateRef.current = false;
      const msg = operatorErrorMessage(
        e,
        "No pudimos regenerar el archivo de revisión.",
      ).message;
      showResultModal("error", "No se pudo regenerar", msg);
    } finally {
      setRegenerateBusy(false);
    }
  }

  if (error) {
    return (
      <div className="process-detail">
        <Link className="back-link" to="/">
          <span aria-hidden="true">&lt;</span> {actionLabels.back_to_dashboard}
        </Link>
        <section className="panel">
          <div className="error-box">{error}</div>
        </section>
      </div>
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
  const regenerateAction = detail.available_actions?.regenerate;
  const regenerateAllowed = Boolean(regenerateAction?.allowed);
  const regenerateReason = regenerateAction?.reason;
  const reviewErroresIssues = detail.operational_issues.filter(
    (issue) =>
      issue.issue_id.startsWith("review-errores-") ||
      (issue.location?.sheet || "").toLowerCase() === "errores",
  );
  const hasReviewErrores = reviewErroresIssues.length > 0;
  const reviewFileMissing = detail.operational_issues.some(
    (issue) => issue.issue_id === "review-file-missing",
  );
  // Foco/alerta solo por Errores o archivo faltante; regenerar opcional no desplaza la fase.
  const needsRegenerateFocus = hasReviewErrores || reviewFileMissing;
  const recipientsConfigured = Boolean(bootstrap?.notify_test_recipients_configured);
  const trackedJob = job ?? detail.active_job;
  const trackedJobStatus = (trackedJob?.status || "").toLowerCase();
  const jobInFlight = trackedJobStatus === "queued" || trackedJobStatus === "running";
  const syncPending = pollWarning === SYNC_RESULTS_MESSAGE;
  const actionBusy =
    finalizeBusy ||
    notifyBusy ||
    mergeBusy ||
    amortizationBusy ||
    regenerateBusy ||
    jobInFlight ||
    syncPending;

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
  const readiness = detail.merge_readiness ?? null;
  const amortizationReadiness = detail.amortization_readiness ?? null;
  const amortizationCompleted =
    detail.operational_status === "COMPLETADO" ||
    (detail.control_estado_proceso || "").toUpperCase() === "AMORTIZACION_APLICADA" ||
    Boolean(detail.idempotency?.apply_idempotency_key) ||
    amortizationReadiness?.status === "already_applied" ||
    (amortizationReason || "").toLowerCase().includes("ya fue aplicada");
  const processFullyCompleted = amortizationCompleted;

  // Destinatarios efectivos: CORREOS.xlsx (EMISOR/RECEPTORES), igual que PA.
  const correosReviewLink = detail.links.find((l) => l.rel === "correos" && l.web_url) ?? null;

  type PhaseCta = {
    label: string;
    onClick: () => void;
    busy: boolean;
    busyLabel: string;
    disabled: boolean;
    reason?: string | null;
  };

  function primaryCtaFor(stepName: StepName): PhaseCta | null {
    switch (stepName) {
      case "finalize":
        if (finalizeCompleted) return null;
        return {
          label: actionLabels.finalize,
          onClick: () => setConfirmFinalize(true),
          busy: finalizeBusy,
          busyLabel: busyLabels.finalize,
          disabled: !csrfReady || !finalizeAllowed || actionBusy,
          reason: csrfPreparing ? "Preparando sesión segura…" : finalizeReason,
        };
      case "notify":
        if (notifyCompleted) return null;
        return {
          label: actionLabels.notify,
          onClick: () => setConfirmNotify(true),
          busy: notifyBusy,
          busyLabel: busyLabels.notify,
          disabled: !csrfReady || !notifyAllowed || actionBusy,
          reason: csrfPreparing ? "Preparando sesión segura…" : notifyReason,
        };
      case "merge":
        if (mergeCompleted) return null;
        return {
          label: actionLabels.merge,
          onClick: () => setConfirmMerge(true),
          busy: mergeBusy,
          busyLabel: busyLabels.merge,
          disabled: !csrfReady || !mergeAllowed || actionBusy,
          reason: csrfPreparing ? "Preparando sesión segura…" : mergeReason,
        };
      case "apply":
        if (amortizationCompleted) return null;
        return {
          label: actionLabels.amortization,
          onClick: () => setConfirmAmortization(true),
          busy: amortizationBusy,
          busyLabel: busyLabels.amortization,
          disabled: !csrfReady || !amortizationAllowed || actionBusy,
          reason: csrfPreparing ? "Preparando sesión segura…" : amortizationReason,
        };
      default:
        return null;
    }
  }

  function ctaForPhase(phaseId: OperatorPhaseId): PhaseCta | null {
    if (phaseId === "review") {
      if (!needsRegenerateFocus) return null;
      return {
        label: actionLabels.regenerate,
        onClick: () => setConfirmRegenerate(true),
        busy: regenerateBusy,
        busyLabel: busyLabels.regenerate,
        disabled: !csrfReady || !regenerateAllowed || actionBusy,
        reason: csrfPreparing
          ? "Preparando sesión segura…"
          : regenerateReason ||
            (hasReviewErrores
              ? "Corrija en SharePoint y luego regenere."
              : reviewFileMissing
                ? actionExplanations.review_file_missing_warning
                : null),
      };
    }
    // Generar archivo no lleva el CTA de Finalizar: esa acción vive en su fase.
    if (phaseId === "finalize") return primaryCtaFor("finalize");
    if (phaseId === "notify") return primaryCtaFor("notify");
    if (phaseId === "merge") return primaryCtaFor("merge");
    if (phaseId === "amortization") return primaryCtaFor("apply");
    return null;
  }

  function phaseExtraInfo(phaseId: OperatorPhaseId): ReactNode {
    if (phaseId === "review" && hasReviewErrores) {
      return (
        <p className="meta" style={{ marginTop: "0.35rem" }}>
          {actionExplanations.review_errores_warning}
        </p>
      );
    }
    if (phaseId === "review" && reviewFileMissing) {
      return (
        <p className="meta" style={{ marginTop: "0.35rem" }}>
          {actionExplanations.review_file_missing_warning}
        </p>
      );
    }
    if (phaseId === "notify") {
      return (
        <>
          <p className="meta">
            Destinatarios desde CORREOS.xlsx: {recipientsConfigured ? "listos" : "no disponibles"}
          </p>
          <p className="meta">
            Emisor y receptores se leen del Excel de control operativo (igual que Power Automate).
          </p>
          {correosReviewLink?.web_url ? (
            <a
              className="text-link"
              href={correosReviewLink.web_url}
              target="_blank"
              rel="noreferrer"
            >
              Revisar destinatarios
            </a>
          ) : null}
        </>
      );
    }
    if (phaseId === "merge") {
      return <MergeReadinessSummary readiness={readiness} />;
    }
    if (phaseId === "amortization") {
      return <AmortizationSummary readiness={amortizationReadiness} />;
    }
    return null;
  }

  const { phases: resolvedPhases, currentId: resolvedCurrentId } = resolveOperatorPhases(
    detail.steps,
  );
  // Con hoja Errores abierta o Excel ausente, el operador debe corregir/regenerar.
  const currentId: OperatorPhaseId = needsRegenerateFocus ? "review" : resolvedCurrentId;
  const currentPhase =
    resolvedPhases.find((p) => p.def.id === currentId)?.def ??
    resolvedPhases.find((p) => p.def.id === resolvedCurrentId)?.def;
  // Carpetas ASIENTOS solo mientras Merge está activo (carga de docs).
  // Tras COMPLETADO / apply done, los asientos viven en el consolidado.
  const applyCompleted =
    detail.steps.find((s) => s.name === "apply")?.status === "completed";
  const showAsientosFolders =
    !applyCompleted &&
    detail.operational_status !== "COMPLETADO" &&
    (currentId === "merge" ||
      resolvedPhases.some((p) => p.def.id === "merge" && p.unlocked));
  const asientosDocs = showAsientosFolders
    ? asientosFolderDocumentLinks(readiness?.folder_links ?? [])
    : [];
  const documentSections = documentSectionsForUnlockedPhases(detail.links, resolvedPhases, {
    merge: asientosDocs,
  });
  const processDocumentGroups = resolveDocumentGroups(
    detail.document_groups,
    detail.links,
  );
  const phaseCta = currentPhase ? ctaForPhase(currentId) : null;
  const reviewExcelLink = detail.links.find((l) => l.rel === "review_excel" && l.web_url) ?? null;
  const phasesForStepper = needsRegenerateFocus
    ? resolvedPhases.map((p) => {
        if (p.def.id === "review") {
          return { ...p, visual: "current" as const, unlocked: true };
        }
        if (p.visual === "current") {
          return { ...p, visual: "upcoming" as const };
        }
        return p;
      })
    : resolvedPhases;

  const statusDescription = (() => {
    if (statusCardNote) return statusCardNote;
    if (detail.operational_message) return detail.operational_message;
    if (displayedAttempt.kind === "none") return null;
    const parts = [displayedAttempt.userMessage, displayedAttempt.nextAction].filter(Boolean);
    return parts.length > 0 ? parts.join(" ") : null;
  })();

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

  function openCatalog(title: string, links: readonly UiLink[]) {
    setCatalogDrawer({ title, links: [...links] });
  }

  function renderPhaseDocCluster(links: readonly UiLink[]) {
    const { inline, mergePdfs, asientosFolders, other } = partitionLinksForPhaseCard(links);
    const nodes: ReactNode[] = [];
    for (const l of inline) {
      nodes.push(renderDocLink(l));
    }
    for (const l of other) {
      nodes.push(renderDocLink(l));
    }
    if (mergePdfs.length === 1) {
      nodes.push(renderDocLink(mergePdfs[0]));
    } else if (shouldOpenCatalogDrawer(mergePdfs.length)) {
      nodes.push(
        <button
          key="merge-pdfs-catalog"
          type="button"
          className="btn secondary"
          onClick={() => openCatalog("PDFs consolidados", mergePdfs)}
        >
          Ver PDFs consolidados ({mergePdfs.length})
        </button>,
      );
    }
    if (asientosFolders.length === 1) {
      nodes.push(renderDocLink(asientosFolders[0]));
    } else if (shouldOpenCatalogDrawer(asientosFolders.length)) {
      nodes.push(
        <button
          key="asientos-folders-catalog"
          type="button"
          className="btn secondary"
          onClick={() => openCatalog("Carpetas ASIENTOS", asientosFolders)}
        >
          Ver carpetas ASIENTOS ({asientosFolders.length})
        </button>,
      );
    }
    return nodes;
  }

  function retryHandlerFor(action: string | null | undefined): (() => void) | undefined {
    switch (action) {
      case "regenerate":
      case "retry_generate":
        return () => setConfirmRegenerate(true);
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

  return (
    <div className="process-detail">
      <div className="process-detail-toolbar">
        <Link className="back-link" to="/">
          <span aria-hidden="true">&lt;</span> {actionLabels.back_to_dashboard}
        </Link>
        <button
          type="button"
          className="icon-refresh"
          onClick={() => void refreshAll()}
          disabled={refreshing}
          aria-label="Actualizar estado"
          title="Actualizar estado"
        >
          <span
            className={refreshing ? "icon-refresh-glyph is-spinning" : "icon-refresh-glyph"}
            aria-hidden="true"
          >
            ↻
          </span>
        </button>
      </div>

      {hasReviewErrores ? (
        <section className="panel" role="alert" aria-labelledby="review-errores-banner-title">
          <h2 id="review-errores-banner-title" className="section-title" style={{ marginTop: 0 }}>
            Casos en la hoja Errores
          </h2>
          <p className="meta">{actionExplanations.review_errores_warning}</p>
          <p className="meta">
            Hay {reviewErroresIssues.length} caso(s) con archivo, carpeta o crédito indicado en
            «Problemas operativos». No complete la distribución hasta corregirlos y regenerar.
          </p>
          <div className="actions" style={{ marginTop: "0.5rem" }}>
            {reviewExcelLink?.web_url ? (
              <a
                className="btn secondary"
                href={reviewExcelLink.web_url}
                target="_blank"
                rel="noreferrer"
              >
                Abrir archivo de revisión
              </a>
            ) : null}
            <LoadingButton
              busy={regenerateBusy}
              busyLabel={busyLabels.regenerate}
              disabled={!csrfReady || !regenerateAllowed || actionBusy}
              title={regenerateReason ?? undefined}
              onClick={() => setConfirmRegenerate(true)}
            >
              {actionLabels.regenerate}
            </LoadingButton>
          </div>
        </section>
      ) : null}

      {reviewFileMissing && !hasReviewErrores ? (
        <section className="panel" role="alert" aria-labelledby="review-missing-banner-title">
          <h2 id="review-missing-banner-title" className="section-title" style={{ marginTop: 0 }}>
            Falta el archivo de revisión
          </h2>
          <p className="meta">{actionExplanations.review_file_missing_warning}</p>
          <div className="actions" style={{ marginTop: "0.5rem" }}>
            <LoadingButton
              busy={regenerateBusy}
              busyLabel={busyLabels.regenerate}
              disabled={!csrfReady || !regenerateAllowed || actionBusy}
              title={regenerateReason ?? undefined}
              onClick={() => setConfirmRegenerate(true)}
            >
              {actionLabels.regenerate}
            </LoadingButton>
          </div>
        </section>
      ) : null}

      {currentPhase && !processFullyCompleted && (
        <section className="panel current-phase-panel" aria-labelledby="current-phase-title">
          <div className="phase-split">
            <div className="phase-split-main">
              <h2 id="current-phase-title" className="section-title">
                {currentPhase.title}
              </h2>
              <p className="meta">{currentPhase.guidance}</p>
              {phaseExtraInfo(currentId)}
              {phaseCta?.disabled && phaseCta.reason ? (
                <p className="meta" style={{ marginTop: "0.5rem" }}>
                  {phaseCta.reason}
                </p>
              ) : null}
            </div>
            <div className="phase-split-action">
              {phaseCta ? (
                <div className="phase-split-action-stack">
                  <LoadingButton
                    busy={phaseCta.busy}
                    busyLabel={phaseCta.busyLabel}
                    disabled={phaseCta.disabled}
                    title={phaseCta.reason ?? undefined}
                    onClick={phaseCta.onClick}
                  >
                    {phaseCta.label}
                  </LoadingButton>
                  {regenerateAllowed &&
                  !needsRegenerateFocus &&
                  (currentId === "review" || currentId === "finalize") ? (
                    <LoadingButton
                      variant="secondary"
                      busy={regenerateBusy}
                      busyLabel={busyLabels.regenerate}
                      disabled={!csrfReady || actionBusy}
                      title={
                        csrfPreparing
                          ? "Preparando sesión segura…"
                          : regenerateReason ?? undefined
                      }
                      onClick={() => setConfirmRegenerate(true)}
                    >
                      {actionLabels.regenerate}
                    </LoadingButton>
                  ) : null}
                </div>
              ) : (
                <p className="meta">No hay acciones pendientes en esta fase.</p>
              )}
            </div>
          </div>
        </section>
      )}

      {processFullyCompleted ? (
        <section className="panel" aria-labelledby="process-completed-title">
          <h2 id="process-completed-title" className="section-title">
            Proceso completado
          </h2>
          <p className="meta">{actionExplanations.process_completed}</p>
        </section>
      ) : null}

      <section className="panel status-summary-card">
        <div className="status-summary-header">
          <h1 className="status-summary-title">{detail.bank_name ?? detail.bank_code}</h1>
        </div>
        <p className="meta">Fecha: {detail.process_date ?? "—"}</p>
        <div className="status-summary-badge-row">
          <span className={`status-pill ${statusClass(detail.operational_status)}`}>
            {detail.operational_title || operationalStatusLabel(detail.operational_status)}
          </span>
        </div>
        {statusDescription ? <p className="status-summary-desc">{statusDescription}</p> : null}
        {csrfPreparing ? (
          <p className="muted" role="status">
            Preparando sesión segura…
          </p>
        ) : null}
      </section>

      <section className="panel">
        <ProcessPhaseStepper
          phases={phasesForStepper}
          currentTitle={
            processFullyCompleted ? "Proceso completado" : (currentPhase?.title ?? "Proceso")
          }
        />
      </section>

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

      <ReviewReadPanel
        processKey={detail.process_key}
        enabled={
          Boolean(detail.files.validation_file_path) ||
          Boolean(detail.links.some((l) => l.rel === "review_excel")) ||
          ["EN_REVISION", "CORRECCION_REQUERIDA", "ERROR_RECUPERABLE"].includes(
            detail.operational_status,
          ) ||
          currentId === "review" ||
          currentId === "finalize"
        }
      />

      <section className="panel" id="process-documents">
        <h2 className="section-title">Documentos por fase</h2>
        {documentSections.length === 0 ? (
          <p className="muted">Aún no hay documentos disponibles para las fases que ya alcanzó.</p>
        ) : (
          <div className="phase-docs-row" role="list">
            {documentSections.map(({ phase, links }) => (
              <div key={phase.id} className="phase-docs-card" role="listitem">
                <h3 className="phase-docs-title">{phase.title}</h3>
                <div className="phase-docs-links">{renderPhaseDocCluster(links)}</div>
              </div>
            ))}
          </div>
        )}
      </section>

      {processDocumentGroups.length > 0 ? (
        <section className="panel" id="process-file-catalog" aria-labelledby="process-file-catalog-title">
          <h2 id="process-file-catalog-title" className="section-title">
            Archivos del proceso
          </h2>
          <p className="meta" style={{ marginTop: 0 }}>
            Listas largas (consolidados, tablas de amortización) se abren aquí sin saturar las fases.
            El correo enviado y el Excel del lote siguen arriba o en Documentos por fase.
          </p>
          <div className="process-file-catalog-actions">
            {processDocumentGroups.map((group) => {
              const title = catalogGroupTitle(group);
              const groupLinks = group.links ?? [];
              if (groupLinks.length === 1) {
                return renderDocLink(groupLinks[0]);
              }
              return (
                <button
                  key={group.id}
                  type="button"
                  className="btn secondary"
                  onClick={() => openCatalog(title, groupLinks)}
                >
                  {title} ({group.count || groupLinks.length})
                </button>
              );
            })}
          </div>
        </section>
      ) : null}

      <LinkCatalogDrawer
        open={catalogDrawer != null}
        title={catalogDrawer?.title ?? ""}
        links={catalogDrawer?.links ?? []}
        onClose={() => setCatalogDrawer(null)}
      />

      {confirmFinalize && (
        <ConfirmDialog
          title={confirmTitles.finalize}
          confirmLabel="Confirmar finalización"
          busyLabel={busyLabels.finalize}
          busy={finalizeBusy}
          onConfirm={() => void runFinalize()}
          onCancel={() => setConfirmFinalize(false)}
        >
          <p>
            Guarde el Excel, espere la sincronización con SharePoint y cierre Excel Online antes de
            continuar.
          </p>
        </ConfirmDialog>
      )}

      {confirmNotify && (
        <ConfirmDialog
          title={confirmTitles.notify}
          confirmLabel="Confirmar envío"
          busyLabel={busyLabels.notify}
          busy={notifyBusy}
          onConfirm={() => void runNotify()}
          onCancel={() => setConfirmNotify(false)}
        >
          <p>
            Se enviará el correo de validación a los receptores definidos en CORREOS.xlsx
            (carpeta de control operativo).
          </p>
          <p className="meta">
            Destinatarios desde CORREOS.xlsx: {recipientsConfigured ? "listos" : "no disponibles"}
          </p>
        </ConfirmDialog>
      )}

      {confirmMerge && (
        <ConfirmDialog
          title={confirmTitles.merge}
          confirmLabel="Generar PDF consolidado"
          busyLabel={busyLabels.merge}
          busy={mergeBusy}
          onConfirm={() => void runMerge()}
          onCancel={() => setConfirmMerge(false)}
        >
          <p>{actionExplanations.merge}</p>
        </ConfirmDialog>
      )}

      {confirmAmortization && (
        <ConfirmDialog
          title={confirmTitles.amortization}
          confirmLabel="Procesar amortización"
          busyLabel={busyLabels.amortization}
          busy={amortizationBusy}
          onConfirm={() => void runAmortization()}
          onCancel={() => setConfirmAmortization(false)}
        >
          <p>{actionExplanations.amortization}</p>
          <p className="meta">
            Si hay datos por corregir, no se realizarán escrituras en las tablas.
          </p>
        </ConfirmDialog>
      )}

      {confirmRegenerate && (
        <ConfirmDialog
          title={confirmTitles.regenerate}
          confirmLabel="Confirmar regeneración"
          busyLabel={busyLabels.regenerate}
          busy={regenerateBusy}
          onConfirm={() => void runRegenerate()}
          onCancel={() => setConfirmRegenerate(false)}
        >
          <p>{actionExplanations.regenerate}</p>
        </ConfirmDialog>
      )}

      {reviewErroresIntroOpen && (
        <Modal
          titleId={reviewErroresTitleId}
          title="Hay casos en la hoja Errores"
          descriptionId={reviewErroresDescId}
          onClose={() => setReviewErroresIntroOpen(false)}
        >
          <div id={reviewErroresDescId}>
            <p>{actionExplanations.review_errores_warning}</p>
          </div>
          <div className="actions">
            {reviewExcelLink?.web_url ? (
              <a
                className="btn primary"
                href={reviewExcelLink.web_url}
                target="_blank"
                rel="noreferrer"
                onClick={() => setReviewErroresIntroOpen(false)}
              >
                Abrir archivo de revisión
              </a>
            ) : null}
            <button
              type="button"
              className="btn secondary"
              onClick={() => setReviewErroresIntroOpen(false)}
            >
              Entendido
            </button>
          </div>
        </Modal>
      )}

      {jobModal ? <JobStatusModal view={jobModal} onDismiss={dismissJobModal} /> : null}
    </div>
  );
}
