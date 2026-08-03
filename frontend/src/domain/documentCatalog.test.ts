import { describe, expect, it } from "vitest";
import type { UiLink } from "../types/contract";
import {
  catalogSummaryLabel,
  emailPdfLinksFromDetail,
  emailPdfLinksFromResultSummary,
  mergePdfLinksFromDetail,
  mergePdfLinksFromResultSummary,
  partitionLinksForPhaseCard,
  processFileCatalogGroups,
  resolveDocumentGroups,
  shouldOpenCatalogDrawer,
} from "./documentCatalog";

function link(rel: string, label = rel): UiLink {
  return {
    rel,
    label,
    path: `${rel}.bin`,
    web_url: `https://example.com/${rel}`,
    open_mode: "sharepoint",
  };
}

describe("documentCatalog", () => {
  it("particiona singletons, merge PDFs y carpetas ASIENTOS", () => {
    const parts = partitionLinksForPhaseCard([
      link("email_pdf", "Correo"),
      link("merge_pdf:0", "PDF 0"),
      link("merge_pdf:1", "PDF 1"),
      link("asientos_folder:0", "ASIENTOS 1"),
      link("asientos_folder:1", "ASIENTOS 2"),
    ]);
    expect(parts.inline.map((l) => l.rel)).toEqual(["email_pdf"]);
    expect(parts.mergePdfs).toHaveLength(2);
    expect(parts.asientosFolders).toHaveLength(2);
  });

  it("drawer desde 2 ítems", () => {
    expect(shouldOpenCatalogDrawer(1)).toBe(false);
    expect(shouldOpenCatalogDrawer(2)).toBe(true);
  });

  it("arma el label agrupado Título (N)", () => {
    expect(catalogSummaryLabel("PDFs consolidados", 24)).toBe("PDFs consolidados (24)");
    expect(catalogSummaryLabel("Tablas de amortización", 3)).toBe(
      "Tablas de amortización (3)",
    );
  });

  it("derive merge + artefactos si el backend no los envió", () => {
    const groups = resolveDocumentGroups(
      [],
      [link("email_pdf"), link("merge_pdf:0"), link("merge_pdf:1")],
    );
    expect(groups.map((g) => g.id)).toEqual(["process_artifacts", "merge_pdfs"]);
    expect(groups[0].links[0].rel).toBe("email_pdf");
    expect(groups[1].count).toBe(2);
  });

  it("Archivos del proceso excluye ASIENTOS y conserva correo/merge/amort", () => {
    const filtered = processFileCatalogGroups([
      {
        id: "process_artifacts",
        title: "Documentos del lote",
        count: 1,
        links: [link("email_pdf")],
      },
      {
        id: "merge_pdfs",
        title: "PDFs consolidados",
        count: 1,
        links: [link("merge_pdf"), link("asientos_folder:0")],
      },
    ]);
    expect(filtered).toHaveLength(2);
    expect(filtered[1].links.map((l) => l.rel)).toEqual(["merge_pdf"]);
  });

  it("extrae merge PDFs del detalle o del result_summary", () => {
    expect(
      mergePdfLinksFromDetail({
        links: [link("email_pdf"), link("merge_pdf")],
      }).map((l) => l.rel),
    ).toEqual(["merge_pdf"]);
    expect(
      mergePdfLinksFromResultSummary({
        merge_pdf_links: [
          {
            rel: "merge_pdf",
            label: "Abrir PDF consolidado",
            path: "m.pdf",
            web_url: "https://sp/m.pdf",
          },
        ],
      })[0]?.web_url,
    ).toBe("https://sp/m.pdf");
  });

  it("extrae email_pdf del detalle, document_groups o result_summary", () => {
    expect(
      emailPdfLinksFromDetail({
        links: [link("email_pdf"), link("merge_pdf")],
      }).map((l) => l.rel),
    ).toEqual(["email_pdf"]);
    expect(
      emailPdfLinksFromDetail({
        links: [],
        document_groups: [
          {
            id: "process_artifacts",
            title: "Documentos del lote",
            count: 1,
            links: [link("email_pdf", "Ver correo enviado")],
          },
        ],
      })[0]?.label,
    ).toBe("Ver correo enviado");
    expect(
      emailPdfLinksFromResultSummary({
        email_pdf_links: [
          {
            rel: "email_pdf",
            label: "Ver correo enviado",
            path: "correo.pdf",
            web_url: "https://sp/correo.pdf",
          },
        ],
      })[0]?.web_url,
    ).toBe("https://sp/correo.pdf");
    expect(
      emailPdfLinksFromResultSummary({
        email_pdf_path: "solo/path.pdf",
        email_pdf_url: "https://sp/solo.pdf",
      })[0],
    ).toMatchObject({
      rel: "email_pdf",
      path: "solo/path.pdf",
      web_url: "https://sp/solo.pdf",
    });
  });
});
