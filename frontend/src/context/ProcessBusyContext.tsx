import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";

export type BusyPhase =
  | "idle"
  | "generate"
  | "finalize"
  | "notify"
  | "merge"
  | "dry_run"
  | "apply"
  | "upload"
  | "control"
  | "generic";

export interface ProcessBusyState {
  busy: boolean;
  phase: BusyPhase;
  label: string;
  detail: string | null;
  processKey: string | null;
  jobId: string | null;
  success: string | null;
  blockedMessage: string | null;
  lastError: string | null;
}

interface ProcessBusyContextValue extends ProcessBusyState {
  adoptBusy: (opts: {
    phase: BusyPhase;
    label: string;
    detail?: string | null;
    processKey?: string | null;
    jobId?: string | null;
  }) => void;
  tryBegin: (opts: {
    phase: BusyPhase;
    label: string;
    detail?: string | null;
    processKey?: string | null;
    jobId?: string | null;
  }) => boolean;
  updateProgress: (label: string, detail?: string | null) => void;
  finishSuccess: (message: string) => void;
  finishError: (message?: string | null) => void;
  clearSuccess: () => void;
  clearBlocked: () => void;
  clearLastError: () => void;
  reset: () => void;
}

const INITIAL: ProcessBusyState = {
  busy: false,
  phase: "idle",
  label: "",
  detail: null,
  processKey: null,
  jobId: null,
  success: null,
  blockedMessage: null,
  lastError: null,
};

const ProcessBusyContext = createContext<ProcessBusyContextValue | null>(null);

export function ProcessBusyProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<ProcessBusyState>(INITIAL);

  const adoptBusy = useCallback<
    ProcessBusyContextValue["adoptBusy"]
  >((opts) => {
    setState((prev) => ({
      ...prev,
      busy: true,
      phase: opts.phase,
      label: opts.label,
      detail: opts.detail ?? null,
      processKey: opts.processKey ?? prev.processKey,
      jobId: opts.jobId ?? prev.jobId,
      success: null,
      blockedMessage: null,
      lastError: null,
    }));
  }, []);

  const tryBegin = useCallback<
    ProcessBusyContextValue["tryBegin"]
  >((opts) => {
    let allowed = false;
    setState((prev) => {
      if (prev.busy) {
        return {
          ...prev,
          blockedMessage: "Ya hay un proceso en curso. Espere a que termine.",
        };
      }
      allowed = true;
      return {
        busy: true,
        phase: opts.phase,
        label: opts.label,
        detail: opts.detail ?? null,
        processKey: opts.processKey ?? null,
        jobId: opts.jobId ?? null,
        success: null,
        blockedMessage: null,
        lastError: null,
      };
    });
    return allowed;
  }, []);

  const updateProgress = useCallback((label: string, detail?: string | null) => {
    setState((prev) =>
      prev.busy
        ? { ...prev, label, detail: detail ?? prev.detail }
        : prev,
    );
  }, []);

  const finishSuccess = useCallback((message: string) => {
    setState((prev) => ({
      ...INITIAL,
      success: message,
      processKey: prev.processKey,
    }));
  }, []);

  const finishError = useCallback((message?: string | null) => {
    setState((prev) => ({
      ...INITIAL,
      processKey: prev.processKey,
      lastError:
        message?.trim() ||
        "La operación falló. Revise los errores e intente de nuevo.",
    }));
  }, []);

  const clearSuccess = useCallback(() => {
    setState((prev) => ({ ...prev, success: null }));
  }, []);

  const clearBlocked = useCallback(() => {
    setState((prev) => ({ ...prev, blockedMessage: null }));
  }, []);

  const clearLastError = useCallback(() => {
    setState((prev) => ({ ...prev, lastError: null }));
  }, []);

  const reset = useCallback(() => {
    setState(INITIAL);
  }, []);

  const value = useMemo(
    () => ({
      ...state,
      adoptBusy,
      tryBegin,
      updateProgress,
      finishSuccess,
      finishError,
      clearSuccess,
      clearBlocked,
      clearLastError,
      reset,
    }),
    [
      state,
      adoptBusy,
      tryBegin,
      updateProgress,
      finishSuccess,
      finishError,
      clearSuccess,
      clearBlocked,
      clearLastError,
      reset,
    ],
  );

  return (
    <ProcessBusyContext.Provider value={value}>{children}</ProcessBusyContext.Provider>
  );
}

export function useProcessBusy(): ProcessBusyContextValue {
  const ctx = useContext(ProcessBusyContext);
  if (!ctx) {
    throw new Error("useProcessBusy debe usarse dentro de ProcessBusyProvider");
  }
  return ctx;
}
