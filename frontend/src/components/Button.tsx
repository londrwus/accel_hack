import type { ButtonHTMLAttributes, ReactNode } from "react";
import { Link } from "react-router-dom";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

export type ButtonVariant = "gold" | "white" | "ghost";
export type ButtonSize = "md" | "sm" | "icon";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  /** md = page header (14px, 9/16 padding) · sm = cards (13px) · icon = icon only (Send) */
  size?: ButtonSize;
  /** Leading lucide icon. */
  icon?: LucideIcon;
  /** Trailing lucide icon. */
  iconRight?: LucideIcon;
  /** Render as a react-router <Link>. */
  to?: string;
  children?: ReactNode;
}

const base =
  "inline-flex shrink-0 items-center gap-[6px] whitespace-nowrap rounded-[12px] tracking-[0.1px] transition-opacity duration-150 hover:opacity-90 active:opacity-95 disabled:pointer-events-none disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-sage";

const variants: Record<ButtonVariant, string> = {
  gold: "gold-surface font-medium text-ink",
  white: "bg-panel hairline shadow-btn font-medium text-ink",
  ghost: "font-normal text-muted",
};

function sizeClass(variant: ButtonVariant, size: ButtonSize): string {
  if (size === "icon") return "p-[6px_8px]";
  if (size === "sm") return cn("text-[13px]", variant === "gold" ? "p-[5px_12px]" : "p-[5px_10px]");
  return cn("text-[14px]", variant === "ghost" ? "p-[9px_12px]" : "p-[9px_16px]");
}

/** Pill button from the Components frame: gold (primary), white (secondary), ghost (text only). */
export function Button({
  variant = "white",
  size = "md",
  icon: Icon,
  iconRight: IconRight,
  to,
  className,
  children,
  type = "button",
  ...rest
}: ButtonProps) {
  const iconSize = size === "sm" ? 13 : 15;
  const iconColor = variant === "gold" ? "text-ink" : "text-muted";
  const cls = cn(base, variants[variant], sizeClass(variant, size), className);
  const content = (
    <>
      {Icon && <Icon size={iconSize} className={iconColor} aria-hidden />}
      {children}
      {IconRight && <IconRight size={iconSize} className={iconColor} aria-hidden />}
    </>
  );
  if (to) {
    return (
      <Link to={to} className={cls}>
        {content}
      </Link>
    );
  }
  return (
    <button type={type} className={cls} {...rest}>
      {content}
    </button>
  );
}
