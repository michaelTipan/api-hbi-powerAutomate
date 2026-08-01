/**
 * Gestor centralizado de CSRF (solo memoria de proceso).
 * Nunca persiste en localStorage/sessionStorage ni registra el valor del token.
 */

export const CSRF_HEADER_NAME = "X-CSRF-Token";

let csrfTokenMemory: string | null = null;
let localSessionMode = false;
let refreshInFlight: Promise<string> | null = null;

type Listener = () => void;
const readyListeners = new Set<Listener>();
const sessionExpiredListeners = new Set<Listener>();

function notifyReady(): void {
  for (const listener of readyListeners) {
    listener();
  }
}

export function isLocalSessionMode(): boolean {
  return localSessionMode;
}

/** Activa/desactiva el gate CSRF de sesión por cookie. */
export function setLocalSessionMode(active: boolean): void {
  localSessionMode = active;
  if (!active) {
    csrfTokenMemory = null;
    refreshInFlight = null;
  }
  notifyReady();
}

export function getCsrfTokenMemory(): string | null {
  return csrfTokenMemory;
}

export function clearCsrfTokenMemory(): void {
  csrfTokenMemory = null;
  refreshInFlight = null;
  notifyReady();
}

export function setCsrfTokenMemory(token: string): void {
  const trimmed = token.trim();
  if (!trimmed) {
    throw new Error("Token CSRF vacío rechazado.");
  }
  csrfTokenMemory = trimmed;
  notifyReady();
}

/**
 * Sin modo local_session el gate no aplica (mocks / bearer).
 * Con local_session hace falta un token no vacío en memoria.
 */
export function isCsrfReady(): boolean {
  if (!localSessionMode) return true;
  return Boolean(csrfTokenMemory && csrfTokenMemory.trim());
}

export function subscribeCsrfReady(listener: Listener): () => void {
  readyListeners.add(listener);
  return () => {
    readyListeners.delete(listener);
  };
}

export function subscribeSessionExpired(listener: Listener): () => void {
  sessionExpiredListeners.add(listener);
  return () => {
    sessionExpiredListeners.delete(listener);
  };
}

export function notifySessionExpired(): void {
  clearCsrfTokenMemory();
  for (const listener of sessionExpiredListeners) {
    listener();
  }
}

/**
 * Obtiene (o reutiliza) un token vigente con single-flight.
 * `loader` debe llamar GET /api/ui/v1/auth/csrf y devolver el string.
 */
export async function ensureCsrfToken(
  loader: () => Promise<string>,
  options?: { force?: boolean },
): Promise<string> {
  if (!options?.force && csrfTokenMemory && csrfTokenMemory.trim()) {
    return csrfTokenMemory;
  }
  if (refreshInFlight) {
    return refreshInFlight;
  }
  refreshInFlight = (async () => {
    try {
      const token = await loader();
      setCsrfTokenMemory(token);
      return csrfTokenMemory as string;
    } finally {
      refreshInFlight = null;
    }
  })();
  return refreshInFlight;
}

/** Solo tests: reinicia estado del módulo. */
export function resetCsrfManagerForTests(): void {
  csrfTokenMemory = null;
  localSessionMode = false;
  refreshInFlight = null;
  readyListeners.clear();
  sessionExpiredListeners.clear();
}
