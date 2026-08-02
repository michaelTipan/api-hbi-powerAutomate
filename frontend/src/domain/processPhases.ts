/**
 * Fases operativas del detalle de proceso (vista del operador).
 * Agrupa los pasos técnicos del backend y decide qué documentos mostrar.
 */
import type { StepName, StepStatus, UiLink, UiStepState } from "../types/contract";

export type OperatorPhaseId = "review" | "finalize" | "notify" | "merge" | "amortization";

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

/** Etiquetas humanas de documentos (anulan labels del API si hace falta). */
export const OPERATOR_DOCUMENT_LABELS: Record<string, string> = {
  review_excel: "Abrir archivo de revisión",
  historical: "Abrir histórico",
  secretary_file: "Abrir asientos pendientes",
  email_pdf: "Ver correo enviado",
  merge_manifest: "Abrir PDF consolidado",
};

export const OPERATOR_PHASES: readonly OperatorPhaseDef[] = [
  {
    id: "review",
    shortLabel: "Generar archivo",
    title: "Generar archivo",
    guidance:
      "Abra el Excel de revisión, complete la validación de pagos y guarde los cambios cuando termine.",
    stepNames: ["generate", "review"],
    // Cada `rel` solo en la fase donde nace (sin duplicar en fases posteriores).
    documentRels: ["review_excel"],
  },
  {
    id: "finalize",
    shortLabel: "Finalizar revisión",
    title: "Finalizar revisión",
    guidance: "Confirme el cierre cuando haya guardado y cerrado el Excel de revisión.",
    stepNames: ["finalize"],
    documentRels: ["historical", "secretary_file"],
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
    documentRels: ["merge_manifest"],
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
  return !HIDDEN_DOCUMENT_RELS.has(link.rel);
}

export function operatorDocumentLabel(link: UiLink): string {
  return OPERATOR_DOCUMENT_LABELS[link.rel] ?? link.label;
}

/** Documentos de una fase ya desbloqueada (sin técnicos). */
export function documentsForPhase(
  links: readonly UiLink[],
  phase: OperatorPhaseDef,
): UiLink[] {
  const allowed = new Set(phase.documentRels);
  return links.filter((l) => isOperatorVisibleLink(l) && allowed.has(l.rel));
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
): Array<{ phase: OperatorPhaseDef; links: UiLink[] }> {
  const sections: Array<{ phase: OperatorPhaseDef; links: UiLink[] }> = [];
  const seenRels = new Set<string>();
  for (const item of resolved) {
    if (!item.unlocked) continue;
    // Primera fase que reclama el `rel` gana: evita el mismo enlace en varias columnas.
    const docs = documentsForPhase(links, item.def).filter((doc) => {
      if (seenRels.has(doc.rel)) return false;
      seenRels.add(doc.rel);
      return true;
    });
    if (docs.length === 0) continue;
    sections.push({ phase: item.def, links: docs });
  }
  return sections;
}
