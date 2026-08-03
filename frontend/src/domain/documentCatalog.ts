import type { UiDocumentGroup, UiLink } from "../types/contract";
import {
  isAsientosFolderDocumentRel,
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
    } else if (
      link.rel === "asientos" ||
      link.rel === "asientos_folder" ||
      link.rel.startsWith("asientos_folder:")
    ) {
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

export function catalogGroupTitle(group: UiDocumentGroup): string {
  return group.title?.trim() || group.id;
}

export function labelForCatalogLink(link: UiLink): string {
  return operatorDocumentLabel(link);
}

/**
 * Une grupos del backend con merge PDFs derivados de `links`
 * (por si document_groups aún no incluye merge).
 */
export function resolveDocumentGroups(
  backendGroups: readonly UiDocumentGroup[] | null | undefined,
  links: readonly UiLink[],
): UiDocumentGroup[] {
  const fromBackend = [...(backendGroups ?? [])];
  const hasMerge = fromBackend.some((g) => g.id === "merge_pdfs");
  if (!hasMerge) {
    const mergeLinks = links.filter((l) => isMergePdfDocumentRel(l.rel));
    if (mergeLinks.length > 0) {
      fromBackend.unshift({
        id: "merge_pdfs",
        title: "PDFs consolidados",
        count: mergeLinks.length,
        links: mergeLinks,
      });
    }
  }
  return fromBackend
    .map((g) => {
      const links = (g.links ?? []).filter((l) => !isAsientosFolderDocumentRel(l.rel));
      return { ...g, links, count: links.length };
    })
    .filter((g) => {
      if (g.id === "asientos_folders" || g.id.startsWith("asientos_folder")) return false;
      return (g.links?.length ?? 0) > 0;
    });
}
