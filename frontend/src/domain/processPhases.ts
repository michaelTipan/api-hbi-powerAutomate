/**
 * Fases operativas del detalle de proceso (vista del operador).
 * Agrupa los pasos técnicos del backend y decide qué documentos mostrar.
 */
import type { StepName, StepStatus, UiLink, UiStepState } from "../types/contract";

/** Ids del stepper (Generate del Panel + revisión Excel + Finalize = una sola fase). */
export type OperatorPhaseId = "review" | "notify" | "merge" | "amortization";

const OPERATOR_PHASE_IDS: ReadonlySet<string> = new Set<OperatorPhaseId>([
  "review",
  "notify",
  "merge",
  "amortization",
]);

/**
 * Interpreta `?phase=` al abrir el detalle (p. ej. tras Generate OK → revisión).
 * Alias: `generate` / `finalize` → `review` (fase unificada).
 */
export function parseOperatorPhaseHint(raw: string | null | undefined): OperatorPhaseId | null {
  if (raw == null) return null;
  const value = raw.trim().toLowerCase();
  if (!value) return null;
  if (value === "generate" || value === "finalize") return "review";
  if (OPERATOR_PHASE_IDS.has(value)) return value as OperatorPhaseId;
  return null;
}

export type PhaseVisualStatus = "completed" | "current" | "upcoming";

export interface OperatorPhaseDef {
  id: OperatorPhaseId;
  /** Etiqueta corta del stepper. */
  shortLabel: string;
  /** Título de la tarjeta de fase activa. */
  title: string;
  /** Guía breve en segunda persona (usted). */
  guidance: string;
  /** Pasos técnicos que componen la fase. */
  stepNames: readonly StepName[];
  /** `rel` de documentos generados/editables en esta fase. */
  documentRels: readonly string[];
}

/** Relaciones técnicas que nunca se muestran al operador. */
export const HIDDEN_DOCUMENT_RELS = new Set(["control", "execution_log"]);

/**
 * Documentos que no van en «Documentos por fase».
 * `correos` / `ibr` viven como CTA de fase (Notify / Amortización), no como documento.
 */
export const PHASE_DOCUMENTS_EXCLUDED_RELS = new Set(["correos", "ibr"]);

/** Etiquetas humanas de documentos (anulan labels del API si hace falta). */
export const OPERATOR_DOCUMENT_LABELS: Record<string, string> = {
  review_excel: "Abrir archivo de revisión",
  historical: "Abrir histórico",
  secretary_file: "Abrir asientos pendientes",
  email_pdf: "Ver correo enviado",
  correos: "Revisar destinatarios",
  ibr: "Actualizar IBR",
  merge_pdf: "Abrir PDF consolidado",
  asientos_folder: "Abrir carpeta de documentos contables",
};

export const OPERATOR_PHASES: readonly OperatorPhaseDef[] = [
  {
    id: "review",
    shortLabel: "Revisión de archivo",
    title: "Revisión de archivo",
    guidance:
      "Abra el Excel de revisión, complete la validación, guarde y cierre Excel Online. Si hay casos en la hoja Errores, corríjalos y regenere antes de finalizar. Cuando esté listo, confirme el cierre.",
    // Generate (Panel) + revisión humana + Finalize: una sola fase operativa.
    stepNames: ["generate", "review", "finalize"],
    documentRels: ["review_excel", "historical", "secretary_file"],
  },
  {
    id: "notify",
    shortLabel: "Enviar correo",
    title: "Enviar correo",
    guidance: "Envíe el correo de validación a los destinatarios configurados para este proceso.",
    stepNames: ["notify"],
    documentRels: ["email_pdf"],
  },
  {
    id: "merge",
    shortLabel: "Generar PDF consolidado",
    title: "Generar PDF consolidado",
    guidance:
      "Revise los documentos contables disponibles y genere el PDF consolidado cuando estén listos.",
    stepNames: ["merge"],
    // PDF consolidado + carpetas ASIENTOS (solo en Documentos por fase).
    documentRels: ["merge_pdf", "asientos_folder", "asientos"],
  },
  {
    id: "amortization",
    shortLabel: "Procesar amortización",
    title: "Procesar amortización",
    guidance: "Cuando el PDF consolidado esté listo, procese la amortización.",
    stepNames: ["dry_run", "apply"],
    // Sin documentos propios: los PDF/correo ya aparecen en su fase de origen.
    documentRels: [],
  },
] as const;

const TERMINAL_OK: ReadonlySet<StepStatus> = new Set(["completed", "skipped"]);

function stepByName(steps: readonly UiStepState[]): Map<StepName, UiStepState> {
  return new Map(steps.map((s) => [s.name, s]));
}

function phaseStepStatuses(phase: OperatorPhaseDef, byName: Map<StepName, UiStepState>): StepStatus[] {
  return phase.stepNames.map((name) => byName.get(name)?.status ?? "not_started");
}

function isPhaseCompleted(statuses: readonly StepStatus[]): boolean {
  return statuses.length > 0 && statuses.every((st) => TERMINAL_OK.has(st));
}

function isPhaseActive(statuses: readonly StepStatus[]): boolean {
  return statuses.some(
    (st) =>
      st === "in_progress" ||
      st === "sync_pending" ||
      st === "failed_retryable" ||
      st === "failed_business" ||
      st === "blocked" ||
      st === "partial",
  );
}

export interface ResolvedOperatorPhase {
  def: OperatorPhaseDef;
  visual: PhaseVisualStatus;
  /** True si la fase ya se alcanzó (completada o actual): puede mostrar sus documentos. */
  unlocked: boolean;
  /** Motivo de bloqueo en el stepper (p. ej. foco de regeneración). */
  lockReason?: string | null;
}

/** Mensaje cuando Finalizar+ están bloqueadas por casos en Errores o archivo faltante. */
export const REGENERATE_FOCUS_LOCK_REASON =
  "Corrija los casos en Errores y regenere antes de continuar";

/**
 * Ajusta el stepper cuando hace falta regenerar: fase viva = Revisión de archivo;
 * Enviar correo y fases posteriores quedan bloqueadas (no seleccionables).
 */
export function buildPhaseStepperModel(
  phases: readonly ResolvedOperatorPhase[],
  needsRegenerateFocus: boolean,
): ResolvedOperatorPhase[] {
  if (!needsRegenerateFocus) return phases.map((p) => ({ ...p, lockReason: null }));
  return phases.map((p) => {
    if (p.def.id === "review") {
      return { ...p, visual: "current" as const, unlocked: true, lockReason: null };
    }
    return {
      ...p,
      visual: p.visual === "current" ? ("upcoming" as const) : p.visual,
      unlocked: false,
      lockReason: REGENERATE_FOCUS_LOCK_REASON,
    };
  });
}

/**
 * Resuelve el estado visual de cada fase y cuál es la actual.
 * La actual es la primera no completada; si todas están listas, la última queda como actual completada.
 */
export function resolveOperatorPhases(steps: readonly UiStepState[]): {
  phases: ResolvedOperatorPhase[];
  currentId: OperatorPhaseId;
} {
  const byName = stepByName(steps);
  const completedFlags = OPERATOR_PHASES.map((phase) =>
    isPhaseCompleted(phaseStepStatuses(phase, byName)),
  );
  const activeFlags = OPERATOR_PHASES.map((phase) => isPhaseActive(phaseStepStatuses(phase, byName)));

  let currentIndex = activeFlags.findIndex(Boolean);
  if (currentIndex < 0) {
    currentIndex = completedFlags.findIndex((done) => !done);
  }
  if (currentIndex < 0) {
    currentIndex = OPERATOR_PHASES.length - 1;
  }

  const phases: ResolvedOperatorPhase[] = OPERATOR_PHASES.map((def, index) => {
    let visual: PhaseVisualStatus;
    if (index < currentIndex) visual = "completed";
    else if (index === currentIndex) {
      visual = completedFlags[index] ? "completed" : "current";
    } else visual = "upcoming";
    // Si la actual ya está completa (proceso terminado), márquela completed.
    if (index === currentIndex && completedFlags[index]) visual = "completed";
    return {
      def,
      visual,
      unlocked: index <= currentIndex,
    };
  });

  return { phases, currentId: OPERATOR_PHASES[currentIndex]!.id };
}

export function isOperatorVisibleLink(link: UiLink): boolean {
  return !HIDDEN_DOCUMENT_RELS.has(link.rel) && !PHASE_DOCUMENTS_EXCLUDED_RELS.has(link.rel);
}

/** `merge_pdf` o `merge_pdf:N` (varios consolidados por crédito/grupo). */
export function isMergePdfDocumentRel(rel: string): boolean {
  return rel === "merge_pdf" || rel.startsWith("merge_pdf:");
}

function isAsientosFolderRel(rel: string): boolean {
  return rel === "asientos" || rel === "asientos_folder" || rel.startsWith("asientos_folder:");
}

export function isAsientosDocumentRel(rel: string): boolean {
  return isAsientosFolderRel(rel);
}

function matchesPhaseDocumentRel(rel: string, documentRels: readonly string[]): boolean {
  return documentRels.some(
    (allowed) =>
      allowed === rel ||
      (allowed === "merge_pdf" && isMergePdfDocumentRel(rel)) ||
      ((allowed === "asientos_folder" || allowed === "asientos") && isAsientosFolderRel(rel)),
  );
}

export function operatorDocumentLabel(link: UiLink): string {
  // La etiqueta completa viene del backend («… · Crédito 265»).
  if (isMergePdfDocumentRel(link.rel)) {
    return link.label || OPERATOR_DOCUMENT_LABELS.merge_pdf;
  }
  if (isAsientosFolderRel(link.rel)) {
    return link.label || OPERATOR_DOCUMENT_LABELS.asientos_folder;
  }
  return OPERATOR_DOCUMENT_LABELS[link.rel] ?? link.label;
}

/** Carpetas ASIENTOS de merge_readiness → enlaces de Documentos por fase. */
export function asientosFolderDocumentLinks(
  folderLinks: readonly {
    rel?: string;
    label?: string;
    path?: string | null;
    web_url?: string | null;
    credito?: string | null;
  }[],
): UiLink[] {
  // rel indexado único: el BE envía rel="asientos" en todas; sin índice
  // se colapsan en seenRels / keys de React y la UI solo muestra una carpeta.
  return folderLinks
    .filter((folder) => Boolean((folder.path || "").trim()))
    .map((folder, index) => {
      const baseLabel = (folder.label || "Carpeta ASIENTOS").trim() || "Carpeta ASIENTOS";
      const credito = (folder.credito || "").trim();
      return {
        rel: `asientos_folder:${index}`,
        label: credito ? `${baseLabel} · Crédito ${credito}` : baseLabel,
        path: folder.path ?? null,
        web_url: folder.web_url ?? null,
        open_mode: "sharepoint" as const,
      };
    });
}

/** Documentos de una fase ya desbloqueada (sin técnicos). */
export function documentsForPhase(
  links: readonly UiLink[],
  phase: OperatorPhaseDef,
): UiLink[] {
  return links.filter(
    (l) => isOperatorVisibleLink(l) && matchesPhaseDocumentRel(l.rel, phase.documentRels),
  );
}

/** Fases donde no se ofrece «Actualizar documentos» (el recargo genérico basta). */
const REFRESH_DOCUMENTS_EXCLUDED_PHASES: ReadonlySet<OperatorPhaseId> = new Set([
  "review",
  "notify",
  "amortization",
]);

const MERGE_REFRESH_STATUSES: ReadonlySet<StepStatus> = new Set([
  "partial",
  "blocked",
  "failed_retryable",
  "failed_business",
]);

export function hasUnavailableOperatorLink(links: readonly UiLink[]): boolean {
  return links.some((link) => isOperatorVisibleLink(link) && !link.web_url);
}

/**
 * Cuándo mostrar el botón «Actualizar documentos».
 * Por defecto oculto; solo cuando una relectura de SharePoint aporta valor.
 * Nunca en COMPLETADO (la consulta residual va por «Actualizar estado» si aplica).
 */
export function shouldShowRefreshDocuments(input: {
  currentPhaseId: OperatorPhaseId;
  operationalStatus: string;
  controlEstadoProceso?: string | null;
  nextActions: readonly { code: string }[];
  steps: readonly UiStepState[];
  links: readonly UiLink[];
}): boolean {
  if (REFRESH_DOCUMENTS_EXCLUDED_PHASES.has(input.currentPhaseId)) {
    return false;
  }
  if (input.operationalStatus === "COMPLETADO") {
    return false;
  }
  const applyStatus = input.steps.find((s) => s.name === "apply")?.status;
  if (applyStatus === "completed") {
    return false;
  }

  const fromBackend = input.nextActions.some((a) => a.code === "refresh_documents");
  const control = (input.controlEstadoProceso || "").trim().toUpperCase();
  const waitingDocuments =
    input.operationalStatus === "ESPERANDO_SOPORTES" || control === "PENDIENTE_ASIENTOS";
  const mergeStatus = input.steps.find((s) => s.name === "merge")?.status;
  const mergeNeedsRefresh =
    mergeStatus !== undefined && MERGE_REFRESH_STATUSES.has(mergeStatus);
  const hasUnavailableLink = hasUnavailableOperatorLink(input.links);

  return fromBackend || waitingDocuments || mergeNeedsRefresh || hasUnavailableLink;
}

/**
 * Recargo genérico «Actualizar estado».
 * Mutuamente excluyente con «Actualizar documentos».
 * En COMPLETADO: oculto salvo consulta justificada (enlace operativo sin URL).
 */
export function shouldShowStatusRefresh(input: {
  operationalStatus: string;
  showRefreshDocuments: boolean;
  links: readonly UiLink[];
}): boolean {
  if (input.showRefreshDocuments) {
    return false;
  }
  if (input.operationalStatus === "COMPLETADO") {
    return hasUnavailableOperatorLink(input.links);
  }
  return true;
}

/** Secciones de documentos para fases desbloqueadas que ya tengan al menos un enlace. */
export function documentSectionsForUnlockedPhases(
  links: readonly UiLink[],
  resolved: readonly ResolvedOperatorPhase[],
  extraLinksByPhase: Partial<Record<OperatorPhaseId, readonly UiLink[]>> = {},
): Array<{ phase: OperatorPhaseDef; links: UiLink[] }> {
  const sections: Array<{ phase: OperatorPhaseDef; links: UiLink[] }> = [];
  const seenRels = new Set<string>();
  for (const item of resolved) {
    if (!item.unlocked) continue;
    const phaseExtras = extraLinksByPhase[item.def.id] ?? [];
    const combined = [...documentsForPhase(links, item.def), ...phaseExtras];
    // Primera fase que reclama el `rel` gana: evita el mismo enlace en varias columnas.
    const docs = combined.filter((doc) => {
      if (seenRels.has(doc.rel)) return false;
      seenRels.add(doc.rel);
      return true;
    });
    if (docs.length === 0) continue;
    sections.push({ phase: item.def, links: docs });
  }
  return sections;
}

/**
 * Documentos de la fase que el operador está viendo en el header
 * (solo esa fase; no todas las desbloqueadas a la vez).
 */
export function documentSectionForSelectedPhase(
  links: readonly UiLink[],
  resolved: readonly ResolvedOperatorPhase[],
  selectedPhaseId: OperatorPhaseId,
  extraLinksByPhase: Partial<Record<OperatorPhaseId, readonly UiLink[]>> = {},
): { phase: OperatorPhaseDef; links: UiLink[] } | null {
  const item = resolved.find((p) => p.def.id === selectedPhaseId);
  if (!item?.unlocked) return null;
  const phaseExtras = extraLinksByPhase[item.def.id] ?? [];
  const docs = [...documentsForPhase(links, item.def), ...phaseExtras];
  if (docs.length === 0) return null;
  return { phase: item.def, links: docs };
}

/**
 * «Documentos por fase»: proceso vivo (excepto amortización vacía) y fases
 * anteriores en proceso terminado. En amortización terminada solo «Archivos».
 */
export function shouldShowPhaseDocumentsSection(input: {
  processFullyCompleted: boolean;
  viewingPhaseId: OperatorPhaseId;
}): boolean {
  if (input.viewingPhaseId === "amortization") {
    return false;
  }
  return true;
}

/**
 * «Archivos del proceso»: solo con proceso cerrado y viendo la última fase.
 */
export function shouldShowProcessFileCatalog(input: {
  processFullyCompleted: boolean;
  viewingPhaseId: OperatorPhaseId;
  hasCatalogGroups: boolean;
}): boolean {
  return (
    input.processFullyCompleted &&
    input.viewingPhaseId === "amortization" &&
    input.hasCatalogGroups
  );
}
