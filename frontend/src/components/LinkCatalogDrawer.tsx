import { useEffect, useId, useMemo, useState } from "react";
import type { UiLink } from "../types/contract";
import { Modal } from "./Modal";
import { Spinner } from "./Spinner";

/** Enlace del catálogo con estado opcional (ASIENTOS listo/falta). */
export type CatalogDrawerLink = UiLink & {
  status?: "ready" | "missing" | "unknown";
  statusLabel?: string;
  statusDetail?: string | null;
};

/** Resumen de grupos listos / pendientes (fase Merge). */
export type CatalogGroupsProgress = {
  label: string;
  complete?: boolean;
};

/**
 * Catálogo modal para N enlaces (PDFs consolidados, tablas amort., ASIENTOS).
 * Evita saturar Documentos por fase: resumen en página + lista aquí.
 */
export function LinkCatalogDrawer({
  open,
  title,
  links,
  onClose,
  refreshing = false,
  groupsProgress = null,
}: {
  open: boolean;
  title: string;
  links: readonly CatalogDrawerLink[];
  onClose: () => void;
  /** GET en curso (p. ej. al abrir ASIENTOS). */
  refreshing?: boolean;
  /** Indicador listos/pendientes (drawer ASIENTOS). */
  groupsProgress?: CatalogGroupsProgress | null;
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
      const hay = `${l.label} ${l.path ?? ""} ${l.rel} ${l.statusLabel ?? ""} ${l.statusDetail ?? ""}`.toLowerCase();
      return hay.includes(q);
    });
  }, [links, query]);

  const showSearch = links.length >= 8;
  const hasStatus = links.some((l) => Boolean(l.statusLabel));

  if (!open) return null;

  return (
    <Modal titleId={titleId} title={`${title} (${links.length})`} onClose={onClose}>
      {groupsProgress ? (
        <p
          className={
            groupsProgress.complete
              ? "merge-groups-progress is-complete"
              : "merge-groups-progress"
          }
          role="status"
        >
          {groupsProgress.label}
        </p>
      ) : null}
      {refreshing ? (
        <p className="link-catalog-refresh" role="status" aria-live="polite">
          <Spinner size="sm" label="Actualizando estado" />
          <span className="meta">Comprobando carpetas…</span>
        </p>
      ) : null}
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
        <p className="muted">{refreshing ? "Cargando…" : "No hay coincidencias."}</p>
      ) : (
        <ul className="link-catalog-list">
          {filtered.map((link) => (
            <li key={link.rel} className="link-catalog-item">
              <div className="link-catalog-main">
                <span className="link-catalog-label" title={link.path ?? undefined}>
                  {link.label}
                </span>
                {hasStatus && link.statusLabel ? (
                  <p
                    className={
                      link.status === "ready"
                        ? "link-catalog-status is-ready"
                        : link.status === "missing"
                          ? "link-catalog-status is-missing"
                          : "link-catalog-status is-unknown"
                    }
                  >
                    {link.statusLabel}
                    {link.statusDetail ? (
                      <span className="link-catalog-status-detail"> — {link.statusDetail}</span>
                    ) : null}
                  </p>
                ) : null}
              </div>
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
