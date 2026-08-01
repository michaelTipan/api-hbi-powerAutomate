/**
 * Mensajes de job para el operador.
 *
 * Prioridad (nunca mostrar códigos técnicos, pipes ni excepciones):
 *   user_message → error.user_message → mensaje operativo de respaldo.
 *
 * `error.message` solo se usa si parece lenguaje humano (sin `|`, sin
 * snake_case de códigos internos). En cualquier otro caso se sustituye por
 * el respaldo operativo.
 */
import type { UiJobView } from "../types/contract";
import { FALLBACK_OPERATOR_MESSAGE } from "../copy/labels";

function text(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

/** Heurística: rechaza códigos internos (`active_process_exists|…`, snake_case). */
export function looksTechnical(value: string | null | undefined): boolean {
  if (!value) return false;
  const v = value.trim();
  if (!v) return false;
  if (v.includes("|")) return true;
  if (/^[a-z][a-z0-9_]{2,}$/.test(v) && v.includes("_")) return true;
  if (/Traceback|Exception|Error:\s/i.test(v) && !/\s/.test(v.slice(0, 40))) return true;
  if (/^\{[\s\S]*\}$/.test(v) || /^\[/.test(v)) return true;
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
