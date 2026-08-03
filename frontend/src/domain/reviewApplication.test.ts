import { describe, expect, it } from "vitest";
import {
  appliedBreakdown,
  filterPagoRows,
  pagoNeedsAttention,
  parseMoneyDraft,
} from "./reviewApplication";
import type { UiReviewPagoRow } from "../types/contract";

function row(partial: Partial<UiReviewPagoRow>): UiReviewPagoRow {
  return {
    row_key: "pagos:10",
    excel_row: 10,
    id_pago: "P1",
    cliente: "ACME",
    credito: "123",
    monto_banco: 1000,
    fecha_banco: null,
    fecha_limite: null,
    dias_mora: null,
    valor_extracto: null,
    aplicar_a_extracto: 400,
    mora_a_aplicar: 100,
    abono_a_capital: 500,
    otros_valores: null,
    total_aplicado: 1000,
    saldo_por_asignar: 0,
    estado_pago: "OK",
    validar_pago: "SI",
    observacion: null,
    tipo_aplicacion_original: null,
    editable_fields: [],
    links: [],
    ...partial,
  };
}

describe("reviewApplication", () => {
  it("parseMoneyDraft acepta coma decimal", () => {
    expect(parseMoneyDraft("1.250,5")).toBeNull(); // formato no soportado
    expect(parseMoneyDraft("1250,5")).toBe(1250.5);
  });

  it("appliedBreakdown suma borrador y calcula saldo", () => {
    const br = appliedBreakdown(row({}), {
      aplicar_a_extracto: "200",
      mora_a_aplicar: "50",
      abono_a_capital: "700",
      otros_valores: "",
    });
    expect(br.total).toBe(950);
    expect(br.saldo).toBe(50);
  });

  it("pagoNeedsAttention marca Validar=SI sin estado o descuadrado", () => {
    expect(
      pagoNeedsAttention(row({ estado_pago: "", validar_pago: "SI" })),
    ).toBe(true);
    expect(
      pagoNeedsAttention(
        row({ validar_pago: "SI", monto_banco: 100, aplicar_a_extracto: 40 }),
        { mora_a_aplicar: "0", abono_a_capital: "0", otros_valores: "0" },
      ),
    ).toBe(true);
    expect(
      pagoNeedsAttention(row({ validar_pago: "NO", estado_pago: "" })),
    ).toBe(false);
  });

  it("filterPagoRows busca por cliente/crédito", () => {
    const rows = [
      row({ cliente: "ACME", credito: "111", row_key: "a" }),
      row({ cliente: "BETA", credito: "222", row_key: "b", id_pago: "ZZ" }),
    ];
    expect(filterPagoRows(rows, "beta")).toHaveLength(1);
    expect(filterPagoRows(rows, "ZZ")).toHaveLength(1);
    expect(filterPagoRows(rows, "")).toHaveLength(2);
  });
});
