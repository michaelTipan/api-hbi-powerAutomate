/**
 * Copy y helpers de lectura para merge_readiness.missing_items / folder_links.
 * Sin lógica de negocio: solo presentación operativa.
 */

import type { UiLink, UiOperationalIssue } from "../types/contract";

export type MergeFolderLink = {
  rel?: string;
  label?: string;
  path?: string | null;
  web_url?: string | null;
  credito?: string | null;
};

export type MergeMissingItem = {
  credito?: string | null;
  document_type?: string | null;
  error_code?: string | null;
  id_pago?: string | null;
  tipo_aplicacion?: string | null;
  /** Nombre del PDF rechazado (mismatch), si el BE lo envió. */
  found_pdf_name?: string | null;
  /** Crédito sugerido por el nombre del PDF, si difiere del esperado. */
  found_credit_hint?: string | null;
};

/** Texto del indicador «Grupos listos: X de Y · Z pendientes». */
export function formatMergeGroupsProgress(input: {
  ready_groups: number;
  expected_groups: number;
  missing_groups: number;
}): string {
  const pending =
    input.missing_groups > 0 ? ` · ${input.missing_groups} pendientes` : "";
  return `Grupos listos: ${input.ready_groups} de ${input.expected_groups}${pending}.`;
}

/** Mensaje corto por código de faltante (nunca el código crudo al operador). */
export function mergeMissingItemMessage(item: MergeMissingItem): string {
  const code = String(item.error_code || "").trim();
  const credito = String(item.credito || "").trim();
  const foundHint = String(item.found_credit_hint || "").trim();
  const pdfName = String(item.found_pdf_name || "").trim().replace(/_/g, " ");

  switch (code) {
    case "asiento_contable_credit_mismatch":
      if (credito && foundHint && foundHint !== credito) {
        return (
          `El PDF en la carpeta del crédito ${credito} parece ser del crédito ${foundHint}: ` +
          "el nombre no coincide."
        );
      }
      if (credito && pdfName) {
        return (
          `El archivo «${pdfName}» en la carpeta del crédito ${credito} ` +
          "no coincide con ese crédito."
        );
      }
      if (credito) {
        return (
          `Hay un PDF en la carpeta del crédito ${credito}, ` +
          "pero el nombre no coincide con ese crédito."
        );
      }
      return "Hay un PDF en la carpeta, pero el nombre no coincide con el crédito.";
    case "asiento_contable_not_found":
      return credito
        ? `Falta el PDF del asiento contable en la carpeta ASIENTOS del crédito ${credito}.`
        : "Falta el PDF del asiento contable en la carpeta ASIENTOS.";
    case "missing_ruta_asientos_contables":
      return credito
        ? `No hay ruta de carpeta ASIENTOS para el crédito ${credito}.`
        : "No hay ruta de carpeta ASIENTOS para este crédito.";
    case "extract_routes_missing":
      return "Falta la ruta del extracto bancario.";
    case "asientos_list_failed":
      return "No se pudo leer la carpeta ASIENTOS. Verifique e intente de nuevo.";
    default:
      return "Falta un documento requerido para consolidar.";
  }
}

/** Enlace ASIENTOS del crédito (match exacto por dígitos). */
export function folderLinkForCredito(
  folderLinks: readonly MergeFolderLink[],
  credito: string | null | undefined,
): MergeFolderLink | null {
  const want = String(credito || "").trim();
  if (!want) return null;
  for (const folder of folderLinks) {
    if (String(folder.credito || "").trim() === want) {
      return folder;
    }
  }
  return null;
}

export function parseMergeMissingItems(
  raw: ReadonlyArray<Record<string, unknown>> | null | undefined,
): MergeMissingItem[] {
  if (!raw || raw.length === 0) return [];
  return raw.map((row) => ({
    credito: row.credito == null ? null : String(row.credito),
    document_type: row.document_type == null ? null : String(row.document_type),
    error_code: row.error_code == null ? null : String(row.error_code),
    id_pago: row.id_pago == null ? null : String(row.id_pago),
    tipo_aplicacion: row.tipo_aplicacion == null ? null : String(row.tipo_aplicacion),
    found_pdf_name: row.found_pdf_name == null ? null : String(row.found_pdf_name),
    found_credit_hint:
      row.found_credit_hint == null ? null : String(row.found_credit_hint),
  }));
}

/**
 * ¿Mostrar banner de errores de soportes?
 * incomplete|unknown con missing_items; nunca si ready / already_merged / sin items.
 * Además requiere verificación explícita del operador (no al entrar por primera vez).
 */
export function shouldShowMergeSupportErrors(
  status: string | null | undefined,
  missingItems: readonly MergeMissingItem[],
  opts?: { supportsVerified?: boolean },
): boolean {
  if (opts?.supportsVerified === false) return false;
  const norm = String(status || "").trim().toLowerCase();
  if (norm !== "incomplete" && norm !== "unknown") return false;
  return missingItems.length > 0;
}

/** Tono visual del chip «Grupos listos» (alineado a statusTone: ok/warn/neutral). */
export function mergeGroupsProgressTone(
  status: string | null | undefined,
): "complete" | "pending" | "unknown" {
  const norm = String(status || "").trim().toLowerCase();
  if (norm === "ready" || norm === "already_merged") return "complete"; // → verde (ok)
  if (norm === "incomplete") return "pending"; // → ámbar (warn)
  return "unknown"; // → gris (neutral)
}

/** Convierte faltantes de merge a issues del modal operativo (mismo patrón Errores). */
export function buildMergeSupportOperationalIssues(
  missingItems: readonly MergeMissingItem[],
  folderLinks: readonly MergeFolderLink[],
): UiOperationalIssue[] {
  return missingItems.map((item, index) => {
    const credito = String(item.credito || "").trim();
    const folder = folderLinkForCredito(folderLinks, credito);
    const links: UiLink[] = [];
    if (folder && ((folder.web_url || "").trim() || (folder.path || "").trim())) {
      links.push({
        rel: "asientos",
        label: "Abrir carpeta ASIENTOS",
        path: folder.path ?? null,
        web_url: folder.web_url ?? null,
        open_mode: "sharepoint",
      });
    }
    const title = credito
      ? `Documento contable · Crédito ${credito}`
      : "Documento contable";
    return {
      issue_id: `merge-support-${credito || "x"}-${item.error_code || "x"}-${index}`,
      stage: "merge",
      category: "correction_required",
      severity: "business",
      recoverable: true,
      title,
      user_message: mergeMissingItemMessage(item),
      // Sin meta de ubicación / IDs / valores esperados / detalle técnico en el modal.
      location: null,
      value_found: null,
      expected_values: [],
      next_action: null,
      retry: null,
      links,
      technical_reference: item.error_code ?? null,
    };
  });
}

/** Estado operativo por carpeta ASIENTOS (drawer). */
export type AsientosFolderStatus = "ready" | "missing" | "unknown";

export type AsientosCatalogItem = {
  rel: string;
  label: string;
  path: string | null;
  web_url: string | null;
  open_mode: "sharepoint";
  credito: string | null;
  status: AsientosFolderStatus;
  statusLabel: string;
  statusDetail: string | null;
};

function missingForCredito(
  missingItems: readonly MergeMissingItem[],
  credito: string,
): MergeMissingItem | null {
  const want = credito.trim();
  if (!want) return null;
  for (const item of missingItems) {
    if (String(item.credito || "").trim() === want) {
      return item;
    }
  }
  return null;
}

/**
 * Lista del drawer «Carpetas ASIENTOS»: una fila por carpeta con listo/falta.
 * Usa missing_items + folder_links del último GET de readiness.
 * Sin verificación explícita, no marca faltantes (el operador aún no comprobó).
 */
export function buildAsientosCatalogItems(
  folderLinks: readonly MergeFolderLink[],
  missingItems: readonly MergeMissingItem[],
  readinessStatus?: string | null,
  opts?: { supportsVerified?: boolean },
): AsientosCatalogItem[] {
  const statusNorm = String(readinessStatus || "").trim().toLowerCase();
  const allReady = statusNorm === "ready" || statusNorm === "already_merged";
  const unknown = statusNorm === "unknown" || !statusNorm;
  // Por defecto true (tests unitarios); la página pasa false hasta verificar.
  const supportsVerified = opts?.supportsVerified !== false;

  return folderLinks
    .filter((folder) => Boolean((folder.path || "").trim() || (folder.web_url || "").trim()))
    .map((folder, index) => {
      const credito = String(folder.credito || "").trim() || null;
      const baseLabel = (folder.label || "Carpeta de documentos contables").trim();
      const label = credito ? `${baseLabel} · Crédito ${credito}` : baseLabel;
      const missing = credito ? missingForCredito(missingItems, credito) : null;

      let status: AsientosFolderStatus;
      let statusLabel: string;
      let statusDetail: string | null = null;

      if (!supportsVerified && !allReady) {
        // Primera entrada / pre-verificar: no alarmar con faltantes aún.
        status = "unknown";
        statusLabel = "Sin verificar";
        statusDetail =
          "Use «Actualizar / verificar soportes» para comprobar si el documento ya está en la carpeta.";
      } else if (missing) {
        status = "missing";
        statusLabel = "Falta documento";
        statusDetail = mergeMissingItemMessage(missing);
      } else if (allReady) {
        status = "ready";
        statusLabel = "Listo";
      } else if (unknown) {
        status = "unknown";
        statusLabel = "Sin verificar";
        statusDetail = "Actualice para comprobar si el documento ya está en la carpeta.";
      } else {
        // incomplete sin faltante para este crédito → listo
        status = "ready";
        statusLabel = "Listo";
      }

      return {
        rel: `asientos_folder:${index}`,
        label,
        path: folder.path ?? null,
        web_url: folder.web_url ?? null,
        open_mode: "sharepoint" as const,
        credito,
        status,
        statusLabel,
        statusDetail,
      };
    });
}
