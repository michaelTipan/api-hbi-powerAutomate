import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-semibold transition-colors focus-visible:outline-none disabled:pointer-events-none disabled:cursor-not-allowed",
  {
    variants: {
      variant: {
        default:
          "bg-[var(--accent)] text-[var(--accent-foreground)] hover:bg-[var(--accent-hover)] disabled:bg-[#d4d4d8] disabled:text-[#3f3f46] disabled:hover:bg-[#d4d4d8]",
        secondary:
          "bg-[var(--brand-blue-secondary)] text-[var(--shell-ink)] border border-[var(--brand-blue-secondary)] hover:bg-[var(--brand-blue-secondary-hover)] hover:border-[var(--brand-blue-secondary-hover)] disabled:bg-[#e4e4e7] disabled:text-[#3f3f46] disabled:border-[#a1a1aa] disabled:hover:bg-[#e4e4e7]",
        outline:
          "border border-zinc-300 bg-white text-[var(--ink)] hover:bg-zinc-50 disabled:bg-zinc-100 disabled:text-zinc-500",
        ghost: "hover:bg-zinc-100 text-[var(--ink)] disabled:text-zinc-400",
        destructive:
          "bg-red-700 text-white hover:bg-red-800 disabled:bg-zinc-300 disabled:text-zinc-500",
      },
      size: {
        default: "min-h-11 px-4 py-2",
        sm: "min-h-9 rounded-md px-3 text-xs",
        lg: "min-h-12 rounded-md px-6 text-base",
        icon: "h-11 w-11",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp
        className={cn(buttonVariants({ variant, size }), className)}
        ref={ref}
        {...props}
      />
    );
  },
);
Button.displayName = "Button";

export { Button, buttonVariants };
