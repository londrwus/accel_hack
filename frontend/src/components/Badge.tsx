import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import type { DealStatus, Health } from "@/lib/types";

/** gold = Bellwether's pick / new · sage = owned / working / under review · grey = neutral / passed ·
 *  warning = recovered, unverified (terracotta text) · danger = needs attention, clash (red text) */
export type BadgeTone = "gold" | "sage" | "grey" | "warning" | "danger";
export type BadgeSize = "xs" | "sm" | "md";

export const BADGE_TONES: Record<BadgeTone, { bg: string; fg: string; dot: string }> = {
  gold: { bg: "bg-predicted-soft", fg: "text-predicted", dot: "bg-predicted" },
  sage: { bg: "bg-accent-soft", fg: "text-accent", dot: "bg-accent" },
  grey: { bg: "bg-chip", fg: "text-muted", dot: "bg-subtle" },
  warning: { bg: "bg-warning-soft", fg: "text-warning", dot: "bg-warning" },
  danger: { bg: "bg-warning-soft", fg: "text-danger", dot: "bg-danger" },
};

const sizes: Record<BadgeSize, string> = {
  xs: "text-[11px] p-[2px_8px]", // stage chip on portfolio tiles
  sm: "text-[12px] p-[3px_10px]", // status chip in tables
  md: "text-[13px] p-[6px_12px] gap-[8px]", // header status chip "Working · 2m 14s"
};

export interface BadgeProps {
  tone?: BadgeTone;
  size?: BadgeSize;
  /** Leading 7px dot (header status chip). */
  dot?: boolean;
  /** Pulse the dot (live / working). */
  pulse?: boolean;
  className?: string;
  children: ReactNode;
}

/** Coloured status pill. */
export function Badge({ tone = "grey", size = "sm", dot, pulse, className, children }: BadgeProps) {
  const t = BADGE_TONES[tone];
  return (
    <span
      className={cn(
        "inline-flex w-fit shrink-0 items-center gap-[6px] whitespace-nowrap rounded-full tracking-[0.1px]",
        t.bg,
        t.fg,
        sizes[size],
        className,
      )}
    >
      {dot && (
        <span className="relative flex size-[7px]">
          {pulse && <span className={cn("absolute inset-0 animate-ping rounded-full opacity-60", t.dot)} />}
          <span className={cn("relative size-[7px] rounded-full", t.dot)} />
        </span>
      )}
      {children}
    </span>
  );
}

const STATUS: Record<DealStatus, { label: string; tone: BadgeTone }> = {
  new: { label: "New", tone: "gold" },
  under_review: { label: "Under review", tone: "sage" },
  passed: { label: "Passed", tone: "grey" },
};

/** Deal Flow status chip: New (gold) · Under review (sage) · Passed (grey). */
export function DealStatusBadge({ status, className }: { status: DealStatus; className?: string }) {
  const s = STATUS[status];
  return (
    <Badge tone={s.tone} className={className}>
      {s.label}
    </Badge>
  );
}

/** Portfolio health: design labels and colours (ids stay good|watch|at_risk|exited). */
export const HEALTH: Record<Health, { label: string; tone: BadgeTone; dot: string }> = {
  at_risk: { label: "Needs attention", tone: "danger", dot: "bg-danger" },
  watch: { label: "Likely to raise soon", tone: "gold", dot: "bg-predicted" },
  good: { label: "Doing well", tone: "sage", dot: "bg-accent" },
  exited: { label: "Exited", tone: "grey", dot: "bg-competitor" },
};
