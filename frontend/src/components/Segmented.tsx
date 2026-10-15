import { useId } from "react";
import { motion } from "motion/react";
import { cn } from "@/lib/utils";

export interface SegmentedOption<T extends string> {
  value: T;
  label: string;
  /** Small grey count after the label ("All 61"). */
  count?: number | null;
}

export interface SegmentedProps<T extends string> {
  options: SegmentedOption<T>[];
  /** null: no segment is highlighted (e.g. the map is centred on one company). */
  value: T | null;
  onChange: (value: T) => void;
  className?: string;
  "aria-label"?: string;
}

/** Grey track with a white pill on the active segment. The pill slides between segments. */
export function Segmented<T extends string>({ options, value, onChange, className, ...aria }: SegmentedProps<T>) {
  const layoutId = useId();
  return (
    <div
      role="tablist"
      aria-label={aria["aria-label"]}
      className={cn("flex w-fit shrink-0 gap-[2px] rounded-[12px] bg-track p-[3px]", className)}
    >
      {options.map((o) => {
        const active = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(o.value)}
            className={cn(
              "relative flex items-center gap-[6px] whitespace-nowrap rounded-[9px] p-[6px_12px] text-[13px] tracking-[0.1px] transition-colors",
              active ? "text-ink" : "text-muted hover:text-ink",
            )}
          >
            {active && (
              <motion.span
                layoutId={layoutId}
                className="absolute inset-0 rounded-[9px] bg-panel shadow-nav hairline"
                transition={{ type: "spring", bounce: 0.15, duration: 0.35 }}
              />
            )}
            <span className="relative">{o.label}</span>
            {o.count != null && <span className="relative text-[12px] text-subtle">{o.count}</span>}
          </button>
        );
      })}
    </div>
  );
}
