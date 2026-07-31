import { useId, useState, type ReactNode } from "react";

/**
 * Sección plegable reutilizable (checklist de ayuda, historial de intentos,
 * detalles técnicos). Usa un botón real con `aria-expanded`/`aria-controls`
 * en vez de `<details>` para mantener un único patrón visual y de a11y.
 */
export function Disclosure({
  summary,
  children,
  defaultOpen = false,
  className,
}: {
  summary: ReactNode;
  children: ReactNode;
  defaultOpen?: boolean;
  className?: string;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const contentId = useId();

  return (
    <div className={`disclosure${className ? ` ${className}` : ""}`}>
      <button
        type="button"
        className="disclosure-trigger"
        aria-expanded={open}
        aria-controls={contentId}
        onClick={() => setOpen((prev) => !prev)}
      >
        <span className={`disclosure-caret${open ? " open" : ""}`} aria-hidden="true">
          ▸
        </span>
        {summary}
      </button>
      {open && (
        <div id={contentId} className="disclosure-content">
          {children}
        </div>
      )}
    </div>
  );
}
