import type { UiLink, UiOperationalIssue } from "../types/contract";

/** True si el texto ya menciona el fragmento (case-insensitive, trim). */
export function messageMentions(haystack: string, needle: string): boolean {
  const h = (haystack || "").toLowerCase();
  const n = (needle || "").trim().toLowerCase();
  if (!n) return false;
  return h.includes(n);
}

/**
 * Presenta value_found al operador: valores de negocio sí; códigos técnicos no.
 * Etiqueta según etapa (Excel de revisión vs asiento/tabla).
 */
export function formatOperationalValueFound(
  value: string | null | undefined,
  stage?: string | null,
): string | null {
  const v = (value || "").trim();
  if (!v) return null;
  if (/^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$/.test(v)) {
    return null;
  }
  const s = (stage || "").trim().toLowerCase();
  const amort =
    s === "amortization" ||
    s === "apply" ||
    s === "dry_run" ||
    s === "amortization_process" ||
    s === "amortization_apply" ||
    s === "amortization_dry_run";
  if (amort) {
    return `Valor detectado: ${v}`;
  }
  return `Valor en Excel: ${v}`;
}

export function isAmortizationIssueStage(stage: string | null | undefined): boolean {
  const s = (stage || "").trim().toLowerCase();
  return (
    s === "amortization" ||
    s === "apply" ||
    s === "dry_run" ||
    s === "amortization_process" ||
    s === "amortization_apply" ||
    s === "amortization_dry_run"
  );
}

function capitalizeSentence(text: string): string {
  const t = text.trim();
  if (!t) return t;
  return t.charAt(0).toLocaleUpperCase("es") + t.slice(1);
}

/**
 * Quita el «Abra …» del next_action cuando ya hay CTA «Abrir …».
 * Conserva el resto del procedimiento.
 */
export function refineNextActionForOpenCta(
  nextAction: string | null | undefined,
  links: readonly UiLink[],
): string | null {
  const raw = (nextAction || "").trim();
  if (!raw) return null;
  const hasOpenCta = links.some((l) =>
    /^abrir\b/i.test((l.label || "").trim()),
  );
  if (!hasOpenCta) return raw;

  let text = raw;
  // «Abra la tabla…, quite…» / «Abra el Excel… y corrija…»
  text = text.replace(
    /^Abra\s+(?:la|el|los|las)?\s*[^,.]+(?:\s+en\s+SharePoint)?\s*,\s*/i,
    "",
  );
  text = text.replace(
    /^Abra\s+(?:la|el|los|las)?\s*[^.]+\.\s*/i,
    "",
  );
  text = text.replace(
    /^Abra\s+(?:la|el|los|las)?\s*\S[^y]*?\s+y\s+/i,
    "",
  );
  text = text.trim();
  if (!text || /^abra\b/i.test(text)) {
    // Si no quedó procedimiento útil, omitir (el CTA basta).
    return text && !/^abra\b/i.test(text) ? capitalizeSentence(text) : null;
  }
  return capitalizeSentence(text);
}

export type IssueEvidenceLine = { key: string; text: string };

/**
 * Evidencia estructurada sin repetir lo ya dicho en user_message.
 */
export function buildIssueEvidenceLines(
  issue: UiOperationalIssue,
): IssueEvidenceLine[] {
  const msg = issue.user_message || "";
  const lines: IssueEvidenceLine[] = [];

  const fileName = (issue.location?.file_name || "").trim();
  if (
    fileName &&
    isAmortizationIssueStage(issue.stage) &&
    !messageMentions(msg, fileName)
  ) {
    lines.push({ key: "file", text: `Archivo afectado: ${fileName}` });
  }

  const row = issue.location?.row;
  if (
    typeof row === "number" &&
    Number.isFinite(row) &&
    row > 0 &&
    !messageMentions(msg, `Fila ${row}`) &&
    !messageMentions(msg, `fila ${row}`)
  ) {
    lines.push({ key: "row", text: `Fila ${row}` });
  }

  const valueLabel = formatOperationalValueFound(issue.value_found, issue.stage);
  if (valueLabel) {
    const raw = (issue.value_found || "").trim();
    // Monto / valor concreto: omitir solo si el texto exacto ya está en el cuerpo.
    if (raw && !messageMentions(msg, raw)) {
      lines.push({ key: "value", text: valueLabel });
    }
  }

  const expected = (issue.expected_values || [])
    .map((v) => v.trim())
    .filter(Boolean);
  if (expected.length > 0) {
    const joined = expected.join(", ");
    // No filtrar por token corto (SI/NO/retenciones): solo si el cuerpo ya listó el bloque.
    const alreadyListed =
      /valores esperados:/i.test(msg) || msg.includes(joined);
    if (!alreadyListed) {
      lines.push({
        key: "expected",
        text: `Valores esperados: ${joined}`,
      });
    }
  }

  return lines;
}

/** Extras para mensajes de fila Finalize (misma regla de no-duplicar). */
export function buildFinalizeMessageExtras(issue: UiOperationalIssue): string[] {
  const msg = issue.user_message || "";
  const extras: string[] = [];
  const valueLabel = formatOperationalValueFound(issue.value_found, issue.stage);
  if (valueLabel) {
    const raw = (issue.value_found || "").trim();
    if (raw && !messageMentions(msg, raw)) extras.push(valueLabel);
  }
  const expected = (issue.expected_values || [])
    .map((v) => v.trim())
    .filter(Boolean);
  if (expected.length > 0) {
    const joined = expected.join(", ");
    const alreadyListed =
      /valores esperados:/i.test(msg) || msg.includes(joined);
    if (!alreadyListed) {
      extras.push(`Valores esperados: ${joined}`);
    }
  }
  return extras;
}
