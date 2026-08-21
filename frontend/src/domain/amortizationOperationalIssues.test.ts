import { describe, expect, it } from "vitest";
import type { UiJobView, UiOperationalIssue } from "../types/contract";
import {
  amortizationIssuesFromDetail,
  amortizationIssuesJobSummary,
  buildAmortizationOperationalIssuesFromJob,
  formatAmortizationIssuesBanner,
  hydrateAmortizationIssueLinks,
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

  it("silencia BANK_ASIENTOS_NO_CUADRAN sin sintetizar fallback", () => {
    const issues = buildAmortizationOperationalIssuesFromJob(
      baseJob({
        result_summary: {
          outcome: "requires_correction",
          can_apply: true,
          operational_issues: [
            {
              issue_id: "amort-BANK_ASIENTOS_NO_CUADRAN-248-0",
              stage: "amortization",
              category: "warning",
              severity: "info",
              recoverable: true,
              title: "Crédito 248",
              user_message:
                "El total de asientos no cuadra con el monto bancario del pago.",
              location: null,
              value_found: null,
              expected_values: [],
              next_action: "Se aplicará según los asientos.",
              retry: null,
              links: [],
              technical_reference: "BANK_ASIENTOS_NO_CUADRAN",
            },
          ],
        },
      }),
    );
    expect(issues).toEqual([]);
  });
});

describe("amortizationIssuesFromDetail", () => {
  it("omite BANK_ASIENTOS_NO_CUADRAN del modal", () => {
    const filtered = amortizationIssuesFromDetail([
      {
        issue_id: "amort-BANK-1",
        stage: "amortization",
        category: "warning",
        severity: "info",
        recoverable: true,
        title: "Crédito 248",
        user_message: "El total de asientos no cuadra con el monto bancario.",
        location: null,
        value_found: null,
        expected_values: [],
        next_action: null,
        retry: null,
        links: [],
        technical_reference: "BANK_ASIENTOS_NO_CUADRAN",
      },
      {
        issue_id: "amort-2",
        stage: "amortization",
        category: "correction_required",
        severity: "business",
        recoverable: true,
        title: "Tabla",
        user_message: "Falta la tabla.",
        location: null,
        value_found: null,
        expected_values: [],
        next_action: null,
        retry: null,
        links: [],
        technical_reference: "TABLE_PATH_NOT_FOUND",
      },
    ]);
    expect(filtered).toHaveLength(1);
    expect(filtered[0].technical_reference).toBe("TABLE_PATH_NOT_FOUND");
  });

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

describe("hydrateAmortizationIssueLinks", () => {
  const issue = (overrides: Partial<UiOperationalIssue> = {}): UiOperationalIssue => ({
    issue_id: "amort-1",
    stage: "amortization",
    category: "correction_required",
    severity: "business",
    recoverable: true,
    title: "Documento contable · Crédito 264",
    user_message: "El PDF no tiene el formato esperado.",
    location: {
      file_name: "asiento.pdf",
      sheet: null,
      row: null,
      column: null,
      credit: "264",
      payment_id: "P1",
      client_name: null,
      file_etag: null,
      file_size: null,
      file_last_modified: null,
    },
    value_found: null,
    expected_values: [],
    next_action: "Reemplace el PDF y reconsolide.",
    retry: null,
    links: [],
    technical_reference: "ACCOUNTING_PARSE_FAILED",
    ...overrides,
  });

  it("completa web_url desde merge_readiness del mismo crédito", () => {
    const hydrated = hydrateAmortizationIssueLinks([issue()], {
      links: [],
      merge_readiness: {
        status: "already_merged",
        expected_groups: 1,
        ready_groups: 1,
        missing_groups: 0,
        missing_items: [],
        folder_links: [
          {
            rel: "asientos",
            label: "Carpeta ASIENTOS",
            path: "clientes/X/CREDITO # 264/ASIENTOS",
            web_url: "https://sp/asientos-264",
            credito: "264",
          },
        ],
        user_message: "",
        next_action: "",
        checked_at: null,
      },
    });
    expect(hydrated[0].links).toHaveLength(1);
    expect(hydrated[0].links[0]?.web_url).toBe("https://sp/asientos-264");
    expect(hydrated[0].links[0]?.label).toMatch(/264/);
  });

  it("si el issue no trae links, usa asientos pendientes como último recurso", () => {
    const hydrated = hydrateAmortizationIssueLinks(
      [issue({ location: null, technical_reference: "preflight_errors" })],
      {
        links: [
          {
            rel: "secretary_file",
            label: "Abrir asientos pendientes",
            path: "logs/pendientes.xlsx",
            web_url: "https://sp/pendientes.xlsx",
            open_mode: "sharepoint",
          },
        ],
      },
    );
    expect(hydrated[0].links[0]?.rel).toBe("secretary_file");
    expect(hydrated[0].links[0]?.web_url).toBe("https://sp/pendientes.xlsx");
  });
});
