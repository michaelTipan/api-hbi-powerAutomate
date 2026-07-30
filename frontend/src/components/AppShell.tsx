import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import type { UiEnvironmentResponse } from "../types/contract";
import { isMockMode } from "../api/client";

export function AppShell({
  environment,
  children,
  onLogout,
}: {
  environment: UiEnvironmentResponse | null;
  children: ReactNode;
  onLogout?: () => void;
}) {
  const label = environment?.display_label ?? "…";
  const isProd = environment?.environment === "production";
  return (
    <div className="app-shell">
      <header className="topbar">
        <div>
          <p className="brand">
            <Link to="/" style={{ color: "inherit", textDecoration: "none" }}>
              HBI Capital
            </Link>
          </p>
          <p className="subtitle">
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
          {onLogout ? (
            <button type="button" className="logout-btn" onClick={onLogout}>
              Cerrar sesión
            </button>
          ) : null}
        </div>
      </header>
      {children}
    </div>
  );
}

export function statusClass(status: string): string {
  if (
    status === "COMPLETADO" ||
    status === "completed" ||
    status === "EN_REVISION" ||
    status === "LISTO_PARA_APLICAR"
  ) {
    return "ok";
  }
  if (
    status.includes("ERROR") ||
    status.includes("failed") ||
    status === "CORRECCION_REQUERIDA"
  ) {
    return "danger";
  }
  if (
    status.includes("PARCIAL") ||
    status.includes("ESPERANDO") ||
    status === "partial" ||
    status === "blocked" ||
    status === "in_progress"
  ) {
    return "warn";
  }
  return "";
}
