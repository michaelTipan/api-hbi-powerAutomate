import { useEffect, useId, useMemo, useState } from "react";
import type { UiLink } from "../types/contract";
import { Modal } from "./Modal";

/**
 * Catálogo modal para N enlaces (PDFs consolidados, tablas amort.).
 * Evita saturar Documentos por fase: resumen en página + lista aquí.
 */
export function LinkCatalogDrawer({
  open,
  title,
  links,
  onClose,
}: {
  open: boolean;
  title: string;
  links: readonly UiLink[];
  onClose: () => void;
}) {
  const titleId = useId();
  const searchId = useId();
  const [query, setQuery] = useState("");

  useEffect(() => {
    if (!open) setQuery("");
  }, [open]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return [...links];
    return links.filter((l) => {
      const hay = `${l.label} ${l.path ?? ""} ${l.rel}`.toLowerCase();
      return hay.includes(q);
    });
  }, [links, query]);

  const showSearch = links.length >= 8;

  if (!open) return null;

  return (
    <Modal titleId={titleId} title={`${title} (${links.length})`} onClose={onClose}>
      {showSearch ? (
        <div className="link-catalog-search">
          <label className="sr-only" htmlFor={searchId}>
            Buscar en la lista
          </label>
          <input
            id={searchId}
            type="search"
            className="link-catalog-search-input"
            placeholder="Buscar por crédito o nombre…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
      ) : null}
      {filtered.length === 0 ? (
        <p className="muted">No hay coincidencias.</p>
      ) : (
        <ul className="link-catalog-list">
          {filtered.map((link) => (
            <li key={link.rel} className="link-catalog-item">
              <span className="link-catalog-label" title={link.path ?? undefined}>
                {link.label}
              </span>
              {link.web_url ? (
                <a
                  className="btn secondary"
                  href={link.web_url}
                  target="_blank"
                  rel="noreferrer"
                >
                  Abrir
                </a>
              ) : (
                <span className="meta" title={link.path ?? undefined}>
                  No disponible
                </span>
              )}
            </li>
          ))}
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
