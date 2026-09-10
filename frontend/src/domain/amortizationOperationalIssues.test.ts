import { describe, expect, it } from "vitest";
import type { UiJobView, UiOperationalIssue } from "../types/contract";
import {
  amortizationIssuesFromDetail,
  amortizationIssuesJobSummary,
  amortizationIssuesProjectionFresh,
  buildAmortizationOperationalIssuesFromJob,
  formatAmortizationIssuesBanner,
  hydrateAmortizationIssueLinks,
  parseOperationalIssuesFromUnknown,
  resolveAmortizationDisplayIssues,
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

  it("silencia PAYOFF_NOT_ACHIEVED sin sintetizar fallback", () => {
    const issues = buildAmortizationOperationalIssuesFromJob(
      baseJob({
        result_summary: {
          outcome: "requires_correction",
          can_apply: true,
          operational_issues: [
            {
              issue_id: "amort-PAYOFF_NOT_ACHIEVED-258-0",
              stage: "amortization",
              category: "warning",
              severity: "info",
              recoverable: true,
              title: "Crédito 258",
              user_message:
                "La cancelación no deja el crédito en cero según el asiento.",
              location: null,
              value_found: null,
              expected_values: [],
              next_action: "Se aplicará el asiento igual.",
              retry: null,
              links: [],
              technical_reference: "PAYOFF_NOT_ACHIEVED",
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

  it("omite PAYOFF_NOT_ACHIEVED del modal", () => {
    const filtered = amortizationIssuesFromDetail([
      {
        issue_id: "amort-PAYOFF-1",
        stage: "amortization",
        category: "warning",
        severity: "info",
        recoverable: true,
        title: "Crédito 258",
        user_message: "Pago total sin cancelación completa del saldo.",
        location: null,
        value_found: null,
        expected_values: [],
        next_action: null,
        retry: null,
        links: [],
        technical_reference: "PAYOFF_NOT_ACHIEVED",
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

  it("errores no identificados enlazan asientos pendientes, no el PDF consolidado", () => {
    const hydrated = hydrateAmortizationIssueLinks(
      [issue({ technical_reference: "WEIRD_UNKNOWN_CODE", links: [] })],
      {
        links: [
          {
            rel: "merge_pdf",
            label: "Abrir PDF consolidado",
            path: "merge/295.pdf",
            web_url: "https://sp/295.pdf",
            open_mode: "sharepoint",
          },
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
    expect(hydrated[0].links).toHaveLength(1);
    expect(hydrated[0].links[0]?.rel).toBe("secretary_file");
    expect(hydrated[0].links.some((l) => l.rel === "merge_pdf")).toBe(false);
  });

  it("POST_UPLOAD_VERIFICATION_FAILED enlaza la tabla, no el consolidado", () => {
    const hydrated = hydrateAmortizationIssueLinks(
      [
        issue({
          technical_reference: "POST_UPLOAD_VERIFICATION_FAILED",
          links: [],
          location: {
            file_name: "tabla.xlsx",
            sheet: null,
            row: null,
            column: null,
            credit: "295",
            payment_id: "P1",
            client_name: null,
            file_etag: null,
            file_size: null,
            file_last_modified: null,
          },
        }),
      ],
      {
        links: [
          {
            rel: "merge_pdf",
            label: "Abrir PDF consolidado",
            path: "merge/295.pdf",
            web_url: "https://sp/295.pdf",
            open_mode: "sharepoint",
          },
          {
            rel: "amortization_table",
            label: "Abrir tabla · Crédito 295",
            path: "clientes/N/tabla.xlsx",
            web_url: "https://sp/tabla-295.xlsx",
            open_mode: "sharepoint",
          },
        ],
      },
    );
    expect(hydrated[0].links[0]?.rel).toBe("amortization_table");
    expect(hydrated[0].links.some((l) => l.rel === "merge_pdf")).toBe(false);
  });

  it("PREFLIGHT_ITEM_ERROR no identificado enlaza asientos pendientes", () => {
    const hydrated = hydrateAmortizationIssueLinks(
      [issue({ technical_reference: "PREFLIGHT_ITEM_ERROR", links: [] })],
      {
        links: [
          {
            rel: "asientos",
            label: "Abrir carpeta ASIENTOS · Crédito 264",
            path: "clientes/X/CREDITO # 264/ASIENTOS",
            web_url: "https://sp/asientos-264",
            open_mode: "sharepoint",
          },
          {
            rel: "merge_pdf",
            label: "Abrir PDF consolidado",
            path: "merge/264.pdf",
            web_url: "https://sp/264.pdf",
            open_mode: "sharepoint",
          },
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
    expect(hydrated[0].links).toHaveLength(1);
    expect(hydrated[0].links[0]?.rel).toBe("secretary_file");
    expect(hydrated[0].links.some((l) => l.rel === "asientos")).toBe(false);
    expect(hydrated[0].links.some((l) => l.rel === "merge_pdf")).toBe(false);
  });

  it("ACCOUNTING_PARSE_FAILED sigue enlazando ASIENTOS", () => {
    const hydrated = hydrateAmortizationIssueLinks([issue()], {
      links: [
        {
          rel: "asientos",
          label: "Abrir carpeta ASIENTOS · Crédito 264",
          path: "clientes/X/CREDITO # 264/ASIENTOS",
          web_url: "https://sp/asientos-264",
          open_mode: "sharepoint",
        },
        {
          rel: "secretary_file",
          label: "Abrir asientos pendientes",
          path: "logs/pendientes.xlsx",
          web_url: "https://sp/pendientes.xlsx",
          open_mode: "sharepoint",
        },
      ],
    });
    expect(hydrated[0].links[0]?.rel).toBe("asientos");
    expect(hydrated[0].links[0]?.web_url).toBe("https://sp/asientos-264");
  });
});

describe("resolveAmortizationDisplayIssues", () => {
  const staleIssue = (id: string, msg: string) => ({
    issue_id: id,
    stage: "amortization",
    category: "correction_required" as const,
    severity: "business" as const,
    recoverable: true,
    title: id,
    user_message: msg,
    location: null,
    value_found: null,
    expected_values: [],
    next_action: null,
    retry: null,
    links: [],
    technical_reference: null,
  });

  it("prioriza issues efímeros del job sobre last_amortization_attempt stale", () => {
    const fresh = [staleIssue("amort-fresh-1", "Solo queda este error.")];
    const resolved = resolveAmortizationDisplayIssues({
      last_amortization_attempt: {
        attempt_id: "old-job",
        outcome: "requires_correction",
        created_at: null,
        operational_issues: [
          staleIssue("amort-old-1", "Error viejo 1"),
          staleIssue("amort-old-2", "Error viejo 2"),
          staleIssue("amort-old-3", "Error viejo 3"),
        ],
        affected_payment_ids: [],
        user_message: null,
        next_action: null,
      },
      operational_issues: [],
      ephemeralIssues: fresh,
    });
    expect(resolved).toHaveLength(1);
    expect(resolved[0].issue_id).toBe("amort-fresh-1");
  });

  it("usa last_amortization_attempt si no hay efímeros", () => {
    const resolved = resolveAmortizationDisplayIssues({
      last_amortization_attempt: {
        attempt_id: "persisted",
        outcome: "requires_correction",
        created_at: null,
        operational_issues: [staleIssue("amort-persisted", "Persistido.")],
        affected_payment_ids: [],
        user_message: null,
        next_action: null,
      },
      operational_issues: [],
      ephemeralIssues: [],
    });
    expect(resolved).toHaveLength(1);
    expect(resolved[0].issue_id).toBe("amort-persisted");
  });

  it("amortizationIssuesProjectionFresh exige attempt_id e issue_ids del job", () => {
    const jobIssue = (id: string) => ({
      issue_id: id,
      stage: "amortization",
      category: "correction_required" as const,
      severity: "business" as const,
      recoverable: true,
      title: id,
      user_message: "Nuevo.",
      location: null,
      value_found: null,
      expected_values: [],
      next_action: null,
      retry: null,
      links: [],
      technical_reference: null,
    });
    const job: UiJobView = {
      ...baseJob({ job_id: "job-amort-retry" }),
      result_summary: {
        outcome: "requires_correction",
        operational_issues: [jobIssue("amort-fresh-128"), jobIssue("amort-fresh-16")],
      },
    };
    expect(
      amortizationIssuesProjectionFresh(
        {
          last_amortization_attempt: {
            attempt_id: "job-amort-old",
            outcome: "requires_correction",
            created_at: null,
            operational_issues: [jobIssue("amort-old-128")],
            affected_payment_ids: [],
            user_message: null,
            next_action: null,
          },
        },
        job,
      ),
    ).toBe(false);
    expect(
      amortizationIssuesProjectionFresh(
        {
          last_amortization_attempt: {
            attempt_id: "job-amort-retry",
            outcome: "requires_correction",
            created_at: null,
            operational_issues: [jobIssue("amort-old-128"), jobIssue("amort-old-16")],
            affected_payment_ids: [],
            user_message: null,
            next_action: null,
          },
        },
        job,
      ),
    ).toBe(false);
    expect(
      amortizationIssuesProjectionFresh(
        {
          last_amortization_attempt: {
            attempt_id: "job-amort-retry",
            outcome: "requires_correction",
            created_at: null,
            operational_issues: [jobIssue("amort-fresh-128"), jobIssue("amort-fresh-16")],
            affected_payment_ids: [],
            user_message: null,
            next_action: null,
          },
        },
        job,
      ),
    ).toBe(true);
  });
});
