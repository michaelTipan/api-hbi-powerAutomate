import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  fetchBanks,
  fetchBootstrap,
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
import { readDetailCache, writeDetailCache } from "../api/readCache";
import type {
  StepName,
  UiBootstrapResponse,
  UiJobView,
  UiLink,
  UiMergeReadiness,
  UiAmortizationReadiness,
  UiNotifyRecipientsPreview,
  UiOperationalIssue,
  UiProcessDetail,
} from "../types/contract";
import { resolveProcessBadgeStatus, LISTO_PARA_CONSOLIDAR } from "../domain/statusTone";
import { OperationalIssuesModal } from "../components/OperationalIssuesModal";
import {
  isActiveStatus,
  isTerminalUiJob,
  resolveDisplayedAttempt,
} from "../domain/resolveDisplayedAttempt";
import { resolveLocalJobWhenActiveAbsent } from "../domain/reconcileLocalJob";
import { LoadingButton } from "../components/LoadingButton";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { TypeConfirmDialog } from "../components/TypeConfirmDialog";
import { JobStatusModal, type JobStatusModalView } from "../components/JobStatusModal";
import { LinkCatalogDrawer, type CatalogDrawerLink } from "../components/LinkCatalogDrawer";
import { ProgressIndicator, type ProgressData } from "../components/ProgressIndicator";
import { PageSkeleton } from "../components/Skeleton";
import { ProcessPhaseStepper } from "../components/ProcessPhaseStepper";
import { Modal } from "../components/Modal";
import {
  amortizationTableLinksFromDetail,
  amortizationTableLinksFromResultSummary,
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
  buildSoftClosePhaseStepperModel,
  documentSectionForSelectedPhase,
  isProcessSoftClosed,
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
  clearGenerateIdentityFollow,
  isProcessNotFoundError,
  processKeyFromUiJob,
  readGenerateIdentityFollow,
  resolveActiveSuccessorKey,
  shouldResumeGenerateIdentityFollow,
  writeGenerateIdentityFollow,
} from "../domain/processIdentityContinuity";
import {
  isReviewErroresIssue,
  resolveGenerateReviewErrorCount,
} from "../domain/generateJobOutcome";
import {
  compactFinalizeFailureMessage,
  dedupeFailureIssuesAgainstMessage,
  finalizeErrorCodeFromJob,
  finalizeFailureModalTitle,
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
import { Button } from "@/components/ui/button";
import { StatusBadge } from "../components/StatusBadge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
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
  hydrateAmortizationIssueLinks,
  resolveAmortizationDisplayIssues,
} from "../domain/amortizationOperationalIssues";

const POLL_FAILURE_WARNING_THRESHOLD = 3;

const operationalAlertBase =
  "mb-4 flex flex-wrap items-center gap-2 rounded-lg border border-l-4 p-3 text-sm";
const operationalAlertDanger = cn(
  operationalAlertBase,
  "border-red-200 border-l-red-500 bg-red-50 text-red-950",
);
const operationalAlertInfo = cn(
  operationalAlertBase,
  "border-[#ffcd11]/40 border-l-[#ffcd11] bg-[#fff9e0] text-[#0e121b]",
);

function progressFromGenerateJob(
  job: Pick<UiJobView, "type" | "progress"> | null | undefined,
): ProgressData | null {
  const type = (job?.type || "").toLowerCase();
  if (!type.includes("generate")) return null;
  const raw = job?.progress;
  if (!raw || typeof raw !== "object") return null;
  const done = (raw as Record<string, unknown>).bank_rows_done;
  const total = (raw as Record<string, unknown>).bank_rows_total;
  if (typeof done !== "number" && typeof total !== "number") return null;
  if (typeof done !== "number" || done <= 0) return null;
  return {
    current: done,
    total: typeof total === "number" ? total : null,
  };
}

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

function shouldPinOperatorReviewPhase(detail: UiProcessDetail): boolean {
  const hasErrores = detail.operational_issues.some(isReviewErroresIssue);
  const fileMissing = detail.operational_issues.some(
    (issue) => issue.issue_id === "review-file-missing",
  );
  const finalizeDone = detail.steps.some(
    (s) => s.name === "finalize" && s.status === "completed",
  );
  // Pre-finalize: Errores o archivo faltante mantienen foco en Revisión.
  // Post-finalize OK: misma regla que Notify/Merge — la fase viva sigue los steps.
  return fileMissing || (hasErrores && !finalizeDone);
}

function AmortizationSummary({
  readiness,
}: {
  readiness: UiAmortizationReadiness | null;
}) {
  if (!readiness) {
    return (
      <div className="amort-readiness-panel">
        <p className="meta">Información de disponibilidad no cargada todavía.</p>
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
    </div>
  );
}

function NotifyRecipientsConfirmSummary({
  preview,
  loading,
  error,
  fileUrl,
  controlFolderUrl,
  recipientsConfigured,
  onRefresh,
}: {
  preview: UiNotifyRecipientsPreview | null;
  loading: boolean;
  error: string | null;
  fileUrl: string | null;
  controlFolderUrl: string | null;
  recipientsConfigured: boolean;
  onRefresh: () => void;
}) {
  const receptores = preview?.receptores ?? [];
  return (
    <>
      <p>
        Se enviará el correo de validación a los receptores definidos en CORREOS.xlsx
        (carpeta de control operativo).
      </p>
      {loading ? (
        <p className="meta">Leyendo CORREOS.xlsx…</p>
      ) : error ? (
        <>
          <p className="meta" role="status">
            {error}
          </p>
          <p className="meta">
            Restaure CORREOS.xlsx en SharePoint si fue eliminado y pulse Actualizar lectura.
            No se puede confirmar el envío sin leer destinatarios.
          </p>
        </>
      ) : preview ? (
        <>
          <p className="confirm-preview-summary" role="status">
            Emisor: {preview.emisor || "—"}
          </p>
          <p className="confirm-preview-status" role="status">
            Destinatarios: {receptores.length}
          </p>
          {receptores.length > 0 ? (
            <div className="confirm-preview-scroll">
              <ul role="list">
                {receptores.map((email) => (
                  <li key={email}>{email}</li>
                ))}
              </ul>
            </div>
          ) : (
            <p className="confirm-preview-status" role="status">
              No hay destinatarios en CORREOS.xlsx.
            </p>
          )}
          {preview.file_last_modified ? (
            <p className="confirm-preview-file-meta">
              Última modificación: {formatOperatorDateTime(preview.file_last_modified)}
            </p>
          ) : null}
        </>
      ) : (
        <p className="meta">
          Destinatarios desde CORREOS.xlsx:{" "}
          {recipientsConfigured ? "listos" : "no disponibles"}
        </p>
      )}
      <div className="actions confirm-preview-actions flex flex-wrap gap-2 pt-2">
        <Button type="button" variant="secondary" size="sm" disabled={loading} onClick={onRefresh}>
          Actualizar lectura
        </Button>
        {fileUrl ? (
          <Button variant="secondary" size="sm" asChild>
            <a href={fileUrl} target="_blank" rel="noreferrer">
              Abrir CORREOS.xlsx
            </a>
          </Button>
        ) : controlFolderUrl ? (
          <Button variant="secondary" size="sm" asChild>
            <a href={controlFolderUrl} target="_blank" rel="noreferrer">
              Abrir carpeta de control
            </a>
          </Button>
        ) : null}
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
  const [initialLoadDone, setInitialLoadDone] = useState(false);
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
  /** Evita bucles de redirect 404→activo→404. */
  const staleIdentityRedirectFromRef = useRef<string | null>(null);
  /** Throttle de /banks mientras Regenerar corre y la URL aún es la vieja. */
  const lastIdentityProbeAtRef = useRef(0);
  const identityFollowResumeRef = useRef(false);
  const liveCurrentIdRef = useRef<OperatorPhaseId | null>(null);
  const keyRef = useRef(key);
  keyRef.current = key;
  const jobRef = useRef<UiJobView | null>(null);
  jobRef.current = job;
  const { csrfReady, csrfPreparing } = useCsrfReady();

  const stopPoll = useCallback(() => {
    if (pollRef.current !== null) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const tryRedirectToActiveSuccessor = useCallback(
    async (staleKey: string): Promise<boolean> => {
      const stale = (staleKey || "").trim();
      if (!stale) return false;
      if (staleIdentityRedirectFromRef.current === stale) return false;
      try {
        const banks = await fetchBanks();
        const next = resolveActiveSuccessorKey({
          staleProcessKey: stale,
          banks,
        });
        if (!next || next === stale) return false;
        staleIdentityRedirectFromRef.current = stale;
        navigate(`/processes/${encodeURIComponent(next)}`, { replace: true });
        return true;
      } catch {
        return false;
      }
    },
    [navigate],
  );

  const load = useCallback(async () => {
    const requestedKey = key;
    const cached = readDetailCache(requestedKey);
    if (cached && keyRef.current === requestedKey) {
      setDetail(cached.detail);
      setError(null);
    }
    setRefreshing(true);
    const p = await fetchProcess(requestedKey);
    if (keyRef.current !== requestedKey) {
      setRefreshing(false);
      return p;
    }
    setDetail(p);
    setError(null);
    writeDetailCache(requestedKey, p);
    setRefreshing(false);
    // Conservar job local en vuelo (queued/running) aunque Control aún no
    // proyecte active_job: si no, actionBusy cae y el CTA se re-habilita.
    // Si active_job ya desapareció, reconsultar el job_id local en vuelo:
    // sin eso, un remount mid-Regenerar deja «Regenerando…» eterno (running
    // fantasma + progreso 11/11) cuando el backend ya marcó completed.
    const keepLocalJob = (prev: UiJobView | null) =>
      isTerminalUiJob(prev) || isActiveStatus(prev?.status) ? prev : null;
    const embedded = p.active_job_view;
    if (embedded?.job_id) {
      setJob((prev) => {
        if (
          prev &&
          isActiveStatus(prev.status) &&
          prev.job_id &&
          prev.job_id !== embedded.job_id
        ) {
          return prev;
        }
        return embedded;
      });
    } else if (p.active_job?.job_id) {
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
      const resolved = resolveLocalJobWhenActiveAbsent(jobRef.current);
      setJob(resolved.keep);
      if (resolved.refreshJobId) {
        const jobId = resolved.refreshJobId;
        try {
          const j = await fetchJob(jobId);
          if (keyRef.current !== requestedKey) {
            return p;
          }
          setJob((cur) => {
            if (!cur || cur.job_id !== jobId) return cur;
            return j;
          });
        } catch {
          // Error transitorio: mantener el in-flight hasta el próximo load.
        }
      }
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

  // Cierra modales de issues stale al entrar en vuelo / sync.
  useEffect(() => {
    const tracked = job ?? detail?.active_job;
    const st = (tracked?.status || "").toLowerCase();
    const inFlight = st === "queued" || st === "running";
    const syncing = pollWarning === SYNC_RESULTS_MESSAGE;
    if (!inFlight && !syncing) return;
    setOperationalIssuesOpen(false);
    setMergeSupportIssuesOpen(false);
    setAmortizationIssuesOpen(false);
    setReviewErroresIntroOpen(false);
  }, [job, detail?.active_job, pollWarning]);

  useEffect(() => {
    if (statusCardNote !== "Procesando…") return;
    const tracked = job ?? detail?.active_job;
    const st = (tracked?.status || "").toLowerCase();
    const inFlight = st === "queued" || st === "running";
    const syncing = pollWarning === SYNC_RESULTS_MESSAGE;
    if (inFlight || syncing) return;
    setStatusCardNote(null);
  }, [statusCardNote, job, detail?.active_job, pollWarning]);

  useEffect(() => {
    setSelectedPhaseId(null);
    liveCurrentIdRef.current = null;
    staleIdentityRedirectFromRef.current = null;
    identityFollowResumeRef.current = false;
    lastIdentityProbeAtRef.current = 0;
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

  useEffect(() => {
    if (confirmNotify) {
      void loadNotifyRecipientsPreview();
    }
  }, [confirmNotify, loadNotifyRecipientsPreview]);

  useEffect(() => {
    if (amortizationBusy) return;
    if (!detail?.last_amortization_attempt?.operational_issues?.length) return;
    const persisted = amortizationIssuesFromLastAttempt(detail);
    if (persisted.length > 0) {
      setAmortizationIssues(persisted);
    }
  }, [amortizationBusy, detail?.last_amortization_attempt, detail?.process_key]);

  useEffect(() => {
    if (!detail) return;
    const needsFocus = shouldPinOperatorReviewPhase(detail);
    const { currentId } = resolveOperatorPhases(detail.steps);
    const liveId: OperatorPhaseId = needsFocus ? "review" : currentId;
    if (liveCurrentIdRef.current !== liveId) {
      liveCurrentIdRef.current = liveId;
      setSelectedPhaseId(liveId);
    }
  }, [detail]);

  // Con Errores/archivo faltante pre-finalize, anular ?phase= que abriría Notify+ bloqueada.
  useEffect(() => {
    if (!detail) return;
    if (!shouldPinOperatorReviewPhase(detail)) return;
    const hint = parseOperatorPhaseHint(searchParams.get("phase"));
    if (hint == null || hint === "review") return;
    const next = new URLSearchParams(searchParams);
    next.delete("phase");
    setSearchParams(next, { replace: true });
  }, [detail, searchParams, setSearchParams]);

  useEffect(() => {
    setInitialLoadDone(false);
    const cached = readDetailCache(key);
    if (cached) {
      setDetail(cached.detail);
    }
  }, [key]);

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;

    const tick = async () => {
      try {
        const p = await load();
        if (cancelled) return;
        setInitialLoadDone(true);
        const running = ["queued", "running"].includes((p.active_job?.status || "").toLowerCase());
        const controlBusy = isOperationalStatusBusy(p.operational_status);
        if (running || controlBusy) {
          timer = window.setTimeout(tick, 4000);
        }
      } catch (e) {
        if (cancelled) return;
        if (isProcessNotFoundError(e)) {
          const redirected = await tryRedirectToActiveSuccessor(key);
          if (cancelled || redirected) return;
        }
        setError(operatorErrorMessage(e, "No pudimos cargar el proceso. Intente de nuevo.").message);
      }
    };

    void tick();
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
      stopPoll();
    };
  }, [load, stopPoll, key, tryRedirectToActiveSuccessor]);

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
          // Regenerar rota el UUID: actualizar la URL apenas Control/job
          // exponga la clave viva (no esperar al completed).
          if (regenerateNavigateRef.current) {
            const fromJob = processKeyFromUiJob(j);
            let successor =
              fromJob && fromJob !== keyRef.current ? fromJob : null;
            const now = Date.now();
            if (
              !successor &&
              now - lastIdentityProbeAtRef.current >= 5000
            ) {
              lastIdentityProbeAtRef.current = now;
              try {
                const banks = await fetchBanks();
                successor = resolveActiveSuccessorKey({
                  staleProcessKey: keyRef.current,
                  banks,
                });
              } catch {
                successor = null;
              }
            }
            if (successor && successor !== keyRef.current) {
              suppressReviewErroresIntroRef.current = true;
              navigate(`/processes/${encodeURIComponent(successor)}`, {
                replace: true,
              });
              return;
            }
          }
        }
        if (st === "completed" || st === "failed") {
          stopPoll();
          if (st === "failed") {
            regenerateNavigateRef.current = false;
            clearGenerateIdentityFollow();
            const failedJobType = (j.type || "").toLowerCase();
            const failedAmortizationJob =
              failedJobType.includes("amortization") ||
              failedJobType.includes("apply");
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
            if (failedAmortizationJob) {
              setAmortizationBusy(false);
            }
            const finalizeFailure = isFinalizeJob(j);
            const issuesRaw = finalizeFailure
              ? resolveFinalizeFailureIssues(j, syncedDetail)
              : [];
            const issues = dedupeFailureIssuesAgainstMessage(full, issuesRaw);
            const errorTitle = finalizeFailure
              ? finalizeFailureModalTitle(finalizeErrorCodeFromJob(j))
              : "No se pudo completar";
            if (
              finalizeFailure &&
              shouldCompactFinalizeJobModal(j, syncedDetail)
            ) {
              showResultModal(
                "error",
                errorTitle,
                compactFinalizeFailureMessage(issuesRaw.length),
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
              errorTitle,
              full,
              reviewLink ? [reviewLink] : undefined,
              issues.length > 0 ? { issues } : undefined,
            );
            return;
          }
          if (regenerateNavigateRef.current) {
            regenerateNavigateRef.current = false;
            clearGenerateIdentityFollow();
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
          clearGenerateIdentityFollow();
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

          // Outcome de negocio terminal: modal con issues del job; sync en segundo plano.
          if (isAmortizationJob && amortizationJobHasBusinessTerminalOutcome(j)) {
            showAmortizationBusinessOutcome(j);
            setAmortizationBusy(false);
            void load().catch(() => {
              /* best-effort */
            });
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
              setAmortizationBusy(false);
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
              links: resolveLinksPreferDetail(
                amortizationTableLinksFromDetail(sync.data),
                amortizationTableLinksFromResultSummary(j.result_summary),
              ),
              catalogTitle: "Tablas de amortización",
            });
            setAmortizationBusy(false);
            return;
          }
          if (jobType.includes("finalize")) {
            const finalizeLinks = resolveLinksPreferDetail(
              finalizeArtifactLinksFromDetail(sync.data ?? {}),
              finalizeArtifactLinksFromResultSummary(j.result_summary),
            );
            if (searchParams.has("phase")) {
              const next = new URLSearchParams(searchParams);
              next.delete("phase");
              setSearchParams(next, { replace: true });
            }
            liveCurrentIdRef.current = null;
            setSelectedPhaseId("notify");
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

  // Tras remount (URL nueva mid-Regenerar o Continuar en otra vista): reanudar
  // poll + flag de navegación si el follow de sesión coincide con el job activo.
  useEffect(() => {
    if (!initialLoadDone) return;
    if (identityFollowResumeRef.current) return;
    if (pollRef.current !== null) return;
    const follow = readGenerateIdentityFollow();
    const tracked = job ?? detail?.active_job;
    if (
      !shouldResumeGenerateIdentityFollow({
        follow,
        jobId: tracked?.job_id,
        jobType: tracked?.type,
        jobStatus: tracked?.status,
        bankCode: detail?.bank_code || follow?.bankCode,
      })
    ) {
      return;
    }
    const jobId = (tracked?.job_id || "").trim();
    if (!jobId) return;
    identityFollowResumeRef.current = true;
    regenerateNavigateRef.current = true;
    startJobPoll(jobId, busyLabels.regenerate);
    // startJobPoll es estable por cierre de render; solo re-evaluar al cambiar
    // identidad / job proyectado.
    // eslint-disable-next-line react-hooks/exhaustive-deps -- poller imperativo
  }, [detail?.active_job?.job_id, detail?.bank_code, job?.job_id, job?.status, key]);

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
    setAmortizationIssues([]);
    setAmortizationIssuesOpen(false);
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
      setAmortizationBusy(false);
      const msg = operatorErrorMessage(e, "No pudimos procesar la amortización.").message;
      showResultModal("error", "No se pudo procesar", msg);
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
      writeGenerateIdentityFollow({
        jobId: accepted.job_id,
        bankCode: bank,
        startedAt: Date.now(),
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
      clearGenerateIdentityFollow();
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
    clearGenerateIdentityFollow();
    regenerateNavigateRef.current = false;
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
    clearGenerateIdentityFollow();
    regenerateNavigateRef.current = false;
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
      <div className="process-detail space-y-4">
        <Link className="back-link text-sm font-medium text-[#0e121b] underline-offset-2 hover:underline" to="/">
          <span aria-hidden="true">&lt;</span> {actionLabels.back_to_dashboard}
        </Link>
        <Card className="border-red-200 bg-red-50">
          <CardContent className="p-5 text-sm text-red-900" role="alert">
            {error}
          </CardContent>
        </Card>
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
  const forceRebuildAction = detail.available_actions?.force_rebuild;
  const forceRebuildAllowed = Boolean(forceRebuildAction?.allowed);
  const forceRebuildReason = forceRebuildAction?.reason;
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
  // Foco/alerta fuerte solo por archivo faltante (bloquea Finalizar).
  // Con Errores visibles: aviso + Finalizar habilitado (waiver Validar=NO en BE).
  const needsRegenerateFocus = reviewFileMissing;
  const recipientsConfigured = Boolean(bootstrap?.notify_test_recipients_configured);
  const trackedJob = job ?? detail.active_job;
  const trackedJobStatus = (trackedJob?.status || "").toLowerCase();
  const jobInFlight = trackedJobStatus === "queued" || trackedJobStatus === "running";
  const syncPending = pollWarning === SYNC_RESULTS_MESSAGE;
  // Note huérfano tras «Seguir en segundo plano»: mantiene el modo ocupado visual.
  const processingNoteActive = statusCardNote === "Procesando…";
  // Evita veredictos stale (Errores / merge / amort) mientras el job recalcula
  // o mientras el POST aún no proyectó active_job (busy local).
  const suppressStaleOperationalAlerts =
    jobInFlight ||
    syncPending ||
    processingNoteActive ||
    regenerateBusy ||
    finalizeBusy ||
    notifyBusy ||
    mergeBusy ||
    amortizationBusy ||
    cancelLoteBusy ||
    softCloseBusy;
  // Progreso de filas solo mientras sigue el modo Procesando (job/sync/note).
  const showProcessingIndicator =
    jobInFlight || syncPending || processingNoteActive;
  const reviewRegenerateProgress =
    showProcessingIndicator ? progressFromGenerateJob(trackedJob) : null;
  // CTAs alineados con el indicador: no liberar mientras diga Procesando…
  const actionBusy =
    finalizeBusy ||
    notifyBusy ||
    mergeBusy ||
    amortizationBusy ||
    regenerateBusy ||
    cancelLoteBusy ||
    softCloseBusy ||
    jobInFlight ||
    syncPending ||
    processingNoteActive;

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
  const controlEstadoAmort = (detail.control_estado_proceso || "").toUpperCase();
  const applyStepPartial = detail.steps.some(
    (s) => s.name === "apply" && s.status === "partial",
  );
  const amortizationPartial =
    controlEstadoAmort === "AMORTIZACION_PARCIAL" ||
    detail.operational_status === "FINALIZADO_PARCIALMENTE" ||
    applyStepPartial;
  const amortizationCompleted =
    !amortizationPartial &&
    (detail.operational_status === "COMPLETADO" ||
      controlEstadoAmort === "AMORTIZACION_APLICADA" ||
      Boolean(detail.idempotency?.apply_idempotency_key) ||
      amortizationReadiness?.status === "already_applied" ||
      (amortizationReason || "").toLowerCase().includes("ya fue aplicada"));
  const processSoftClosed = isProcessSoftClosed(
    detail.operational_status,
    detail.control_estado_proceso,
  );
  const processFullyCompleted =
    amortizationCompleted || detail.operational_status === "CANCELADO";

  const amortizationDisplayIssues = hydrateAmortizationIssueLinks(
    resolveAmortizationDisplayIssues({
      last_amortization_attempt: detail.last_amortization_attempt,
      operational_issues: detail.operational_issues,
      ephemeralIssues: amortizationIssues,
    }),
    detail,
  );
  const hasFormatRecoveryIssues = hasAmortFormatRecoveryIssues(
    amortizationDisplayIssues,
  );

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
          busy: finalizeBusy || showProcessingIndicator,
          busyLabel: jobInFlight
            ? processingTitleForJob(trackedJob)
            : syncPending
              ? "Sincronizando resultados…"
              : busyLabels.finalize,
          disabled: !csrfReady || !finalizeAllowed || actionBusy,
          reason: csrfPreparing ? "Preparando sesión segura…" : finalizeReason,
        };
      case "notify":
        if (notifyCompleted) return null;
        return {
          label: actionLabels.notify,
          onClick: () => setConfirmNotify(true),
          busy: notifyBusy || showProcessingIndicator,
          busyLabel: jobInFlight
            ? processingTitleForJob(trackedJob)
            : syncPending
              ? "Sincronizando resultados…"
              : busyLabels.notify,
          disabled: !csrfReady || !notifyAllowed || actionBusy,
          reason: csrfPreparing ? "Preparando sesión segura…" : notifyReason,
        };
      case "merge":
        if (mergeCompleted) {
          if (!recoveryFromAmortFormat) return null;
          return {
            label: actionLabels.reconsolidate_merge,
            onClick: () => setConfirmMerge(true),
            busy: mergeBusy || showProcessingIndicator,
            busyLabel: jobInFlight
              ? processingTitleForJob(trackedJob)
              : syncPending
                ? "Sincronizando resultados…"
                : busyLabels.reconsolidate_merge,
            disabled: !csrfReady || !forceRebuildAllowed || actionBusy,
            reason: csrfPreparing
              ? "Preparando sesión segura…"
              : forceRebuildReason || actionExplanations.reconsolidate_merge,
          };
        }
        return {
          label: actionLabels.merge,
          onClick: () => setConfirmMerge(true),
          busy: mergeBusy || showProcessingIndicator,
          busyLabel: jobInFlight
            ? processingTitleForJob(trackedJob)
            : syncPending
              ? "Sincronizando resultados…"
              : busyLabels.merge,
          disabled: !csrfReady || !mergeAllowed || actionBusy,
          reason: csrfPreparing ? "Preparando sesión segura…" : mergeReason,
        };
      case "apply":
        if (amortizationCompleted) return null;
        return {
          label: actionLabels.amortization,
          onClick: () => setConfirmAmortization(true),
          busy: amortizationBusy || showProcessingIndicator,
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
      // Solo archivo faltante fuerza Regenerar como CTA primario (Finalize bloqueado).
      // Con Errores visibles: Finalizar es el primario; Regenerar queda como secundario.
      if (needsRegenerateFocus) {
        return {
          label: actionLabels.regenerate,
          onClick: () => setConfirmRegenerate(true),
          busy: regenerateBusy || showProcessingIndicator,
          busyLabel: jobInFlight
            ? processingTitleForJob(trackedJob)
            : syncPending
              ? "Sincronizando resultados…"
              : busyLabels.regenerate,
          disabled: !csrfReady || !regenerateAllowed || actionBusy,
          reason: csrfPreparing
            ? "Preparando sesión segura…"
            : regenerateReason || actionExplanations.review_file_missing_warning,
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
    if (phaseId === "review" && hasReviewErrores && !suppressStaleOperationalAlerts) {
      return (
        <p className="meta" style={{ marginTop: "0.35rem" }}>
          {actionExplanations.review_errores_warning}
        </p>
      );
    }
    if (phaseId === "review" && reviewFileMissing && !suppressStaleOperationalAlerts) {
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
            <Button variant="secondary" size="sm" className="btn secondary" asChild>
              <a href={correosReviewLink.web_url} target="_blank" rel="noreferrer">
                Revisar destinatarios
              </a>
            </Button>
          ) : null}
        </>
      );
    }
    if (phaseId === "merge") {
      const controlEstado = (detail?.control_estado_proceso || "").toUpperCase();
      return (
        <>
          {opts?.mergeRecovery &&
          controlEstado === "AMORTIZACION_PARCIAL" &&
          !hasFormatRecoveryIssues ? (
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
            <div className="merge-verify-actions mt-2">
              <Button
                type="button"
                variant="secondary"
                size="sm"
                onClick={opts.onShowAllRecoveryFolders}
              >
                Ver todas las carpetas
              </Button>
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
          <AmortizationSummary readiness={amortizationReadiness} />
        </>
      );
    }
    return null;
  }

  const { phases: resolvedPhases, currentId: resolvedCurrentId } = resolveOperatorPhases(
    detail.steps,
  );
  // Con Excel de revisión ausente, el operador debe regenerar antes de avanzar.
  const liveCurrentId: OperatorPhaseId = needsRegenerateFocus ? "review" : resolvedCurrentId;
  const phasesForStepper = processSoftClosed
    ? buildSoftClosePhaseStepperModel(resolvedPhases)
    : buildPhaseStepperModel(resolvedPhases, needsRegenerateFocus);
  const selectedUnlocked =
    selectedPhaseId != null &&
    phasesForStepper.some((p) => p.def.id === selectedPhaseId && p.unlocked);
  // Tras Generate OK el Panel pasa `?phase=review` (fase unificada Revisión de archivo).
  // Con needsRegenerateFocus, Notify+ están locked: ?phase=notify no debe abrirse.
  const phaseQueryHint = parseOperatorPhaseHint(searchParams.get("phase"));
  const hintedUnlocked =
    phaseQueryHint != null &&
    phasesForStepper.some((p) => p.def.id === phaseQueryHint && p.unlocked);
  // Preferir selección explícita (p. ej. tras Finalize OK) sobre ?phase= de Generate.
  let viewingPhaseId: OperatorPhaseId = selectedUnlocked
    ? (selectedPhaseId as OperatorPhaseId)
    : hintedUnlocked
      ? (phaseQueryHint as OperatorPhaseId)
      : liveCurrentId;
  // Cinturón: nunca mostrar Notify+ mientras haga falta regenerar.
  if (needsRegenerateFocus && viewingPhaseId !== "review") {
    viewingPhaseId = "review";
  }
  if (processSoftClosed && viewingPhaseId === "amortization") {
    viewingPhaseId =
      phasesForStepper.filter((p) => p.unlocked).at(-1)?.def.id ?? "merge";
  }
  const viewingPhase =
    resolvedPhases.find((p) => p.def.id === viewingPhaseId)?.def ??
    resolvedPhases.find((p) => p.def.id === liveCurrentId)?.def;
  const viewingResolved = resolvedPhases.find((p) => p.def.id === viewingPhaseId);
  const viewingCompletedPhase =
    processSoftClosed ||
    (viewingResolved?.visual === "completed" && viewingPhaseId !== liveCurrentId);
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
    !suppressStaleOperationalAlerts &&
    viewingPhaseId === "merge" &&
    mergeSupportIssues.length > 0;
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
    !suppressStaleOperationalAlerts &&
    viewingPhaseId === "amortization" &&
    hasFormatRecoveryIssues &&
    !recoveryFromAmortFormat;
  const showAmortizationIssuesBanner =
    !suppressStaleOperationalAlerts &&
    viewingPhaseId === "amortization" &&
    amortizationDisplayIssues.length > 0 &&
    !showAmortFormatGoMergeBanner;
  const showReviewErroresBanner =
    !suppressStaleOperationalAlerts && hasReviewErrores;
  const showReviewFileMissingBanner =
    !suppressStaleOperationalAlerts && reviewFileMissing && !hasReviewErrores;
  const showReviewOperationalIssuesBanner =
    !suppressStaleOperationalAlerts &&
    !showReviewErroresBanner &&
    !showMergeSupportBanner &&
    !showAmortFormatGoMergeBanner &&
    !showAmortizationIssuesBanner &&
    reviewOperationalIssues.length > 0;
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
  // Escape: Cancelar solo fases 1–3. En CONSOLIDADO+ (fase 4, incluso si el
  // operador abre merge para reconsolidar) solo Cerrar sin amortizar.
  const controlEstadoEscape = (detail.control_estado_proceso || "").toUpperCase();
  const inAmortizationEscapePhase = new Set([
    "CONSOLIDADO",
    "AMORTIZACION_PARCIAL",
    "ERROR_APPLY",
    "AMORTIZACION_APLICADA",
  ]).has(controlEstadoEscape);
  const showCancelLoteEscape =
    cancelLoteAllowed && !processFullyCompleted && !inAmortizationEscapePhase;
  const showSoftCloseEscape =
    softCloseAllowed && inAmortizationEscapePhase && !processFullyCompleted;
  const showProcessEscapeFooter = showCancelLoteEscape || showSoftCloseEscape;
  // CTA solo en la fase viva: fases completadas consultables no re-ejecutan acciones.
  // Recuperación formato: CTA de reconsolidar en fase 3 aunque merge ya esté completed.
  // Mientras haya foco de corrección no se muestra Finalizar aunque se navegue a esa fase.
  const phaseCta =
    viewingPhase &&
    !processSoftClosed &&
    ((viewingLiveCurrent && !viewingCompletedPhase) || mergeRecoveryActive)
      ? ctaForPhase(viewingPhaseId)
      : null;
  const reviewExcelLink = detail.links.find((l) => l.rel === "review_excel" && l.web_url) ?? null;

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
        <Button key={l.rel} variant="secondary" size="sm" asChild>
          <a href={l.web_url} target="_blank" rel="noreferrer">
            {label}
          </a>
        </Button>
      );
    }
    return (
      <Button
        key={l.rel}
        variant="secondary"
        size="sm"
        disabled
        title={l.path ?? undefined}
        aria-disabled="true"
      >
        {label} (no disponible)
      </Button>
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
        <Button
          key="asientos-folders-catalog"
          type="button"
          variant="secondary"
          size="sm"
          onClick={() => void openAsientosCatalog()}
        >
          {opts?.asientosCatalogLabel || defaultLabel}
        </Button>,
      );
    };

    const pushMergePdfs = () => {
      if (mergePdfs.length === 1) {
        nodes.push(renderDocLink(mergePdfs[0]));
      } else if (shouldOpenCatalogDrawer(mergePdfs.length)) {
        nodes.push(
          <Button
            key="merge-pdfs-catalog"
            type="button"
            variant="secondary"
            size="sm"
            onClick={() => openCatalog("PDFs consolidados", mergePdfs)}
          >
            {catalogSummaryLabel("PDFs consolidados", mergePdfs.length)}
          </Button>,
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
    <div className="process-detail space-y-4">
      <div className="process-detail-toolbar flex items-center justify-between gap-3">
        <Link className="back-link text-sm font-medium text-[#0e121b] underline-offset-2 hover:underline" to="/">
          <span aria-hidden="true">&lt;</span> {actionLabels.back_to_dashboard}
        </Link>
        <div className="flex items-center gap-3">
          {refreshing ? (
            <span className="text-sm text-zinc-500" role="status">Actualizando…</span>
          ) : null}
          <Button
            type="button"
            variant="outline"
            size="icon"
            className="icon-refresh shrink-0 rounded-full"
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
          </Button>
        </div>
      </div>

      <Card className="process-phase-header sticky top-0 z-20 overflow-hidden shadow-sm">
        <CardContent className="p-4">
          <ProcessPhaseStepper
          phases={phasesForStepper}
          currentTitle={
            processFullyCompleted
              ? detail.operational_status === "CANCELADO"
                ? "Proceso cancelado"
                : "Proceso completado"
              : processSoftClosed
                ? (viewingPhase?.title ?? "Proceso cerrado sin amortizar")
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
        </CardContent>
      </Card>

      <Card className="status-summary-card">
        <CardHeader className="pb-2">
          <CardTitle className="status-summary-title text-xl font-semibold">
            {detail.bank_name ?? detail.bank_code}
          </CardTitle>
          <p className="text-sm text-zinc-500">Fecha: {detail.process_date ?? "—"}</p>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="status-summary-badge-row flex flex-wrap items-center gap-2">
            <StatusBadge status={statusBadgeStatus}>{statusBadgeTitle}</StatusBadge>
          </div>
        {showProcessingIndicator ? (
          <div className="status-summary-processing-block">
            <p
              className="status-summary-desc status-summary-processing"
              role="status"
              aria-live="polite"
              aria-busy="true"
            >
              <Spinner size="sm" label={processingIndicatorLabel} />
              <span>{processingIndicatorLabel}</span>
            </p>
            {reviewRegenerateProgress ? (
              <ProgressIndicator progress={reviewRegenerateProgress} />
            ) : null}
          </div>
        ) : statusDescription ? (
          <p className="status-summary-desc">{statusDescription}</p>
        ) : null}
        {csrfPreparing ? (
          <p className="text-sm text-zinc-500" role="status">
            Preparando sesión segura…
          </p>
        ) : null}
        </CardContent>
      </Card>

      {showReviewFileMissingBanner ? (
        <Card className="border-amber-200 bg-amber-50" role="alert" aria-labelledby="review-missing-banner-title">
          <CardHeader className="pb-2">
            <CardTitle id="review-missing-banner-title" className="text-base text-amber-950">
              Falta el archivo de revisión
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm text-amber-900">
            <p className="m-0">{actionExplanations.review_file_missing_warning}</p>
            <p className="m-0">{actionExplanations.regenerate_use_phase_cta}</p>
          </CardContent>
        </Card>
      ) : null}

      {viewingPhase && (!processFullyCompleted || processSoftClosed) && (
        <Card className="current-phase-panel">
          <CardContent className="space-y-4 p-5">
          {showReviewErroresBanner ? (
            <div
              className={cn(operationalAlertDanger, "phase-operational-alert")}
              role="alert"
              aria-labelledby="review-errores-banner-title"
            >
              <p id="review-errores-banner-title" className="phase-operational-alert-text m-0 flex-1 font-medium">
                {reviewErroresIssues.length} caso(s) en la hoja Errores.
              </p>
              <Button
                type="button"
                variant="secondary"
                size="sm"
                className="btn secondary btn-compact"
                onClick={() => setOperationalIssuesOpen(true)}
              >
                Ver problemas operativos
              </Button>
            </div>
          ) : showMergeSupportBanner ? (
            <div
              className={cn(operationalAlertDanger, "phase-operational-alert")}
              role="alert"
              aria-labelledby="merge-support-errors-banner-title"
            >
              <p id="merge-support-errors-banner-title" className="phase-operational-alert-text m-0 flex-1 font-medium">
                {mergeSupportIssues.length} problema(s) con los documentos contables.
              </p>
              <Button
                type="button"
                variant="secondary"
                size="sm"
                className="btn secondary btn-compact"
                onClick={() => setMergeSupportIssuesOpen(true)}
              >
                Ver problemas de asientos contables
              </Button>
            </div>
          ) : showAmortFormatGoMergeBanner ? (
            <div
              className={cn(operationalAlertInfo, "phase-operational-alert is-info")}
              role="status"
              aria-labelledby="amortization-format-recovery-banner-title"
            >
              <p
                id="amortization-format-recovery-banner-title"
                className="phase-operational-alert-text m-0 flex-1 font-medium"
              >
                {actionExplanations.amortization_format_go_merge_banner}
              </p>
              <Button
                type="button"
                variant="secondary"
                size="sm"
                className="btn secondary btn-compact"
                onClick={() => setAmortizationIssuesOpen(true)}
              >
                {actionLabels.view_amortization_issues}
              </Button>
              <Button
                type="button"
                size="sm"
                className="btn primary btn-compact primary"
                onClick={() => {
                  recoveryFromAmortFormatRef.current = true;
                  setRecoveryFromAmortFormat(true);
                  setSelectedPhaseId("merge");
                }}
              >
                {actionLabels.go_reconsolidate_short}
              </Button>
            </div>
          ) : showAmortizationIssuesBanner ? (
            <div
              className={cn(operationalAlertDanger, "phase-operational-alert")}
              role="alert"
              aria-labelledby="amortization-issues-banner-title"
            >
              <p
                id="amortization-issues-banner-title"
                className="phase-operational-alert-text m-0 flex-1 font-medium"
              >
                {formatAmortizationIssuesBanner(amortizationDisplayIssues.length)}
              </p>
              <Button
                type="button"
                variant="secondary"
                size="sm"
                className="btn secondary btn-compact"
                onClick={() => setAmortizationIssuesOpen(true)}
              >
                {actionLabels.view_amortization_issues}
              </Button>
            </div>
          ) : showReviewOperationalIssuesBanner ? (
            <div
              className={cn(operationalAlertDanger, "phase-operational-alert")}
              role="alert"
              aria-labelledby="operational-issues-banner-title"
            >
              <p id="operational-issues-banner-title" className="phase-operational-alert-text m-0 flex-1 font-medium">
                {reviewOperationalIssues.length} problema(s) operativo(s).
              </p>
              <Button
                type="button"
                variant="secondary"
                size="sm"
                className="btn secondary btn-compact"
                onClick={() => setOperationalIssuesOpen(true)}
              >
                Ver problemas operativos
              </Button>
            </div>
          ) : null}
          <div className="phase-split">
            <div className="phase-split-main space-y-2">
              <h2 id="current-phase-title" className="section-title text-lg font-semibold text-zinc-900">
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
                <div className="phase-split-action-stack w-full max-w-xs">
                  <LoadingButton
                    className="w-full"
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
                      className="w-full"
                      variant="secondary"
                      busy={regenerateBusy || showProcessingIndicator}
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
          </CardContent>
        </Card>
      )}

      {processSoftClosed ? (
        <Card aria-labelledby="process-soft-closed-title">
          <CardHeader>
            <CardTitle id="process-soft-closed-title" className="text-base">
              Proceso cerrado sin amortizar
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-zinc-600 m-0">
              {detail.operational_message || actionExplanations.soft_close}
            </p>
          </CardContent>
        </Card>
      ) : processFullyCompleted ? (
        <Card aria-labelledby="process-completed-title">
          <CardHeader>
            <CardTitle id="process-completed-title" className="text-base">
              {detail.operational_status === "CANCELADO"
                ? "Proceso cancelado"
                : "Proceso completado"}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-zinc-600 m-0">
              {detail.operational_status === "CANCELADO"
                ? detail.operational_message || actionExplanations.soft_close
                : actionExplanations.process_completed}
            </p>
          </CardContent>
        </Card>
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
        <Card id="process-documents">
          <CardHeader>
            <CardTitle className="text-base">Recursos por fase</CardTitle>
            <p className="text-sm text-zinc-500 m-0">
              Recursos de «{viewingPhase?.title ?? "esta fase"}».
            </p>
          </CardHeader>
          <CardContent>
          {!selectedDocumentSection ? (
            <p className="text-sm text-zinc-500">Aún no hay documentos disponibles para esta fase.</p>
          ) : (
            <div className="phase-docs-row" role="list">
              <div className="phase-docs-card rounded-lg border border-zinc-200 bg-zinc-50 p-4" role="listitem">
                <h3 className="phase-docs-title text-sm font-semibold text-zinc-900">{selectedDocumentSection.phase.title}</h3>
                <div className="phase-docs-links mt-3 flex flex-wrap gap-2">
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
          </CardContent>
        </Card>
      ) : null}

      {showProcessFiles ? (
        <Card id="process-file-catalog" aria-labelledby="process-file-catalog-title">
          <CardHeader>
            <CardTitle id="process-file-catalog-title" className="text-base">
              Archivos del proceso
            </CardTitle>
            <p className="text-sm text-zinc-500 m-0">
              Documentos del lote (revisión, correo), PDF consolidado y tablas de amortización.
              Las fases anteriores siguen disponibles en el encabezado.
            </p>
          </CardHeader>
          <CardContent>
          <div className="process-file-catalog-actions flex flex-wrap gap-2">
            {processDocumentGroups.map((group) => {
              const title = catalogGroupTitle(group);
              const groupLinks = group.links ?? [];
              if (groupLinks.length === 1) {
                return renderDocLink(groupLinks[0]);
              }
              return (
                <Button
                  key={group.id}
                  type="button"
                  variant="secondary"
                  size="sm"
                  onClick={() => openCatalog(title, groupLinks)}
                >
                  {catalogSummaryLabel(title, group.count || groupLinks.length)}
                </Button>
              );
            })}
          </div>
          </CardContent>
        </Card>
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
          {hasReviewErrores ? (
            <p className="meta">{actionExplanations.finalize_with_review_errores_warning}</p>
          ) : null}
        </ConfirmDialog>
      )}

      {confirmNotify && (
        <ConfirmDialog
          title={confirmTitles.notify}
          confirmLabel="Confirmar envío"
          busyLabel={busyLabels.notify}
          busy={notifyBusy}
          confirmDisabled={
            notifyPreviewLoading ||
            Boolean(notifyPreviewError) ||
            !notifyRecipientsPreview ||
            (notifyRecipientsPreview.receptores?.length ?? 0) === 0
          }
          confirmDisabledTitle={
            notifyPreviewLoading
              ? "Espere a que termine la lectura de CORREOS.xlsx"
              : notifyPreviewError
                ? "No se pudo leer CORREOS.xlsx"
                : "No hay destinatarios para enviar"
          }
          onConfirm={() => void runNotify()}
          onCancel={() => setConfirmNotify(false)}
        >
          <NotifyRecipientsConfirmSummary
            preview={notifyRecipientsPreview}
            loading={notifyPreviewLoading}
            error={notifyPreviewError}
            fileUrl={
              detail.links.find((l) => l.rel === "correos" && l.web_url)?.web_url ?? null
            }
            controlFolderUrl={
              detail.links.find((l) => l.rel === "control" && l.web_url)?.web_url ?? null
            }
            recipientsConfigured={recipientsConfigured}
            onRefresh={() => void loadNotifyRecipientsPreview()}
          />
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
          confirmDisabled={recoveryFromAmortFormat && mergeCompleted && !forceRebuildAllowed}
          confirmDisabledTitle={forceRebuildReason ?? undefined}
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
            {amortizationPartial
              ? actionExplanations.amortization_partial_retry
              : "Si hay datos por corregir, no se realizarán escrituras en las tablas."}
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
          <div className="modal-actions flex flex-wrap justify-end gap-2 pt-4">
            <Button
              type="button"
              variant="secondary"
              onClick={() => setReviewErroresIntroOpen(false)}
            >
              Entendido
            </Button>
            {reviewExcelLink?.web_url ? (
              <Button variant="default" className="primary" asChild>
                <a
                  href={reviewExcelLink.web_url}
                  target="_blank"
                  rel="noreferrer"
                  onClick={() => setReviewErroresIntroOpen(false)}
                >
                  Abrir archivo de revisión
                </a>
              </Button>
            ) : null}
          </div>
        </Modal>
      )}

      {jobModal ? <JobStatusModal view={jobModal} onDismiss={dismissJobModal} /> : null}
    </div>
  );
}
