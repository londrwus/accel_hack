import type { ButtonHTMLAttributes, ReactNode } from "react";
import { ArrowRight } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Landing-page pill buttons. The marketing page uses flat, fully rounded pills (not the app's glossy Button):
 * gold #D8B56A or sage #A3BBA6, 0 2px 5px shadow, optional arrow circle that nudges right on hover.
 */
export interface PillProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  tone?: "gold" | "sage";
  size?: "lg" | "md" | "sm";
  arrow?: boolean;
  shadow?: boolean;
  children: ReactNode;
}

export function Pill({ tone = "gold", size = "lg", arrow, shadow = true, className, children, type = "button", ...rest }: PillProps) {
  const pad =
    size === "sm"
      ? "p-[8px_8px_8px_16px] text-[13px]"
      : arrow
        ? "p-[10px_10px_10px_20px] text-[16px]"
        : size === "md"
          ? "p-[12px_20px] text-[14px]"
          : "p-[12px_20px] text-[16px]";
  return (
    <button
      type={type}
      className={cn(
        "group inline-flex shrink-0 items-center gap-[10px] whitespace-nowrap rounded-full font-normal leading-normal tracking-[0.2px] text-ink",
        "transition-opacity duration-150 hover:opacity-90 active:opacity-95 disabled:opacity-60",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
        tone === "gold" ? "bg-cta" : "bg-sage",
        shadow && "shadow-[0_2px_5px_#32326926]",
        pad,
        className,
      )}
      {...rest}
    >
      <span>{children}</span>
      {arrow && (
        <span
          aria-hidden
          className={cn(
            "flex shrink-0 items-center justify-center rounded-full transition-transform duration-200 ease-[cubic-bezier(0.22,1,0.36,1)] group-hover:translate-x-[2px]",
            size === "sm" ? "size-[20px]" : "size-[24px] bg-[#1A181714]",
          )}
        >
          <ArrowRight size={size === "sm" ? 11 : 13} strokeWidth={2.25} className="text-ink" />
        </span>
      )}
    </button>
  );
}
