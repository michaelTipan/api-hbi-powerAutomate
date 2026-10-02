import type {
  ExclusionReasonCode,
  UiAmortizationDecisions,
  UiConfirmedConciliation,
  UiExcludedCredit,
  UiOperationalIssue,
} from "../types/contract";

export const EXCLUSION_REASONS: ReadonlyArray<{ code: ExclusionReasonCode; label: string }> = [
  { code: "FALTA_ASIENTO", label: "Falta el asiento de Contabilidad" },
  { code: "ASIENTO_CON_ERROR", label: "Asiento con error, pendiente de corrección" },
  { code: "TABLA_CON_ERROR", label: "Tabla de amortización con error" },
  { code: "APLICACION_MANUAL", label: "Se aplicará manualmente" },
  { code: "OTRO", label: "Otro (especificar)" },
];

export const EXCLUSION_NOTE_MAX = 300;

/** Número de crédito normalizado (misma regla que el backend para «CREDITO # 87»). */
export function creditToken(raw: string | null | undefined): string {
  const s = String(raw ?? "").trim();
  if (!s) return "";
  const hash = /#\s*(\d{1,8})\b/.exec(s);
  if (hash) return String(Number(hash[1]));
  if (/^\d{1,8}$/.test(s)) return String(Number(s));
  const any = /\b(\d{1,8})\b/.exec(s);
  return any ? String(Number(any[1])) : s;
}

function issueCredits(issue: UiOperationalIssue): string[] {
  const out = new Set<string>();
  const main = creditToken(issue.location?.credit);
  if (main) out.add(main);
  return [...out];
}

export function exclusionForIssue(
  issue: UiOperationalIssue,
  decisions: UiAmortizationDecisions | null | undefined,
): UiExcludedCredit | null {
  const rows = decisions?.excluded ?? [];
  if (rows.length === 0) return null;
  const candidates = new Set([
    ...issueCredits(issue),
    ...(issue.decision?.group_credits ?? []).map(creditToken),
  ]);
  return rows.find((row) => candidates.has(creditToken(row.credit))) ?? null;
}

export function confirmationForIssue(
  issue: UiOperationalIssue,
  decisions: UiAmortizationDecisions | null | undefined,
): UiConfirmedConciliation | null {
  const key = issue.decision?.conciliation_key;
  if (!key) return null;
  return (decisions?.confirmations ?? []).find((c) => c.conciliation_key === key) ?? null;
}

/** Problemas que siguen pendientes (la franja roja no cuenta excluidos ni confirmados). */
export function pendingAmortizationIssues(
  issues: readonly UiOperationalIssue[],
  decisions: UiAmortizationDecisions | null | undefined,
): UiOperationalIssue[] {
  return issues.filter(
    (i) => !exclusionForIssue(i, decisions) && !confirmationForIssue(i, decisions),
  );
}

function joinSpanish(items: readonly string[]): string {
  if (items.length <= 1) return items.join("");
  return `${items.slice(0, -1).join(", ")} y ${items[items.length - 1]}`;
}

/** Aviso al excluir un crédito que comparte consignación con otros. */
export function groupExclusionWarning(credit: string, groupCredits: readonly string[]): string | null {
  const own = creditToken(credit);
  const others = [...new Set(groupCredits.map(creditToken))].filter((c) => c && c !== own);
  if (others.length === 0) return null;
  if (others.length === 1) {
    return `El crédito ${own} comparte consignación con el crédito ${others[0]}. Se excluirán ambos.`;
  }
  return `El crédito ${own} comparte consignación con los créditos ${joinSpanish(others)}. Se excluirán todos.`;
}

export function excludedCreditLabel(row: Pick<UiExcludedCredit, "credit" | "client_name">): string {
  return row.client_name ? `${row.credit} · ${row.client_name}` : row.credit;
}

export function excludedPhaseLine(
  row: UiExcludedCredit,
  appliedCredits: readonly string[] = [],
): string {
  const base = `Excluido: crédito ${excludedCreditLabel(row)}`;
  return isAppliedCredit(row.credit, appliedCredits)
    ? `${base} (ya quedó registrado en su tabla)`
    : base;
}

/** Crédito ya registrado en su tabla en este proceso: nunca cuenta como «sin amortizar». */
export function isAppliedCredit(credit: string, appliedCredits: readonly string[]): boolean {
  const tok = creditToken(credit);
  return !!tok && appliedCredits.some((c) => creditToken(c) === tok);
}

export function plannedWritesLine(lines: number | null, tables: number | null): string | null {
  if (lines == null || tables == null || lines <= 0) return null;
  const l = lines === 1 ? "1 línea" : `${lines} líneas`;
  const t = tables === 1 ? "1 tabla" : `${tables} tablas`;
  return `Se registrarán ${l} en ${t}`;
}

export const NOTHING_PENDING_AFTER_PARTIAL =
  "No quedan créditos por procesar. Para terminar, use Cerrar con amortización incompleta.";

export type PartialAmortizationProgress = {
  /** Sin créditos por registrar ni problemas abiertos: solo queda cerrar. */
  nothingPending: boolean;
  lines: string[];
};

/**
 * Tarjeta de fase 4 tras una amortización parcial. `planned_lines` ya descuenta
 * excluidos y créditos registrados; null = no se sabe (se conserva Procesar).
 */
export function partialAmortizationProgress(args: {
  partial: boolean;
  decisions: UiAmortizationDecisions | null | undefined;
  pendingIssues: number;
}): PartialAmortizationProgress | null {
  if (!args.partial) return null;
  const decisions = args.decisions ?? null;
  const applied = new Set((decisions?.applied_credits ?? []).map(creditToken).filter(Boolean));
  const lines: string[] = [];
  if (applied.size === 1) lines.push("Ya quedó registrado 1 crédito en su tabla.");
  else if (applied.size > 1) lines.push(`Ya quedaron registrados ${applied.size} créditos en sus tablas.`);
  const nothingPending = decisions?.planned_lines === 0 && args.pendingIssues === 0;
  if (nothingPending) {
    lines.push(NOTHING_PENDING_AFTER_PARTIAL);
    return { nothingPending, lines };
  }
  const pendingLines = decisions?.planned_lines ?? 0;
  const pendingTables = decisions?.planned_tables ?? 0;
  if (pendingLines > 0 && pendingTables > 0) {
    const l = pendingLines === 1 ? "Queda 1 línea" : `Quedan ${pendingLines} líneas`;
    const t = pendingTables === 1 ? "1 tabla" : `${pendingTables} tablas`;
    lines.push(`${l} por registrar en ${t}.`);
  }
  if (args.pendingIssues > 0) {
    lines.push("Corrija lo pendiente o excluya el crédito y vuelva a procesar la amortización.");
  } else {
    lines.push("Procese la amortización para registrar los créditos pendientes.");
  }
  return { nothingPending, lines };
}

/** Texto de la confirmación de cierre cuando hay créditos excluidos. */
export function softCloseExcludedSentence(
  excluded: readonly UiExcludedCredit[],
  appliedCredits: readonly string[] = [],
): string | null {
  const seen = new Set<string>();
  const labels: string[] = [];
  for (const row of excluded) {
    const tok = creditToken(row.credit);
    if (!tok || seen.has(tok) || isAppliedCredit(row.credit, appliedCredits)) continue;
    seen.add(tok);
    labels.push(excludedCreditLabel(row));
  }
  if (labels.length === 0) return null;
  const n = labels.length === 1 ? "1 crédito" : `${labels.length} créditos`;
  return `El proceso se cerrará con ${n} sin amortizar: ${labels.join(", ")}.`;
}

export function formatCop(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "";
  const hasCents = Math.abs(value - Math.round(value)) > 0.004;
  return `$${value.toLocaleString("es-CO", {
    minimumFractionDigits: hasCents ? 2 : 0,
    maximumFractionDigits: 2,
  })}`;
}
