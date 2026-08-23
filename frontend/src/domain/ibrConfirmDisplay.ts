import type { UiIbrRateByDate } from "../types/contract";

export type IbrStatusTone = "ok" | "warn" | "info" | "danger" | "readonly";

export function ibrCreditLabel(row: UiIbrRateByDate): string {
  const labeled = (row.credito_label || "").trim();
  if (labeled) return labeled;
  const id = (row.credito || "").trim();
  return id ? `Crédito ${id}` : "—";
}

export function ibrRateDisplay(row: UiIbrRateByDate): string {
  if (row.updates_ibr === false) return "—";
  return (row.rate_label || "").trim() || "—";
}

export function ibrStatusDisplay(row: UiIbrRateByDate): {
  label: string;
  tone: IbrStatusTone;
} {
  if (row.updates_ibr === false) {
    if (row.status === "skipped_adelantado") {
      return { label: "Omitido (pago antes del corte)", tone: "info" };
    }
    const reason = (row.skip_reason || "").trim();
    return {
      label: reason ? `No se actualiza (${reason})` : "No se actualiza",
      tone: "readonly",
    };
  }
  if (row.status === "found" && (row.rate_label || row.rate != null)) {
    return { label: "Se actualiza", tone: "ok" };
  }
  if (row.status === "missing") {
    return { label: "Sin tasa", tone: "danger" };
  }
  return { label: "Sin tasa", tone: "warn" };
}

/** Resumen de conteos encima de la tabla (copy estable para tests). */
export function ibrPreviewSummaryLine(rates: readonly UiIbrRateByDate[]): string {
  const needed = rates.filter((r) => r.updates_ibr !== false);
  const withRate = needed.filter((r) => r.status === "found");
  const missing = needed.filter((r) => r.status === "missing");
  const skipped = rates.filter((r) => r.updates_ibr === false);
  if (needed.length === 0) {
    return `IBR: no se actualizará en este lote${
      skipped.length > 0 ? ` (${skipped.length} corte(s) omitidos)` : ""
    }.`;
  }
  return (
    `${needed.length} corte(s) · ${withRate.length} con tasa` +
    (missing.length > 0 ? ` · ${missing.length} sin tasa` : "") +
    (skipped.length > 0 ? ` · ${skipped.length} sin actualizar` : "")
  );
}
