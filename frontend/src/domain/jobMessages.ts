/**
 * Mensajes de job para el operador.
 *
 * Prioridad (nunca mostrar códigos técnicos, pipes ni excepciones):
 *   user_message → error.user_message → mensaje operativo de respaldo.
 *
 * `error.message` solo se usa si parece lenguaje humano (sin `|`, sin
 * snake_case de códigos internos, sin «Error HTTP 5xx»). En cualquier otro
 * caso se sustituye por el respaldo operativo.
 */
import { fallbackMessageForHttpStatus, UiApiError } from "../api/errors";
import type { UiJobView } from "../types/contract";
import { FALLBACK_OPERATOR_MESSAGE } from "../copy/labels";

function text(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

/** Heurística: rechaza códigos internos (`active_process_exists|…`, snake_case, HTTP). */
export function looksTechnical(value: string | null | undefined): boolean {
  if (!value) return false;
  const v = value.trim();
  if (!v) return false;
  if (v.includes("|")) return true;
  if (/^[a-z][a-z0-9_]{2,}$/.test(v) && v.includes("_")) return true;
  if (/Traceback|Exception|Error:\s/i.test(v) && !/\s/.test(v.slice(0, 40))) return true;
  if (/^\{[\s\S]*\}$/.test(v) || /^\[/.test(v)) return true;
  // «Error HTTP 502», «HTTP 500», status codes sueltos
  if (/^Error HTTP\s*\d{3}/i.test(v)) return true;
  if (/^HTTP\s*\d{3}\b/i.test(v)) return true;
  if (/^\d{3}\s+(Bad Gateway|Internal Server|Service Unavailable)/i.test(v)) return true;
  return false;
}

function humanOrNull(value: unknown): string | null {
  const t = text(value);
  if (!t || looksTechnical(t)) return null;
  return t;
}

/** Mensaje al operador; nunca devuelve códigos técnicos. */
export function jobUserMessage(job: UiJobView): string | null {
  return (
    humanOrNull(job.user_message) ??
    humanOrNull(job.error?.user_message) ??
    humanOrNull(job.error?.message) ??
    (job.status === "failed" ? FALLBACK_OPERATOR_MESSAGE : null)
  );
}

export function jobNextAction(job: UiJobView): string | null {
  return humanOrNull(job.next_action) ?? humanOrNull(job.error?.next_action);
}

/** Mensaje genérico a partir de un cuerpo de error (API o job). */
export function humanizeErrorPayload(payload: {
  user_message?: unknown;
  next_action?: unknown;
  message?: unknown;
  error?: { user_message?: unknown; next_action?: unknown; message?: unknown } | null;
}): { message: string; nextAction: string | null } {
  const message =
    humanOrNull(payload.user_message) ??
    humanOrNull(payload.error?.user_message) ??
    humanOrNull(payload.message) ??
    humanOrNull(payload.error?.message) ??
    FALLBACK_OPERATOR_MESSAGE;
  const nextAction =
    humanOrNull(payload.next_action) ?? humanOrNull(payload.error?.next_action);
  return { message, nextAction };
}

/**
 * Convierte cualquier excepción capturada en copy para el operador.
 * Nunca propaga «Error HTTP 502» ni códigos técnicos.
 */
export function operatorErrorMessage(
  error: unknown,
  fallback: string = FALLBACK_OPERATOR_MESSAGE,
): { message: string; nextAction: string | null } {
  if (error instanceof UiApiError) {
    const message = humanOrNull(error.userMessage) ?? fallbackMessageForHttpStatus(error.status);
    const nextAction = humanOrNull(error.nextAction);
    return { message, nextAction };
  }
  if (error instanceof Error) {
    const raw = error.message || "";
    const httpMatch = raw.match(/Error HTTP\s*(\d{3})/i) || raw.match(/\bHTTP\s*(\d{3})\b/i);
    if (httpMatch) {
      const status = Number(httpMatch[1]);
      return {
        message: Number.isFinite(status) ? fallbackMessageForHttpStatus(status) : fallback,
        nextAction: "Espere unos segundos y actualice el estado.",
      };
    }
    const message = humanOrNull(raw) ?? fallback;
    return { message, nextAction: null };
  }
  return { message: fallback, nextAction: null };
}
