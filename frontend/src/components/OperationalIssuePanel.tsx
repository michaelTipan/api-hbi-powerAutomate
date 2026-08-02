import type { UiOperationalIssue } from "../types/contract";

function locationSummary(issue: UiOperationalIssue): string | null {
  const loc = issue.location;
  if (!loc) return null;
  const parts = [
    loc.file_name ? `Archivo: ${loc.file_name}` : null,
    loc.sheet ? `Hoja: ${loc.sheet}` : null,
    loc.row != null ? `Fila: ${loc.row}` : null,
    loc.column ? `Columna: ${loc.column}` : null,
    loc.client_name ? `Cliente: ${loc.client_name}` : null,
    loc.credit ? `Crédito: ${loc.credit}` : null,
    loc.payment_id ? `ID pago: ${loc.payment_id}` : null,
  ].filter((p): p is string => Boolean(p));
  return parts.length > 0 ? parts.join(" · ") : null;
}

export function OperationalIssuePanel({
  issue,
  onRetry,
  retryBusy = false,
}: {
  issue: UiOperationalIssue;
  onRetry?: () => void;
  retryBusy?: boolean;
}) {
  const location = locationSummary(issue);
  const canRetry = Boolean(issue.retry?.allowed && onRetry);

  return (
    <div className="error-box" role="alert" data-issue-id={issue.issue_id}>
      <strong>{issue.title}</strong>
      <p style={{ margin: "0.35rem 0" }}>{issue.user_message}</p>
      {location && <p className="meta">{location}</p>}
      {issue.value_found && (
        <p className="meta">Código / detalle: {issue.value_found}</p>
      )}
      {issue.expected_values.length > 0 && (
        <p className="meta">
          Valores esperados: {issue.expected_values.join(", ")}
        </p>
      )}
      {issue.next_action && <p className="meta">{issue.next_action}</p>}
      {(issue.links.length > 0 || canRetry) && (
        <div className="actions" style={{ marginTop: "0.5rem" }}>
          {issue.links
            .filter((l) => Boolean(l.web_url))
            .map((l) => (
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
