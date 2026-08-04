import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
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
import { OperationalIssuesModal } from "../components/OperationalIssuesModal";
import { isTerminalUiJob, resolveDisplayedAttempt } from "../domain/resolveDisplayedAttempt";
import { LoadingButton } from "../components/LoadingButton";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { JobStatusModal, type JobStatusModalView } from "../components/JobStatusModal";
import { LinkCatalogDrawer, type CatalogDrawerLink } from "../components/LinkCatalogDrawer";
import { PageSkeleton } from "../components/Skeleton";
import { ProcessPhaseStepper } from "../components/ProcessPhaseStepper";
import { Modal } from "../components/Modal";
import {
  catalogGroupTitle,
  catalogSummaryLabel,
  emailPdfLinksFromDetail,
  emailPdfLinksFromResultSummary,
  mergePdfLinksFromDetail,
  mergePdfLinksFromResultSummary,
  partitionLinksForPhaseCard,
  processFileCatalogGroups,
  resolveDocumentGroups,
  shouldOpenCatalogDrawer,
} from "../domain/documentCatalog";
import {
  documentSectionForSelectedPhase,
  operatorDocumentLabel,
  parseOperatorPhaseHint,
  resolveOperatorPhases,
  shouldShowPhaseDocumentsSection,
  shouldShowProcessFileCatalog,
  type OperatorPhaseId,
} from "../domain/processPhases";
import { jobNextAction, jobUserMessage, operatorErrorMessage } from "../domain/jobMessages";
import {
  AMORT_SYNC_SOFT_TIMEOUT_MESSAGE,
  AMORT_SYNC_SOFT_TIMEOUT_TITLE,
  SYNC_RESULTS_MESSAGE,
  SYNC_TIMEOUT_MESSAGE,
  amortizationJobHasBusinessTerminalOutcome,
  amortizationOutcomeFromJob,
  postJobReloadDelaysFor,
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
import { Spinner } from "../components/Spinner";
import {
  buildAsientosCatalogItems,
  buildMergeSupportOperationalIssues,
  formatMergeGroupsProgress,
  parseMergeMissingItems,
  shouldShowMergeSupportErrors,
} from "../domain/mergeReadinessCopy";
import {
  amortMissingItemMessage,
  amortWarningMessage,
  parseAmortMissingItems,
} from "../domain/amortizationReadinessCopy";

const POLL_FAILURE_WARNING_THRESHOLD = 3;

function MergeGroupsProgressBanner({
  readiness,
}: {
  readiness: Pick<
    UiMergeReadiness,
    "status" | "ready_groups" | "expected_groups" | "missing_groups"
  >;
}) {
  if (readiness.expected_groups <= 0) return null;
  const complete =
    readiness.status === "ready" || readiness.status === "already_merged";
  // incomplete / ready / already_merged; unknown sin conteo útil se omite arriba.
  if (!complete && readiness.status !== "incomplete") return null;
  return (
    <p
      className={
        complete ? "merge-groups-progress is-complete" : "merge-groups-progress"
      }
      role="status"
    >
      {formatMergeGroupsProgress(readiness)}
    </p>
  );
}

function MergeReadinessSummary({
  readiness,
  onVerifySupports,
  verifying,
  showVerifyAction,
}: {
  readiness: UiMergeReadiness | null;
  onVerifySupports?: () => void;
  verifying?: boolean;
  /** Solo en la fase Merge viva (incomplete/unknown). */
  showVerifyAction?: boolean;
}) {
  if (!readiness) {
    return <p className="meta">La verificación de documentos aún no está disponible.</p>;
  }

  const needsRecovery =
    readiness.status === "incomplete" || readiness.status === "unknown";
  const showVerify = Boolean(showVerifyAction && needsRecovery && onVerifySupports);

  return (
    <div className="merge-readiness-panel">
      {readiness.status === "ready" || readiness.status === "already_merged" ? (
        <>
          <MergeGroupsProgressBanner readiness={readiness} />
          {readiness.user_message ? <p className="meta">{readiness.user_message}</p> : null}
        </>
      ) : (
        <>
          {readiness.user_message ? <p className="meta">{readiness.user_message}</p> : null}
          <MergeGroupsProgressBanner readiness={readiness} />
          {needsRecovery ? (
            <p className="meta">{actionExplanations.merge_verify_after_fix}</p>
          ) : null}
        </>
      )}
      {showVerify ? (
        <div className="merge-verify-actions">
          <LoadingButton
            variant="secondary"
            busy={Boolean(verifying)}
            busyLabel={busyLabels.verify_merge_supports}
            disabled={Boolean(verifying)}
            onClick={onVerifySupports}
          >
            {actionLabels.verify_merge_supports}
          </LoadingButton>
        </div>
      ) : null}
    </div>
  );
}

function AmortizationSummary({
  readiness,
  ibrLink,
}: {
  readiness: UiAmortizationReadiness | null;
  ibrLink: UiLink | null;
}) {
  if (!readiness) {
    return (
      <div className="amort-readiness-panel">
        <p className="meta">Información de disponibilidad no cargada todavía.</p>
        {ibrLink?.web_url ? (
          <a
            className="btn secondary"
            href={ibrLink.web_url}
            target="_blank"
            rel="noreferrer"
          >
            Actualizar IBR
          </a>
        ) : null}
      </div>
    );
  }
  const missingItems = parseAmortMissingItems(readiness.missing_items);
  const warnings = (readiness.warnings ?? [])
    .map((w) => amortWarningMessage(w))
    .filter((w): w is string => Boolean(w));
  return (
    <div className="amort-readiness-panel">
      {readiness.user_message ? <p className="meta">{readiness.user_message}</p> : null}
      <p className="meta">
        Ítems listos: {readiness.ready_items} de {readiness.expected_items}.
      </p>
      {missingItems.length > 0 ? (
        <ul className="merge-missing-list">
          {missingItems.map((item, index) => {
            const credito = (item.credito || "").trim();
            const key = `${credito || item.id_pago || "x"}-${item.error_code || "x"}-${index}`;
            return (
              <li key={key} className="merge-missing-item">
                <p className="merge-missing-item-title">
                  {credito
                    ? `Crédito ${credito}`
                    : item.id_pago
                      ? `Pago ${item.id_pago}`
                      : "Pendiente de consolidación"}
                </p>
                <p className="meta">{amortMissingItemMessage(item)}</p>
              </li>
            );
          })}
        </ul>
      ) : null}
      {warnings.length > 0 ? (
        <ul className="merge-missing-list">
          {warnings.map((msg) => (
            <li key={msg} className="merge-missing-item">
              <p className="meta">{msg}</p>
            </li>
          ))}
        </ul>
      ) : null}
      {readiness.next_action ? <p className="meta">{readiness.next_action}</p> : null}
      {ibrLink?.web_url ? (
        <a
          className="btn secondary"
          href={ibrLink.web_url}
          target="_blank"
          rel="noreferrer"
        >
          Actualizar IBR
        </a>
      ) : null}
    </div>
  );
}

export function ProcessDetailPage() {
  const { processKey = "" } = useParams();
  const key = decodeURIComponent(processKey);
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
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
  const [catalogDrawer, setCatalogDrawer] = useState<
    | { kind: "links"; title: string; links: CatalogDrawerLink[] }
    | { kind: "asientos"; refreshing: boolean }
    | null
  >(null);
  const [reviewErroresIntroOpen, setReviewErroresIntroOpen] = useState(false);
  const [operationalIssuesOpen, setOperationalIssuesOpen] = useState(false);
  const [mergeSupportIssuesOpen, setMergeSupportIssuesOpen] = useState(false);
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
  /** Fase que el operador está consultando en el header (puede diferir de la viva). */
  const [selectedPhaseId, setSelectedPhaseId] = useState<OperatorPhaseId | null>(null);
  /** El operador cerró el modal de progreso; el job sigue y el resultado se muestra al terminar. */
  const jobModalBackgroundRef = useRef(false);
  const pollRef = useRef<number | null>(null);
  const pollFailureCountRef = useRef(0);
  const pollInFlightRef = useRef(false);
  const reviewErroresIntroShownRef = useRef(false);
  const regenerateNavigateRef = useRef(false);
  const liveCurrentIdRef = useRef<OperatorPhaseId | null>(null);
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
    setSelectedPhaseId(null);
    liveCurrentIdRef.current = null;
    reviewErroresIntroShownRef.current = false;
  }, [key]);

  useEffect(() => {
    if (!detail) return;
    const hasErrores = detail.operational_issues.some(
      (issue) =>
        issue.issue_id.startsWith("review-errores-") ||
        (issue.location?.sheet || "").toLowerCase() === "errores",
    );
    const fileMissing = detail.operational_issues.some(
      (issue) => issue.issue_id === "review-file-missing",
    );
    const needsFocus = hasErrores || fileMissing;
    const { currentId } = resolveOperatorPhases(detail.steps);
    const liveId: OperatorPhaseId = needsFocus ? "review" : currentId;
    if (liveCurrentIdRef.current !== liveId) {
      liveCurrentIdRef.current = liveId;
      setSelectedPhaseId(liveId);
    }
  }, [detail]);

  useEffect(() => {
    setSelectedPhaseId(null);
    liveCurrentIdRef.current = null;
    reviewErroresIntroShownRef.current = false;
  }, [key]);

  useEffect(() => {
    if (!detail) return;
    const hasErrores = detail.operational_issues.some(
      (issue) =>
        issue.issue_id.startsWith("review-errores-") ||
        (issue.location?.sheet || "").toLowerCase() === "errores",
    );
    const fileMissing = detail.operational_issues.some(
      (issue) => issue.issue_id === "review-file-missing",
    );
    const needsFocus = hasErrores || fileMissing;
    const { currentId } = resolveOperatorPhases(detail.steps);
    const liveId: OperatorPhaseId = needsFocus ? "review" : currentId;
    if (liveCurrentIdRef.current !== liveId) {
      liveCurrentIdRef.current = liveId;
      setSelectedPhaseId(liveId);
    }
  }, [detail]);

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

  function showResultModal(
    outcome: "success" | "warning" | "error",
    title: string,
    message: string,
    links?: readonly UiLink[],
    options?: { dismissLabel?: string },
  ) {
    jobModalBackgroundRef.current = false;
    if (outcome === "success") {
      setJobModal({
        kind: "success",
        title,
        message,
        links: links ? [...links] : undefined,
        dismissLabel: options?.dismissLabel,
      });
    } else if (outcome === "warning") {
      setJobModal({
        kind: "warning",
        title,
        message,
        dismissLabel: options?.dismissLabel || "Actualizar estado",
      });
    } else {
      setJobModal({ kind: "error", title, message, dismissLabel: options?.dismissLabel });
    }
    setStatusCardNote(message);
  }

  function dismissJobModal() {
    if (jobModal?.kind === "processing" && jobModal.dismissible) {
      jobModalBackgroundRef.current = true;
      setStatusCardNote("Procesando…");
      setJobModal(null);
      return;
    }
    const shouldRefreshAfterWarning = jobModal?.kind === "warning";
    setJobModal(null);
    if (shouldRefreshAfterWarning) {
      void refreshAll();
    }
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
      const data = await load();
      return { synced: true as const, data };
    }
    setPollWarning(SYNC_RESULTS_MESSAGE);
    showProcessingModal(
      "Sincronizando resultados…",
      "La acción terminó; estamos actualizando el estado del proceso.",
      { dismissible: true },
    );
    const { synced, data } = await reloadUntilProjectionMatchesJob(
      load,
      terminalJob,
      projectionReflectsTerminalJob,
      postJobReloadDelaysFor(terminalJob),
    );
    setPollWarning(synced ? null : SYNC_TIMEOUT_MESSAGE);
    return { synced, data };
  }

  function amortizationTableLinksFromDetail(data: UiProcessDetail | null | undefined): UiLink[] {
    if (!data) return [];
    const group = (data.document_groups ?? []).find((g) => g.id === "amortization_tables");
    return [...(group?.links ?? [])].filter((l) => Boolean(l.web_url));
  }

  function showAmortizationBusinessOutcome(j: UiJobView) {
    const outcome = amortizationOutcomeFromJob(j);
    const msg =
      jobUserMessage(j) ||
      (outcome === "requires_correction"
        ? "La amortización requiere correcciones antes de continuar."
        : outcome === "partial"
          ? "La amortización terminó de forma parcial. Revise el estado del proceso."
          : "La amortización no se completó. Revise el estado e inténtelo de nuevo.");
    const next = jobNextAction(j);
    const full = next ? `${msg} ${next}` : msg;
    if (outcome === "failed") {
      showResultModal("error", "No se pudo completar", full);
      return;
    }
    showResultModal("warning", "Revisión requerida", full);
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
            // Misma clave: sincronizar proyección (path/web_url) como el resto de jobs.
            const sync = await syncProjectionAfterJob(j);
            if (!sync.synced) {
              showResultModal(
                "error",
                "Sincronización incompleta",
                SYNC_TIMEOUT_MESSAGE,
              );
              return;
            }
            // Tras sync limpia, el foco de corrección se recalcula del detalle.
            reviewErroresIntroShownRef.current = false;
            showResultModal(
              "success",
              "Archivo regenerado",
              jobUserMessage(j) ||
                "Se generó un archivo de revisión nuevo. Si ya no hay casos en Errores, continúe con Finalizar revisión.",
            );
            return;
          }
          const jobType = (j.type || "").toLowerCase();
          const isAmortizationJob =
            jobType.includes("amortization") || jobType.includes("apply");

          // Outcome de negocio terminal: mostrar resultado real sin exigir Control.
          if (isAmortizationJob && amortizationJobHasBusinessTerminalOutcome(j)) {
            try {
              await load();
            } catch {
              /* best-effort */
            }
            showAmortizationBusinessOutcome(j);
            return;
          }

          const sync = await syncProjectionAfterJob(j);
          if (!sync.synced) {
            if (isAmortizationJob) {
              // El job ya terminó; Graph stale no es fallo duro.
              showResultModal(
                "warning",
                AMORT_SYNC_SOFT_TIMEOUT_TITLE,
                AMORT_SYNC_SOFT_TIMEOUT_MESSAGE,
                undefined,
                { dismissLabel: "Actualizar estado" },
              );
              return;
            }
            showResultModal(
              "error",
              "Sincronización incompleta",
              SYNC_TIMEOUT_MESSAGE,
            );
            return;
          }
          if (isAmortizationJob) {
            const tableLinks = amortizationTableLinksFromDetail(sync.data);
            showResultModal(
              "success",
              jobSuccessCopy.amortization.title,
              jobUserMessage(j) || jobSuccessCopy.amortization.message,
              tableLinks,
            );
            return;
          }
          if (jobType.includes("notify")) {
            const fromDetail = emailPdfLinksFromDetail(sync.data);
            const fromSummary = emailPdfLinksFromResultSummary(j.result_summary);
            const notifyLinks = fromDetail.length > 0 ? fromDetail : fromSummary;
            const withUrl = notifyLinks.filter((l) => Boolean(l.web_url));
            showResultModal(
              "success",
              jobSuccessCopy.notify.title,
              jobUserMessage(j) || jobSuccessCopy.notify.message,
              withUrl,
            );
            return;
          }
          if (jobType.includes("merge")) {
            const fromDetail = mergePdfLinksFromDetail(sync.data);
            const fromSummary = mergePdfLinksFromResultSummary(j.result_summary);
            const mergeLinks = fromDetail.length > 0 ? fromDetail : fromSummary;
            const withUrl = mergeLinks.filter((l) => Boolean(l.web_url));
            const mergeTitle = jobSuccessCopy.merge.title;
            const mergeMessage = jobUserMessage(j) || jobSuccessCopy.merge.message;
            // N≥2: mismo patrón que Archivos/amort — CTA → LinkCatalogDrawer.
            if (shouldOpenCatalogDrawer(withUrl.length)) {
              const catalogLinks = [...withUrl];
              jobModalBackgroundRef.current = false;
              setJobModal({
                kind: "success",
                title: mergeTitle,
                message: mergeMessage,
                catalogCta: {
                  label: catalogSummaryLabel("PDFs consolidados", catalogLinks.length),
                  onOpen: () => {
                    setJobModal(null);
                    setCatalogDrawer({
                      kind: "links",
                      title: "PDFs consolidados",
                      links: catalogLinks,
                    });
                  },
                },
              });
              setStatusCardNote(mergeMessage);
              return;
            }
            showResultModal("success", mergeTitle, mergeMessage, withUrl);
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
  // Badge alineado con readiness: ready no debe decir «esperando…».
  const statusBadgeTitle =
    detail.operational_status === "ESPERANDO_SOPORTES" && readiness?.status === "ready"
      ? "Listo para consolidar"
      : detail.operational_title || operationalStatusLabel(detail.operational_status);
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
  // Libro de tasas IBR_DIARIO.xlsx (solo CTA en fase amortización).
  const ibrUpdateLink = detail.links.find((l) => l.rel === "ibr" && l.web_url) ?? null;

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

  function phaseExtraInfo(
    phaseId: OperatorPhaseId,
    opts?: { showMergeVerify?: boolean },
  ): ReactNode {
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
              className="btn secondary"
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
      return (
        <MergeReadinessSummary
          readiness={readiness}
          showVerifyAction={Boolean(opts?.showMergeVerify)}
          verifying={refreshing}
          onVerifySupports={() => void refreshAll()}
        />
      );
    }
    if (phaseId === "amortization") {
      return (
        <AmortizationSummary readiness={amortizationReadiness} ibrLink={ibrUpdateLink} />
      );
    }
    return null;
  }

  const { phases: resolvedPhases, currentId: resolvedCurrentId } = resolveOperatorPhases(
    detail.steps,
  );
  // Con hoja Errores abierta o Excel ausente, el operador debe corregir/regenerar.
  const liveCurrentId: OperatorPhaseId = needsRegenerateFocus ? "review" : resolvedCurrentId;
  const selectedUnlocked =
    selectedPhaseId != null &&
    resolvedPhases.some((p) => p.def.id === selectedPhaseId && p.unlocked);
  // Tras Generate OK el Panel pasa `?phase=review` para abrir la fase 1 (readonly si ya completed).
  const phaseQueryHint = parseOperatorPhaseHint(searchParams.get("phase"));
  const hintedUnlocked =
    phaseQueryHint != null &&
    resolvedPhases.some((p) => p.def.id === phaseQueryHint && p.unlocked);
  const viewingPhaseId: OperatorPhaseId = hintedUnlocked
    ? phaseQueryHint
    : selectedUnlocked
      ? (selectedPhaseId as OperatorPhaseId)
      : liveCurrentId;
  const viewingPhase =
    resolvedPhases.find((p) => p.def.id === viewingPhaseId)?.def ??
    resolvedPhases.find((p) => p.def.id === liveCurrentId)?.def;
  const viewingResolved = resolvedPhases.find((p) => p.def.id === viewingPhaseId);
  const viewingCompletedPhase =
    viewingResolved?.visual === "completed" && viewingPhaseId !== liveCurrentId;
  const viewingLiveCurrent = viewingPhaseId === liveCurrentId;
  // Carpetas ASIENTOS solo mientras Merge está activo (carga de docs).
  // Tras COMPLETADO / apply done, los asientos viven en el consolidado.
  const applyCompleted =
    detail.steps.find((s) => s.name === "apply")?.status === "completed";
  const showAsientosFolders =
    !applyCompleted &&
    detail.operational_status !== "COMPLETADO" &&
    viewingPhaseId === "merge" &&
    resolvedPhases.some((p) => p.def.id === "merge" && p.unlocked);
  const mergeMissingItems = parseMergeMissingItems(readiness?.missing_items);
  const mergeSupportIssues =
    readiness &&
    shouldShowMergeSupportErrors(readiness.status, mergeMissingItems)
      ? buildMergeSupportOperationalIssues(
          mergeMissingItems,
          readiness.folder_links ?? [],
        )
      : [];
  const showMergeSupportBanner =
    viewingPhaseId === "merge" && mergeSupportIssues.length > 0;
  const asientosCatalogItems = showAsientosFolders
    ? buildAsientosCatalogItems(
        readiness?.folder_links ?? [],
        mergeMissingItems,
        readiness?.status,
      )
    : [];
  const selectedDocumentSection = documentSectionForSelectedPhase(
    detail.links,
    resolvedPhases,
    viewingPhaseId,
    {
      merge: asientosCatalogItems.map((item) => ({
        rel: item.rel,
        label: item.label,
        path: item.path,
        web_url: item.web_url,
        open_mode: item.open_mode,
      })),
    },
  );
  const processDocumentGroups = processFileCatalogGroups(
    resolveDocumentGroups(detail.document_groups, detail.links),
  );
  const showPhaseDocuments = shouldShowPhaseDocumentsSection({
    processFullyCompleted,
    viewingPhaseId,
  });
  const showProcessFiles = shouldShowProcessFileCatalog({
    processFullyCompleted,
    viewingPhaseId,
    hasCatalogGroups: processDocumentGroups.length > 0,
  });
  // CTA solo en la fase viva: fases completadas consultables no re-ejecutan acciones.
  // Mientras haya foco de corrección no se muestra Finalizar aunque se navegue a esa fase.
  const phaseCta =
    viewingLiveCurrent && !viewingCompletedPhase && viewingPhase
      ? ctaForPhase(viewingPhaseId)
      : null;
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

  const showProcessingIndicator =
    jobInFlight || syncPending || statusCardNote === "Procesando…";
  const processingIndicatorLabel = (() => {
    if (syncPending && !jobInFlight) return "Sincronizando resultados…";
    if (jobInFlight) return processingTitleForJob(trackedJob);
    return statusCardNote || "Procesando…";
  })();
  const statusDescription = (() => {
    if (showProcessingIndicator) return null;
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
    setCatalogDrawer({ kind: "links", title, links: [...links] });
  }

  async function openAsientosCatalog() {
    setCatalogDrawer({ kind: "asientos", refreshing: true });
    try {
      await load();
    } catch (e) {
      const msg = operatorErrorMessage(e, "No pudimos actualizar el estado.").message;
      showResultModal("error", "No se pudo actualizar", msg);
    } finally {
      setCatalogDrawer((prev) =>
        prev?.kind === "asientos" ? { kind: "asientos", refreshing: false } : prev,
      );
    }
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
          {catalogSummaryLabel("PDFs consolidados", mergePdfs.length)}
        </button>,
      );
    }
    // ASIENTOS: siempre drawer con estado listo/falta + GET fresco al abrir.
    if (asientosFolders.length >= 1) {
      const count = asientosFolders.length;
      nodes.push(
        <button
          key="asientos-folders-catalog"
          type="button"
          className="btn secondary"
          onClick={() => void openAsientosCatalog()}
        >
          {count === 1 ? "Ver carpeta ASIENTOS" : `Ver carpetas ASIENTOS (${count})`}
        </button>,
      );
    }
    return nodes;
  }

  function retryHandlerFor(action: string | null | undefined): (() => void) | undefined {
    // Regenerar solo desde el CTA de la fase (evita botones duplicados en alertas).
    switch (action) {
      case "regenerate":
      case "retry_generate":
        return undefined;
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

      <header className="process-phase-header panel">
        <ProcessPhaseStepper
          phases={phasesForStepper}
          currentTitle={
            processFullyCompleted
              ? "Proceso completado"
              : (viewingPhase?.title ?? "Proceso")
          }
          selectedId={viewingPhaseId}
          onSelectPhase={(id) => {
            setSelectedPhaseId(id);
            if (searchParams.has("phase")) {
              const next = new URLSearchParams(searchParams);
              next.delete("phase");
              setSearchParams(next, { replace: true });
            }
          }}
        />
      </header>

      <section className="panel status-summary-card">
        <div className="status-summary-header">
          <h1 className="status-summary-title">{detail.bank_name ?? detail.bank_code}</h1>
        </div>
        <p className="meta">Fecha: {detail.process_date ?? "—"}</p>
        <div className="status-summary-badge-row">
          <span className={`status-pill ${statusClass(detail.operational_status)}`}>
            {statusBadgeTitle}
          </span>
        </div>
        {showProcessingIndicator ? (
          <p
            className="status-summary-desc status-summary-processing"
            role="status"
            aria-live="polite"
            aria-busy="true"
          >
            <Spinner size="sm" label={processingIndicatorLabel} />
            <span>{processingIndicatorLabel}</span>
          </p>
        ) : statusDescription ? (
          <p className="status-summary-desc">{statusDescription}</p>
        ) : null}
        {csrfPreparing ? (
          <p className="muted" role="status">
            Preparando sesión segura…
          </p>
        ) : null}
      </section>

      {showMergeSupportBanner ? (
        <section
          className="phase-operational-alert"
          role="alert"
          aria-labelledby="merge-support-errors-banner-title"
        >
          <p id="merge-support-errors-banner-title" className="phase-operational-alert-text">
            {mergeSupportIssues.length} problema(s) con los documentos contables.
          </p>
          <button
            type="button"
            className="btn secondary btn-compact"
            onClick={() => setMergeSupportIssuesOpen(true)}
          >
            Ver problemas de soportes
          </button>
        </section>
      ) : null}

      {reviewFileMissing && !hasReviewErrores ? (
        <section className="panel" role="alert" aria-labelledby="review-missing-banner-title">
          <h2 id="review-missing-banner-title" className="section-title" style={{ marginTop: 0 }}>
            Falta el archivo de revisión
          </h2>
          <p className="meta">{actionExplanations.review_file_missing_warning}</p>
          <p className="meta">{actionExplanations.regenerate_use_phase_cta}</p>
        </section>
      ) : null}

      {viewingPhase && !processFullyCompleted && (
        <section className="panel current-phase-panel" aria-labelledby="current-phase-title">
          {hasReviewErrores ? (
            <div
              className="phase-operational-alert"
              role="alert"
              aria-labelledby="review-errores-banner-title"
            >
              <p id="review-errores-banner-title" className="phase-operational-alert-text">
                {reviewErroresIssues.length} caso(s) en la hoja Errores.
              </p>
              <button
                type="button"
                className="btn secondary btn-compact"
                onClick={() => setOperationalIssuesOpen(true)}
              >
                Ver problemas operativos
              </button>
            </div>
          ) : detail.operational_issues.length > 0 ? (
            <div
              className="phase-operational-alert"
              role="alert"
              aria-labelledby="operational-issues-banner-title"
            >
              <p id="operational-issues-banner-title" className="phase-operational-alert-text">
                {detail.operational_issues.length} problema(s) operativo(s).
              </p>
              <button
                type="button"
                className="btn secondary btn-compact"
                onClick={() => setOperationalIssuesOpen(true)}
              >
                Ver problemas operativos
              </button>
            </div>
          ) : null}
          <div className="phase-split">
            <div className="phase-split-main">
              <h2 id="current-phase-title" className="section-title">
                {viewingPhase.title}
              </h2>
              <p className="meta">{viewingPhase.guidance}</p>
              {viewingCompletedPhase ? (
                <p className="meta" style={{ marginTop: "0.35rem" }}>
                  {actionExplanations.phase_completed_readonly}
                </p>
              ) : (
                phaseExtraInfo(viewingPhaseId, {
                  showMergeVerify: viewingLiveCurrent && !mergeCompleted,
                })
              )}
              {phaseCta?.disabled &&
              phaseCta.reason &&
              !(
                viewingPhaseId === "merge" &&
                readiness &&
                (readiness.status === "incomplete" || readiness.status === "unknown")
              ) ? (
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
                  (viewingPhaseId === "review" || viewingPhaseId === "finalize") ? (
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
              ) : needsRegenerateFocus && viewingPhaseId !== "review" ? (
                <p className="meta">{actionExplanations.regenerate_use_phase_cta}</p>
              ) : viewingCompletedPhase ? (
                <p className="meta">Consulta solamente.</p>
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

      <OperationalIssuesModal
        open={operationalIssuesOpen && detail.operational_issues.length > 0}
        issues={detail.operational_issues}
        onClose={() => setOperationalIssuesOpen(false)}
        onRetryFor={retryHandlerFor}
        retryBusy={actionBusy}
      />

      <OperationalIssuesModal
        open={mergeSupportIssuesOpen && mergeSupportIssues.length > 0}
        title="Problemas de soportes"
        issues={mergeSupportIssues}
        onClose={() => setMergeSupportIssuesOpen(false)}
      />

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

      {showPhaseDocuments ? (
        <section className="panel" id="process-documents">
          <h2 className="section-title">Documentos por fase</h2>
          <p className="meta" style={{ marginTop: 0 }}>
            Documentos de «{viewingPhase?.title ?? "esta fase"}».
          </p>
          {!selectedDocumentSection ? (
            <p className="muted">Aún no hay documentos disponibles para esta fase.</p>
          ) : (
            <div className="phase-docs-row" role="list">
              <div className="phase-docs-card" role="listitem">
                <h3 className="phase-docs-title">{selectedDocumentSection.phase.title}</h3>
                <div className="phase-docs-links">
                  {renderPhaseDocCluster(selectedDocumentSection.links)}
                </div>
              </div>
            </div>
          )}
        </section>
      ) : null}

      {showProcessFiles ? (
        <section className="panel" id="process-file-catalog" aria-labelledby="process-file-catalog-title">
          <h2 id="process-file-catalog-title" className="section-title">
            Archivos del proceso
          </h2>
          <p className="meta" style={{ marginTop: 0 }}>
            Documentos del lote (revisión, correo), PDF consolidado y tablas de amortización.
            Las fases anteriores siguen disponibles en el encabezado.
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
                  {catalogSummaryLabel(title, group.count || groupLinks.length)}
                </button>
              );
            })}
          </div>
        </section>
      ) : null}

      <LinkCatalogDrawer
        open={catalogDrawer != null}
        title={
          catalogDrawer?.kind === "asientos"
            ? "Carpetas ASIENTOS"
            : (catalogDrawer?.title ?? "")
        }
        links={
          catalogDrawer?.kind === "asientos"
            ? buildAsientosCatalogItems(
                readiness?.folder_links ?? [],
                mergeMissingItems,
                readiness?.status,
              )
            : (catalogDrawer?.links ?? [])
        }
        groupsProgress={
          catalogDrawer?.kind === "asientos" &&
          readiness &&
          readiness.expected_groups > 0 &&
          (readiness.status === "incomplete" ||
            readiness.status === "ready" ||
            readiness.status === "already_merged")
            ? {
                label: formatMergeGroupsProgress(readiness),
                complete:
                  readiness.status === "ready" || readiness.status === "already_merged",
              }
            : null
        }
        refreshing={catalogDrawer?.kind === "asientos" ? catalogDrawer.refreshing : false}
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
