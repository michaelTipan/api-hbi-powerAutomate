import { describe, expect, it } from "vitest";
import type { UiJobView, UiProcessDetail } from "../types/contract";
import {
  finalizeIssuesFromDetail,
  finalizeIssuesFromJob,
  formatIssueLocation,
  isFinalizeJob,
  resolveFinalizeFailureIssues,
  reviewExcelModalLink,
} from "./finalizeJobFailure";

function job(overrides: Partial<UiJobView> = {}): UiJobView {
  return {
    job_id: "j1",
    type: "finalize",
    status: "failed",
    store: "job_manager",
    process_key: "pk",
    bank_code: "banco_bancolombia",
    environment: "sandbox",
    created_at: null,
    started_at: null,
    finished_at: null,
    result_summary: null,
    error: null,
    user_message: null,
    next_action: null,
    raw_available: true,
    ...overrides,
  };
}

describe("finalizeJobFailure", () => {
  it("formatea ubicación operativa", () => {
    expect(
      formatIssueLocation({
        file_name: null,
        sheet: "Distribucion_Pagos",
        row: 6,
        column: "Aplicar a extracto",
        credit: "CREDITO # 265",
        payment_id: null,
        client_name: "EQUINORTE",
      }),
    ).toBe(
      "Hoja: Distribucion_Pagos · Fila: 6 · Columna: Aplicar a extracto · Cliente: EQUINORTE · Crédito: CREDITO # 265",
    );
  });

  it("lee issues adjuntos en error del job", () => {
    const issues = finalizeIssuesFromJob(
      job({
        error: {
          error_code: "multiple_review_errors",
          issues: [
            {
              issue_id: "HBI-FINALIZE-a",
              user_message: "Total aplicado en cero.",
              location: {
                sheet: "Distribucion_Pagos",
                row: 6,
                column: null,
                credit: null,
                payment_id: null,
                client_name: null,
                file_name: null,
              },
            },
          ],
        },
      }),
    );
    expect(issues).toHaveLength(1);
    expect(issues[0]!.message).toBe("Total aplicado en cero.");
    expect(issues[0]!.location).toContain("Fila: 6");
  });

  it("prioriza issues del job sobre el detalle", () => {
    const fromJob = resolveFinalizeFailureIssues(
      job({
        error: {
          issues: [{ issue_id: "from-job", user_message: "Desde el job" }],
        },
      }),
      {
        operational_issues: [
          {
            issue_id: "HBI-FINALIZE-x",
            stage: "finalize",
            category: "correction_required",
            severity: "warning",
            recoverable: true,
            title: "t",
            user_message: "Desde el detalle",
            location: null,
            value_found: null,
            expected_values: [],
            next_action: null,
            retry: null,
            links: [],
            technical_reference: null,
          },
        ],
      } as UiProcessDetail,
    );
    expect(fromJob.map((i) => i.message)).toEqual(["Desde el job"]);
  });

  it("cae al detalle cuando el job no trae issues", () => {
    const issues = finalizeIssuesFromDetail({
      operational_issues: [
        {
          issue_id: "HBI-FINALIZE-x",
          stage: "finalize",
          category: "correction_required",
          severity: "warning",
          recoverable: true,
          title: "t",
          user_message: "Estado Pago vacío.",
          location: {
            file_name: null,
            sheet: "Distribucion_Pagos",
            row: 2,
            column: "Estado Pago",
            credit: null,
            payment_id: "ID1",
            client_name: null,
          },
          value_found: null,
          expected_values: [],
          next_action: "Complete Estado Pago.",
          retry: null,
          links: [],
          technical_reference: null,
        },
      ],
    } as UiProcessDetail);
    expect(issues).toHaveLength(1);
    expect(issues[0]!.message).toContain("Estado Pago");
  });

  it("arma el enlace de revisión con etiqueta operativa", () => {
    const link = reviewExcelModalLink({
      links: [
        {
          rel: "review_excel",
          label: "Abrir archivo de revisión",
          path: "/x.xlsx",
          web_url: "https://sp/review.xlsx",
          open_mode: "sharepoint",
        },
      ],
    } as UiProcessDetail);
    expect(link?.web_url).toBe("https://sp/review.xlsx");
    expect(isFinalizeJob({ type: "finalize" })).toBe(true);
    expect(isFinalizeJob({ type: "notify_validar_extractos" })).toBe(false);
  });
});
