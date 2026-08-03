/**
 * Etiquetas de banco solo para UI.
 * No altera bank_code, process_key ni nombres de carpetas Graph/SharePoint.
 */

const BANK_UI_LABELS: Readonly<Record<string, string>> = {
  banco_bogota: "Bogotá",
  banco_bancolombia: "Bancolombia",
};

/**
 * Quita el prefijo «Banco » / «Banco de » cuando el nombre es Bogotá
 * (redundante junto a «Seleccionar banco»). Otros bancos se dejan igual.
 */
export function normalizeBankDisplayName(bankName: string): string {
  const trimmed = bankName.trim();
  if (/^banco\s+(?:de\s+)?bogot[aá]$/i.test(trimmed)) {
    return "Bogotá";
  }
  return trimmed;
}

/**
 * Label de display por bank_code (preferido) o normalización de bank_name del API.
 */
export function bankDisplayName(
  bankCode: string,
  bankName?: string | null,
): string {
  const code = bankCode.trim().toLowerCase();
  const mapped = BANK_UI_LABELS[code];
  if (mapped) return mapped;
  const name = (bankName ?? "").trim();
  if (name) return normalizeBankDisplayName(name);
  return bankCode;
}
