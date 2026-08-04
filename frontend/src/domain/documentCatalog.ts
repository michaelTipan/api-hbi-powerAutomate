import type { UiDocumentGroup, UiLink } from "../types/contract";
import {
  isAsientosDocumentRel,
  isMergePdfDocumentRel,
  operatorDocumentLabel,
} from "./processPhases";

/** Enlaces 1:1 del lote que siguen como botones directos. */
const SINGLETON_RELS = new Set([
  "review_excel",
  "historical",
  "secretary_file",
  "email_pdf",
  "correos",
]);

export function isSingletonDocumentRel(rel: string): boolean {
  return SINGLETON_RELS.has(rel);
}

export function partitionLinksForPhaseCard(links: readonly UiLink[]): {
  inline: UiLink[];
  mergePdfs: UiLink[];
  asientosFolders: UiLink[];
  other: UiLink[];
} {
  const inline: UiLink[] = [];
  const mergePdfs: UiLink[] = [];
  const asientosFolders: UiLink[] = [];
  const other: UiLink[] = [];
  for (const link of links) {
    if (isMergePdfDocumentRel(link.rel)) {
      mergePdfs.push(link);
    } else if (isAsientosDocumentRel(link.rel)) {
      asientosFolders.push(link);
    } else if (isSingletonDocumentRel(link.rel)) {
      inline.push(link);
    } else {
      other.push(link);
    }
  }
  return { inline, mergePdfs, asientosFolders, other };
}

/** Umbral: 1 link → botón directo; 2+ → resumen + drawer. */
export const CATALOG_DRAWER_THRESHOLD = 2;

export function shouldOpenCatalogDrawer(count: number): boolean {
  return count >= CATALOG_DRAWER_THRESHOLD;
}

/** CTA agrupado (Archivos / Documentos / modal éxito): «Título (N)». */
export function catalogSummaryLabel(title: string, count: number): string {
  return `${title} (${count})`;
}

export function catalogGroupTitle(group: UiDocumentGroup): string {
  return group.title?.trim() || group.id;
}

export function labelForCatalogLink(link: UiLink): string {
  return operatorDocumentLabel(link);
}

/** Rels 1:1 del lote para «Archivos del proceso» (cerrado). */
const PROCESS_ARTIFACT_RELS = new Set([
  "review_excel",
  "historical",
  "secretary_file",
  "email_pdf",
]);

export function isProcessArtifactRel(rel: string): boolean {
  return PROCESS_ARTIFACT_RELS.has(rel);
}

function processArtifactLinksFrom(links: readonly UiLink[]): UiLink[] {
  return links.filter((l) => isProcessArtifactRel(l.rel) && !isAsientosDocumentRel(l.rel));
}

/**
 * Une grupos del backend con merge PDFs / artefactos derivados de `links`
 * (por si document_groups aún no los incluye).
 */
export function resolveDocumentGroups(
  backendGroups: readonly UiDocumentGroup[] | null | undefined,
  links: readonly UiLink[],
): UiDocumentGroup[] {
  const fromBackend = [...(backendGroups ?? [])];
  const hasArtifacts = fromBackend.some((g) => g.id === "process_artifacts");
  if (!hasArtifacts) {
    const artifactLinks = processArtifactLinksFrom(links);
    if (artifactLinks.length > 0) {
      fromBackend.unshift({
        id: "process_artifacts",
        title: "Documentos del lote",
        count: artifactLinks.length,
        links: artifactLinks,
      });
    }
  }
  const hasMerge = fromBackend.some((g) => g.id === "merge_pdfs");
  if (!hasMerge) {
    const mergeLinks = links.filter((l) => isMergePdfDocumentRel(l.rel));
    if (mergeLinks.length > 0) {
      const insertAt = fromBackend.findIndex((g) => g.id === "process_artifacts") + 1;
      const mergeGroup: UiDocumentGroup = {
        id: "merge_pdfs",
        title: "PDFs consolidados",
        count: mergeLinks.length,
        links: mergeLinks,
      };
      if (insertAt > 0) {
        fromBackend.splice(insertAt, 0, mergeGroup);
      } else {
        fromBackend.unshift(mergeGroup);
      }
    }
  }
  return fromBackend.filter((g) => (g.links?.length ?? 0) > 0);
}

/**
 * Catálogo cerrado: documentos del lote + PDF merge + tablas amort;
 * sin carpetas ASIENTOS (obsoletas al cerrar el proceso).
 */
export function processFileCatalogGroups(
  groups: readonly UiDocumentGroup[],
): UiDocumentGroup[] {
  const out: UiDocumentGroup[] = [];
  for (const group of groups) {
    const links = (group.links ?? []).filter((l) => !isAsientosDocumentRel(l.rel));
    if (links.length === 0) continue;
    out.push({
      id: group.id,
      title: group.title,
      count: links.length,
      links,
    });
  }
  return out;
}

/** PDFs consolidados desde detalle o result_summary seguro del job Merge. */
export function mergePdfLinksFromDetail(detail: {
  links?: readonly UiLink[] | null;
  document_groups?: readonly UiDocumentGroup[] | null;
}): UiLink[] {
  const fromLinks = (detail.links ?? []).filter((l) => isMergePdfDocumentRel(l.rel));
  if (fromLinks.length > 0) return [...fromLinks];
  const group = (detail.document_groups ?? []).find((g) => g.id === "merge_pdfs");
  return [...(group?.links ?? [])].filter((l) => isMergePdfDocumentRel(l.rel));
}

/** Tablas de amortización (Excel) desde document_groups del detalle. */
export function amortizationTableLinksFromDetail(detail: {
  links?: readonly UiLink[] | null;
  document_groups?: readonly UiDocumentGroup[] | null;
} | null | undefined): UiLink[] {
  if (!detail) return [];
  const group = (detail.document_groups ?? []).find((g) => g.id === "amortization_tables");
  if (group?.links?.length) {
    return [...group.links].filter((l) => Boolean(l.web_url || l.path));
  }
  // Fallback: rels amort_table / amort_table:N en links planos.
  return (detail.links ?? []).filter(
    (l) =>
      (l.rel === "amort_table" || l.rel.startsWith("amort_table:")) &&
      Boolean(l.web_url || l.path),
  );
}

/** Fallback: links sanitizados en result_summary.merge_pdf_links. */
export function mergePdfLinksFromResultSummary(
  summary: Record<string, unknown> | null | undefined,
): UiLink[] {
  if (!summary || typeof summary !== "object") return [];
  const raw = summary.merge_pdf_links;
  if (!Array.isArray(raw)) return [];
  const out: UiLink[] = [];
  for (let idx = 0; idx < raw.length; idx += 1) {
    const item = raw[idx];
    if (!item || typeof item !== "object") continue;
    const row = item as Record<string, unknown>;
    const webUrl = typeof row.web_url === "string" ? row.web_url.trim() : "";
    const path = typeof row.path === "string" ? row.path.trim() : "";
    if (!webUrl && !path) continue;
    const rel =
      typeof row.rel === "string" && row.rel.trim()
        ? row.rel.trim()
        : raw.length === 1
          ? "merge_pdf"
          : `merge_pdf:${idx}`;
    const label =
      typeof row.label === "string" && row.label.trim()
        ? row.label.trim()
        : "Abrir PDF consolidado";
    out.push({
      rel,
      label,
      path: path || null,
      web_url: webUrl || null,
      open_mode: "sharepoint",
    });
  }
  return out;
}

/** PDF del correo (Notify) desde detalle o document_groups. */
export function emailPdfLinksFromDetail(detail: {
  links?: readonly UiLink[] | null;
  document_groups?: readonly UiDocumentGroup[] | null;
}): UiLink[] {
  const fromLinks = (detail.links ?? []).filter((l) => l.rel === "email_pdf");
  if (fromLinks.length > 0) return [...fromLinks];
  const group = (detail.document_groups ?? []).find((g) => g.id === "process_artifacts");
  return [...(group?.links ?? [])].filter((l) => l.rel === "email_pdf");
}

/** Fallback: links sanitizados en result_summary.email_pdf_links (o path/url). */
export function emailPdfLinksFromResultSummary(
  summary: Record<string, unknown> | null | undefined,
): UiLink[] {
  if (!summary || typeof summary !== "object") return [];
  const raw = summary.email_pdf_links;
  if (Array.isArray(raw)) {
    const out: UiLink[] = [];
    for (const item of raw) {
      if (!item || typeof item !== "object") continue;
      const row = item as Record<string, unknown>;
      const webUrl = typeof row.web_url === "string" ? row.web_url.trim() : "";
      const path = typeof row.path === "string" ? row.path.trim() : "";
      if (!webUrl && !path) continue;
      const rel =
        typeof row.rel === "string" && row.rel.trim() ? row.rel.trim() : "email_pdf";
      const label =
        typeof row.label === "string" && row.label.trim()
          ? row.label.trim()
          : "Ver correo enviado";
      out.push({
        rel,
        label,
        path: path || null,
        web_url: webUrl || null,
        open_mode: "sharepoint",
      });
    }
    if (out.length > 0) return out;
  }
  const path =
    typeof summary.email_pdf_path === "string" ? summary.email_pdf_path.trim() : "";
  const webUrl =
    typeof summary.email_pdf_url === "string" ? summary.email_pdf_url.trim() : "";
  if (!path && !webUrl) return [];
  return [
    {
      rel: "email_pdf",
      label: "Ver correo enviado",
      path: path || null,
      web_url: webUrl || null,
      open_mode: "sharepoint",
    },
  ];
}

const FINALIZE_ARTIFACT_RELS = new Set(["historical", "secretary_file"]);

/** Histórico + soporte asientos tras Finalize (detalle o document_groups). */
export function finalizeArtifactLinksFromDetail(detail: {
  links?: readonly UiLink[] | null;
  document_groups?: readonly UiDocumentGroup[] | null;
}): UiLink[] {
  const fromLinks = (detail.links ?? []).filter((l) => FINALIZE_ARTIFACT_RELS.has(l.rel));
  if (fromLinks.length > 0) return [...fromLinks];
  const group = (detail.document_groups ?? []).find((g) => g.id === "process_artifacts");
  return [...(group?.links ?? [])].filter((l) => FINALIZE_ARTIFACT_RELS.has(l.rel));
}

/**
 * Fallback: paths/URLs del result_summary de Finalize
 * (`historical_file_*`, `secretary_file_*`).
 */
export function finalizeArtifactLinksFromResultSummary(
  summary: Record<string, unknown> | null | undefined,
): UiLink[] {
  if (!summary || typeof summary !== "object") return [];
  const out: UiLink[] = [];
  const histPath =
    typeof summary.historical_file_path === "string"
      ? summary.historical_file_path.trim()
      : "";
  const histUrl =
    typeof summary.historical_file_url === "string"
      ? summary.historical_file_url.trim()
      : "";
  if (histPath || histUrl) {
    out.push({
      rel: "historical",
      label: "Abrir histórico",
      path: histPath || null,
      web_url: histUrl || null,
      open_mode: "sharepoint",
    });
  }
  const secPath =
    typeof summary.secretary_file_path === "string"
      ? summary.secretary_file_path.trim()
      : "";
  const secUrl =
    typeof summary.secretary_file_url === "string"
      ? summary.secretary_file_url.trim()
      : "";
  if (secPath || secUrl) {
    out.push({
      rel: "secretary_file",
      label: "Abrir asientos pendientes",
      path: secPath || null,
      web_url: secUrl || null,
      open_mode: "sharepoint",
    });
  }
  return out;
}

/** Excel de revisión tras Generate / Regenerar. */
export function reviewExcelLinksFromDetail(detail: {
  links?: readonly UiLink[] | null;
  document_groups?: readonly UiDocumentGroup[] | null;
}): UiLink[] {
  const fromLinks = (detail.links ?? []).filter((l) => l.rel === "review_excel");
  if (fromLinks.length > 0) return [...fromLinks];
  const group = (detail.document_groups ?? []).find((g) => g.id === "process_artifacts");
  return [...(group?.links ?? [])].filter((l) => l.rel === "review_excel");
}

/** Fallback: validation_file_path / validation_file_url del job Generate. */
export function reviewExcelLinksFromResultSummary(
  summary: Record<string, unknown> | null | undefined,
): UiLink[] {
  if (!summary || typeof summary !== "object") return [];
  const path =
    typeof summary.validation_file_path === "string"
      ? summary.validation_file_path.trim()
      : "";
  const webUrl =
    typeof summary.validation_file_url === "string"
      ? summary.validation_file_url.trim()
      : "";
  if (!path && !webUrl) return [];
  return [
    {
      rel: "review_excel",
      label: "Abrir archivo de revisión",
      path: path || null,
      web_url: webUrl || null,
      open_mode: "sharepoint",
    },
  ];
}

/** Preferir web_url del detalle; completar rels faltantes desde el summary del job. */
export function resolveLinksPreferDetail(
  fromDetail: readonly UiLink[],
  fromSummary: readonly UiLink[],
): UiLink[] {
  const byRel = new Map<string, UiLink>();
  for (const link of fromSummary) {
    if (link.web_url) byRel.set(link.rel, link);
  }
  for (const link of fromDetail) {
    if (link.web_url) byRel.set(link.rel, link);
  }
  const ordered: UiLink[] = [];
  const seen = new Set<string>();
  for (const source of [fromDetail, fromSummary]) {
    for (const link of source) {
      const hit = byRel.get(link.rel);
      if (!hit || seen.has(hit.rel)) continue;
      ordered.push(hit);
      seen.add(hit.rel);
    }
  }
  return ordered;
}
