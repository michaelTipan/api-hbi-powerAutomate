import type { UiOperationalIssue } from "../types/contract";
import {
  CORRECTION_PRIMARY_LINKS_MAX,
  primaryIssueLinks,
} from "../domain/correctionTargets";

/**
 * Presenta value_found al operador: valores de negocio sí; códigos técnicos no.
 */
export function formatOperationalValueFound(value: string | null | undefined): string | null {
  const v = (value || "").trim();
  if (!v) return null;
  // Código técnico snake_case (p. ej. invalid_estado_pago).
  if (/^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$/.test(v)) {
    return null;
  }
  return `Valor en Excel: ${v}`;
}

export function OperationalIssuePanel({
  issue,
  onRetry,
  retryBusy = false,
  maxPrimaryLinks = CORRECTION_PRIMARY_LINKS_MAX,
  hideLinks = false,
}: {
  issue: UiOperationalIssue;
  onRetry?: () => void;
  retryBusy?: boolean;
  /** Máximo de botones de enlace (prioritarios). 0 = ninguno. */
  maxPrimaryLinks?: number;
  /** Oculta enlaces (p. ej. cuando el drawer concentra los destinos). */
  hideLinks?: boolean;
}) {
  const canRetry = Boolean(issue.retry?.allowed && onRetry);
  const valueFoundLabel = formatOperationalValueFound(issue.value_found);
  const links = hideLinks ? [] : primaryIssueLinks(issue, maxPrimaryLinks);

  return (
    <div className="error-box" role="alert" data-issue-id={issue.issue_id}>
      <strong>{issue.title}</strong>
      <p style={{ margin: "0.35rem 0" }}>{issue.user_message}</p>
      {valueFoundLabel ? <p className="meta">{valueFoundLabel}</p> : null}
      {issue.expected_values.length > 0 && (
        <p className="meta">
          Valores esperados: {issue.expected_values.join(", ")}
        </p>
      )}
      {issue.next_action && <p className="meta">{issue.next_action}</p>}
      {(links.length > 0 || canRetry) && (
        <div className="actions" style={{ marginTop: "0.5rem" }}>
          {links.map((l) => (
            <a
              key={`${l.rel}-${l.web_url}`}
              className="btn secondary"
              href={l.web_url!}
              target="_blank"
              rel="noreferrer"
            >
              {l.label || "Abrir enlace"}
            </a>
          ))}
          {canRetry && (
            <button
              type="button"
              className="btn primary"
              onClick={onRetry}
              disabled={retryBusy}
            >
              {issue.retry?.label || "Reintentar"}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
