import type { UiError, UiLink, UiNextAction } from "../types/contract";

const ACTION_TO_LINK_REL: Record<string, string> = {
  open_review_excel: "review_excel",
  open_asientos_pendientes: "secretary_file",
};

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
}: {
  errors: UiError[];
  links: UiLink[];
  nextActions: UiNextAction[];
  onRetry?: () => void;
  onReload?: () => void;
}) {
  if (errors.length === 0) return null;

  const excel = reviewLink(nextActions, links);

  return (
    <section className="panel panel-danger">
      <h2 style={{ marginTop: 0, fontSize: "1.05rem" }}>
        Errores a corregir
      </h2>
      <p className="meta" style={{ marginTop: 0 }}>
        Corrija los puntos siguientes en SharePoint o en el Excel de revisión y
        luego reintente. El detalle del proceso permanece visible abajo.
      </p>
      <ul className="error-list">
        {errors.map((e, idx) => {
          const hint = hintLine(e);
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
              </div>
            </li>
          );
        })}
      </ul>
      <div className="actions">
        {onRetry && (
          <button className="btn primary" type="button" onClick={onRetry}>
            Reintentar
          </button>
        )}
        {onReload && (
          <button className="btn" type="button" onClick={onReload}>
            Volver a cargar proceso
          </button>
        )}
        {excel?.web_url && (
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
