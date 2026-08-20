import { describe, expect, it } from "vitest";
import type { UiJobView, UiOperationalIssue } from "../types/contract";
import {
  amortizationIssuesFromDetail,
  amortizationIssuesJobSummary,
  buildAmortizationOperationalIssuesFromJob,
  formatAmortizationIssuesBanner,
  parseOperationalIssuesFromUnknown,
  sanitizeOperationalIssue,
} from "./amortizationOperationalIssues";

function baseJob(overrides: Partial<UiJobView> = {}): UiJobView {
  return {
    job_id: "job-1",
    type: "amortization_process",
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
    progress: null,
    raw_available: false,
    ...overrides,
  };
}

describe("sanitizeOperationalIssue / parseOperationalIssuesFromUnknown", () => {
  it("normaliza campos y descarta filas inválidas", () => {
    const issues = parseOperationalIssuesFromUnknown([
      null,
      {
        issue_id: "amort-1",
        stage: "amortization",
        category: "correction_required",
        severity: "business",
        recoverable: true,
        title: "Tabla incompleta",
        user_message: "Falta el valor de capital en la fila 3.",
        location: null,
        value_found: null,
        expected_values: [],
        next_action: null,
        retry: null,
        links: [
          {
            rel: "amort_table",
            label: "Abrir tabla",
            path: null,
            web_url: "https://sp/tabla.xlsx",
            open_mode: "sharepoint",
          },
        ],
        technical_reference: "missing_capital",
      },
    ]);
    expect(issues).toHaveLength(1);
    expect(issues[0].issue_id).toBe("amort-1");
    expect(issues[0].links[0]?.web_url).toBe("https://sp/tabla.xlsx");
    expect(issues[0].technical_reference).toBe("missing_capital");
  });

  it("asigna defaults seguros si faltan campos", () => {
    const issue = sanitizeOperationalIssue({ title: "X" }, 0);
    expect(issue).not.toBeNull();
    expect(issue!.issue_id).toBe("amortization-issue-1");
    expect(issue!.stage).toBe("amortization");
    expect(issue!.category).toBe("correction_required");
    expect(issue!.severity).toBe("business");
    expect(issue!.user_message.length).toBeGreaterThan(10);
  });
});

describe("buildAmortizationOperationalIssuesFromJob", () => {
  it("mapea operational_issues del result_summary", () => {
    const issues = buildAmortizationOperationalIssuesFromJob(
      baseJob({
        result_summary: {
          outcome: "requires_correction",
          operational_issues: [
            {
              issue_id: "a1",
              stage: "amortization",
              category: "correction_required",
              severity: "business",
              recoverable: true,
              title: "Capital inválido",
              user_message: "El capital no puede ser negativo.",
              location: null,
              value_found: null,
              expected_values: [],
              next_action: null,
              retry: null,
              links: [],
              technical_reference: null,
            },
          ],
        },
      }),
    );
    expect(issues).toHaveLength(1);
    expect(issues[0].title).toMatch(/Capital/i);
    expect(issues[0].stage).toBe("amortization");
  });

  it("sintetiza un issue de respaldo si requires_correction sin lista", () => {
    const issues = buildAmortizationOperationalIssuesFromJob(
      baseJob({
        result_summary: {
          outcome: "requires_correction",
          user_message: "Debe corregir la tabla antes de reintentar.",
          next_action: "Abra la tabla y corrija los datos.",
        },
      }),
    );
    expect(issues).toHaveLength(1);
    expect(issues[0].issue_id).toBe("amortization-correction-fallback");
    expect(issues[0].user_message).toMatch(/corregir la tabla/i);
    expect(issues[0].next_action).toMatch(/Abra la tabla/i);
  });

  it("sintetiza fallback para outcome partial o failed sin operational_issues", () => {
    const partial = buildAmortizationOperationalIssuesFromJob(
      baseJob({ result_summary: { outcome: "partial" } }),
    );
    expect(partial).toHaveLength(1);
    expect(partial[0].issue_id).toBe("amortization-partial-fallback");
    expect(partial[0].category).toBe("partial_result");

    const failed = buildAmortizationOperationalIssuesFromJob(
      baseJob({ result_summary: { outcome: "failed" } }),
    );
    expect(failed).toHaveLength(1);
    expect(failed[0].issue_id).toBe("amortization-correction-fallback");

    expect(
      buildAmortizationOperationalIssuesFromJob(
        baseJob({ result_summary: { outcome: "applied" } }),
      ),
    ).toEqual([]);
  });
});

describe("amortizationIssuesFromDetail", () => {
  it("filtra por stage o prefijo de issue_id", () => {
    const all: UiOperationalIssue[] = [
      {
        issue_id: "review-errores-1",
        stage: "review",
        category: "correction_required",
        severity: "business",
        recoverable: true,
        title: "Errores",
        user_message: "x",
        location: null,
        value_found: null,
        expected_values: [],
        next_action: null,
        retry: null,
        links: [],
        technical_reference: null,
      },
      {
        issue_id: "amort-2",
        stage: "notify",
        category: "correction_required",
        severity: "business",
        recoverable: true,
        title: "Amort",
        user_message: "y",
        location: null,
        value_found: null,
        expected_values: [],
        next_action: null,
        retry: null,
        links: [],
        technical_reference: null,
      },
      {
        issue_id: "x",
        stage: "amortization",
        category: "correction_required",
        severity: "business",
        recoverable: true,
        title: "Amort stage",
        user_message: "z",
        location: null,
        value_found: null,
        expected_values: [],
        next_action: null,
        retry: null,
        links: [],
        technical_reference: null,
      },
    ];
    const filtered = amortizationIssuesFromDetail(all);
    expect(filtered.map((i) => i.issue_id)).toEqual(["amort-2", "x"]);
  });
});

describe("copy helpers", () => {
  it("formatea banner y resumen del modal", () => {
    expect(formatAmortizationIssuesBanner(2)).toBe("2 problema(s) de amortización.");
    expect(amortizationIssuesJobSummary(1)).toMatch(/1 problema/);
    expect(amortizationIssuesJobSummary(3)).toMatch(/3 problemas/);
  });
});
