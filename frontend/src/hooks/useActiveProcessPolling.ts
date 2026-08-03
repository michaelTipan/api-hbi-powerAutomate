import { useEffect, useRef } from "react";
import { fetchJob } from "../api/client";
import { useProcessBusy } from "../context/ProcessBusyContext";
import {
  formatJobAmounts,
  isJobRunningStatus,
  jobFailureMessage,
  progressLabelForDetail,
  successMessageFromJob,
} from "../lib/progressLabels";
import type { UiJobView, UiProcessDetail } from "../types/contract";

/** Sincroniza el overlay global con jobs activos del proceso. */
export function useActiveProcessPolling(
  detail: UiProcessDetail | null,
  onRefresh?: () => void,
) {
  const busy = useProcessBusy();
  const jobRef = useRef<UiJobView | null>(null);
  const beganRef = useRef(false);

  useEffect(() => {
    const job = detail?.active_job;
    const running = Boolean(job && isJobRunningStatus(job.status));
    if (running && !beganRef.current) {
      beganRef.current = true;
      busy.adoptBusy({
        phase: "generic",
        label: progressLabelForDetail(detail),
        detail: detail?.bank_name ?? detail?.bank_code ?? null,
        processKey: detail?.process_key ?? null,
        jobId: job?.job_id ?? null,
      });
    }
    if (!running) {
      beganRef.current = false;
    }
  }, [detail?.active_job?.job_id, detail?.active_job?.status]);

  useEffect(() => {
    const jobId = detail?.active_job?.job_id;
    if (!jobId || !isJobRunningStatus(detail?.active_job?.status)) {
      return;
    }

    let cancelled = false;
    let timer: number | undefined;

    const poll = async () => {
      try {
        const j = await fetchJob(jobId);
        if (cancelled) return;
        jobRef.current = j;
        const amounts = formatJobAmounts(j);
        busy.updateProgress(
          progressLabelForDetail(detail),
          amounts ?? detail?.bank_name ?? null,
        );
        if (isJobRunningStatus(j.status)) {
          timer = window.setTimeout(() => void poll(), 3500);
          return;
        }
        beganRef.current = false;
        if (j.status === "completed") {
          busy.finishSuccess(successMessageFromJob(j) ?? "Operación completada.");
          onRefresh?.();
          return;
        }
        if (j.status === "failed") {
          busy.finishError(jobFailureMessage(j));
          onRefresh?.();
        }
      } catch {
        if (!cancelled) {
          timer = window.setTimeout(() => void poll(), 5000);
        }
      }
    };

    void poll();
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [detail?.active_job?.job_id, detail?.active_job?.status, onRefresh]);
}
