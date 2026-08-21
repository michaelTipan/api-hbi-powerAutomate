/**
 * Continuidad de identidad tras Regenerar: el job cancela el lote y crea un
 * process_key nuevo. La URL vieja deja de resolver; el Panel /banks sí conoce
 * el proceso vivo del mismo banco.
 */
import { UiApiError } from "../api/errors";

export const GENERATE_IDENTITY_FOLLOW_STORAGE_KEY = "hbi.ui.generateIdentityFollow";

export type GenerateIdentityFollow = {
  jobId: string;
  bankCode: string;
  /** Epoch ms; se ignora si es demasiado antiguo. */
  startedAt: number;
};

const FOLLOW_MAX_AGE_MS = 2 * 60 * 60 * 1000;

/** Extrae banco de `payment-validation|banco_*|YYYY-MM-DD|uuid`. */
export function bankCodeFromProcessKey(processKey: string): string | null {
  const parts = (processKey || "").trim().split("|");
  if (parts.length < 4) return null;
  if (parts[0] !== "payment-validation") return null;
  const bank = (parts[1] || "").trim().toLowerCase();
  if (bank !== "banco_bogota" && bank !== "banco_bancolombia") return null;
  return bank;
}

export function processKeyFromUiJob(job: {
  process_key?: string | null;
  result_summary?: unknown;
}): string | null {
  const fromJob = (job.process_key || "").trim();
  if (fromJob) return fromJob;
  const summary = job.result_summary;
  if (summary && typeof summary === "object") {
    const raw = (summary as { process_key?: unknown }).process_key;
    if (typeof raw === "string" && raw.trim()) return raw.trim();
  }
  return null;
}

export function isProcessNotFoundError(error: unknown): boolean {
  if (error instanceof UiApiError) {
    return error.status === 404 && error.errorCode === "process_not_found";
  }
  if (error instanceof Error) {
    return /No se encontró el proceso solicitado/i.test(error.message || "");
  }
  return false;
}

type BankActiveHint = {
  bank_code: string;
  active_process_key?: string | null;
};

/**
 * Si la URL apunta a un process_key muerto pero el banco sigue con proceso
 * activo distinto, devolver esa clave viva (p. ej. tras Regenerar).
 */
export function resolveActiveSuccessorKey(opts: {
  staleProcessKey: string;
  banks: readonly BankActiveHint[];
}): string | null {
  const stale = (opts.staleProcessKey || "").trim();
  if (!stale) return null;
  const bank = bankCodeFromProcessKey(stale);
  if (!bank) return null;
  const hit = opts.banks.find(
    (b) => (b.bank_code || "").trim().toLowerCase() === bank,
  );
  const live = (hit?.active_process_key || "").trim();
  if (!live || live === stale) return null;
  return live;
}

function canUseSessionStorage(): boolean {
  try {
    return typeof sessionStorage !== "undefined";
  } catch {
    return false;
  }
}

export function writeGenerateIdentityFollow(
  follow: GenerateIdentityFollow,
): void {
  if (!canUseSessionStorage()) return;
  try {
    sessionStorage.setItem(
      GENERATE_IDENTITY_FOLLOW_STORAGE_KEY,
      JSON.stringify(follow),
    );
  } catch {
    /* private mode / quota */
  }
}

export function readGenerateIdentityFollow(): GenerateIdentityFollow | null {
  if (!canUseSessionStorage()) return null;
  try {
    const raw = sessionStorage.getItem(GENERATE_IDENTITY_FOLLOW_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<GenerateIdentityFollow>;
    const jobId = typeof parsed.jobId === "string" ? parsed.jobId.trim() : "";
    const bankCode =
      typeof parsed.bankCode === "string"
        ? parsed.bankCode.trim().toLowerCase()
        : "";
    const startedAt =
      typeof parsed.startedAt === "number" ? parsed.startedAt : 0;
    if (!jobId || !bankCode || !startedAt) return null;
    if (Date.now() - startedAt > FOLLOW_MAX_AGE_MS) {
      clearGenerateIdentityFollow();
      return null;
    }
    return { jobId, bankCode, startedAt };
  } catch {
    return null;
  }
}

export function clearGenerateIdentityFollow(): void {
  if (!canUseSessionStorage()) return;
  try {
    sessionStorage.removeItem(GENERATE_IDENTITY_FOLLOW_STORAGE_KEY);
  } catch {
    /* ignore */
  }
}

/** ¿Este job activo es el Regenerar que estamos siguiendo? */
export function shouldResumeGenerateIdentityFollow(opts: {
  follow: GenerateIdentityFollow | null;
  jobId: string | null | undefined;
  jobType: string | null | undefined;
  jobStatus: string | null | undefined;
  bankCode: string | null | undefined;
}): boolean {
  const follow = opts.follow;
  if (!follow) return false;
  const jobId = (opts.jobId || "").trim();
  if (!jobId || jobId !== follow.jobId) return false;
  const bank = (opts.bankCode || "").trim().toLowerCase();
  if (bank && bank !== follow.bankCode) return false;
  const st = (opts.jobStatus || "").toLowerCase();
  if (st !== "queued" && st !== "running") return false;
  const type = (opts.jobType || "").toLowerCase();
  // Generate/regenerate; si el tipo aún no llegó, confiar en el follow.
  if (type && !type.includes("generate")) return false;
  return true;
}
