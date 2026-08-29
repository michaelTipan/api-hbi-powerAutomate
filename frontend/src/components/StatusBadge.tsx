import type { HTMLAttributes, ReactNode } from "react";
import { statusClass } from "../domain/statusTone";
import { cn } from "@/lib/utils";

/**
 * Badge de estado operador unificado (panel + detalle).
 * Usa `.status-pill` + tokens semánticos de `statusTone`.
 */
export function StatusBadge({
  status,
  children,
  className,
  ...rest
}: {
  status: string | null | undefined;
  children: ReactNode;
  className?: string;
} & HTMLAttributes<HTMLSpanElement>) {
  const tone = statusClass(status);
  return (
    <span
      className={cn("status-pill", tone || undefined, className)}
      role="status"
      {...rest}
    >
      {children}
    </span>
  );
}
