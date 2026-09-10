import { describe, expect, it } from "vitest";
import type { UiJobView, UiOperationalIssue, UiProcessDetail } from "../types/contract";
import {
  formatReviewBannerHeadline,
  formatReviewOutcomeMessage,
  resolveReviewDisplayIssues,
  resolveReviewEphemeralFromTerminal,
  reviewBannerUsesErroresHint,
  reviewIssuesProjectionFresh,
} from "./reviewDisplayIssues";

function erroresIssue(id: string): UiOperationalIssue {
  return {
    issue_id: id,
    stage: "review",
    category: "correction_required",
    severity: "business",
    recoverable: true,
    title: "Caso en Errores",
    user_message: "Mensaje",
    location: { sheet: "Errores", file_name: null, row: 2, column: null, credit: null, payment_id: null, client_name: null },
    value_found: null,
    expected_values: [],
    next_action: null,
    retry: null,
    links: [],
    technical_reference: null,
  };
}

function detail(issues: UiOperationalIssue[], status = "CORRECCION_REQUERIDA"): UiProcessDetail {
  return {
    process_key: "pk",
    process_id: "id",
    bank_code: "banco_bogota",
    bank_name: "Bogotá",
    process_date: "2026-08-01",
    environment: "sandbox",
    operational_status: status,
    control_estado_proceso: "REVISION_CREADA",
    is_active: true,
    steps: [],
    items: [],
    active_job: null,
    last_attempt: null,
    latest_attempts_by_stage: {},
    attempts: [],
    next_actions: [],
    available_actions: {},
    errors: [],
    operational_issues: issues,
    links: [],
    files: {
      validation_file_path: null,
      historical_file_path: null,
      secretary_file_path: null,
      email_pdf_path: null,
      merge_manifest_path: null,
      control_file_path: null,
      execution_log_path: null,
    },
    idempotency: {
      notify_idempotency_key: null,
      merge_idempotency_key: null,
      apply_idempotency_key: null,
    },
    trigger_source: null,
    requested_by: null,
    operator_checklist: [],
    merge_readiness: null,
    amortization_readiness: null,
  };
}

function job(overrides: Partial<UiJobView>): UiJobView {
  return {
    job_id: "j1",
    type: "generate",
    status: "completed",
    store: "job_manager",
    process_key: "pk",
    bank_code: "banco_bogota",
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

describe("resolveReviewDisplayIssues", () => {
  it("prioriza issues efímeros del job sobre detalle stale", () => {
    const stale = [erroresIssue("review-errores-1")];
    const fresh = [erroresIssue("review-errores-fresh-1"), erroresIssue("review-errores-fresh-2")];
    const resolved = resolveReviewDisplayIssues({
      operational_issues: stale,
      ephemeralIssues: fresh,
    });
    expect(resolved).toHaveLength(2);
    expect(resolved[0]?.issue_id).toBe("review-errores-fresh-1");
  });
});

describe("formatReviewBannerHeadline", () => {
  it("con mezcla Errores + otros issues usa el total (como el modal)", () => {
    const mixed = [
      erroresIssue("review-errores-1"),
      {
        ...erroresIssue("review-row-4"),
        issue_id: "review-row-4",
        location: { sheet: "Distribución", file_name: null, row: 4, column: null, credit: null, payment_id: null, client_name: null },
      },
      {
        ...erroresIssue("extract-325"),
        issue_id: "extract-325",
        location: { sheet: "Extracto", file_name: null, row: null, column: null, credit: "325", payment_id: null, client_name: null },
      },
    ];
    expect(formatReviewBannerHeadline(mixed)).toBe("3 problema(s) operativo(s).");
    expect(reviewBannerUsesErroresHint(mixed)).toBe(false);
  });

  it("solo Errores mantiene copy de hoja Errores", () => {
    const onlyErrores = [erroresIssue("review-errores-1"), erroresIssue("review-errores-2")];
    expect(formatReviewBannerHeadline(onlyErrores)).toBe("2 caso(s) en la hoja Errores");
    expect(reviewBannerUsesErroresHint(onlyErrores)).toBe(true);
  });
});

describe("formatReviewOutcomeMessage", () => {
  it("usa el mismo total que el banner para mezcla de issues", () => {
    const mixed = [
      erroresIssue("review-errores-1"),
      {
        ...erroresIssue("review-row-4"),
        issue_id: "review-row-4",
        location: { sheet: "Distribución", file_name: null, row: 4, column: null, credit: null, payment_id: null, client_name: null },
      },
      {
        ...erroresIssue("extract-325"),
        issue_id: "extract-325",
        location: { sheet: "Extracto", file_name: null, row: null, column: null, credit: "325", payment_id: null, client_name: null },
      },
    ];
    expect(formatReviewOutcomeMessage(mixed)).toBe(
      "Hay 3 problemas en la revisión. Revíselos en Problemas operativos, corrija el Excel, guarde y vuelva a verificar.",
    );
  });
});

describe("resolveReviewEphemeralFromTerminal", () => {
  it("prefiere issues frescos del job sobre el detalle stale", () => {
    const finalizeJob = job({
      type: "finalize",
      status: "completed",
      result_summary: {
        operational_issues: [
          {
            issue_id: "HBI-FINALIZE-missing_tipo-abc",
            user_message: "Falta tipo.",
            stage: "finalize",
          },
          {
            issue_id: "HBI-FINALIZE-missing_extract-def",
            user_message: "Falta extracto.",
            stage: "finalize",
          },
        ],
      },
    });
    const d = detail([
      {
        ...erroresIssue("HBI-FINALIZE-missing_tipo-abc"),
        issue_id: "HBI-FINALIZE-missing_tipo-abc",
        stage: "finalize",
        location: { sheet: "Aplicacion_Pagos", file_name: null, row: 4, column: null, credit: "325", payment_id: null, client_name: null },
      },
      {
        ...erroresIssue("HBI-FINALIZE-missing_extract-def"),
        issue_id: "HBI-FINALIZE-missing_extract-def",
        stage: "finalize",
        location: { sheet: "Aplicacion_Pagos", file_name: null, row: 5, column: null, credit: "325", payment_id: null, client_name: null },
      },
      {
        ...erroresIssue("HBI-FINALIZE-extra-ghi"),
        issue_id: "HBI-FINALIZE-extra-ghi",
        stage: "finalize",
        location: { sheet: "Aplicacion_Pagos", file_name: null, row: 6, column: null, credit: "326", payment_id: null, client_name: null },
      },
    ]);
    const merged = resolveReviewEphemeralFromTerminal(finalizeJob, d);
    expect(merged).toHaveLength(2);
    expect(formatReviewOutcomeMessage(merged)).toMatch(/2 problemas/);
  });

  it("Generate completed con errores=0 limpia issues efímeros", () => {
    expect(
      resolveReviewEphemeralFromTerminal(
        job({ result_summary: { errores: 0 } }),
        detail([erroresIssue("stale-1")]),
      ),
    ).toEqual([]);
  });

  it("Generate completed: job autoritativo sin inflar con detalle stale", () => {
    const j = job({
      result_summary: {
        errores: 1,
        operational_issues: [erroresIssue("review-errores-fresh-1")],
      },
    });
    const stale = detail([
      erroresIssue("review-errores-1"),
      erroresIssue("review-errores-2"),
      erroresIssue("review-errores-3"),
    ]);
    expect(resolveReviewEphemeralFromTerminal(j, stale)).toHaveLength(1);
  });
});

describe("reviewIssuesProjectionFresh", () => {
  it("Generate: exige conteo de Errores en detalle cuando el job solo trae errores=N", () => {
    const j = job({ result_summary: { errores: 2 } });
    expect(reviewIssuesProjectionFresh(detail([]), j)).toBe(false);
    expect(
      reviewIssuesProjectionFresh(
        detail([erroresIssue("review-errores-1"), erroresIssue("review-errores-2")]),
        j,
      ),
    ).toBe(true);
  });

  it("Finalize failed sin issues esperados: no bloquea sync", () => {
    expect(
      reviewIssuesProjectionFresh(
        detail([]),
        job({ type: "finalize", status: "failed" }),
      ),
    ).toBe(true);
  });
});
