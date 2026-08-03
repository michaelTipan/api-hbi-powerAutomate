import type { UiError, UiLink, UiNextAction } from "../types/contract";

const ACTION_TO_LINK_REL: Record<string, string> = {
  open_review_excel: "review_excel",
  open_asientos_pendientes: "secretary_file",
};

export type RecoveryActionKind =
  | "regenerate"
  | "merge"
  | "retry"
  | "reload"
  | "open_excel";

/** Infiere la acción de recuperación según el código de error de negocio. */
export function recoveryKindForError(error: UiError): RecoveryActionKind {
  const code = (error.error_code || "").toLowerCase();
  const stage = (error.stage || "").toLowerCase();
  const msg = `${error.user_message || ""} ${error.next_action || ""}`.toLowerCase();

  if (
    code.includes("asiento") ||
    code.includes("merge_readiness") ||
    code.includes("missing_asiento") ||
    msg.includes("asiento") ||
    msg.includes("merge")
  ) {
    if (
      code.includes("missing") ||
      code.includes("incomplete") ||
      code.includes("readiness") ||
      msg.includes("falt") ||
      msg.includes("asiento")
    ) {
      return "merge";
    }
  }

  if (
    code === "review_has_open_errors" ||
    code.includes("requires_regeneration") ||
    code === "review_file_not_found" ||
    msg.includes("regenere") ||
    msg.includes("regenerar") ||
    (stage.includes("generate") && code.includes("error"))
  ) {
    return "regenerate";
  }

  if (
    code === "sharepoint_file_locked" ||
    code === "file_locked" ||
    msg.includes("423") ||
    msg.includes("bloqueado") ||
    msg.includes("abierto")
  ) {
    return "retry";
  }

  if (
    code === "process_not_approved" ||
    code.startsWith("missing_") ||
    code.includes("amount_mismatch") ||
    code.includes("empty_") ||
    code.includes("preflight")
  ) {
    return "open_excel";
  }

  return "retry";
}

function reviewLink(
  actions: UiNextAction[],
  links: UiLink[],
): UiLink | undefined {
  const rel = ACTION_TO_LINK_REL.open_review_excel;
  if (actions.some((a) => a.code === "open_review_excel" && a.enabled)) {
    return links.find((l) => l.rel === rel);
  }
  return links.find((l) => l.rel === rel && l.web_url);
}

function hintLine(error: UiError): string | null {
  const parts: string[] = [];
  if (error.excel_row != null && String(error.excel_row).trim()) {
    parts.push(`Fila Excel: ${error.excel_row}`);
  }
  if (error.field) {
    parts.push(`Columna: ${error.field}`);
  }
  if (error.payment_id) {
    parts.push(`ID Pago: ${error.payment_id}`);
  }
  return parts.length ? parts.join(" · ") : null;
}

export function BusinessErrorsPanel({
  errors,
  links,
  nextActions,
  onRetry,
  onReload,
  onRegenerate,
  onMerge,
}: {
  errors: UiError[];
  links: UiLink[];
  nextActions: UiNextAction[];
  onRetry?: () => void;
  onReload?: () => void;
  onRegenerate?: () => void;
  onMerge?: () => void;
}) {
  if (errors.length === 0) return null;

  const excel = reviewLink(nextActions, links);
  const kinds = new Set(errors.map(recoveryKindForError));

  return (
    <section className="panel panel-danger">
      <h2 style={{ marginTop: 0, fontSize: "1.05rem" }}>Errores a corregir</h2>
      <p className="meta" style={{ marginTop: 0 }}>
        Corrija lo indicado y use el botón de recuperación adecuado. El detalle
        del proceso permanece visible abajo.
      </p>
      <ul className="error-list">
        {errors.map((e, idx) => {
          const hint = hintLine(e);
          const kind = recoveryKindForError(e);
          return (
            <li key={`${e.error_code ?? "err"}-${idx}`}>
              <div className="error-box" role="alert">
                <strong>
                  {(e.stage ?? "proceso").toString()} ·{" "}
                  {e.error_code ?? e.severity}
                </strong>
                <p style={{ margin: "0.35rem 0" }}>
                  {e.user_message ||
                    "Revise el código de error y corrija los datos."}
                </p>
                {hint && <p className="meta">{hint}</p>}
                {e.next_action && <p className="meta">{e.next_action}</p>}
                <p className="meta">
                  Recuperación sugerida:{" "}
                  {kind === "regenerate"
                    ? "Regenerar archivo de revisión"
                    : kind === "merge"
                      ? "Completar asientos y volver a consolidar (merge)"
                      : kind === "open_excel"
                        ? "Completar montos / Procesar=SI en la revisión"
                        : "Reintentar la acción"}
                </p>
              </div>
            </li>
          );
        })}
      </ul>
      <div className="actions">
        {kinds.has("regenerate") && onRegenerate && (
          <button className="btn primary" type="button" onClick={onRegenerate}>
            Regenerar revisión
          </button>
        )}
        {kinds.has("merge") && onMerge && (
          <button className="btn primary" type="button" onClick={onMerge}>
            Reintentar merge / asientos
          </button>
        )}
        {onRetry && (
          <button className="btn" type="button" onClick={onRetry}>
            Reintentar
          </button>
        )}
        {onReload && (
          <button className="btn" type="button" onClick={onReload}>
            Volver a cargar proceso
          </button>
        )}
        {(kinds.has("open_excel") || excel?.web_url) && excel?.web_url && (
          <a
            className="btn"
            href={excel.web_url}
            target="_blank"
            rel="noreferrer"
          >
            Abrir Excel de revisión
          </a>
        )}
      </div>
    </section>
  );
}
