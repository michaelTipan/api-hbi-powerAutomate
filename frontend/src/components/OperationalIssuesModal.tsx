import { useEffect, useId, useMemo, useState } from "react";
import type { UiOperationalIssue } from "../types/contract";
import { correctionTargetEntryLabel } from "../domain/correctionTargets";
import { Modal } from "./Modal";
import { OperationalIssuePanel } from "./OperationalIssuePanel";

/**
 * Modal con el detalle completo de problemas operativos (hoja Errores u otros).
 * Evita saturar ProcessDetailPage: la página solo muestra un banner compacto.
 */
export function OperationalIssuesModal({
  open,
  title = "Problemas operativos",
  issues,
  onClose,
  onRetryFor,
  retryBusy = false,
}: {
  open: boolean;
  title?: string;
  issues: readonly UiOperationalIssue[];
  onClose: () => void;
  onRetryFor?: (action: string | null | undefined) => (() => void) | undefined;
  retryBusy?: boolean;
}) {
  const titleId = useId();
  const searchId = useId();
  const [query, setQuery] = useState("");

  useEffect(() => {
    if (!open) setQuery("");
  }, [open]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return [...issues];
    return issues.filter((issue) => {
      const label = correctionTargetEntryLabel(issue);
      const linksTxt = (issue.links ?? [])
        .map((l) => `${l.label} ${l.rel}`)
        .join(" ");
      const hay =
        `${label} ${issue.user_message} ${issue.next_action ?? ""} ${linksTxt}`.toLowerCase();
      return hay.includes(q);
    });
  }, [issues, query]);

  const showSearch = issues.length >= 8;

  if (!open) return null;

  return (
    <Modal
      titleId={titleId}
      title={`${title} (${issues.length})`}
      onClose={onClose}
    >
      <p className="meta" style={{ marginTop: 0 }}>
        Revise cada caso, abra los enlaces en SharePoint y regenere o verifique
        según corresponda.
      </p>
      {showSearch ? (
        <div className="link-catalog-search">
          <label className="sr-only" htmlFor={searchId}>
            Buscar problemas operativos
          </label>
          <input
            id={searchId}
            type="search"
            className="link-catalog-search-input"
            placeholder="Buscar por crédito, cliente o mensaje…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
      ) : null}
      {filtered.length === 0 ? (
        <p className="muted">No hay coincidencias.</p>
      ) : (
        <div className="operational-issues-modal-list">
          {filtered.map((issue) => (
            <OperationalIssuePanel
              key={issue.issue_id}
              issue={issue}
              onRetry={onRetryFor?.(issue.retry?.action)}
              retryBusy={retryBusy}
              maxPrimaryLinks={Number.POSITIVE_INFINITY}
            />
          ))}
        </div>
      )}
      <div className="modal-actions">
        <button type="button" className="btn secondary" onClick={onClose}>
          Cerrar
        </button>
      </div>
    </Modal>
  );
}
