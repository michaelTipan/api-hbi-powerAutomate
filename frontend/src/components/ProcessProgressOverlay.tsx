import { useEffect } from "react";
import { useProcessBusy } from "../context/ProcessBusyContext";

export function ProcessProgressOverlay() {
  const {
    busy,
    label,
    detail,
    success,
    blockedMessage,
    lastError,
    clearSuccess,
    clearBlocked,
    clearLastError,
  } = useProcessBusy();

  useEffect(() => {
    if (!success) return;
    const t = window.setTimeout(() => clearSuccess(), 6000);
    return () => window.clearTimeout(t);
  }, [success, clearSuccess]);

  useEffect(() => {
    if (!blockedMessage) return;
    const t = window.setTimeout(() => clearBlocked(), 4000);
    return () => window.clearTimeout(t);
  }, [blockedMessage, clearBlocked]);

  if (!busy && !success && !blockedMessage && !lastError) {
    return null;
  }

  return (
    <div
      className="progress-overlay"
      role={busy ? "alertdialog" : "status"}
      aria-busy={busy}
      aria-live="polite"
    >
      <div className="progress-card">
        {busy && (
          <>
            <div className="progress-spinner" aria-hidden="true" />
            <h2 className="progress-title">{label || "Procesando…"}</h2>
            {detail && <p className="progress-detail">{detail}</p>}
            <p className="progress-hint muted">
              No cierre esta ventana. Las acciones quedan bloqueadas hasta terminar.
            </p>
          </>
        )}
        {!busy && success && (
          <>
            <div className="progress-success-icon" aria-hidden="true">
              ✓
            </div>
            <h2 className="progress-title">Listo</h2>
            <p className="progress-detail">{success}</p>
            <button className="btn" type="button" onClick={clearSuccess}>
              Cerrar
            </button>
          </>
        )}
        {!busy && lastError && (
          <>
            <h2 className="progress-title">Operación no completada</h2>
            <p className="progress-detail">{lastError}</p>
            <p className="progress-hint muted">
              Revise la lista «Errores a corregir» en el detalle del proceso.
            </p>
            <button className="btn primary" type="button" onClick={clearLastError}>
              Entendido
            </button>
          </>
        )}
        {!busy && blockedMessage && (
          <>
            <h2 className="progress-title">Proceso en curso</h2>
            <p className="progress-detail">{blockedMessage}</p>
            <button className="btn" type="button" onClick={clearBlocked}>
              Entendido
            </button>
          </>
        )}
      </div>
    </div>
  );
}
