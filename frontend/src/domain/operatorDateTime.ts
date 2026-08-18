/** Fecha-hora de Graph (UTC) a texto operador en America/Bogota. */

const MONTHS_ES = [
  "ene",
  "feb",
  "mar",
  "abr",
  "may",
  "jun",
  "jul",
  "ago",
  "sep",
  "oct",
  "nov",
  "dic",
] as const;

function looksLikeIsoDateTime(raw: string): boolean {
  return /\d{4}-\d{2}-\d{2}T/.test(raw) || /Z$/i.test(raw);
}

/** «18 ago 2026, 12:52 p. m.»; si ya viene formateado, se deja igual. */
export function formatOperatorDateTime(raw: string | null | undefined): string {
  const text = (raw || "").trim();
  if (!text) return "";
  if (!looksLikeIsoDateTime(text)) return text;
  let normalized = text;
  if (text.endsWith("Z") || text.endsWith("z")) {
    normalized = `${text.slice(0, -1)}+00:00`;
  }
  const parsed = Date.parse(normalized);
  if (!Number.isFinite(parsed)) return text;
  const bogotaMs = parsed - 5 * 60 * 60 * 1000;
  const dt = new Date(bogotaMs);
  const hour = dt.getUTCHours();
  const minute = dt.getUTCMinutes();
  const hour12 = hour % 12 || 12;
  const suffix = hour < 12 ? "a. m." : "p. m.";
  const mm = String(minute).padStart(2, "0");
  return `${dt.getUTCDate()} ${MONTHS_ES[dt.getUTCMonth()]} ${dt.getUTCFullYear()}, ${hour12}:${mm} ${suffix}`;
}
