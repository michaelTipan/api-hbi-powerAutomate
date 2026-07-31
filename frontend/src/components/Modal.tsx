import { useEffect, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";

const FOCUSABLE_SELECTOR =
  'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export interface ModalProps {
  titleId: string;
  title: string;
  descriptionId?: string;
  onClose: () => void;
  /** Si el cierre está deshabilitado (p. ej. acción en curso), Escape/backdrop no cierran. */
  closeDisabled?: boolean;
  children: ReactNode;
}

/**
 * Diálogo accesible reutilizable: `role="dialog"` + `aria-modal`, trampa de
 * foco, cierre con Escape, restauración del foco anterior y fondo `inert`
 * (el resto de la app deja de ser accesible por teclado/lector de pantalla
 * mientras el modal está abierto).
 */
export function Modal({
  titleId,
  title,
  descriptionId,
  onClose,
  closeDisabled = false,
  children,
}: ModalProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    previousFocusRef.current = document.activeElement as HTMLElement | null;
    const appRoot = document.getElementById("root");
    appRoot?.setAttribute("inert", "");
    appRoot?.setAttribute("aria-hidden", "true");

    const dialog = dialogRef.current;
    const first = dialog?.querySelector<HTMLElement>(FOCUSABLE_SELECTOR);
    first?.focus();

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        if (closeDisabled) return;
        event.stopPropagation();
        onClose();
        return;
      }
      if (event.key === "Tab" && dialog) {
        const items = Array.from(dialog.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR));
        if (items.length === 0) return;
        const firstItem = items[0];
        const lastItem = items[items.length - 1];
        if (event.shiftKey && document.activeElement === firstItem) {
          event.preventDefault();
          lastItem.focus();
        } else if (!event.shiftKey && document.activeElement === lastItem) {
          event.preventDefault();
          firstItem.focus();
        }
      }
    }

    document.addEventListener("keydown", handleKeyDown, true);
    return () => {
      document.removeEventListener("keydown", handleKeyDown, true);
      appRoot?.removeAttribute("inert");
      appRoot?.removeAttribute("aria-hidden");
      previousFocusRef.current?.focus();
    };
  }, [onClose, closeDisabled]);

  return createPortal(
    <div
      className="modal-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !closeDisabled) {
          onClose();
        }
      }}
    >
      <div
        ref={dialogRef}
        className="panel modal-card"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
      >
        <h2 id={titleId} style={{ marginTop: 0 }}>
          {title}
        </h2>
        {children}
      </div>
    </div>,
    document.body,
  );
}
