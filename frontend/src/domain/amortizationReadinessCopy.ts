/**
 * Copy y helpers de lectura para amortization_readiness.missing_items / warnings.
 * Sin lógica de negocio: solo presentación operativa.
 */

export type AmortMissingItem = {
  credito?: string | null;
  id_pago?: string | null;
  error_code?: string | null;
  missing_creditos?: string[] | null;
  document_type?: string | null;
};

/** Mensaje corto por faltante de amortización (nunca el código crudo). */
export function amortMissingItemMessage(item: AmortMissingItem): string {
  const code = String(item.error_code || "").trim();
  switch (code) {
    case "asiento_contable_credit_mismatch":
      return "Hay un PDF en ASIENTOS, pero el nombre no coincide con el crédito.";
    case "asiento_contable_not_found":
    case "MERGE_GROUP_PENDING_INPUTS":
      return "Faltan documentos contables para completar la consolidación de este grupo.";
    case "missing_ruta_asientos_contables":
      return "No hay ruta de carpeta ASIENTOS para este crédito.";
    case "extract_routes_missing":
      return "Falta la ruta del extracto bancario.";
    case "MERGE_EXPECTED_CREDITS_MISMATCH":
    case "output_validation_failed":
      return "El consolidado no coincide con los créditos esperados.";
    default: {
      const missing = (item.missing_creditos || []).filter(Boolean);
      if (missing.length > 0) {
        return `Faltan documentos para el/los crédito(s): ${missing.join(", ")}.`;
      }
      return "Falta información requerida para procesar la amortización.";
    }
  }
}

/** Humaniza warnings técnicos del readiness (p. ej. manifest_status=…). */
export function amortWarningMessage(raw: string): string | null {
  const text = String(raw || "").trim();
  if (!text) return null;
  if (text.startsWith("manifest_status=")) {
    const status = text.slice("manifest_status=".length).trim();
    if (status && status !== "complete") {
      return "El manifiesto de consolidación aún no está completo.";
    }
    return null;
  }
  if (text.includes("incomplete_groups") || text.includes("eligible_for_dry_run")) {
    return "La consolidación de asientos contables quedó incompleta.";
  }
  if (text.includes("output_validation")) {
    return "Hay inconsistencias en el PDF consolidado.";
  }
  // No mostrar códigos crudos snake_case / key=value técnicos.
  if (/^[a-z][a-z0-9_]*(?:=|$)/.test(text) || text.includes("=")) {
    return "Hay un aviso técnico pendiente; actualice e intente de nuevo.";
  }
  return text;
}

/** Tono del chip «Ítems listos» (misma semántica que Grupos listos / statusTone). */
export function amortItemsProgressTone(
  status: string | null | undefined,
): "complete" | "pending" | "unknown" {
  const norm = String(status || "").trim().toLowerCase();
  if (norm === "ready" || norm === "already_applied") return "complete";
  if (norm === "incomplete") return "pending";
  return "unknown";
}

/** Texto del indicador «Ítems listos: X de Y». */
export function formatAmortItemsProgress(input: {
  ready_items: number;
  expected_items: number;
}): string {
  return `Ítems listos: ${input.ready_items} de ${input.expected_items}`;
}

export function parseAmortMissingItems(
  raw: ReadonlyArray<Record<string, unknown>> | null | undefined,
): AmortMissingItem[] {
  if (!raw || raw.length === 0) return [];
  return raw.map((row) => {
    const missingRaw = row.missing_creditos;
    let missing_creditos: string[] | null = null;
    if (Array.isArray(missingRaw)) {
      missing_creditos = missingRaw.map((c) => String(c));
    }
    const firstMissing = missing_creditos?.[0] ?? null;
    return {
      credito:
        row.credito == null
          ? firstMissing
          : String(row.credito),
      id_pago: row.id_pago == null ? null : String(row.id_pago),
      error_code: row.error_code == null ? null : String(row.error_code),
      missing_creditos,
      document_type: row.document_type == null ? null : String(row.document_type),
    };
  });
}
