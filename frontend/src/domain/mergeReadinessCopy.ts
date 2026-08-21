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
  observed_pdfs?: readonly MergeObservedPdf[] | null;
  list_ok?: boolean | null;
};

export type MergeObservedPdf = {
  name?: string | null;
  size?: number | null;
  etag?: string | null;
  last_modified?: string | null;
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
  return `Grupos listos: ${input.ready_groups} de ${input.expected_groups}${pending}`;
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
    case "PDF_TEXT_NOT_EXTRACTABLE":
      return credito
        ? `El PDF del crédito ${credito} no trae texto que se pueda leer.`
        : "El PDF no trae texto que se pueda leer.";
    case "ACCOUNTING_PARSE_FAILED":
      return credito
        ? `El PDF del crédito ${credito} no tiene el formato de asiento esperado.`
        : "El PDF no tiene el formato de asiento esperado.";
    case "MISSING_BANK_VALUE_BUT_HAS_ACCOUNTING_LINES":
      return credito
        ? `El asiento del crédito ${credito} no trae la línea del recaudo del banco.`
        : "El asiento no trae la línea del recaudo del banco.";
    case "asiento_download_failed":
      return credito
        ? `No se pudo descargar el PDF del asiento del crédito ${credito}.`
        : "No se pudo descargar el PDF del asiento.";
    case "missing_ruta_asientos_contables":
      return credito
        ? `No hay ruta de carpeta ASIENTOS para el crédito ${credito}.`
        : "No hay ruta de carpeta ASIENTOS para este crédito.";
    case "extract_routes_missing":
      return credito
        ? `Falta el extracto PDF del crédito ${credito} (ruta vacía o archivo ausente).`
        : "Falta la ruta del extracto bancario o el PDF no está en SharePoint.";
    case "asientos_list_failed":
      return "No se pudo leer la carpeta ASIENTOS. Verifique e intente de nuevo.";
    case "ASIENTO_ASSIGNMENT_PARSE_FAILED":
      return credito
        ? `Hay un PDF de asiento del crédito ${credito} que no se pudo leer como asiento contable.`
        : "Hay un PDF de asiento que no se pudo leer como asiento contable.";
    case "ASIENTO_ASSIGNMENT_NO_MATCH":
      return credito
        ? `Los montos de los asientos del crédito ${credito} no cuadran con el monto banco del pago.`
        : "Los montos de los asientos no cuadran con el monto banco del pago.";
    case "ASIENTO_ASSIGNMENT_AMBIGUOUS":
      return credito
        ? `Hay más de una forma de cuadrar los asientos del crédito ${credito} con los pagos del lote.`
        : "Hay más de una forma de cuadrar los asientos con los pagos del lote.";
    case "ASIENTO_ASSIGNMENT_COMPLEXITY_LIMIT":
      return "Hay demasiadas combinaciones posibles entre asientos y pagos. Deje en ASIENTOS solo los de este lote.";
    default:
      return credito
        ? `Falta un documento requerido para consolidar el crédito ${credito}.`
        : "Falta un documento requerido para consolidar.";
  }
}

/** Acción corta por faltante (el botón de carpeta va en el panel). */
export function mergeMissingItemNextAction(item: MergeMissingItem): string | null {
  const code = String(item.error_code || "").trim();
  switch (code) {
    case "extract_routes_missing":
      return "Verifique el extracto en la carpeta del crédito y vuelva a unir PDFs.";
    case "ASIENTO_ASSIGNMENT_PARSE_FAILED":
      return "Reemplace el PDF por la exportación del ERP con texto seleccionable y vuelva a unir PDFs.";
    case "ASIENTO_ASSIGNMENT_NO_MATCH":
    case "ASIENTO_ASSIGNMENT_AMBIGUOUS":
    case "ASIENTO_ASSIGNMENT_COMPLEXITY_LIMIT":
      return "Deje en ASIENTOS solo los PDF de este lote y vuelva a unir PDFs.";
    case "asiento_contable_not_found":
    case "asiento_contable_credit_mismatch":
    case "missing_ruta_asientos_contables":
      return "Cargue o corrija el asiento en ASIENTOS y vuelva a unir PDFs.";
    case "PDF_TEXT_NOT_EXTRACTABLE":
    case "ACCOUNTING_PARSE_FAILED":
    case "MISSING_BANK_VALUE_BUT_HAS_ACCOUNTING_LINES":
      return "Reemplace el PDF por la exportación del ERP con texto seleccionable y vuelva a verificar.";
    case "asiento_download_failed":
      return "Verifique que el archivo exista en SharePoint y vuelva a verificar.";
    default:
      return "Corrija el documento indicado y vuelva a unir PDFs.";
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
 * ¿Mostrar banner de errores de asientos contables?
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
      location: credito
        ? {
            file_name: null,
            sheet: null,
            row: null,
            column: null,
            credit: credito,
            payment_id: item.id_pago ?? null,
            client_name: null,
          }
        : null,
      value_found: null,
      expected_values: [],
      next_action: mergeMissingItemNextAction(item),
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
          "Use «Actualizar / verificar asientos contables» para comprobar si el documento ya está en la carpeta.";
      } else if (missing) {
        const fmt = String(missing.error_code || "").trim();
        const isFormat =
          fmt === "PDF_TEXT_NOT_EXTRACTABLE" ||
          fmt === "ACCOUNTING_PARSE_FAILED" ||
          fmt === "MISSING_BANK_VALUE_BUT_HAS_ACCOUNTING_LINES";
        status = "missing";
        statusLabel = isFormat ? "Documento no usable" : "Falta documento";
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

/** Filtra carpetas ASIENTOS a créditos afectados por issues de amortización. */
export function filterFolderLinksForAmortRecovery(
  folderLinks: readonly MergeFolderLink[],
  issues: readonly UiOperationalIssue[],
): { filtered: MergeFolderLink[]; hasFilter: boolean } {
  const credits = new Set<string>();
  for (const issue of issues) {
    const credit = String(issue.location?.credit || "").trim();
    if (credit) credits.add(credit);
  }
  if (credits.size === 0) {
    return { filtered: [...folderLinks], hasFilter: false };
  }
  const filtered = folderLinks.filter((folder) =>
    credits.has(String(folder.credito || "").trim()),
  );
  if (filtered.length === 0) {
    return { filtered: [...folderLinks], hasFilter: false };
  }
  return { filtered, hasFilter: filtered.length < folderLinks.length };
}

export type RecoveryVerifyKind =
  | "unchanged"
  | "replaced"
  | "missing"
  | "mismatch"
  | "unknown";

export type RecoveryVerifyItem = {
  credit: string;
  kind: RecoveryVerifyKind;
  messageKey:
    | "recovery_verify_unchanged"
    | "recovery_verify_replaced"
    | "recovery_verify_missing"
    | "recovery_verify_mismatch"
    | "recovery_verify_unknown";
};

function creditDigitsInName(name: string, credit: string): boolean {
  const digits = credit.replace(/\D/g, "");
  if (!digits) return false;
  const nameDigits = name.replace(/\D/g, "");
  // Evitar substring falso (crédito "2" en "264"): buscar token del crédito.
  const re = new RegExp(`(?:^|\\D)${digits}(?:\\D|$)`);
  return re.test(name) || nameDigits.includes(digits);
}

function metaChanged(
  snap: {
    file_name?: string | null;
    file_etag?: string | null;
    file_size?: number | null;
    file_last_modified?: string | null;
  },
  pdf: MergeObservedPdf,
): boolean {
  const snapName = String(snap.file_name || "").trim().toLowerCase();
  const pdfName = String(pdf.name || "").trim().toLowerCase();
  if (snapName && pdfName && snapName !== pdfName) return true;
  const snapEtag = String(snap.file_etag || "").trim();
  const pdfEtag = String(pdf.etag || "").trim();
  if (snapEtag && pdfEtag && snapEtag !== pdfEtag) return true;
  const snapMod = String(snap.file_last_modified || "").trim();
  const pdfMod = String(pdf.last_modified || "").trim();
  if (snapMod && pdfMod && snapMod !== pdfMod) return true;
  if (
    typeof snap.file_size === "number" &&
    typeof pdf.size === "number" &&
    snap.file_size !== pdf.size
  ) {
    return true;
  }
  return false;
}

/**
 * Comparación ligera recovery: nombre+crédito y metadata vs snapshot del fallo.
 * Informativo; no bloquea Reconsolidar ni cambia already_merged.
 */
export function buildRecoveryVerifyItems(
  issues: readonly UiOperationalIssue[],
  folderLinks: readonly MergeFolderLink[],
): RecoveryVerifyItem[] {
  const byCredit = new Map<string, MergeFolderLink>();
  for (const folder of folderLinks) {
    const credit = String(folder.credito || "").trim();
    if (credit && !byCredit.has(credit)) byCredit.set(credit, folder);
  }

  const out: RecoveryVerifyItem[] = [];
  const seen = new Set<string>();
  for (const issue of issues) {
    const credit = String(issue.location?.credit || "").trim();
    if (!credit || seen.has(credit)) continue;
    seen.add(credit);
    const folder = byCredit.get(credit);
    if (!folder) {
      out.push({
        credit,
        kind: "unknown",
        messageKey: "recovery_verify_unknown",
      });
      continue;
    }
    if (folder.list_ok === false) {
      out.push({
        credit,
        kind: "unknown",
        messageKey: "recovery_verify_unknown",
      });
      continue;
    }
    const pdfs = folder.observed_pdfs ?? [];
    if (pdfs.length === 0) {
      out.push({
        credit,
        kind: "missing",
        messageKey: "recovery_verify_missing",
      });
      continue;
    }
    const matching = pdfs.filter((p) =>
      creditDigitsInName(String(p.name || ""), credit),
    );
    if (matching.length === 0) {
      out.push({
        credit,
        kind: "mismatch",
        messageKey: "recovery_verify_mismatch",
      });
      continue;
    }
    const loc = issue.location;
    const hasSnapshot = Boolean(
      loc &&
        (loc.file_name ||
          loc.file_etag ||
          loc.file_last_modified ||
          typeof loc.file_size === "number"),
    );
    if (!hasSnapshot) {
      // Sin snapshot: presencia + nombre con crédito basta → parece listo.
      out.push({
        credit,
        kind: "replaced",
        messageKey: "recovery_verify_replaced",
      });
      continue;
    }
    const anyChanged = matching.some((pdf) =>
      metaChanged(
        {
          file_name: loc?.file_name,
          file_etag: loc?.file_etag,
          file_size: loc?.file_size,
          file_last_modified: loc?.file_last_modified,
        },
        pdf,
      ),
    );
    if (anyChanged) {
      out.push({
        credit,
        kind: "replaced",
        messageKey: "recovery_verify_replaced",
      });
    } else {
      out.push({
        credit,
        kind: "unchanged",
        messageKey: "recovery_verify_unchanged",
      });
    }
  }
  return out;
}
