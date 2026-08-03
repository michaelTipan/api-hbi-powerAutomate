import { describe, expect, it } from "vitest";
import type { UiLink } from "../types/contract";
import {
  partitionLinksForPhaseCard,
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

  it("derive merge group si el backend no lo envió", () => {
    const groups = resolveDocumentGroups([], [link("merge_pdf:0"), link("merge_pdf:1")]);
    expect(groups).toHaveLength(1);
    expect(groups[0].id).toBe("merge_pdfs");
    expect(groups[0].count).toBe(2);
  });
});
