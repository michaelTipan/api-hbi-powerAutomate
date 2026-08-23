import { describe, expect, it } from "vitest";
import type { UiIbrRateByDate } from "../types/contract";
import {
  ibrCreditLabel,
  ibrPreviewSummaryLine,
  ibrRateDisplay,
  ibrStatusDisplay,
} from "./ibrConfirmDisplay";

function row(partial: Partial<UiIbrRateByDate>): UiIbrRateByDate {
  return {
    date: "2026-07-15",
    date_label: "15 jul 2026",
    rate: null,
    rate_pct: null,
    rate_label: null,
    status: "found",
    ...partial,
  };
}

describe("ibrConfirmDisplay", () => {
  it("arma celdas de crédito, tasa y estado", () => {
    const found = row({
      credito: "248",
      rate_label: "33,33 %",
      rate: 0.3333,
      updates_ibr: true,
      status: "found",
    });
    expect(ibrCreditLabel(found)).toBe("Crédito 248");
    expect(ibrRateDisplay(found)).toBe("33,33 %");
    expect(ibrStatusDisplay(found)).toEqual({
      label: "Se actualiza",
      tone: "ok",
    });

    const skipped = row({
      credito: "16",
      updates_ibr: false,
      status: "skipped_adelantado",
    });
    expect(ibrRateDisplay(skipped)).toBe("—");
    expect(ibrStatusDisplay(skipped).label).toMatch(/pago antes del corte/i);
  });

  it("resume conteos sin prosa por fila", () => {
    const line = ibrPreviewSummaryLine([
      row({ updates_ibr: true, status: "found", rate_label: "9 %" }),
      row({
        date: "2026-08-04",
        updates_ibr: false,
        status: "skipped_adelantado",
      }),
    ]);
    expect(line).toMatch(/1 corte\(s\)/);
    expect(line).toMatch(/1 con tasa/);
    expect(line).toMatch(/1 sin actualizar/);
  });
});
