import { describe, expect, it } from "vitest";
import type { UiOperationalIssue } from "../types/contract";
import {
  buildIssueEvidenceLines,
  formatOperationalValueFound,
  refineNextActionForOpenCta,
} from "./operationalIssueDisplay";

function baseIssue(
  overrides: Partial<UiOperationalIssue> = {},
): UiOperationalIssue {
  return {
    issue_id: "t1",
    stage: "amortization",
    category: "correction_required",
    severity: "business",
    recoverable: true,
    title: "Tabla de amortización · Crédito 128",
    user_message:
      "La tabla de amortización del crédito no tiene la columna de retenciones, pero el asiento sí trae retenciones. No se realizó ninguna modificación.",
    location: {
      file_name: "Tabla de amortizacion INV TORRES N.xlsx",
      sheet: null,
      row: null,
      column: null,
      credit: "128",
      payment_id: null,
      client_name: null,
    },
    value_found: "$205.396",
    expected_values: ["RETENCIONES"],
    next_action:
      "Corrija la plantilla para incluir la columna RETENCIONES y vuelva a procesar la amortización.",
    retry: null,
    links: [
      {
        rel: "amortization_table",
        label: "Abrir tabla de amortización",
        path: null,
        web_url: "https://example.com/tabla",
        open_mode: "sharepoint",
      },
    ],
    technical_reference: "RETENCIONES_COLUMN_MISSING",
    ...overrides,
  };
}

describe("operationalIssueDisplay", () => {
  it("no duplica monto ni columna ya ausentes del cuerpo", () => {
    const lines = buildIssueEvidenceLines(baseIssue());
    expect(lines.map((l) => l.text)).toEqual([
      "Archivo afectado: Tabla de amortizacion INV TORRES N.xlsx",
      "Valor detectado: $205.396",
      "Valores esperados: RETENCIONES",
    ]);
  });

  it("omite evidencia si el cuerpo ya la menciona", () => {
    const lines = buildIssueEvidenceLines(
      baseIssue({
        user_message:
          "Falta RETENCIONES y hay retenciones por $205.396. Archivo afectado: Tabla de amortizacion INV TORRES N.xlsx.",
      }),
    );
    expect(lines).toEqual([]);
  });

  it("acorta next_action cuando hay CTA Abrir", () => {
    const refined = refineNextActionForOpenCta(
      "Abra la tabla de amortización, quite o mueva ese contenido y vuelva a procesar.",
      baseIssue().links,
    );
    expect(refined).toMatch(/quite o mueva/i);
    expect(refined).not.toMatch(/^abra/i);
  });

  it("conserva next_action sin Abrir cuando no hay CTA Abrir", () => {
    expect(
      refineNextActionForOpenCta("Corrija el valor y verifique.", []),
    ).toBe("Corrija el valor y verifique.");
  });

  it("usa Valor en Excel fuera de amortización", () => {
    expect(formatOperationalValueFound("PENDIENTE", "finalize")).toBe(
      "Valor en Excel: PENDIENTE",
    );
  });
});
