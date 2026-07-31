import type { UiOperationalIssue } from "../types/contract";

function locationSummary(issue: UiOperationalIssue): string | null {
  const loc = issue.location;
  if (!loc) return null;
  const parts = [
    loc.file_name ? `Archivo: ${loc.file_name}` : null,
    loc.sheet ? `Hoja: ${loc.sheet}` : null,
    loc.row != null ? `Fila: ${loc.row}` : null,
    loc.column ? `Columna: ${loc.column}` : null,
    loc.credit ? `Crédito: ${loc.credit}` : null,
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
  const reviewLink =
    issue.links.find((l) => l.rel === "review_excel") ?? issue.links[0] ?? null;
  const canRetry = Boolean(issue.retry?.allowed && onRetry);

  return (
    <div className="error-box" role="alert" data-issue-id={issue.issue_id}>
      <strong>{issue.title}</strong>
      <p style={{ margin: "0.35rem 0" }}>{issue.user_message}</p>
      {location && <p className="meta">{location}</p>}
      {issue.value_found && (
        <p className="meta">Valor encontrado: {issue.value_found}</p>
      )}
      {issue.expected_values.length > 0 && (
        <p className="meta">
          Valores esperados: {issue.expected_values.join(", ")}
        </p>
      )}
      {issue.next_action && <p className="meta">{issue.next_action}</p>}
      {(reviewLink?.web_url || canRetry) && (
        <div className="actions" style={{ marginTop: "0.5rem" }}>
          {reviewLink?.web_url && (
            <a
              className="btn"
              href={reviewLink.web_url}
              target="_blank"
              rel="noreferrer"
            >
              Abrir Excel de revisión
            </a>
          )}
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
