import { describe, expect, it } from "vitest";
import {
  folderLinkForCredito,
  formatMergeGroupsProgress,
  mergeMissingItemMessage,
  parseMergeMissingItems,
  buildAsientosCatalogItems,
  buildMergeSupportOperationalIssues,
  shouldShowMergeSupportErrors,
} from "./mergeReadinessCopy";

describe("formatMergeGroupsProgress", () => {
  it("incluye pendientes cuando faltan grupos", () => {
    expect(
      formatMergeGroupsProgress({
        ready_groups: 0,
        expected_groups: 2,
        missing_groups: 2,
      }),
    ).toBe("Grupos listos: 0 de 2 · 2 pendientes.");
  });

  it("omite el sufijo pendientes cuando todo está listo", () => {
    expect(
      formatMergeGroupsProgress({
        ready_groups: 2,
        expected_groups: 2,
        missing_groups: 0,
      }),
    ).toBe("Grupos listos: 2 de 2.");
  });
});

describe("mergeMissingItemMessage", () => {
  it("distingue ausencia vs mismatch", () => {
    expect(
      mergeMissingItemMessage({ error_code: "asiento_contable_not_found" }),
    ).toMatch(/Falta el PDF/i);
    expect(
      mergeMissingItemMessage({ error_code: "asiento_contable_credit_mismatch" }),
    ).toMatch(/nombre no coincide/i);
  });

  it("explica mismatch 258-en-264 con copy de negocio", () => {
    const msg = mergeMissingItemMessage({
      error_code: "asiento_contable_credit_mismatch",
      credito: "264",
      found_credit_hint: "258",
      found_pdf_name: "asiento_banco_bogota_credito-258.pdf",
    });
    expect(msg).toMatch(/crédito 264/i);
    expect(msg).toMatch(/crédito 258/i);
    expect(msg).not.toContain("asiento_contable_credit_mismatch");
  });

  it("no expone el código crudo en el respaldo", () => {
    const msg = mergeMissingItemMessage({ error_code: "codigo_raro_xyz" });
    expect(msg).not.toContain("codigo_raro_xyz");
    expect(msg.length).toBeGreaterThan(10);
  });
});

describe("folderLinkForCredito", () => {
  const folders = [
    { credito: "100", web_url: "https://sp/100", path: "a/100" },
    { credito: "200", web_url: "https://sp/200", path: "a/200" },
  ];

  it("empareja por dígitos de crédito", () => {
    expect(folderLinkForCredito(folders, "200")?.web_url).toBe("https://sp/200");
  });

  it("devuelve null si no hay match", () => {
    expect(folderLinkForCredito(folders, "999")).toBeNull();
    expect(folderLinkForCredito(folders, "")).toBeNull();
  });
});

describe("parseMergeMissingItems", () => {
  it("normaliza campos desconocidos a string|null", () => {
    const items = parseMergeMissingItems([
      {
        credito: 258,
        error_code: "asiento_contable_not_found",
        found_pdf_name: "x.pdf",
        found_credit_hint: 999,
      },
    ]);
    expect(items[0]).toEqual({
      credito: "258",
      document_type: null,
      error_code: "asiento_contable_not_found",
      id_pago: null,
      tipo_aplicacion: null,
      found_pdf_name: "x.pdf",
      found_credit_hint: "999",
    });
  });
});

describe("shouldShowMergeSupportErrors", () => {
  it("solo con incomplete|unknown y missing_items", () => {
    const items = [{ error_code: "asiento_contable_not_found", credito: "1" }];
    expect(shouldShowMergeSupportErrors("incomplete", items)).toBe(true);
    expect(shouldShowMergeSupportErrors("unknown", items)).toBe(true);
    expect(shouldShowMergeSupportErrors("ready", items)).toBe(false);
    expect(shouldShowMergeSupportErrors("already_merged", items)).toBe(false);
    expect(shouldShowMergeSupportErrors("incomplete", [])).toBe(false);
  });
});

describe("buildMergeSupportOperationalIssues", () => {
  it("arma issues con link ASIENTOS y mensaje humanizado", () => {
    const issues = buildMergeSupportOperationalIssues(
      [
        {
          credito: "264",
          error_code: "asiento_contable_credit_mismatch",
          found_credit_hint: "258",
          found_pdf_name: "asiento_banco_bogota_credito-258.pdf",
        },
      ],
      [
        {
          credito: "264",
          path: "clientes/264/ASIENTOS",
          web_url: "https://sp/asientos/264",
        },
      ],
    );
    expect(issues).toHaveLength(1);
    expect(issues[0].title).toMatch(/Crédito 264/);
    expect(issues[0].user_message).toMatch(/258/);
    expect(issues[0].links[0]?.label).toMatch(/Abrir carpeta ASIENTOS/i);
    expect(issues[0].links[0]?.web_url).toBe("https://sp/asientos/264");
    expect(issues[0].technical_reference).toBe("asiento_contable_credit_mismatch");
  });
});

describe("buildAsientosCatalogItems", () => {
  it("marca listo vs falta por crédito", () => {
    const items = buildAsientosCatalogItems(
      [
        { credito: "100", label: "Carpeta", path: "a/100", web_url: "https://sp/100" },
        { credito: "200", label: "Carpeta", path: "a/200", web_url: "https://sp/200" },
      ],
      [{ credito: "100", error_code: "asiento_contable_not_found" }],
      "incomplete",
    );
    expect(items).toHaveLength(2);
    expect(items[0].status).toBe("missing");
    expect(items[0].statusLabel).toBe("Falta documento");
    expect(items[0].statusDetail).toMatch(/Falta el PDF/i);
    expect(items[1].status).toBe("ready");
    expect(items[1].statusLabel).toBe("Listo");
  });

  it("con readiness ready marca todas listo", () => {
    const items = buildAsientosCatalogItems(
      [{ credito: "1", path: "a/1", web_url: "https://sp/1" }],
      [],
      "ready",
    );
    expect(items[0].status).toBe("ready");
  });
});
