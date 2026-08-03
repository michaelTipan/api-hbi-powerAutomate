/** Cálculo de montos aplicados en la revisión UI (pagos). */

import type { UiReviewPagoRow } from "../types/contract";

export function formatMoneyCo(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toLocaleString("es-CO", {
    style: "currency",
    currency: "COP",
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  });
}

export function parseMoneyDraft(raw: string | null | undefined): number | null {
  if (raw === null || raw === undefined) return null;
  const trimmed = String(raw).trim();
  if (!trimmed) return null;
  const n = Number(trimmed.replace(",", "."));
  return Number.isFinite(n) ? n : null;
}

export type AppliedBreakdown = {
  extracto: number | null;
  mora: number | null;
  capital: number | null;
  otros: number | null;
  total: number;
  banco: number | null;
  saldo: number | null;
};

/** Totales efectivos (borrador sobreescribe fila). */
export function appliedBreakdown(
  row: UiReviewPagoRow,
  draft?: Record<string, string>,
): AppliedBreakdown {
  const pick = (field: keyof UiReviewPagoRow, draftKey: string): number | null => {
    if (draft && draftKey in draft) return parseMoneyDraft(draft[draftKey]);
    const v = row[field];
    return typeof v === "number" && Number.isFinite(v) ? v : null;
  };
  const extracto = pick("aplicar_a_extracto", "aplicar_a_extracto");
  const mora = pick("mora_a_aplicar", "mora_a_aplicar");
  const capital = pick("abono_a_capital", "abono_a_capital");
  const otros = pick("otros_valores", "otros_valores");
  const parts = [extracto, mora, capital, otros].map((n) => n ?? 0);
  const total = parts.reduce((a, b) => a + b, 0);
  const banco = row.monto_banco;
  const saldo =
    banco === null || banco === undefined ? null : Math.round((banco - total) * 100) / 100;
  return { extracto, mora, capital, otros, total, banco, saldo };
}

/** Fila incompleta para Validar=SI (falta estado o montos que cuadren). */
export function pagoNeedsAttention(
  row: UiReviewPagoRow,
  draft?: Record<string, string>,
): boolean {
  const validar = (draft?.validar_pago ?? row.validar_pago ?? "").trim().toUpperCase();
  if (validar !== "SI") return false;
  const estado = (draft?.estado_pago ?? row.estado_pago ?? "").trim();
  if (!estado) return true;
  const br = appliedBreakdown(row, draft);
  if (br.banco !== null && br.saldo !== null && Math.abs(br.saldo) > 0.009) return true;
  return false;
}

export function filterPagoRows(
  rows: readonly UiReviewPagoRow[],
  query: string,
): UiReviewPagoRow[] {
  const q = query.trim().toLowerCase();
  if (!q) return [...rows];
  return rows.filter((r) => {
    const hay = `${r.cliente} ${r.credito} ${r.id_pago} ${r.estado_pago ?? ""}`.toLowerCase();
    return hay.includes(q);
  });
}
