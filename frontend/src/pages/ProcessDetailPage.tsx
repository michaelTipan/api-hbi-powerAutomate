import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  fetchBootstrap,
  fetchIbrPreview,
  fetchJob,
  fetchNotifyRecipientsPreview,
  fetchProcess,
  postAmortization,
  postCancelLote,
  postFinalize,
  postGenerate,
  postMerge,
  postNotify,
  postSoftClose,
  type UiBankCode,
} from "../api/client";
import { useCsrfReady } from "../api/useCsrfReady";
import type {
  StepName,
  UiBootstrapResponse,
  UiIbrPreview,
  UiJobView,
  UiLink,
  UiMergeReadiness,
  UiAmortizationReadiness,
  UiNotifyRecipientsPreview,
  UiOperationalIssue,
  UiProcessDetail,
} from "../types/contract";
import { statusClass } from "../components/AppShell";
import { resolveProcessBadgeStatus, LISTO_PARA_CONSOLIDAR } from "../domain/statusTone";
import { OperationalIssuesModal } from "../components/OperationalIssuesModal";
import {
  isActiveStatus,
  isTerminalUiJob,
  resolveDisplayedAttempt,
} from "../domain/resolveDisplayedAttempt";
import { LoadingButton } from "../components/LoadingButton";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { TypeConfirmDialog } from "../components/TypeConfirmDialog";
import { JobStatusModal, type JobStatusModalView } from "../components/JobStatusModal";
import { LinkCatalogDrawer, type CatalogDrawerLink } from "../components/LinkCatalogDrawer";
import { PageSkeleton } from "../components/Skeleton";
import { ProcessPhaseStepper } from "../components/ProcessPhaseStepper";
import { Modal } from "../components/Modal";
import {
  amortizationTableLinksFromDetail,
  catalogGroupTitle,
  catalogSummaryLabel,
  emailPdfLinksFromDetail,
  emailPdfLinksFromResultSummary,
  finalizeArtifactLinksFromDetail,
  finalizeArtifactLinksFromResultSummary,
  mergePdfLinksFromDetail,
  mergePdfLinksFromResultSummary,
  partitionLinksForPhaseCard,
  processFileCatalogGroups,
  resolveDocumentGroups,
  resolveLinksPreferDetail,
  reviewExcelLinksFromDetail,
  reviewExcelLinksFromResultSummary,
  shouldOpenCatalogDrawer,
} from "../domain/documentCatalog";
import {
  buildPhaseStepperModel,
  documentSectionForSelectedPhase,
  operatorDocumentLabel,
  parseOperatorPhaseHint,
  resolveOperatorPhases,
  shouldShowPhaseDocumentsSection,
  shouldShowProcessFileCatalog,
  type OperatorPhaseId,
} from "../domain/processPhases";
import { isDurableNotifySuccessKey, isNotifyMailUncertainJob } from "../domain/notifyMailUncertain";
import { formatOperatorDateTime } from "../domain/operatorDateTime";
import { jobNextAction, jobUserMessage, operatorErrorMessage } from "../domain/jobMessages";
import {
  isReviewErroresIssue,
  resolveGenerateReviewErrorCount,
} from "../domain/generateJobOutcome";
import {
  compactFinalizeFailureMessage,
  isFinalizeJob,
  resolveFinalizeFailureIssues,
  reviewExcelModalLink,
  shouldCompactFinalizeJobModal,
  type JobFailureIssue,
} from "../domain/finalizeJobFailure";
import {
  AMORT_SYNC_SOFT_TIMEOUT_MESSAGE,
  AMORT_SYNC_SOFT_TIMEOUT_TITLE,
  MERGE_SYNC_SOFT_TIMEOUT_MESSAGE,
  MERGE_SYNC_SOFT_TIMEOUT_TITLE,
  SYNC_RESULTS_MESSAGE,
  SYNC_TIMEOUT_MESSAGE,
  amortizationJobHasBusinessTerminalOutcome,
  amortizationOutcomeFromJob,
  mergeJobIsPartial,
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
  jobWarningCopy,
  isOperationalStatusBusy,
  operationalStatusLabel,
} from "../copy/labels";
import { Spinner } from "../components/Spinner";
import {
  buildAsientosCatalogItems,
  buildMergeSupportOperationalIssues,
  buildRecoveryVerifyItems,
  filterFolderLinksForAmortRecovery,
  formatMergeGroupsProgress,
  mergeGroupsProgressTone,
  parseMergeMissingItems,
  shouldShowMergeSupportErrors,
  type RecoveryVerifyItem,
} from "../domain/mergeReadinessCopy";
import {
  amortMissingItemMessage,
  amortWarningMessage,
  amortItemsProgressTone,
  formatAmortItemsProgress,
  parseAmortMissingItems,
} from "../domain/amortizationReadinessCopy";
import {
  amortizationIssuesFromLastAttempt,
  amortizationIssuesJobSummary,
  buildAmortizationOperationalIssuesFromJob,
  formatAmortizationIssuesBanner,
  hasAmortFormatRecoveryIssues,
  resolveAmortizationDisplayIssues,
} from "../domain/amortizationOperationalIssues";

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
  const tone = mergeGroupsProgressTone(readiness.status);
  // incomplete / ready / already_merged; unknown sin conteo útil se omite.
  if (tone === "unknown") return null;
  return (
    <p
      className={`merge-groups-progress ${
        tone === "complete" ? "is-complete" : "is-pending"
      }`}
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
  recoveryMode = false,
  recoveryVerifyItems = [],
}: {
  readiness: UiMergeReadiness | null;
  onVerifySupports?: () => void;
  verifying?: boolean;
  /** Solo en la fase Merge viva (incomplete/unknown) o recuperación. */
  showVerifyAction?: boolean;
  /** Recuperación post-formato: copy de reconsolidar, no primer merge. */
  recoveryMode?: boolean;
  /** Resultados informativos del verify ligero (solo recovery + tras verificar). */
  recoveryVerifyItems?: readonly RecoveryVerifyItem[];
}) {
  if (!readiness) {
    return <p className="meta">La verificación de documentos aún no está disponible.</p>;
  }

  const needsRecovery =
    readiness.status === "incomplete" || readiness.status === "unknown";
  const showVerify = Boolean(
    showVerifyAction && onVerifySupports && (needsRecovery || recoveryMode),
  );

  return (
    <div className="merge-readiness-panel">
      {recoveryMode ? (
        <p className="meta" style={{ marginTop: 0 }}>
          {actionExplanations.merge_recovery_banner}
        </p>
      ) : null}
      {readiness.status === "ready" || readiness.status === "already_merged" ? (
        <>
          <MergeGroupsProgressBanner readiness={readiness} />
          {!recoveryMode && readiness.user_message ? (
            <p className="meta">{readiness.user_message}</p>
          ) : null}
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
      {recoveryMode && recoveryVerifyItems.length > 0 ? (
        <ul className="merge-recovery-verify-list" style={{ margin: "0.5rem 0 0", paddingLeft: "1.25rem" }}>
          {recoveryVerifyItems.map((item) => (
            <li key={item.credit} className="meta" style={{ marginBottom: "0.25rem" }}>
              Crédito {item.credit}: {actionExplanations[item.messageKey]}
            </li>
          ))}
        </ul>
      ) : null}
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
          <div className="amort-ibr-action">
            <a
              className="btn secondary"
              href={ibrLink.web_url}
              target="_blank"
              rel="noreferrer"
            >
              Actualizar IBR
            </a>
          </div>
        ) : null}
      </div>
    );
  }
  const missingItems = parseAmortMissingItems(readiness.missing_items);
  const warnings = (readiness.warnings ?? [])
    .map((w) => amortWarningMessage(w))
    .filter((w): w is string => Boolean(w));
  const itemsTone = amortItemsProgressTone(readiness.status);
  const showItemsChip = readiness.expected_items > 0;
  return (
    <div className="amort-readiness-panel">
      {readiness.user_message ? <p className="meta">{readiness.user_message}</p> : null}
      {showItemsChip ? (
        <p
          className={`merge-groups-progress ${
            itemsTone === "complete"
              ? "is-complete"
              : itemsTone === "pending"
                ? "is-pending"
                : "is-unknown"
          }`}
          role="status"
        >
          {formatAmortItemsProgress(readiness)}
        </p>
      ) : null}
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
        <div className="amort-ibr-action">
          <a
            className="btn secondary"
            href={ibrLink.web_url}
            target="_blank"
            rel="noreferrer"
          >
            Actualizar IBR
          </a>
        </div>
      ) : null}
    </div>
  );
}

function IbrConfirmSummary({
  preview,
  loading,
  error,
  onRefresh,
}: {
  preview: UiIbrPreview | null;
  loading: boolean;
  error: string | null;
  onRefresh: () => void;
}) {
  const rates = preview?.rates ?? [];
  return (
    <>
      {loading ? (
        <p className="meta">Leyendo IBR_DIARIO.xlsx…</p>
      ) : error ? (
        <p className="meta" role="status">
          {error}
        </p>
      ) : preview ? (
        <>
          {rates.length > 1 ? (
            <>
              <p role="status">
                Este lote tiene cuotas con distintos cortes. Cada corte usa su tasa
                IBR:
              </p>
              <ul style={{ margin: "0.35rem 0 0.5rem", paddingLeft: "1.25rem" }}>
                {rates.map((row) => (
                  <li key={row.date} className="meta">
                    {row.date_label}: {row.rate_label || "sin tasa"}
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <p role="status">{preview.user_message}</p>
          )}
          {preview.file_last_modified ? (
            <p className="meta">
              Archivo IBR modificado: {formatOperatorDateTime(preview.file_last_modified)}
            </p>
          ) : null}
        </>
      ) : null}
      <div className="actions" style={{ marginTop: "0.5rem" }}>
        <button type="button" className="btn secondary" disabled={loading} onClick={onRefresh}>
          Actualizar lectura
        </button>
      </div>
    </>
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
  const [confirmCancelLote, setConfirmCancelLote] = useState(false);
  const [confirmSoftClose, setConfirmSoftClose] = useState(false);
  const [notifyRecipientsPreview, setNotifyRecipientsPreview] =
    useState<UiNotifyRecipientsPreview | null>(null);
  const [notifyPreviewLoading, setNotifyPreviewLoading] = useState(false);
  const [notifyPreviewError, setNotifyPreviewError] = useState<string | null>(null);
  const [ibrPreview, setIbrPreview] = useState<UiIbrPreview | null>(null);
  const [ibrPreviewLoading, setIbrPreviewLoading] = useState(false);
  const [ibrPreviewError, setIbrPreviewError] = useState<string | null>(null);
  const [catalogDrawer, setCatalogDrawer] = useState<
    | { kind: "links"; title: string; links: CatalogDrawerLink[] }
    | { kind: "asientos"; refreshing: boolean }
    | null
  >(null);
  const [reviewErroresIntroOpen, setReviewErroresIntroOpen] = useState(false);
  const [operationalIssuesOpen, setOperationalIssuesOpen] = useState(false);
  const [mergeSupportIssuesOpen, setMergeSupportIssuesOpen] = useState(false);
  const [amortizationIssuesOpen, setAmortizationIssuesOpen] = useState(false);
  /** Issues del último job de amortización con requires_correction (hasta refresh/nuevo proceso). */
  const [amortizationIssues, setAmortizationIssues] = useState<UiOperationalIssue[]>(
    [],
  );
  /**
   * Sesión: el operador eligió ir a reconsolidar tras fallos de formato de asiento.
   * No dispara merge automático; solo guía fase 3 (Merge) + force_rebuild.
   */
  const [recoveryFromAmortFormat, setRecoveryFromAmortFormat] = useState(false);
  /** Tras reconsolidar OK: pista en fase 4 (amortización) para volver a amortizar. */
  const [amortAfterReconsolidateHint, setAmortAfterReconsolidateHint] =
    useState(false);
  /** Recuperación: mostrar todas las carpetas ASIENTOS (no solo créditos afectados). */
  const [showAllRecoveryFolders, setShowAllRecoveryFolders] = useState(false);
  const recoveryFromAmortFormatRef = useRef(false);
  const pendingGoAmortAfterMergeRef = useRef(false);
  /**
   * Tras Notify, la proyección ya puede reportar faltantes de ASIENTOS.
   * No mostramos el banner de problemas hasta que el operador verifique
   * (botón «Actualizar / verificar asientos contables», Actualizar de toolbar o abrir carpetas).
   */
  const [mergeSupportsVerified, setMergeSupportsVerified] = useState(false);
  const [finalizeBusy, setFinalizeBusy] = useState(false);
  const [notifyBusy, setNotifyBusy] = useState(false);
  const [mergeBusy, setMergeBusy] = useState(false);
  const [amortizationBusy, setAmortizationBusy] = useState(false);
  const [regenerateBusy, setRegenerateBusy] = useState(false);
  const [cancelLoteBusy, setCancelLoteBusy] = useState(false);
  const [softCloseBusy, setSoftCloseBusy] = useState(false);
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
  const suppressReviewErroresIntroRef = useRef(false);
  const regenerateNavigateRef = useRef(false);
  const liveCurrentIdRef = useRef<OperatorPhaseId | null>(null);
  const keyRef = useRef(key);
  keyRef.current = key;
  const { csrfReady, csrfPreparing } = useCsrfReady();

  const stopPoll = useCallback(() => {
    if (pollRef.current !== null) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const load = useCallback(async () => {
    const requestedKey = key;
    const p = await fetchProcess(requestedKey);
    if (keyRef.current !== requestedKey) {
      return p;
    }
    setDetail(p);
    setError(null);
    // Conservar job local en vuelo (queued/running) aunque Control aún no
    // proyecte active_job: si no, actionBusy cae y el CTA se re-habilita.
    const keepLocalJob = (prev: UiJobView | null) =>
      isTerminalUiJob(prev) || isActiveStatus(prev?.status) ? prev : null;
    if (p.active_job?.job_id) {
      try {
        const j = await fetchJob(p.active_job.job_id);
        setJob((prev) => {
          if (
            prev &&
            isActiveStatus(prev.status) &&
            prev.job_id &&
            prev.job_id !== j.job_id
          ) {
            return prev;
          }
          return j;
        });
      } catch {
        setJob(keepLocalJob);
      }
    } else {
      setJob(keepLocalJob);
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
    const hasErrores = detail.operational_issues.some(isReviewErroresIssue);
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
    if (suppressReviewErroresIntroRef.current) {
      reviewErroresIntroShownRef.current = true;
      setReviewErroresIntroOpen(false);
      suppressReviewErroresIntroRef.current = false;
    } else {
      reviewErroresIntroShownRef.current = false;
    }
    setError(null);
    setMergeSupportsVerified(false);
    setMergeSupportIssuesOpen(false);
    setAmortizationIssuesOpen(false);
    setAmortizationIssues([]);
    setShowAllRecoveryFolders(false);
    setNotifyRecipientsPreview(null);
    setNotifyPreviewError(null);
    setIbrPreview(null);
    setIbrPreviewError(null);
  }, [key]);

  const loadNotifyRecipientsPreview = useCallback(async () => {
    if (!key) return;
    setNotifyPreviewLoading(true);
    setNotifyPreviewError(null);
    try {
      const preview = await fetchNotifyRecipientsPreview(key);
      setNotifyRecipientsPreview(preview);
    } catch (e) {
      setNotifyRecipientsPreview(null);
      setNotifyPreviewError(
        operatorErrorMessage(e, "No pudimos leer CORREOS.xlsx.").message,
      );
    } finally {
      setNotifyPreviewLoading(false);
    }
  }, [key]);

  const loadIbrPreview = useCallback(async () => {
    if (!key) return;
    setIbrPreviewLoading(true);
    setIbrPreviewError(null);
    try {
      const preview = await fetchIbrPreview(key);
      setIbrPreview(preview);
    } catch (e) {
      setIbrPreview(null);
      setIbrPreviewError(
        operatorErrorMessage(e, "No pudimos leer IBR_DIARIO.xlsx.").message,
      );
    } finally {
      setIbrPreviewLoading(false);
    }
  }, [key]);

  useEffect(() => {
    if (confirmNotify) {
      void loadNotifyRecipientsPreview();
    }
  }, [confirmNotify, loadNotifyRecipientsPreview]);

  useEffect(() => {
    if (confirmAmortization) {
      void loadIbrPreview();
    }
  }, [confirmAmortization, loadIbrPreview]);

  useEffect(() => {
    if (!detail?.last_amortization_attempt?.operational_issues?.length) return;
    const persisted = amortizationIssuesFromLastAttempt(detail);
    if (persisted.length > 0) {
      setAmortizationIssues(persisted);
    }
  }, [detail?.last_amortization_attempt, detail?.process_key]);

  useEffect(() => {
    if (!detail) return;
    const hasErrores = detail.operational_issues.some(isReviewErroresIssue);
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

  // Con Errores/archivo faltante, anular ?phase= que abriría Notify u otra fase bloqueada.
  useEffect(() => {
    if (!detail) return;
    const hasErrores = detail.operational_issues.some(isReviewErroresIssue);
    const fileMissing = detail.operational_issues.some(
      (issue) => issue.issue_id === "review-file-missing",
    );
    if (!(hasErrores || fileMissing)) return;
    const hint = parseOperatorPhaseHint(searchParams.get("phase"));
    if (hint == null || hint === "review") return;
    const next = new URLSearchParams(searchParams);
    next.delete("phase");
    setSearchParams(next, { replace: true });
  }, [detail, searchParams, setSearchParams]);

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;

    const tick = async () => {
      try {
        const p = await load();
        if (cancelled) return;
        const running = ["queued", "running"].includes((p.active_job?.status || "").toLowerCase());
        const controlBusy = isOperationalStatusBusy(p.operational_status);
        if (running || controlBusy) {
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
    if (t.includes("notify")) return busyLabels.notify;
    if (t.includes("finalize")) return busyLabels.finalize;
    if (t.includes("merge")) return busyLabels.merge;
    if (t.includes("amortization") || t.includes("apply")) return busyLabels.amortization;
    if (t === "soft_close_process" || t.includes("soft_close")) return busyLabels.soft_close;
    if (t === "cancel_active_process" || t.includes("cancel")) return busyLabels.cancel_lote;
    if (t.includes("generate")) {
      return busyLabels.regenerate;
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
    options?: {
      dismissLabel?: string;
      issues?: readonly JobFailureIssue[];
      secondaryCta?: { label: string; onClick: () => void };
    },
  ) {
    jobModalBackgroundRef.current = false;
    const issueList = options?.issues?.length ? [...options.issues] : undefined;
    if (outcome === "success") {
      setJobModal({
        kind: "success",
        title,
        message,
        links: links ? [...links] : undefined,
        dismissLabel: options?.dismissLabel,
        secondaryCta: options?.secondaryCta,
      });
    } else if (outcome === "warning") {
      setJobModal({
        kind: "warning",
        title,
        message,
        links: links ? [...links] : undefined,
        issues: issueList,
        dismissLabel: options?.dismissLabel || "Actualizar estado",
        secondaryCta: options?.secondaryCta,
      });
    } else {
      setJobModal({
        kind: "error",
        title,
        message,
        links: links ? [...links] : undefined,
        issues: issueList,
        dismissLabel: options?.dismissLabel,
        secondaryCta: options?.secondaryCta,
      });
    }
    setStatusCardNote(message);
  }

  function showGenerateReviewOutcome(
    j: UiJobView,
    links: readonly UiLink[] | undefined,
    opts: { regenerate: boolean; detail?: UiProcessDetail | null },
  ) {
    suppressReviewErroresIntroRef.current = true;
    reviewErroresIntroShownRef.current = true;
    setReviewErroresIntroOpen(false);
    const errorCount = resolveGenerateReviewErrorCount(j, opts.detail);
    if (errorCount > 0) {
      const copy = opts.regenerate
        ? jobWarningCopy.regenerate_with_errors
        : jobWarningCopy.generate_with_errors;
      showResultModal("warning", copy.title, copy.message(errorCount), links, {
        dismissLabel: "Entendido",
      });
      return;
    }
    const copy = opts.regenerate ? jobSuccessCopy.regenerate : jobSuccessCopy.generate;
    showResultModal(
      "success",
      copy.title,
      jobUserMessage(j) || copy.message,
      links,
    );
  }

  function dismissJobModal() {
    if (jobModal?.kind === "processing" && jobModal.dismissible) {
      jobModalBackgroundRef.current = true;
      setStatusCardNote("Procesando…");
      setJobModal(null);
      return;
    }
    const shouldRefreshAfterWarning = jobModal?.kind === "warning";
    const goAmortAfterMerge = pendingGoAmortAfterMergeRef.current;
    pendingGoAmortAfterMergeRef.current = false;
    setJobModal(null);
    if (goAmortAfterMerge) {
      recoveryFromAmortFormatRef.current = false;
      setRecoveryFromAmortFormat(false);
      setAmortAfterReconsolidateHint(true);
      setAmortizationIssues([]);
      setAmortizationIssuesOpen(false);
      setPollWarning(null);
      setSelectedPhaseId("amortization");
      return;
    }
    if (shouldRefreshAfterWarning) {
      void refreshAll();
    }
  }

  async function refreshAll() {
    setRefreshing(true);
    try {
      await load();
      // Verificación explícita (toolbar o «Actualizar / verificar asientos contables»).
      setMergeSupportsVerified(true);
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
    const delays = postJobReloadDelaysFor(terminalJob);
    const { synced, data } = await reloadUntilProjectionMatchesJob(
      load,
      terminalJob,
      projectionReflectsTerminalJob,
      Array.isArray(delays) && delays.length > 0 ? delays : [0],
    );
    setPollWarning(synced ? null : SYNC_TIMEOUT_MESSAGE);
    return { synced, data };
  }

  /**
   * Éxito con artefactos N: 1 link directo; 2+ → un solo CTA que abre
   * LinkCatalogDrawer (lista limpia, sin chips de listo/falta).
   */
  function showSuccessWithOptionalCatalog(input: {
    title: string;
    message: string;
    links: readonly UiLink[];
    catalogTitle: string;
  }) {
    const withUrl = input.links.filter((l) => Boolean(l.web_url));
    if (shouldOpenCatalogDrawer(withUrl.length)) {
      const catalogLinks = [...withUrl];
      jobModalBackgroundRef.current = false;
      setJobModal({
        kind: "success",
        title: input.title,
        message: input.message,
        catalogCta: {
          label: catalogSummaryLabel(input.catalogTitle, catalogLinks.length),
          onOpen: () => {
            setJobModal(null);
            setCatalogDrawer({
              kind: "links",
              title: input.catalogTitle,
              links: catalogLinks,
            });
          },
        },
      });
      setStatusCardNote(input.message);
      return;
    }
    showResultModal("success", input.title, input.message, withUrl);
  }

  function showAmortizationBusinessOutcome(j: UiJobView) {
    const outcome = amortizationOutcomeFromJob(j);
    const amortIssues = buildAmortizationOperationalIssuesFromJob(j);
    if (amortIssues.length > 0) {
      setAmortizationIssues(amortIssues);
    }
    const openAmortIssuesCta =
      amortIssues.length >= 1
        ? {
            label: actionLabels.view_amortization_issues,
            onClick: () => {
              setJobModal(null);
              setAmortizationIssuesOpen(true);
            },
          }
        : undefined;
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
      showResultModal(
        "error",
        "No se pudo completar",
        amortIssues.length >= 1
          ? amortizationIssuesJobSummary(amortIssues.length)
          : full,
        undefined,
        openAmortIssuesCta ? { secondaryCta: openAmortIssuesCta } : undefined,
      );
      return;
    }
    if (amortIssues.length >= 1) {
      showResultModal(
        "warning",
        "Revisión requerida",
        amortizationIssuesJobSummary(amortIssues.length),
        undefined,
        { secondaryCta: openAmortIssuesCta },
      );
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
            const full = next ? `${msg} ${next}` : msg;
            let syncedDetail: UiProcessDetail | null = null;
            try {
              syncedDetail = await load();
            } catch {
              syncedDetail = null;
            }
            const finalizeFailure = isFinalizeJob(j);
            const issues = finalizeFailure
              ? resolveFinalizeFailureIssues(j, syncedDetail)
              : [];
            if (
              finalizeFailure &&
              shouldCompactFinalizeJobModal(j, syncedDetail)
            ) {
              showResultModal(
                "error",
                "No se pudo completar",
                compactFinalizeFailureMessage(issues.length),
                undefined,
                {
                  secondaryCta: {
                    label: "Ver problemas operativos",
                    onClick: () => {
                      setJobModal(null);
                      setOperationalIssuesOpen(true);
                    },
                  },
                },
              );
              return;
            }
            const reviewLink = finalizeFailure
              ? reviewExcelModalLink(syncedDetail)
              : null;
            showResultModal(
              "error",
              "No se pudo completar",
              full,
              reviewLink ? [reviewLink] : undefined,
              issues.length > 0 ? { issues } : undefined,
            );
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
              suppressReviewErroresIntroRef.current = true;
              reviewErroresIntroShownRef.current = true;
              setReviewErroresIntroOpen(false);
              let freshDetail: UiProcessDetail | null = null;
              try {
                freshDetail = await fetchProcess(newKey);
                if (keyRef.current === key) {
                  setDetail(freshDetail);
                  setError(null);
                }
              } catch {
                freshDetail = null;
              }
              const regenLinks = resolveLinksPreferDetail(
                reviewExcelLinksFromDetail(freshDetail ?? {}),
                reviewExcelLinksFromResultSummary(j.result_summary),
              );
              showGenerateReviewOutcome(j, regenLinks, {
                regenerate: true,
                detail: freshDetail,
              });
              // Sin ?phase=: el detalle recalcula la fase viva (review si quedan Errores).
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
            // Quitar ?phase=finalize (u otra) para no saltar a Finalizar con Errores restantes.
            if (searchParams.has("phase")) {
              const next = new URLSearchParams(searchParams);
              next.delete("phase");
              setSearchParams(next, { replace: true });
            }
            setSelectedPhaseId("review");
            liveCurrentIdRef.current = null;
            const regenLinks = resolveLinksPreferDetail(
              reviewExcelLinksFromDetail(sync.data ?? {}),
              reviewExcelLinksFromResultSummary(j.result_summary),
            );
            showGenerateReviewOutcome(j, regenLinks, {
              regenerate: true,
              detail: sync.data,
            });
            return;
          }
          const jobType = (j.type || "").toLowerCase();
          const isAmortizationJob =
            jobType.includes("amortization") || jobType.includes("apply");
          const isProcessControlCloseJob =
            jobType === "cancel_active_process" ||
            jobType === "soft_close_process" ||
            jobType.includes("soft_close");

          // Cancelar lote / cerrar sin amortizar: el detalle puede dejar de existir.
          if (isProcessControlCloseJob) {
            const closedCopy =
              jobType === "soft_close_process" || jobType.includes("soft_close")
                ? jobSuccessCopy.soft_close
                : jobSuccessCopy.cancel_lote;
            showResultModal(
              "success",
              closedCopy.title,
              jobUserMessage(j) || closedCopy.message,
            );
            navigate("/", { replace: true });
            return;
          }

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
            if (jobType.includes("merge")) {
              const mergeLinks = resolveLinksPreferDetail(
                mergePdfLinksFromDetail(sync.data ?? {}),
                mergePdfLinksFromResultSummary(j.result_summary),
              );
              // Recovery: aunque Control Graph vaya atrasado, el PDF ya se reconsolidó.
              if (recoveryFromAmortFormatRef.current) {
                pendingGoAmortAfterMergeRef.current = true;
                setPollWarning(null);
                setAmortizationIssues([]);
                setAmortizationIssuesOpen(false);
                showResultModal(
                  "warning",
                  MERGE_SYNC_SOFT_TIMEOUT_TITLE,
                  MERGE_SYNC_SOFT_TIMEOUT_MESSAGE,
                  mergeLinks,
                  {
                    dismissLabel: actionLabels.go_amortization_after_reconsolidate,
                  },
                );
                return;
              }
              setPollWarning(null);
              showResultModal(
                "warning",
                MERGE_SYNC_SOFT_TIMEOUT_TITLE,
                MERGE_SYNC_SOFT_TIMEOUT_MESSAGE,
                mergeLinks,
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
            setAmortizationIssues([]);
            setAmortizationIssuesOpen(false);
            showSuccessWithOptionalCatalog({
              title: jobSuccessCopy.amortization.title,
              message: jobUserMessage(j) || jobSuccessCopy.amortization.message,
              links: amortizationTableLinksFromDetail(sync.data),
              catalogTitle: "Tablas de amortización",
            });
            return;
          }
          if (jobType.includes("finalize")) {
            const finalizeLinks = resolveLinksPreferDetail(
              finalizeArtifactLinksFromDetail(sync.data ?? {}),
              finalizeArtifactLinksFromResultSummary(j.result_summary),
            );
            showResultModal(
              "success",
              jobSuccessCopy.finalize.title,
              jobUserMessage(j) || jobSuccessCopy.finalize.message,
              finalizeLinks,
            );
            return;
          }
          if (jobType.includes("notify")) {
            if (isNotifyMailUncertainJob(j)) {
              showResultModal(
                "warning",
                jobSuccessCopy.notify_uncertain.title,
                jobUserMessage(j) || jobSuccessCopy.notify_uncertain.message,
              );
              return;
            }
            const notifyLinks = resolveLinksPreferDetail(
              emailPdfLinksFromDetail(sync.data ?? {}),
              emailPdfLinksFromResultSummary(j.result_summary),
            );
            showResultModal(
              "success",
              jobSuccessCopy.notify.title,
              jobUserMessage(j) || jobSuccessCopy.notify.message,
              notifyLinks,
            );
            return;
          }
          if (jobType.includes("merge")) {
            const mergeLinks = resolveLinksPreferDetail(
              mergePdfLinksFromDetail(sync.data ?? {}),
              mergePdfLinksFromResultSummary(j.result_summary),
            );
            const mergePartial = mergeJobIsPartial(j, sync.data);
            if (recoveryFromAmortFormatRef.current) {
              if (mergePartial) {
                pendingGoAmortAfterMergeRef.current = false;
                showResultModal(
                  "warning",
                  jobWarningCopy.merge_partial.title,
                  jobUserMessage(j) || jobWarningCopy.merge_partial.message,
                  mergeLinks,
                  { dismissLabel: "Entendido" },
                );
                return;
              }
              pendingGoAmortAfterMergeRef.current = true;
              setAmortizationIssues([]);
              setAmortizationIssuesOpen(false);
              showResultModal(
                "success",
                jobSuccessCopy.merge.title,
                jobUserMessage(j) || jobSuccessCopy.merge.message,
                mergeLinks,
                {
                  dismissLabel: actionLabels.go_amortization_after_reconsolidate,
                },
              );
              return;
            }
            if (mergePartial) {
              showResultModal(
                "warning",
                jobWarningCopy.merge_partial.title,
                jobUserMessage(j) || jobWarningCopy.merge_partial.message,
                mergeLinks,
                { dismissLabel: "Entendido" },
              );
              return;
            }
            showSuccessWithOptionalCatalog({
              title: jobSuccessCopy.merge.title,
              message: jobUserMessage(j) || jobSuccessCopy.merge.message,
              links: mergeLinks,
              catalogTitle: "PDFs consolidados",
            });
            return;
          }
          if (jobType.includes("generate")) {
            const generateLinks = resolveLinksPreferDetail(
              reviewExcelLinksFromDetail(sync.data ?? {}),
              reviewExcelLinksFromResultSummary(j.result_summary),
            );
            showGenerateReviewOutcome(j, generateLinks, {
              regenerate: false,
              detail: sync.data,
            });
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
      const reviewLink = reviewExcelModalLink(detail);
      showResultModal(
        "error",
        "No se pudo finalizar",
        msg,
        reviewLink ? [reviewLink] : undefined,
      );
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
    const forceRebuild = recoveryFromAmortFormatRef.current && mergeCompleted;
    setMergeBusy(true);
    setConfirmMerge(false);
    showProcessingModal(
      forceRebuild ? busyLabels.reconsolidate_merge : busyLabels.merge,
    );
    try {
      const accepted = await postMerge(bank, detail.process_key, {
        forceRebuild,
      });
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
      startJobPoll(
        accepted.job_id,
        forceRebuild ? busyLabels.reconsolidate_merge : busyLabels.merge,
      );
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
    setAmortAfterReconsolidateHint(false);
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

  async function runCancelLote() {
    if (!detail) return;
    const bank = detail.bank_code as UiBankCode;
    if (bank !== "banco_bogota" && bank !== "banco_bancolombia") return;
    setCancelLoteBusy(true);
    setConfirmCancelLote(false);
    showProcessingModal(busyLabels.cancel_lote);
    try {
      const accepted = await postCancelLote(bank, detail.process_key);
      setJob({
        job_id: accepted.job_id,
        type: "cancel_active_process",
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
      startJobPoll(accepted.job_id, busyLabels.cancel_lote);
    } catch (e) {
      const msg = operatorErrorMessage(e, "No pudimos cancelar el proceso.").message;
      showResultModal("error", "No se pudo cancelar", msg);
    } finally {
      setCancelLoteBusy(false);
    }
  }

  async function runSoftClose() {
    if (!detail) return;
    const bank = detail.bank_code as UiBankCode;
    if (bank !== "banco_bogota" && bank !== "banco_bancolombia") return;
    setSoftCloseBusy(true);
    setConfirmSoftClose(false);
    showProcessingModal(busyLabels.soft_close);
    try {
      const accepted = await postSoftClose(bank, detail.process_key);
      setJob({
        job_id: accepted.job_id,
        type: "soft_close_process",
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
      startJobPoll(accepted.job_id, busyLabels.soft_close);
    } catch (e) {
      const msg = operatorErrorMessage(e, "No pudimos cerrar el proceso.").message;
      showResultModal("error", "No se pudo cerrar", msg);
    } finally {
      setSoftCloseBusy(false);
    }
  }

  if (error && !jobModal) {
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

  if (!detail || detail.process_key !== key) {
    return (
      <>
        <PageSkeleton rows={4} label="Cargando proceso…" />
        {jobModal ? <JobStatusModal view={jobModal} onDismiss={dismissJobModal} /> : null}
      </>
    );
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
  const cancelLoteAction = detail.available_actions?.cancel_lote;
  const cancelLoteAllowed = Boolean(cancelLoteAction?.allowed);
  const cancelLoteReason = cancelLoteAction?.reason;
  const softCloseAction = detail.available_actions?.soft_close;
  const softCloseAllowed = Boolean(softCloseAction?.allowed);
  const softCloseReason = softCloseAction?.reason;
  const reviewErroresIssues = detail.operational_issues.filter(isReviewErroresIssue);
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
    cancelLoteBusy ||
    softCloseBusy ||
    jobInFlight ||
    syncPending;

  const finalizeCompleted = detail.steps.some((s) => s.name === "finalize" && s.status === "completed");
  const notifyCompleted =
    detail.steps.some((s) => s.name === "notify" && s.status === "completed") ||
    (detail.control_estado_proceso || "").toUpperCase() === "PENDIENTE_ASIENTOS" ||
    isDurableNotifySuccessKey(
      detail.idempotency?.notify_idempotency_key,
      detail.process_key,
    ) ||
    (notifyReason || "").toLowerCase().includes("ya fue enviado");
  const mergeStep = detail.steps.find((s) => s.name === "merge");
  const readiness = detail.merge_readiness ?? null;
  const mergeCompleted =
    mergeStep?.status === "completed" ||
    (detail.control_estado_proceso || "").toUpperCase() === "CONSOLIDADO" ||
    Boolean(detail.idempotency?.merge_idempotency_key) ||
    readiness?.status === "already_merged" ||
    (mergeReason || "").toLowerCase().includes("ya fueron consolidados") ||
    (mergeReason || "").toLowerCase().includes("ya consolidado") ||
    (mergeReason || "").toLowerCase().includes("already_merged");
  // Badge alineado con readiness: ready → copy + tono ok (no ámbar de ESPERANDO_*).
  const statusBadgeStatus = resolveProcessBadgeStatus({
    operationalStatus: detail.operational_status,
    mergeReadinessStatus: readiness?.status,
  });
  const statusBadgeTitle =
    statusBadgeStatus === LISTO_PARA_CONSOLIDAR
      ? "Listo para consolidar"
      : detail.operational_title || operationalStatusLabel(detail.operational_status);
  const amortizationReadiness = detail.amortization_readiness ?? null;
  const amortizationCompleted =
    detail.operational_status === "COMPLETADO" ||
    (detail.control_estado_proceso || "").toUpperCase() === "AMORTIZACION_APLICADA" ||
    Boolean(detail.idempotency?.apply_idempotency_key) ||
    amortizationReadiness?.status === "already_applied" ||
    (amortizationReason || "").toLowerCase().includes("ya fue aplicada");
  const processFullyCompleted =
    amortizationCompleted ||
    detail.operational_status === "CERRADO_SIN_AMORTIZAR" ||
    detail.operational_status === "CANCELADO" ||
    (detail.control_estado_proceso || "").toUpperCase() === "CERRADO_SIN_AMORTIZAR";

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
          busy: finalizeBusy || jobInFlight || syncPending,
          busyLabel: jobInFlight ? processingTitleForJob(trackedJob) : busyLabels.finalize,
          disabled: !csrfReady || !finalizeAllowed || actionBusy,
          reason: csrfPreparing ? "Preparando sesión segura…" : finalizeReason,
        };
      case "notify":
        if (notifyCompleted) return null;
        return {
          label: actionLabels.notify,
          onClick: () => setConfirmNotify(true),
          busy: notifyBusy || jobInFlight || syncPending,
          busyLabel: jobInFlight ? processingTitleForJob(trackedJob) : busyLabels.notify,
          disabled: !csrfReady || !notifyAllowed || actionBusy,
          reason: csrfPreparing ? "Preparando sesión segura…" : notifyReason,
        };
      case "merge":
        if (mergeCompleted) {
          if (!recoveryFromAmortFormat) return null;
          const controlEstado = (detail?.control_estado_proceso || "").toUpperCase();
          if (controlEstado === "AMORTIZACION_PARCIAL") return null;
          return {
            label: actionLabels.reconsolidate_merge,
            onClick: () => setConfirmMerge(true),
            busy: mergeBusy || jobInFlight || syncPending,
            busyLabel: jobInFlight
              ? processingTitleForJob(trackedJob)
              : busyLabels.reconsolidate_merge,
            disabled: !csrfReady || actionBusy,
            reason: csrfPreparing
              ? "Preparando sesión segura…"
              : actionExplanations.reconsolidate_merge,
          };
        }
        return {
          label: actionLabels.merge,
          onClick: () => setConfirmMerge(true),
          busy: mergeBusy || jobInFlight || syncPending,
          busyLabel: jobInFlight ? processingTitleForJob(trackedJob) : busyLabels.merge,
          disabled: !csrfReady || !mergeAllowed || actionBusy,
          reason: csrfPreparing ? "Preparando sesión segura…" : mergeReason,
        };
      case "apply":
        if (amortizationCompleted) return null;
        return {
          label: actionLabels.amortization,
          onClick: () => setConfirmAmortization(true),
          busy: amortizationBusy || jobInFlight || syncPending,
          busyLabel: syncPending
            ? SYNC_RESULTS_MESSAGE
            : jobInFlight
              ? processingTitleForJob(trackedJob)
              : busyLabels.amortization,
          disabled: !csrfReady || !amortizationAllowed || actionBusy,
          reason: csrfPreparing ? "Preparando sesión segura…" : amortizationReason,
        };
      default:
        return null;
    }
  }

  function ctaForPhase(phaseId: OperatorPhaseId): PhaseCta | null {
    if (phaseId === "review") {
      // Con Errores / archivo faltante: Regenerar es el CTA primario (Finalize bloqueado en BE/UI).
      if (needsRegenerateFocus) {
        return {
          label: actionLabels.regenerate,
          onClick: () => setConfirmRegenerate(true),
          busy: regenerateBusy || jobInFlight || syncPending,
          busyLabel: jobInFlight ? processingTitleForJob(trackedJob) : busyLabels.regenerate,
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
      return primaryCtaFor("finalize");
    }
    if (phaseId === "notify") return primaryCtaFor("notify");
    if (phaseId === "merge") return primaryCtaFor("merge");
    if (phaseId === "amortization") return primaryCtaFor("apply");
    return null;
  }

  function phaseExtraInfo(
    phaseId: OperatorPhaseId,
    opts?: {
      showMergeVerify?: boolean;
      mergeRecovery?: boolean;
      recoveryFoldersFiltered?: boolean;
      recoveryVerifyItems?: readonly RecoveryVerifyItem[];
      onShowAllRecoveryFolders?: () => void;
    },
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
            Abra el Excel de destinatarios, guarde y cierre Excel Online. El resumen
            del envío se mostrará al confirmar.
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
      const controlEstado = (detail?.control_estado_proceso || "").toUpperCase();
      return (
        <>
          {opts?.mergeRecovery && controlEstado === "AMORTIZACION_PARCIAL" ? (
            <p className="meta" role="status">
              {actionExplanations.reconsolidate_partial_blocked}
            </p>
          ) : null}
          <MergeReadinessSummary
            readiness={readiness}
            showVerifyAction={Boolean(opts?.showMergeVerify)}
            recoveryMode={Boolean(opts?.mergeRecovery)}
            recoveryVerifyItems={opts?.recoveryVerifyItems}
            verifying={refreshing}
            onVerifySupports={() => void refreshAll()}
          />
          {opts?.recoveryFoldersFiltered ? (
            <div className="merge-verify-actions" style={{ marginTop: "0.5rem" }}>
              <button
                type="button"
                className="btn secondary btn-compact"
                onClick={opts.onShowAllRecoveryFolders}
              >
                Ver todas las carpetas
              </button>
            </div>
          ) : null}
        </>
      );
    }
    if (phaseId === "amortization") {
      return (
        <>
          {amortAfterReconsolidateHint ? (
            <p className="meta" role="status" style={{ marginTop: "0.35rem" }}>
              {actionExplanations.amortization_after_reconsolidate_hint}
            </p>
          ) : null}
          <AmortizationSummary readiness={amortizationReadiness} ibrLink={ibrUpdateLink} />
        </>
      );
    }
    return null;
  }

  const { phases: resolvedPhases, currentId: resolvedCurrentId } = resolveOperatorPhases(
    detail.steps,
  );
  // Con hoja Errores abierta o Excel ausente, el operador debe corregir/regenerar.
  const liveCurrentId: OperatorPhaseId = needsRegenerateFocus ? "review" : resolvedCurrentId;
  const phasesForStepper = buildPhaseStepperModel(resolvedPhases, needsRegenerateFocus);
  const selectedUnlocked =
    selectedPhaseId != null &&
    phasesForStepper.some((p) => p.def.id === selectedPhaseId && p.unlocked);
  // Tras Generate OK el Panel pasa `?phase=review` (fase unificada Revisión de archivo).
  // Con needsRegenerateFocus, Notify+ están locked: ?phase=notify no debe abrirse.
  const phaseQueryHint = parseOperatorPhaseHint(searchParams.get("phase"));
  const hintedUnlocked =
    phaseQueryHint != null &&
    phasesForStepper.some((p) => p.def.id === phaseQueryHint && p.unlocked);
  let viewingPhaseId: OperatorPhaseId = hintedUnlocked
    ? (phaseQueryHint as OperatorPhaseId)
    : selectedUnlocked
      ? (selectedPhaseId as OperatorPhaseId)
      : liveCurrentId;
  // Cinturón: nunca mostrar Notify+ mientras haga falta regenerar.
  if (needsRegenerateFocus && viewingPhaseId !== "review") {
    viewingPhaseId = "review";
  }
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
  const mergeSupportFromReadiness =
    readiness &&
    shouldShowMergeSupportErrors(readiness.status, mergeMissingItems, {
      supportsVerified: mergeSupportsVerified,
    })
      ? buildMergeSupportOperationalIssues(
          mergeMissingItems,
          readiness.folder_links ?? [],
        )
      : [];
  const mergeJobIssues = detail.operational_issues.filter(
    (issue) => (issue.stage || "").toLowerCase() === "merge",
  );
  const mergeSupportSeen = new Set(
    mergeSupportFromReadiness.map((issue) => {
      const credit = (issue.location?.credit || "").trim();
      const code = (issue.technical_reference || "").trim();
      return `${credit}|${code}`;
    }),
  );
  const mergeSupportIssues = [
    ...mergeSupportFromReadiness,
    ...mergeJobIssues.filter((issue) => {
      const credit = (issue.location?.credit || "").trim();
      const ref = (issue.technical_reference || "").trim();
      const fromRef = /(?:^|\|)code:([^|]+)/i.exec(ref);
      const code = (fromRef?.[1] || ref).trim();
      const key = `${credit}|${code}`;
      if (mergeSupportSeen.has(key)) return false;
      mergeSupportSeen.add(key);
      return true;
    }),
  ];
  const reviewOperationalIssues = detail.operational_issues.filter(
    (issue) => (issue.stage || "").toLowerCase() !== "merge",
  );
  const showMergeSupportBanner =
    viewingPhaseId === "merge" && mergeSupportIssues.length > 0;
  const amortizationDisplayIssues = resolveAmortizationDisplayIssues({
    last_amortization_attempt: detail.last_amortization_attempt,
    operational_issues: detail.operational_issues,
    ephemeralIssues: amortizationIssues,
  });
  const hasFormatRecoveryIssues = hasAmortFormatRecoveryIssues(
    amortizationDisplayIssues,
  );
  const mergeRecoveryActive =
    recoveryFromAmortFormat && viewingPhaseId === "merge";
  const recoveryFolderFilter =
    recoveryFromAmortFormat && amortizationDisplayIssues.length > 0
      ? filterFolderLinksForAmortRecovery(
          readiness?.folder_links ?? [],
          amortizationDisplayIssues,
        )
      : { filtered: readiness?.folder_links ?? [], hasFilter: false };
  const folderLinksForCatalog =
    recoveryFromAmortFormat &&
    recoveryFolderFilter.hasFilter &&
    !showAllRecoveryFolders
      ? recoveryFolderFilter.filtered
      : readiness?.folder_links ?? [];
  const recoveryVerifyItems =
    recoveryFromAmortFormat &&
    mergeSupportsVerified &&
    viewingPhaseId === "merge" &&
    amortizationDisplayIssues.length > 0
      ? buildRecoveryVerifyItems(amortizationDisplayIssues, folderLinksForCatalog)
      : [];
  const showAmortFormatGoMergeBanner =
    viewingPhaseId === "amortization" &&
    hasFormatRecoveryIssues &&
    !recoveryFromAmortFormat;
  const showAmortizationIssuesBanner =
    viewingPhaseId === "amortization" &&
    amortizationDisplayIssues.length > 0 &&
    !showAmortFormatGoMergeBanner;
  const asientosCatalogItems = showAsientosFolders
    ? buildAsientosCatalogItems(
        folderLinksForCatalog,
        mergeMissingItems,
        readiness?.status,
        { supportsVerified: mergeSupportsVerified },
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
  // Escape excepcional: Cancelar proceso se habilita por autoridad backend en
  // cualquier fase activa previa a Apply. Soft-close continúa separado en fase 4.
  const showCancelLoteEscape =
    cancelLoteAllowed && !processFullyCompleted;
  const showSoftCloseEscape =
    softCloseAllowed && viewingPhaseId === "amortization" && !processFullyCompleted;
  const showProcessEscapeFooter = showCancelLoteEscape || showSoftCloseEscape;
  // CTA solo en la fase viva: fases completadas consultables no re-ejecutan acciones.
  // Recuperación formato: CTA de reconsolidar en fase 3 aunque merge ya esté completed.
  // Mientras haya foco de corrección no se muestra Finalizar aunque se navegue a esa fase.
  const phaseCta =
    viewingPhase &&
    ((viewingLiveCurrent && !viewingCompletedPhase) || mergeRecoveryActive)
      ? ctaForPhase(viewingPhaseId)
      : null;
  const reviewExcelLink = detail.links.find((l) => l.rel === "review_excel" && l.web_url) ?? null;

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
      // Abrir carpetas fuerza GET fresco a SharePoint → cuenta como verificar.
      setMergeSupportsVerified(true);
    } catch (e) {
      const msg = operatorErrorMessage(e, "No pudimos actualizar el estado.").message;
      showResultModal("error", "No se pudo actualizar", msg);
    } finally {
      setCatalogDrawer((prev) =>
        prev?.kind === "asientos" ? { kind: "asientos", refreshing: false } : prev,
      );
    }
  }

  function renderPhaseDocCluster(
    links: readonly UiLink[],
    opts?: { prioritizeAsientos?: boolean; asientosCatalogLabel?: string },
  ) {
    const { inline, mergePdfs, asientosFolders, other } = partitionLinksForPhaseCard(links);
    const nodes: ReactNode[] = [];
    const prioritizeAsientos = Boolean(opts?.prioritizeAsientos);

    const pushAsientos = () => {
      if (asientosFolders.length < 1) return;
      const count = asientosFolders.length;
      const defaultLabel =
        count === 1 ? "Ver carpeta ASIENTOS" : `Ver carpetas ASIENTOS (${count})`;
      nodes.push(
        <button
          key="asientos-folders-catalog"
          type="button"
          className="btn secondary"
          onClick={() => void openAsientosCatalog()}
        >
          {opts?.asientosCatalogLabel || defaultLabel}
        </button>,
      );
    };

    const pushMergePdfs = () => {
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
    };

    for (const l of inline) {
      nodes.push(renderDocLink(l));
    }
    for (const l of other) {
      nodes.push(renderDocLink(l));
    }
    if (prioritizeAsientos) {
      // Recovery: solo carpetas ASIENTOS (el consolidado viejo confunde).
      pushAsientos();
    } else {
      pushMergePdfs();
      pushAsientos();
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
              ? detail.operational_status === "CANCELADO"
                ? "Proceso cancelado"
                : detail.operational_status === "CERRADO_SIN_AMORTIZAR"
                  ? "Proceso cerrado sin amortizar"
                  : "Proceso completado"
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
          <span className={`status-pill ${statusClass(statusBadgeStatus)}`}>
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
          ) : showMergeSupportBanner ? (
            <div
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
                Ver problemas de asientos contables
              </button>
            </div>
          ) : showAmortFormatGoMergeBanner ? (
            <div
              className="phase-operational-alert is-info"
              role="status"
              aria-labelledby="amortization-format-recovery-banner-title"
            >
              <p
                id="amortization-format-recovery-banner-title"
                className="phase-operational-alert-text"
              >
                {actionExplanations.amortization_format_go_merge_banner}
              </p>
              <button
                type="button"
                className="btn secondary btn-compact"
                onClick={() => setAmortizationIssuesOpen(true)}
              >
                {actionLabels.view_amortization_issues}
              </button>
              <button
                type="button"
                className="btn primary btn-compact"
                onClick={() => {
                  recoveryFromAmortFormatRef.current = true;
                  setRecoveryFromAmortFormat(true);
                  setSelectedPhaseId("merge");
                }}
              >
                {actionLabels.go_reconsolidate_short}
              </button>
            </div>
          ) : showAmortizationIssuesBanner ? (
            <div
              className="phase-operational-alert"
              role="alert"
              aria-labelledby="amortization-issues-banner-title"
            >
              <p
                id="amortization-issues-banner-title"
                className="phase-operational-alert-text"
              >
                {formatAmortizationIssuesBanner(amortizationDisplayIssues.length)}
              </p>
              <button
                type="button"
                className="btn secondary btn-compact"
                onClick={() => setAmortizationIssuesOpen(true)}
              >
                {actionLabels.view_amortization_issues}
              </button>
            </div>
          ) : reviewOperationalIssues.length > 0 ? (
            <div
              className="phase-operational-alert"
              role="alert"
              aria-labelledby="operational-issues-banner-title"
            >
              <p id="operational-issues-banner-title" className="phase-operational-alert-text">
                {reviewOperationalIssues.length} problema(s) operativo(s).
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
              {viewingCompletedPhase && !mergeRecoveryActive ? (
                <p className="meta" style={{ marginTop: "0.35rem" }}>
                  {actionExplanations.phase_completed_readonly}
                </p>
              ) : (
                phaseExtraInfo(viewingPhaseId, {
                  showMergeVerify:
                    (viewingLiveCurrent && !mergeCompleted) || mergeRecoveryActive,
                  mergeRecovery: mergeRecoveryActive,
                  recoveryFoldersFiltered:
                    recoveryFromAmortFormat &&
                    recoveryFolderFilter.hasFilter &&
                    !showAllRecoveryFolders,
                  recoveryVerifyItems,
                  onShowAllRecoveryFolders: () => setShowAllRecoveryFolders(true),
                })
              )}
              {phaseCta?.disabled &&
              phaseCta.reason &&
              !(
                viewingPhaseId === "merge" &&
                readiness &&
                (readiness.status === "incomplete" ||
                  readiness.status === "unknown" ||
                  // Evita duplicar el mismo texto que ya muestra MergeReadinessSummary.
                  Boolean(readiness.user_message) &&
                    readiness.user_message.trim() === phaseCta.reason.trim())
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
                  viewingPhaseId === "review" ? (
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
              ) : viewingCompletedPhase && !mergeRecoveryActive ? (
                <span className="status-pill readonly" role="status">
                  {actionExplanations.phase_readonly_badge}
                </span>
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
            {detail.operational_status === "CERRADO_SIN_AMORTIZAR"
              ? "Proceso cerrado sin amortizar"
              : detail.operational_status === "CANCELADO"
                ? "Proceso cancelado"
                : "Proceso completado"}
          </h2>
          <p className="meta">
            {detail.operational_status === "CERRADO_SIN_AMORTIZAR" ||
            detail.operational_status === "CANCELADO"
              ? detail.operational_message || actionExplanations.soft_close
              : actionExplanations.process_completed}
          </p>
        </section>
      ) : null}

      <OperationalIssuesModal
        open={operationalIssuesOpen && reviewOperationalIssues.length > 0}
        issues={reviewOperationalIssues}
        onClose={() => setOperationalIssuesOpen(false)}
        onRetryFor={retryHandlerFor}
        retryBusy={actionBusy}
      />

      <OperationalIssuesModal
        open={mergeSupportIssuesOpen && mergeSupportIssues.length > 0}
        title="Problemas de asientos contables"
        issues={mergeSupportIssues}
        onClose={() => setMergeSupportIssuesOpen(false)}
      />

      <OperationalIssuesModal
        open={amortizationIssuesOpen && amortizationDisplayIssues.length > 0}
        title={actionExplanations.amortization_issues_modal_title}
        issues={amortizationDisplayIssues}
        formatRecovery={hasFormatRecoveryIssues}
        onGoReconsolidate={
          hasFormatRecoveryIssues
            ? () => {
                recoveryFromAmortFormatRef.current = true;
                setRecoveryFromAmortFormat(true);
                setAmortizationIssuesOpen(false);
                setSelectedPhaseId("merge");
              }
            : undefined
        }
        onClose={() => setAmortizationIssuesOpen(false)}
        onRetryFor={retryHandlerFor}
        retryBusy={actionBusy}
      />

      {showPhaseDocuments ? (
        <section className="panel" id="process-documents">
          <h2 className="section-title">Recursos por fase</h2>
          <p className="meta" style={{ marginTop: 0 }}>
            Recursos de «{viewingPhase?.title ?? "esta fase"}».
          </p>
          {!selectedDocumentSection ? (
            <p className="muted">Aún no hay documentos disponibles para esta fase.</p>
          ) : (
            <div className="phase-docs-row" role="list">
              <div className="phase-docs-card" role="listitem">
                <h3 className="phase-docs-title">{selectedDocumentSection.phase.title}</h3>
                <div className="phase-docs-links">
                  {renderPhaseDocCluster(selectedDocumentSection.links, {
                    prioritizeAsientos: mergeRecoveryActive,
                    asientosCatalogLabel: mergeRecoveryActive
                      ? asientosCatalogItems.length === 1
                        ? "Ver carpeta ASIENTOS"
                        : asientosCatalogItems.length > 1
                          ? `Carpetas a corregir (${asientosCatalogItems.length})`
                          : undefined
                      : undefined,
                  })}
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

      {showProcessEscapeFooter ? (
        <div className="process-escape-footer" role="group" aria-label="Acciones de cierre del lote">
          {showCancelLoteEscape ? (
            <button
              type="button"
              className="process-escape-action"
              disabled={!csrfReady || actionBusy}
              aria-busy={cancelLoteBusy || undefined}
              title={!csrfReady ? "Preparando sesión segura…" : cancelLoteReason ?? undefined}
              onClick={() => setConfirmCancelLote(true)}
            >
              {cancelLoteBusy ? (
                <Spinner size="sm" />
              ) : (
                <svg
                  className="process-escape-icon"
                  viewBox="0 0 24 24"
                  width="16"
                  height="16"
                  aria-hidden="true"
                  focusable="false"
                >
                  {/* Cancelar: basura — abandonar el intento y limpiar reversibles */}
                  <path
                    fill="currentColor"
                    d="M9 3h6l1 2h4v2H4V5h4l1-2zm1 6h2v9h-2V9zm4 0h2v9h-2V9zM7 9h2v9H7V9zm-1 12h12a1 1 0 0 0 1-1V8H5v12a1 1 0 0 0 1 1z"
                  />
                </svg>
              )}
              <span>{cancelLoteBusy ? busyLabels.cancel_lote : actionLabels.cancel_lote}</span>
            </button>
          ) : null}
          {showSoftCloseEscape ? (
            <button
              type="button"
              className="process-escape-action"
              disabled={!csrfReady || actionBusy}
              aria-busy={softCloseBusy || undefined}
              title={!csrfReady ? "Preparando sesión segura…" : softCloseReason ?? undefined}
              onClick={() => setConfirmSoftClose(true)}
            >
              {softCloseBusy ? (
                <Spinner size="sm" />
              ) : (
                <svg
                  className="process-escape-icon"
                  viewBox="0 0 24 24"
                  width="16"
                  height="16"
                  aria-hidden="true"
                  focusable="false"
                >
                  {/* Cerrar sin amortizar: check en círculo — cierre intencional del lote */}
                  <path
                    fill="currentColor"
                    d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm-1.1 13.4-3.4-3.4 1.4-1.4 2 2 4.6-4.6 1.4 1.4-6 6z"
                  />
                </svg>
              )}
              <span>{softCloseBusy ? busyLabels.soft_close : actionLabels.soft_close}</span>
            </button>
          ) : null}
        </div>
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
                folderLinksForCatalog,
                mergeMissingItems,
                readiness?.status,
                { supportsVerified: mergeSupportsVerified },
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
                tone: mergeGroupsProgressTone(readiness.status),
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
          {notifyPreviewLoading ? (
            <p className="meta">Leyendo CORREOS.xlsx…</p>
          ) : notifyPreviewError ? (
            <p className="meta" role="status">
              {notifyPreviewError}
            </p>
          ) : notifyRecipientsPreview ? (
            <>
              <p className="meta" role="status">
                Emisor: {notifyRecipientsPreview.emisor || "—"}
              </p>
              <p className="meta" role="status">
                Destinatarios:{" "}
                {notifyRecipientsPreview.receptores.length > 0
                  ? notifyRecipientsPreview.receptores.join(", ")
                  : "ninguno"}
              </p>
              {notifyRecipientsPreview.file_last_modified ? (
                <p className="meta">
                  Última modificación:{" "}
                  {formatOperatorDateTime(notifyRecipientsPreview.file_last_modified)}
                </p>
              ) : null}
            </>
          ) : (
            <p className="meta">
              Destinatarios desde CORREOS.xlsx:{" "}
              {recipientsConfigured ? "listos" : "no disponibles"}
            </p>
          )}
          <div className="actions" style={{ marginTop: "0.5rem" }}>
            <button
              type="button"
              className="btn secondary"
              disabled={notifyPreviewLoading || notifyBusy}
              onClick={() => void loadNotifyRecipientsPreview()}
            >
              Actualizar lectura
            </button>
          </div>
        </ConfirmDialog>
      )}

      {confirmMerge && (
        <ConfirmDialog
          title={
            recoveryFromAmortFormat && mergeCompleted
              ? actionLabels.reconsolidate_merge
              : confirmTitles.merge
          }
          confirmLabel={
            recoveryFromAmortFormat && mergeCompleted
              ? actionLabels.reconsolidate_merge
              : "Generar PDF consolidado"
          }
          busyLabel={
            recoveryFromAmortFormat && mergeCompleted
              ? busyLabels.reconsolidate_merge
              : busyLabels.merge
          }
          busy={mergeBusy}
          onConfirm={() => void runMerge()}
          onCancel={() => setConfirmMerge(false)}
        >
          <p>
            {recoveryFromAmortFormat && mergeCompleted
              ? actionExplanations.reconsolidate_merge
              : actionExplanations.merge}
          </p>
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
          <IbrConfirmSummary
            preview={ibrPreview}
            loading={ibrPreviewLoading}
            error={ibrPreviewError}
            onRefresh={() => void loadIbrPreview()}
          />
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

      {confirmCancelLote && (
        <TypeConfirmDialog
          title={confirmTitles.cancel_lote}
          confirmLabel="Cancelar proceso"
          busyLabel={busyLabels.cancel_lote}
          busy={cancelLoteBusy}
          onConfirm={() => void runCancelLote()}
          onCancel={() => setConfirmCancelLote(false)}
        >
          <p>
            {notifyCompleted
              ? "El correo ya enviado se conservará como evidencia. Se cancelarán únicamente las fases posteriores y artefactos reversibles de este proceso."
              : mergeCompleted
                ? "El PDF consolidado identificado de este proceso se eliminará. No se borrarán extractos, soportes, historial ni tablas de amortización."
                : actionExplanations.cancel_lote}
          </p>
        </TypeConfirmDialog>
      )}

      {confirmSoftClose && (
        <TypeConfirmDialog
          title={confirmTitles.soft_close}
          confirmLabel="Confirmar cierre"
          busyLabel={busyLabels.soft_close}
          busy={softCloseBusy}
          onConfirm={() => void runSoftClose()}
          onCancel={() => setConfirmSoftClose(false)}
        >
          <p>{actionExplanations.soft_close}</p>
        </TypeConfirmDialog>
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
