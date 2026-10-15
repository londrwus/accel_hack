import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { formatRowId } from "@/lib/format";
import type { Source } from "@/lib/types";

export type ChipSize = "xs" | "sm" | "md";

export interface ChipProps {
  /** xs = source chip (11px) · sm = "never used" chips (12px) · md = meta value chip (13px, ink) */
  size?: ChipSize;
  /** "warning" = terracotta (e.g. "not verified"). */
  tone?: "default" | "warning";
  icon?: LucideIcon;
  /** Strike the text through (e.g. "Never used: Gender"). */
  strike?: boolean;
  mono?: boolean;
  /** Makes the chip a link (opens in a new tab). */
  href?: string | null;
  title?: string;
  className?: string;
  children: ReactNode;
}

const sizes: Record<ChipSize, string> = {
  xs: "text-[11px] p-[2px_8px] text-ink/80",
  sm: "text-[12px] p-[3px_10px] text-muted",
  md: "text-[13px] p-[3px_9px] text-ink",
};

/** Subtle filled grey pill for values, sources and filters. */
export function Chip({ size = "sm", tone = "default", icon: Icon, strike, mono, href, title, className, children }: ChipProps) {
  const cls = cn(
    "inline-flex w-fit shrink-0 items-center gap-[5px] whitespace-nowrap rounded-full tracking-[0.2px]",
    sizes[size],
    tone === "warning" ? "bg-warning-soft text-warning hairline" : size === "xs" ? "bg-[#1a181712] hairline" : "bg-chip",
    strike && "line-through decoration-subtle",
    mono && "font-mono",
    href && "transition-opacity hover:opacity-80",
    className,
  );
  const inner = (
    <>
      {Icon && <Icon size={size === "md" ? 13 : 12} aria-hidden />}
      {children}
    </>
  );
  if (href) {
    return (
      <a href={href} target="_blank" rel="noreferrer" className={cls} title={title}>
        {inner}
      </a>
    );
  }
  return (
    <span className={cls} title={title}>
      {inner}
    </span>
  );
}

/** Quiet "Label: value" pair, e.g. Stage: [Seed]. */
export function LabeledChip({ label, children, className }: { label: string; children: ReactNode; className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-[8px]", className)}>
      <span className="text-[13px] tracking-[0.2px] text-subtle">{label}</span>
      <Chip size="md">{children}</Chip>
    </span>
  );
}

/** Source chip for a memo claim: links to the URL, or shows "dataset #4821". null source = "not verified". */
export function SourceChip({ source, verified = true }: { source: Source | null; verified?: boolean }) {
  if (!verified || !source) {
    return (
      <Chip size="xs" tone="warning">
        not verified
      </Chip>
    );
  }
  const label = source.label || (source.row_id != null ? `dataset ${formatRowId(source.row_id)}` : "source");
  return (
    <Chip size="xs" href={source.url}>
      {label}
    </Chip>
  );
}
