import { Spinner } from "./Spinner";

/**
 * Indicador visible mientras un job está en cola o en curso.
 * Complementa el texto del botón: el operador ve que el sistema sigue trabajando
 * aunque el modal de confirmación ya se haya cerrado.
 */
export function ProcessingBanner({
  title,
  message,
}: {
  title?: string;
  message?: string | null;
}) {
  return (
    <div className="processing-banner" role="status" aria-live="polite" aria-busy="true">
      <Spinner size="md" label={title || "Procesando…"} />
      <div className="processing-banner-text">
        <strong>{title || "Procesando…"}</strong>
        {message ? <p className="meta">{message}</p> : null}
      </div>
    </div>
  );
}
