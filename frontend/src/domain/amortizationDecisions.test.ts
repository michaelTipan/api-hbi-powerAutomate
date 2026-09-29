import { describe, expect, it } from "vitest";
import type {
  UiAmortizationDecisions,
  UiExcludedCredit,
  UiOperationalIssue,
} from "../types/contract";
import {
  EXCLUSION_REASONS,
  confirmationForIssue,
  creditToken,
  exclusionForIssue,
  excludedPhaseLine,
  formatCop,
  groupExclusionWarning,
  pendingAmortizationIssues,
  plannedWritesLine,
  softCloseExcludedSentence,
} from "./amortizationDecisions";
import { parseOperationalIssuesFromUnknown } from "./amortizationOperationalIssues";

function issue(overrides: Partial<UiOperationalIssue> = {}): UiOperationalIssue {
  return {
    issue_id: "amort-CONCILIACION_ASIENTOS_MAYOR_BANCO-133-0",
    stage: "amortization",
    category: "correction_required",
    severity: "business",
    recoverable: true,
    title: "Consignación · Crédito 133",
    user_message: "Los asientos suman más que la consignación.",
    location: {
      file_name: null,
      sheet: null,
      row: null,
      column: null,
      credit: "133",
      payment_id: "P1",
      client_name: "CLIENTE UNO",
    },
    value_found: null,
    expected_values: [],
    next_action: null,
    retry: null,
    links: [],
    technical_reference: "CONCILIACION_ASIENTOS_MAYOR_BANCO",
    decision: {
      excludable: true,
      group_credits: ["102", "133"],
      group_key: "102+133",
      confirmable: false,
      conciliation_key: null,
      fecha_banco: "2026-07-31",
      bank_amount: 1000,
      asientos_amount: 1200,
      unapplied_amount: null,
    },
    ...overrides,
  };
}

function excluded(overrides: Partial<UiExcludedCredit> = {}): UiExcludedCredit {
  return {
    credit: "133",
    client_name: "CLIENTE UNO",
    motivo: "Falta el asiento de Contabilidad",
    motivo_codigo: "FALTA_ASIENTO",
    nota: null,
    group_credits: ["102", "133"],
    exclusion_id: "x1",
    can_undo: true,
    table_link: null,
    ...overrides,
  };
}

function decisions(overrides: Partial<UiAmortizationDecisions> = {}): UiAmortizationDecisions {
  return {
    available: true,
    user_message: null,
    excluded: [],
    confirmations: [],
    planned_lines: null,
    planned_tables: null,
    credits_not_amortized: [],
    ...overrides,
  };
}

describe("amortizationDecisions", () => {
  it("motivos de exclusión en el orden y la redacción acordados", () => {
    expect(EXCLUSION_REASONS.map((r) => r.label)).toEqual([
      "Falta el asiento de Contabilidad",
      "Asiento con error, pendiente de corrección",
      "Tabla de amortización con error",
      "Se aplicará manualmente",
      "Otro (especificar)",
    ]);
  });

  it("creditToken normaliza «CREDITO # 087» y números sueltos", () => {
    expect(creditToken("CREDITO # 087")).toBe("87");
    expect(creditToken("0133")).toBe("133");
    expect(creditToken("")).toBe("");
    expect(creditToken(null)).toBe("");
  });

  it("exclusionForIssue reconoce el crédito del grupo aunque el problema sea del otro crédito", () => {
    const d = decisions({ excluded: [excluded({ credit: "102" })] });
    expect(exclusionForIssue(issue(), d)?.credit).toBe("102");
    expect(exclusionForIssue(issue(), decisions())).toBeNull();
  });

  it("confirmationForIssue exige la misma clave de conciliación", () => {
    const i = issue({
      decision: {
        ...issue().decision!,
        excludable: false,
        confirmable: true,
        conciliation_key: "k1",
        unapplied_amount: 4,
      },
    });
    const conf = {
      conciliation_key: "k1",
      credits: ["133"],
      fecha_banco: "2026-07-31",
      bank_amount: 104,
      asientos_amount: 100,
      unapplied_amount: 4,
      nota: null,
      can_undo: true,
    };
    expect(confirmationForIssue(i, decisions({ confirmations: [conf] }))).toEqual(conf);
    expect(
      confirmationForIssue(
        i,
        decisions({ confirmations: [{ ...conf, conciliation_key: "k2" }] }),
      ),
    ).toBeNull();
  });

  it("pendingAmortizationIssues deja fuera excluidos y confirmados", () => {
    const other = issue({
      issue_id: "amort-X-250-0",
      location: { ...issue().location!, credit: "250" },
      decision: { ...issue().decision!, group_credits: ["250"], group_key: "250" },
    });
    const d = decisions({ excluded: [excluded()] });
    expect(pendingAmortizationIssues([issue(), other], d).map((i) => i.issue_id)).toEqual([
      "amort-X-250-0",
    ]);
    expect(pendingAmortizationIssues([issue(), other], null)).toHaveLength(2);
  });

  it("groupExclusionWarning redacta el aviso de consignación compartida", () => {
    expect(groupExclusionWarning("133", ["102", "133"])).toBe(
      "El crédito 133 comparte consignación con el crédito 102. Se excluirán ambos.",
    );
    expect(groupExclusionWarning("133", ["133"])).toBeNull();
    expect(groupExclusionWarning("1", ["1", "2", "3"])).toBe(
      "El crédito 1 comparte consignación con los créditos 2 y 3. Se excluirán todos.",
    );
  });

  it("línea de fase y resumen de escrituras", () => {
    expect(excludedPhaseLine(excluded())).toBe("Excluido: crédito 133 · CLIENTE UNO");
    expect(excludedPhaseLine(excluded({ client_name: null }))).toBe("Excluido: crédito 133");
    expect(plannedWritesLine(3, 2)).toBe("Se registrarán 3 líneas en 2 tablas");
    expect(plannedWritesLine(1, 1)).toBe("Se registrarán 1 línea en 1 tabla");
    expect(plannedWritesLine(null, 2)).toBeNull();
  });

  it("frase del cierre con créditos sin amortizar (sin duplicados)", () => {
    expect(softCloseExcludedSentence([])).toBeNull();
    expect(softCloseExcludedSentence([excluded()])).toBe(
      "El proceso se cerrará con 1 crédito sin amortizar: 133 · CLIENTE UNO.",
    );
    expect(
      softCloseExcludedSentence([
        excluded(),
        excluded({ credit: "102", client_name: "CLIENTE DOS" }),
        excluded(),
      ]),
    ).toBe(
      "El proceso se cerrará con 2 créditos sin amortizar: 133 · CLIENTE UNO, 102 · CLIENTE DOS.",
    );
  });

  it("formatCop usa separador de miles y centavos solo si existen", () => {
    expect(formatCop(2516)).toBe("$2.516");
    expect(formatCop(4.5)).toBe("$4,50");
    expect(formatCop(null)).toBe("");
  });

  it("el parser de issues conserva la decisión del backend", () => {
    const [parsed] = parseOperationalIssuesFromUnknown([issue()]);
    expect(parsed.decision).toEqual(issue().decision);
    const [withoutDecision] = parseOperationalIssuesFromUnknown([
      { ...issue(), decision: undefined },
    ]);
    expect(withoutDecision).not.toHaveProperty("decision");
  });
});
