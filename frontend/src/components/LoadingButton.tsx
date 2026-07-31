import type { ButtonHTMLAttributes, ReactNode } from "react";
import { Spinner } from "./Spinner";

interface LoadingButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "children"> {
  busy?: boolean;
  busyLabel?: string;
  variant?: "primary" | "secondary";
  children: ReactNode;
}

/**
 * Botón con estado de carga: deshabilita, marca `aria-busy` y cambia el
 * texto visible por uno operativo (p. ej. "Verificando revisión…") en vez de
 * dejar solo un spinner sin contexto.
 */
export function LoadingButton({
  busy = false,
  busyLabel,
  variant = "primary",
  className = "",
  children,
  disabled,
  type = "button",
  ...rest
}: LoadingButtonProps) {
  const classes = ["btn", variant === "primary" ? "primary" : "secondary", className]
    .filter(Boolean)
    .join(" ");
  return (
    <button
      type={type}
      className={classes}
      disabled={Boolean(disabled) || busy}
      aria-busy={busy ? "true" : undefined}
      {...rest}
    >
      {busy && <Spinner size="sm" />}
      <span>{busy && busyLabel ? busyLabel : children}</span>
    </button>
  );
}
