/** Indicador de carga mínimo, accesible vía `role="status"` + texto oculto. */
export function Spinner({
  size = "sm",
  label = "Cargando…",
}: {
  size?: "sm" | "md";
  label?: string;
}) {
  return (
    <span className={`spinner spinner-${size}`} role="status">
      <span className="sr-only">{label}</span>
    </span>
  );
}
