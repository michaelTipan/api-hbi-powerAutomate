import type { ButtonHTMLAttributes, ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { Spinner } from "./Spinner";

interface LoadingButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "children"> {
  busy?: boolean;
  busyLabel?: string;
  variant?: "primary" | "secondary" | "danger";
  children: ReactNode;
}

const shadcnVariant = {
  primary: "default" as const,
  secondary: "secondary" as const,
  danger: "destructive" as const,
};

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
  const legacyClass =
    variant === "secondary" ? "secondary" : variant === "danger" ? "danger" : "primary";
  return (
    <Button
      type={type}
      variant={shadcnVariant[variant]}
      className={cn(legacyClass, className)}
      disabled={Boolean(disabled) || busy}
      aria-busy={busy ? "true" : undefined}
      {...rest}
    >
      {busy && <Spinner size="sm" />}
      <span>{busy && busyLabel ? busyLabel : children}</span>
    </Button>
  );
}
