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
      <a href="#main-content" className="skip-link">
        Saltar al contenido principal
      </a>
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
      <main id="main-content" tabIndex={-1}>
        {children}
      </main>
    </div>
  );
}

/**
 * Clase visual para un estado (`OperationalStatus`, `StepStatus` o similar).
 *
 * `EN_REVISION` es un estado de espera de acción humana, no un éxito: usa la
 * clase neutral `info` en vez de `ok` (verde), reservado para lo ya
 * completado. `in_progress` y `CORRECCION_REQUERIDA` nunca deben caer en `ok`.
 */
export function statusClass(status: string): string {
  if (status === "COMPLETADO" || status === "completed" || status === "LISTO_PARA_APLICAR") {
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
  if (
    status === "EN_REVISION" ||
    status === "GENERANDO" ||
    status === "FINALIZANDO" ||
    status === "PENDIENTE_NOTIFICACION" ||
    status === "NOTIFICANDO" ||
    status === "CONSOLIDANDO" ||
    status === "VALIDANDO_AMORTIZACION" ||
    status === "APLICANDO" ||
    status === "SINCRONIZANDO" ||
    status === "sync_pending" ||
    status === "queued" ||
    status === "running"
  ) {
    return "info";
  }
  if (status === "DESCONOCIDO") {
    return "warn";
  }
  return "";
}
