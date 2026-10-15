import type { ReactNode } from "react";
import { Ellipsis, Plus } from "lucide-react";
import { cn } from "@/lib/utils";
import { formatShare } from "@/lib/format";
import { Button } from "./Button";

export interface BarSegment {
  label: string;
  /** 0..1 of the full bar width. Shares that sum to < 1 leave the rest of the track empty, like the design. */
  share: number;
  color: string;
  /** Legend value, e.g. a count (14). Defaults to the share as %. */
  value?: ReactNode;
}

/** Thin multi-colour bar (10px, 2px gaps, radius 3). */
export function SegmentedBar({ segments, height = 10, className }: { segments: BarSegment[]; height?: number; className?: string }) {
  return (
    <div className={cn("flex w-full gap-[2px] overflow-hidden rounded-[3px]", className)} style={{ height }}>
      {segments.map((s) => (
        <div
          key={s.label}
          title={`${s.label}: ${formatShare(s.share)}`}
          className="h-full shrink-0"
          style={{ width: `${s.share * 100}%`, background: s.color }}
        />
      ))}
    </div>
  );
}

/** Legend rows: dot · label · value · (%). */
export function BarLegend({ segments, showPercent = true, className }: { segments: BarSegment[]; showPercent?: boolean; className?: string }) {
  return (
    <div className={cn("flex flex-col gap-[6px]", className)}>
      {segments.map((s) => (
        <div key={s.label} className="flex items-center gap-[10px] text-[13px] tracking-[0.1px]">
          <span className="size-[7px] shrink-0 rounded-[2px]" style={{ background: s.color }} />
          <span className="flex-1 text-ink">{s.label}</span>
          <span className="font-medium text-ink">{s.value ?? formatShare(s.share)}</span>
          {showPercent && s.value != null && <span className="text-subtle">({formatShare(s.share)})</span>}
        </div>
      ))}
    </div>
  );
}

export interface DataCardProps {
  title: ReactNode;
  segments: BarSegment[];
  /** Footer text on the left, e.g. "Save to the fund profile". Omit to hide the footer. */
  footer?: ReactNode;
  /** Footer button label (default "Save"). */
  actionLabel?: string;
  onAction?: () => void;
  onMenu?: () => void;
  className?: string;
}

/** Hairline card: header label + ⋯ · segmented bar · legend · footer action + Save. */
export function DataCard({ title, segments, footer, actionLabel = "Save", onAction, onMenu, className }: DataCardProps) {
  return (
    <div className={cn("flex w-full flex-col overflow-hidden rounded-[14px] hairline", className)}>
      <div className="flex items-center justify-between border-b border-hair p-[11px_14px]">
        <span className="text-[13px] tracking-[0.1px] text-muted">{title}</span>
        <button type="button" onClick={onMenu} aria-label="More" className="text-muted hover:text-ink">
          <Ellipsis size={16} />
        </button>
      </div>
      <div className="p-[12px_14px_4px_14px]">
        <SegmentedBar segments={segments} />
      </div>
      <BarLegend segments={segments} className="p-[6px_14px_10px_14px]" />
      {footer != null && (
        <div className="flex items-center justify-between border-t border-hair p-[8px_10px_8px_14px]">
          <span className="text-[13px] tracking-[0.1px] text-muted">{footer}</span>
          <Button size="sm" icon={Plus} onClick={onAction}>
            {actionLabel}
          </Button>
        </div>
      )}
    </div>
  );
}
