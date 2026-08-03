/**
 * Umbral y helpers para destinos de corrección (hoja Errores / operational_issues).
 * Evita saturar la página con N paneles × muchos botones.
 */
import type { UiLink, UiOperationalIssue } from "../types/contract";

/** Con más issues o links, mostrar resumen + drawer en lugar de N paneles. */
export const CORRECTION_INLINE_ISSUE_MAX = 5;
export const CORRECTION_INLINE_LINK_MAX = 10;
/** En cada panel inline, máximo de botones de enlace. */
export const CORRECTION_PRIMARY_LINKS_MAX = 2;

export function openableIssueLinks(issue: UiOperationalIssue): UiLink[] {
  return (issue.links ?? []).filter((l) => Boolean((l.web_url || "").trim()));
}

export function countOpenableCorrectionLinks(
  issues: readonly UiOperationalIssue[],
): number {
  return issues.reduce((n, issue) => n + openableIssueLinks(issue).length, 0);
}

export function shouldUseCorrectionTargetsDrawer(
  issues: readonly UiOperationalIssue[],
): boolean {
  if (issues.length === 0) return false;
  if (issues.length > CORRECTION_INLINE_ISSUE_MAX) return true;
  return countOpenableCorrectionLinks(issues) > CORRECTION_INLINE_LINK_MAX;
}

export function primaryIssueLinks(
  issue: UiOperationalIssue,
  max = CORRECTION_PRIMARY_LINKS_MAX,
): UiLink[] {
  return openableIssueLinks(issue).slice(0, Math.max(0, max));
}

/** Etiqueta de negocio para una fila del drawer de destinos. */
export function correctionTargetEntryLabel(issue: UiOperationalIssue): string {
  const loc = issue.location;
  const bits: string[] = [issue.title];
  if (loc?.client_name) bits.push(loc.client_name);
  if (loc?.credit) bits.push(`Crédito ${loc.credit}`);
  if (loc?.row != null) bits.push(`Fila ${loc.row}`);
  return bits.join(" · ");
}
