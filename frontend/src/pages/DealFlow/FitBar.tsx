import { motion } from "motion/react";
import { cn } from "@/lib/utils";
import { isStrongFit } from "@/lib/format";

const EASE = [0.22, 1, 0.36, 1] as const;

/** "94%" + a 44px mini bar. Gold at 80% and above, otherwise ink text and a grey bar. */
export function FitCell({ fit, delay = 0 }: { fit: number; delay?: number }) {
  const strong = isStrongFit(fit);
  const width = Math.round((Math.max(0, Math.min(100, fit)) * 44) / 100);
  return (
    <div className="flex w-[96px] shrink-0 items-center gap-[8px]">
      <span className={cn("min-w-[27px] whitespace-nowrap text-[14px] font-medium", strong ? "text-predicted" : "text-ink")}>
        {fit}%
      </span>
      <span className="flex h-[4px] w-[44px] shrink-0 rounded-[2px] bg-[#1A18170F]" aria-hidden>
        <motion.span
          className={cn("h-[4px] rounded-[2px]", strong ? "bg-predicted" : "bg-competitor")}
          initial={{ width: 0 }}
          animate={{ width }}
          transition={{ duration: 0.7, delay: delay + 0.15, ease: EASE }}
        />
      </span>
    </div>
  );
}

/** One line of the fit breakdown in the expanded row: label, bar, %. */
export function FitPartBar({ label, value, strong }: { label: string; value: number; strong: boolean }) {
  const pct = Math.round(value * 100);
  return (
    <div className="flex items-center gap-[10px]">
      <span className="w-[130px] shrink-0 whitespace-nowrap text-[13px] text-muted">{label}</span>
      <span className="flex h-[4px] w-[120px] shrink-0 rounded-[2px] bg-[#1A18170F]" aria-hidden>
        <motion.span
          className={cn("h-[4px] rounded-[2px]", strong ? "bg-predicted" : "bg-competitor")}
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: 0.6, delay: 0.1, ease: EASE }}
        />
      </span>
      <span className="w-[36px] text-right font-mono text-[12px] text-subtle">{pct}%</span>
    </div>
  );
}
