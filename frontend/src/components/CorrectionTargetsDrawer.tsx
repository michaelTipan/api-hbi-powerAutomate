import { useEffect, useId, useMemo, useState } from "react";
import type { UiOperationalIssue } from "../types/contract";
import {
  correctionTargetEntryLabel,
  openableIssueLinks,
} from "../domain/correctionTargets";
import { Modal } from "./Modal";

export type CorrectionTargetEntry = {
  issue: UiOperationalIssue;
  label: string;
};

/**
 * Drawer de destinos de corrección (hoja Errores / problemas operativos).
 * Hermano de LinkCatalogDrawer: no altera el catálogo ASIENTOS/amort.
 */
export function CorrectionTargetsDrawer({
  open,
  title = "Destinos de corrección",
  issues,
  onClose,
}: {
  open: boolean;
  title?: string;
  issues: readonly UiOperationalIssue[];
  onClose: () => void;
}) {
  const titleId = useId();
  const searchId = useId();
  const [query, setQuery] = useState("");

  useEffect(() => {
    if (!open) setQuery("");
  }, [open]);

  const entries = useMemo((): CorrectionTargetEntry[] => {
    return issues
      .map((issue) => ({
        issue,
        label: correctionTargetEntryLabel(issue),
      }))
      .filter((e) => openableIssueLinks(e.issue).length > 0);
  }, [issues]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return entries;
    return entries.filter((e) => {
      const linksTxt = openableIssueLinks(e.issue)
        .map((l) => `${l.label} ${l.rel}`)
        .join(" ");
      const hay = `${e.label} ${e.issue.user_message} ${e.issue.next_action ?? ""} ${linksTxt}`.toLowerCase();
      return hay.includes(q);
    });
  }, [entries, query]);

  const showSearch = entries.length >= 8;
  const destinationCount = entries.reduce(
    (n, e) => n + openableIssueLinks(e.issue).length,
    0,
  );

  if (!open) return null;

  return (
    <Modal
      titleId={titleId}
      title={`${title} (${destinationCount})`}
      onClose={onClose}
    >
      <p className="meta" style={{ marginTop: 0 }}>
        Enlaces del último archivo de revisión. Tras corregir en SharePoint, use
        Regenerar en la fase actual.
      </p>
      {showSearch ? (
        <div className="link-catalog-search">
          <label className="sr-only" htmlFor={searchId}>
            Buscar destinos de corrección
          </label>
          <input
            id={searchId}
            type="search"
            className="link-catalog-search-input"
            placeholder="Buscar por crédito, cliente o tipo…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
      ) : null}
      {filtered.length === 0 ? (
        <p className="muted">No hay coincidencias.</p>
      ) : (
        <ul className="link-catalog-list correction-targets-list">
          {filtered.map((entry) => {
            const links = openableIssueLinks(entry.issue);
            return (
              <li key={entry.issue.issue_id} className="correction-targets-item">
                <div className="correction-targets-head">
                  <span className="link-catalog-label" title={entry.issue.user_message}>
                    {entry.label}
                  </span>
                  {entry.issue.next_action ? (
                    <p className="meta correction-targets-action">
                      {entry.issue.next_action}
                    </p>
                  ) : null}
                </div>
                <div className="correction-targets-links">
                  {links.map((link) => (
                    <a
                      key={`${entry.issue.issue_id}-${link.rel}-${link.web_url}`}
                      className="btn secondary"
                      href={link.web_url!}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {link.label || "Abrir"}
                    </a>
                  ))}
                </div>
              </li>
            );
          })}
        </ul>
      )}
      <div className="modal-actions">
        <button type="button" className="btn secondary" onClick={onClose}>
          Cerrar
        </button>
      </div>
    </Modal>
  );
}
