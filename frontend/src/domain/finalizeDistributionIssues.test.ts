import { describe, expect, it } from "vitest";
import type { UiOperationalIssue } from "../types/contract";
import {
  compactFinalizeFailureMessage,
  groupFinalizeIssuesByRow,
  isFinalizeDistributionRowIssue,
  shouldCompactFinalizeJobModal,
} from "./finalizeDistributionIssues";

function issue(overrides: Partial<UiOperationalIssue> = {}): UiOperationalIssue {
  return {
    issue_id: "HBI-FINALIZE-missing_mora_a_aplicar-abc-0",
    stage: "finalize",
    category: "correction_required",
    severity: "warning",
    recoverable: true,
    title: "La revisión requiere correcciones.",
    user_message: "Falta Mora a aplicar en una fila con Validar Pago = SI.",
    location: {
      file_name: "rev.xlsx",
      sheet: "Distribucion_Pagos",
      row: 10,
      column: "Mora a aplicar",
      credit: "100",
      payment_id: "P1",
      client_name: "Cliente",
    },
    value_found: null,
    expected_values: [],
    next_action: "Complete Mora a aplicar.",
    retry: { allowed: true, action: "finalize", label: "Verificar nuevamente" },
    links: [
      {
        rel: "review_excel",
        label: "Abrir archivo de revisión",
        path: "/r.xlsx",
        web_url: "https://sp/r.xlsx",
        open_mode: "sharepoint",
      },
    ],
    technical_reference: "job:j1|code:missing_mora_a_aplicar",
    ...overrides,
  };
}

describe("finalizeDistributionIssues", () => {
  it("agrupa varios errores de la misma fila en una tarjeta", () => {
    const groups = groupFinalizeIssuesByRow([
      issue({
        issue_id: "HBI-FINALIZE-missing_mora_a_aplicar-a-0",
        user_message: "Falta Mora a aplicar.",
        technical_reference: "job:j|code:missing_mora_a_aplicar",
      }),
      issue({
        issue_id: "HBI-FINALIZE-missing_abono_capital-a-1",
        user_message: "Falta Abono a capital.",
        location: {
          file_name: "rev.xlsx",
          sheet: "Distribucion_Pagos",
          row: 10,
          column: "Abono a capital",
          credit: "100",
          payment_id: "P1",
          client_name: "Cliente",
        },
        technical_reference: "job:j|code:missing_abono_capital",
      }),
      issue({
        issue_id: "HBI-FINALIZE-missing_otros_valores-b-0",
        user_message: "Faltan Otros valores.",
        location: {
          file_name: "rev.xlsx",
          sheet: "Distribucion_Pagos",
          row: 12,
          column: "Otros valores",
          credit: "200",
          payment_id: "P2",
          client_name: null,
        },
        technical_reference: "job:j|code:missing_otros_valores",
      }),
    ]);
    expect(groups).toHaveLength(2);
    expect(groups[0]!.title).toBe("Fila 10");
    expect(groups[0]!.messages).toEqual([
      "Falta Mora a aplicar.",
      "Falta Abono a capital.",
    ]);
    expect(groups[1]!.title).toBe("Fila 12");
  });

  it("no trata process_not_approved como fila de distribución", () => {
    const gate = issue({
      issue_id: "HBI-FINALIZE-process_not_approved-xyz",
      technical_reference: "job:j|code:process_not_approved",
      location: null,
      user_message: "Aún no se marcó el archivo como listo para procesar.",
    });
    expect(isFinalizeDistributionRowIssue(gate)).toBe(false);
  });

  it("compacta el modal de job para multiple_review_errors", () => {
    expect(
      shouldCompactFinalizeJobModal(
        {
          error: { error_code: "multiple_review_errors" },
        } as never,
        null,
      ),
    ).toBe(true);
    expect(
      shouldCompactFinalizeJobModal(
        {
          error: { error_code: "process_not_approved" },
        } as never,
        null,
      ),
    ).toBe(false);
    expect(compactFinalizeFailureMessage(12)).toMatch(/Hay 12 problemas/);
    expect(compactFinalizeFailureMessage(12)).toMatch(/Problemas operativos/);
  });
});
