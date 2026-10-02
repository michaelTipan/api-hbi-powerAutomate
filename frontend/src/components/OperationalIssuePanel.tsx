import { Fragment, type ReactNode } from "react";
import type { UiOperationalIssue } from "../types/contract";
import {
  CORRECTION_PRIMARY_LINKS_MAX,
  primaryIssueLinks,
} from "../domain/correctionTargets";
import {
  buildIssueEvidenceLines,
  formatOperationalValueFound,
  refineNextActionForOpenCta,
} from "../domain/operationalIssueDisplay";

export { formatOperationalValueFound };

function renderMarkdownLite(text: string) {
  if (!text) return null;
  return text.split("\n").map((line, i) => {
    const isBullet = line.startsWith("* ");
    const content = isBullet ? line.slice(2) : line;
    const parts = content.split(/\*\*(.*?)\*\*/g);
    const rendered = parts.map((p, j) =>
      j % 2 === 1 ? <strong key={j}>{p}</strong> : p,
    );
    return (
      <Fragment key={i}>
        {i > 0 && <br />}
        {isBullet ? (
          <span style={{ paddingLeft: "0.75rem" }}>{"• "}{rendered}</span>
        ) : (
          rendered
        )}
      </Fragment>
    );
  });
}

export function OperationalIssuePanel({
  issue,
  onRetry,
  retryBusy = false,
  maxPrimaryLinks = CORRECTION_PRIMARY_LINKS_MAX,
  hideLinks = false,
  footer,
}: {
  issue: UiOperationalIssue;
  onRetry?: () => void;
  retryBusy?: boolean;
  /** Máximo de botones de enlace (prioritarios). 0 = ninguno. */
  maxPrimaryLinks?: number;
  /** Oculta enlaces (p. ej. cuando el drawer concentra los destinos). */
  hideLinks?: boolean;
  /** Acciones propias del problema (p. ej. «Excluir crédito 148»), dentro de la tarjeta. */
  footer?: ReactNode;
}) {
  const canRetry = Boolean(issue.retry?.allowed && onRetry);
  const links = hideLinks ? [] : primaryIssueLinks(issue, maxPrimaryLinks);
  const evidence = buildIssueEvidenceLines(issue);
  const nextAction = refineNextActionForOpenCta(issue.next_action, links);

  return (
    <div className="error-box" role="alert" data-issue-id={issue.issue_id}>
      <strong className="operational-issue-title">{issue.title}</strong>
      <p className="operational-issue-body">{renderMarkdownLite(issue.user_message)}</p>
      {evidence.length > 0 ? (
        <div className="operational-issue-evidence">
          {evidence.map((line) => (
            <p key={line.key} className="meta">
              {line.text}
            </p>
          ))}
        </div>
      ) : null}
      {nextAction ? (
        <p className="operational-issue-next meta">{nextAction}</p>
      ) : null}
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
      {footer ? <div className="operational-issue-footer">{footer}</div> : null}
    </div>
  );
}
