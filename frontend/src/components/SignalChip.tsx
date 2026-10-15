import type { MouseEvent } from "react";
import { Link } from "react-router-dom";
import { ExternalLink } from "lucide-react";
import { cn } from "@/lib/utils";
import { iconFor } from "@/lib/icons";
import type { Signal, SignalKind } from "@/lib/types";

/** Fixed meaning: timing = gold · strength = sage · info = grey · risk = terracotta. */
export const SIGNAL_TONES: Record<SignalKind, { bg: string; fg: string }> = {
  timing: { bg: "bg-predicted-soft", fg: "text-predicted" },
  strength: { bg: "bg-accent-soft", fg: "text-accent" },
  info: { bg: "bg-chip", fg: "text-muted" },
  risk: { bg: "bg-warning-soft", fg: "text-danger" },
};

export interface SignalChipProps {
  signal: Pick<Signal, "kind" | "label" | "icon"> & { source_url?: string | null };
  /** chip = Deal Flow pill (icon + label) · row = Portfolio tile line (20px tinted icon tile + 13px ink label) */
  variant?: "chip" | "row";
  /** In-app link (the company page). The chip/row goes there; the source stays one click away on a small icon. */
  to?: string;
  className?: string;
}

const stop = (e: MouseEvent) => e.stopPropagation();

/** Small "open the source" icon next to a signal that also links somewhere in the app. */
function SourceIcon({ href, className }: { href: string; className?: string }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      onClick={stop}
      title="Open the source"
      aria-label="Open the source"
      className={cn("inline-flex shrink-0 items-center opacity-60 hover:opacity-100", className)}
    >
      <ExternalLink size={11} aria-hidden />
    </a>
  );
}

/** A signal with its icon. Goes to `to` when given (source on a small icon), else links to its source. */
export function SignalChip({ signal, variant = "chip", to, className }: SignalChipProps) {
  const Icon = iconFor(signal.icon);
  const tone = SIGNAL_TONES[signal.kind];
  const href = signal.source_url ?? undefined;

  if (variant === "row") {
    const content = (
      <>
        <span className={cn("flex size-[20px] shrink-0 items-center justify-center rounded-[6px]", tone.bg)}>
          <Icon size={12} className={tone.fg} aria-hidden />
        </span>
        <span className="flex-1 text-[13px] tracking-[0.1px] text-ink">{signal.label}</span>
      </>
    );
    const cls = cn("flex w-full items-center gap-[8px]", (href || to) && "hover:opacity-80", className);
    if (to) {
      return (
        <div className={cn("flex w-full items-center gap-[6px]", className)}>
          <Link to={to} onClick={stop} className="flex min-w-0 flex-1 items-center gap-[8px] hover:opacity-80">
            {content}
          </Link>
          {href && <SourceIcon href={href} className="text-muted" />}
        </div>
      );
    }
    return href ? (
      <a href={href} target="_blank" rel="noreferrer" className={cls}>
        {content}
      </a>
    ) : (
      <div className={cls}>{content}</div>
    );
  }

  const cls = cn(
    "inline-flex w-fit shrink-0 items-center gap-[5px] whitespace-nowrap rounded-full p-[3px_8px] text-[12px] tracking-[0.1px]",
    tone.bg,
    tone.fg,
    (href || to) && "hover:opacity-80",
    className,
  );
  const content = (
    <>
      <Icon size={12} aria-hidden />
      {signal.label}
    </>
  );
  if (to) {
    return (
      <span className={cls}>
        <Link to={to} onClick={stop} className="inline-flex items-center gap-[5px]">
          {content}
        </Link>
        {href && <SourceIcon href={href} />}
      </span>
    );
  }
  return href ? (
    <a href={href} target="_blank" rel="noreferrer" className={cls}>
      {content}
    </a>
  ) : (
    <span className={cls}>{content}</span>
  );
}
