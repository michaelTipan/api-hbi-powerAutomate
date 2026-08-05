import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";
import type { UiEnvironmentResponse } from "../types/contract";
import { isMockMode } from "../api/client";

export function AppShell({
  environment,
  children,
  onLogout,
  historyEnabled = false,
}: {
  environment: UiEnvironmentResponse | null;
  children: ReactNode;
  onLogout?: () => void;
  /** Nav Historial; default false (UI_HISTORY_ENABLED). Archivo Apply intacto. */
  historyEnabled?: boolean;
}) {
  const label = environment?.display_label ?? "…";
  const isProd = environment?.environment === "production";
  return (
    <div className="app-shell-frame">
      <a href="#main-content" className="skip-link">
        Saltar al contenido principal
      </a>
      <aside className="app-sidebar" aria-label="Navegación principal">
        <div className="sidebar-brand">
          <span className="sidebar-brand-mark" aria-hidden="true">
            HBI
          </span>
          <span className="sidebar-brand-text">HBI Capital</span>
        </div>
        <nav className="sidebar-nav">
          <NavLink
            to="/"
            end
            className={({ isActive }) =>
              isActive ? "sidebar-link is-active" : "sidebar-link"
            }
          >
            <span className="sidebar-link-icon" aria-hidden="true">
              <svg
                className="sidebar-link-svg"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.75"
                strokeLinecap="round"
                strokeLinejoin="round"
                focusable="false"
              >
                <rect x="3" y="3" width="8" height="8" rx="1.25" />
                <rect x="13" y="3" width="8" height="5" rx="1.25" />
                <rect x="13" y="10" width="8" height="11" rx="1.25" />
                <rect x="3" y="13" width="8" height="8" rx="1.25" />
              </svg>
            </span>
            Panel
          </NavLink>
          {historyEnabled ? (
            <NavLink
              to="/historial"
              className={({ isActive }) =>
                isActive ? "sidebar-link is-active" : "sidebar-link"
              }
            >
              <span className="sidebar-link-icon" aria-hidden="true">
                <svg
                  className="sidebar-link-svg"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.75"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  focusable="false"
                >
                  <path d="M3 12a9 9 0 1 0 3-6.7" />
                  <polyline points="3 4 3 9 8 9" />
                  <polyline points="12 7 12 12 16 14" />
                </svg>
              </span>
              Historial
            </NavLink>
          ) : null}
        </nav>
        {onLogout ? (
          <div className="sidebar-footer">
            <button type="button" className="sidebar-logout" onClick={onLogout}>
              Cerrar sesión
            </button>
          </div>
        ) : null}
      </aside>
      <div className="app-shell">
        <header className="topbar">
          <div>
            <p className="subtitle topbar-title">
              Validación de pagos · operación centralizada
              {isMockMode() ? " · datos de demostración" : ""}
            </p>
          </div>
          <div className="topbar-actions">
            <div
              className={`env-badge${isProd ? " production" : ""}`}
              title="Ambiente activo (backend)"
            >
              {label}
            </div>
            <div className="operator-badge" title="Rol de sesión">
              <span className="operator-badge-icon" aria-hidden="true">
                <svg
                  className="operator-badge-svg"
                  viewBox="0 0 24 24"
                  focusable="false"
                >
                  <circle cx="12" cy="8" r="3.25" fill="currentColor" />
                  <path
                    fill="currentColor"
                    d="M5.5 18.75c.6-3.35 3.2-5.25 6.5-5.25s5.9 1.9 6.5 5.25a.75.75 0 0 1-.73.9H6.23a.75.75 0 0 1-.73-.9Z"
                  />
                </svg>
              </span>
              <span>Operador HBI</span>
            </div>
          </div>
        </header>
        <main id="main-content" tabIndex={-1}>
          {children}
        </main>
      </div>
    </div>
  );
}

/** Reexport: mapeo semántico central en `domain/statusTone`. */
export { statusClass } from "../domain/statusTone";
