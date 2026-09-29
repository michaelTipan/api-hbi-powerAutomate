import { describe, expect, it } from "vitest";
import {
  asiento,
  assignment,
  group,
  payment,
  twoPaymentGroup,
  verification,
} from "../mocks/mergeVerification";
import {
  canConfirmAssignment,
  excludedCreditsList,
  hasShortfall,
  initialSelection,
  mergeConfirmSentence,
  paymentAssignmentLines,
  shortDate,
  unusedReasonFor,
  verificationSummary,
} from "./mergeVerification";

describe("mergeVerification — textos", () => {
  it("resumen «N de M créditos listos para consolidar»", () => {
    const v = verification(
      [group(), group({ group_key: "250", credits: ["250"] }), twoPaymentGroup()],
      { credits_total: 14, credits_ready: 12 },
    );
    expect(verificationSummary(v)).toBe("12 de 14 créditos listos para consolidar.");
  });

  it("confirmación de Consolidar con excluidos", () => {
    const excluded = group({
      group_key: "95",
      credits: ["95"],
      clientes: { "95": "TRANSPORTES SINTETICO" },
      status: "excluded",
      exclusion: { motivo: "Se aplicará manualmente", motivo_codigo: "APLICACION_MANUAL", can_undo: true },
    });
    const v = verification([group(), group({ group_key: "250", credits: ["250"] }), excluded]);
    expect(mergeConfirmSentence(v)).toBe("Se generarán 2 consolidados. Excluidos: 1");
    expect(excludedCreditsList(v)).toBe("crédito 95 · TRANSPORTES SINTETICO");
  });

  it("confirmación con un solo consolidado y sin excluidos", () => {
    const v = verification([group()]);
    expect(mergeConfirmSentence(v)).toBe("Se generará 1 consolidado. Excluidos: 0");
    expect(excludedCreditsList(v)).toBeNull();
  });

  it("fecha corta dd/mm", () => {
    expect(shortDate("2026-09-22")).toBe("22/09");
  });

  it("motivo de «No corresponde» según el estado del asiento", () => {
    expect(unusedReasonFor({ state: "otro_credito" })).toBe("OTRO_CREDITO");
    expect(unusedReasonFor({ state: "pago_anterior" })).toBe("PAGO_ANTERIOR");
    expect(unusedReasonFor({ state: "usable" })).toBe("NO_CORRESPONDE");
  });
});

describe("mergeVerification — asignación", () => {
  it("parte de la propuesta cuando no hay asignación guardada", () => {
    expect(initialSelection(twoPaymentGroup())).toEqual({
      "ASIENTOS/133/A.pdf": "P1",
      "ASIENTOS/133/B.pdf": "P2",
    });
  });

  it("en empate no preselecciona nada", () => {
    const g = twoPaymentGroup({ assignment: assignment({ tie: true, proposal: {}, payments: twoPaymentGroup().assignment!.payments }) });
    expect(initialSelection(g)).toEqual({});
    expect(canConfirmAssignment(g, {})).toBe(false);
  });

  it("la asignación guardada tiene prioridad sobre la propuesta", () => {
    const base = twoPaymentGroup();
    const g = twoPaymentGroup({
      assignment: { ...base.assignment!, explicit: true },
      asientos: base.asientos.map((a) => ({ ...a, assigned_id_pago: "P1" })),
    });
    expect(initialSelection(g)).toEqual({
      "ASIENTOS/133/A.pdf": "P1",
      "ASIENTOS/133/B.pdf": "P1",
    });
  });

  it("no preselecciona pagos no elegibles (fecha posterior al asiento)", () => {
    const g = twoPaymentGroup({
      asientos: [
        asiento({ path: "ASIENTOS/133/A.pdf", credito: "133", cash: 100, eligible_id_pagos: ["P1"] }),
        asiento({ path: "ASIENTOS/133/B.pdf", credito: "133", cash: 50, eligible_id_pagos: ["P1"] }),
      ],
    });
    expect(initialSelection(g)).toEqual({ "ASIENTOS/133/A.pdf": "P1" });
  });

  it("resumen por pago: Cuadra, Faltan y Sobran en centavos", () => {
    const g = twoPaymentGroup();
    expect(paymentAssignmentLines(g, initialSelection(g)).map((l) => l.text)).toEqual([
      "Pago 22/09 $100 · Asignado $100 · Cuadra",
      "Pago 25/09 $50 · Asignado $50 · Cuadra",
    ]);
    const swapped = { "ASIENTOS/133/A.pdf": "P2", "ASIENTOS/133/B.pdf": "P1" };
    expect(paymentAssignmentLines(g, swapped).map((l) => l.text)).toEqual([
      "Pago 22/09 $100 · Asignado $50 · Faltan $50",
      "Pago 25/09 $50 · Asignado $100 · Sobran $50",
    ]);
    expect(canConfirmAssignment(g, swapped)).toBe(false);
  });

  it("un faltante se permite (Diferencia no aplicada) pero un exceso no", () => {
    const g = twoPaymentGroup({
      asientos: [asiento({ path: "ASIENTOS/133/A.pdf", credito: "133", cash: 99.5, eligible_id_pagos: ["P1", "P2"] })],
      assignment: assignment({ payments: [payment({ monto: 100 })] }),
    });
    const sel = { "ASIENTOS/133/A.pdf": "P1" };
    expect(canConfirmAssignment(g, sel)).toBe(true);
    expect(hasShortfall(g, sel)).toBe(true);
    expect(paymentAssignmentLines(g, sel)[0].text).toBe("Pago 22/09 $100 · Asignado $99,50 · Faltan $0,50");
  });

  it("Confirmar exige todos los asientos asignados", () => {
    const g = twoPaymentGroup();
    expect(canConfirmAssignment(g, { "ASIENTOS/133/A.pdf": "P1" })).toBe(false);
  });

  it("los asientos no utilizables no cuentan para Confirmar", () => {
    const base = twoPaymentGroup();
    const g = twoPaymentGroup({
      asientos: [
        ...base.asientos,
        asiento({
          path: "ASIENTOS/133/OLD.pdf",
          credito: "133",
          state: "ya_aplicado",
          state_label: "Ya aplicado el 10/09",
          eligible_id_pagos: [],
        }),
      ],
    });
    expect(canConfirmAssignment(g, initialSelection(g))).toBe(true);
  });
});
