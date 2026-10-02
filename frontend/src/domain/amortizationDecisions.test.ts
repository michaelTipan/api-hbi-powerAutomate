import { describe, expect, it } from "vitest";
import type {
  UiAmortizationDecisions,
  UiExcludedCredit,
  UiJobView,
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
  NOTHING_PENDING_AFTER_PARTIAL,
  partialAmortizationProgress,
  pendingAmortizationIssues,
  isAppliedCredit,
  plannedWritesLine,
  softCloseExcludedSentence,
} from "./amortizationDecisions";
import {
  buildAmortizationOperationalIssuesFromJob,
  parseOperationalIssuesFromUnknown,
} from "./amortizationOperationalIssues";

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
    expect(plannedWritesLine(0, 0)).toBeNull();
  });

  describe("avance parcial de amortización", () => {
    const base: UiAmortizationDecisions = {
      available: true,
      user_message: null,
      excluded: [],
      confirmations: [],
      planned_lines: null,
      planned_tables: null,
      credits_not_amortized: [],
    };

    it("fuera de parcial no aplica", () => {
      expect(
        partialAmortizationProgress({ partial: false, decisions: base, pendingIssues: 0 }),
      ).toBeNull();
    });

    it("sin nada pendiente: solo queda cerrar, sin «Se registrarán»", () => {
      const view = partialAmortizationProgress({
        partial: true,
        decisions: { ...base, planned_lines: 0, planned_tables: 0, applied_credits: ["60", "61"] },
        pendingIssues: 0,
      });
      expect(view?.nothingPending).toBe(true);
      expect(view?.lines).toEqual([
        "Ya quedaron registrados 2 créditos en sus tablas.",
        NOTHING_PENDING_AFTER_PARTIAL,
      ]);
      expect(view?.lines.join(" ")).not.toMatch(/Se registrarán/);
    });

    it("con problemas abiertos conserva Procesar y cuenta solo lo pendiente", () => {
      const view = partialAmortizationProgress({
        partial: true,
        decisions: { ...base, planned_lines: 2, planned_tables: 1, applied_credits: ["60"] },
        pendingIssues: 1,
      });
      expect(view?.nothingPending).toBe(false);
      expect(view?.lines).toEqual([
        "Ya quedó registrado 1 crédito en su tabla.",
        "Quedan 2 líneas por registrar en 1 tabla.",
        "Corrija lo pendiente o excluya el crédito y vuelva a procesar la amortización.",
      ]);
    });

    it("sin plan conocido no se asume que no queda nada", () => {
      const view = partialAmortizationProgress({
        partial: true,
        decisions: base,
        pendingIssues: 0,
      });
      expect(view?.nothingPending).toBe(false);
      expect(view?.lines).toEqual([
        "Procese la amortización para registrar los créditos pendientes.",
      ]);
    });
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

  it("un crédito ya registrado en su tabla no cuenta como sin amortizar aunque esté excluido", () => {
    const rows = [
      excluded({ credit: "151", client_name: "ASFALTOS MEDELLIN" }),
      excluded({ credit: "102", client_name: "CLIENTE DOS" }),
    ];
    expect(softCloseExcludedSentence(rows, ["151"])).toBe(
      "El proceso se cerrará con 1 crédito sin amortizar: 102 · CLIENTE DOS.",
    );
    expect(softCloseExcludedSentence(rows, ["CREDITO # 151", "102"])).toBeNull();
    expect(excludedPhaseLine(rows[0], ["151"])).toBe(
      "Excluido: crédito 151 · ASFALTOS MEDELLIN (ya quedó registrado en su tabla)",
    );
    expect(excludedPhaseLine(rows[1], ["151"])).toBe("Excluido: crédito 102 · CLIENTE DOS");
    expect(isAppliedCredit("CREDITO # 151", ["151"])).toBe(true);
    expect(isAppliedCredit("15", ["151"])).toBe(false);
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

  it("parcial solo por créditos excluidos no inventa un problema de respaldo", () => {
    const job = (summary: Record<string, unknown>): UiJobView => ({
      job_id: "job-1",
      type: "amortization_process",
      status: "completed",
      store: "job_manager",
      process_key: "k",
      bank_code: "banco_bogota",
      environment: "sandbox",
      created_at: null,
      started_at: null,
      finished_at: null,
      result_summary: { outcome: "partial", status: "partial", ...summary },
      error: null,
      user_message: "Se actualizaron 2 tabla(s). Créditos excluidos: 133.",
      next_action: null,
      severity: "warning",
      raw_available: true,
    });
    expect(buildAmortizationOperationalIssuesFromJob(job({ partial_only_exclusions: true }))).toEqual([]);
    expect(buildAmortizationOperationalIssuesFromJob(job({}))).toHaveLength(1);
  });
});
