import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { formatCount } from "@/lib/format";
import type { Backtest } from "@/lib/types";
import type { DatasetMeta } from "./useUniverseRows";
import { CountUp } from "./CountUp";

function Kpi({ value, label, tone = "ink", first, last }: { value: ReactNode; label: ReactNode; tone?: "ink" | "gold" | "sage" | "subtle"; first?: boolean; last?: boolean }) {
  return (
    <div className={cn("flex min-w-0 flex-col gap-[2px]", first ? "pr-[20px]" : "px-[20px]", !last && "border-r border-hair")}>
      <div
        className={cn(
          "whitespace-nowrap text-[28px] tracking-[-0.5px]",
          tone === "gold" && "text-predicted",
          tone === "sage" && "text-accent",
          tone === "ink" && "text-ink",
          tone === "subtle" && "text-subtle",
        )}
      >
        {value}
      </div>
      <div className="text-[13px] tracking-[0.1px] text-muted">{label}</div>
    </div>
  );
}

const dash = <span aria-label="not available">–</span>;

/** Boxless KPI strip: dataset size, sectors, countries, backtest hit rate (gold), scoring speed (sage). */
export function KpiStrip({ meta, backtest, backtestMissing, fundName }: { meta: DatasetMeta | null; backtest: Backtest | null; backtestMissing: boolean; fundName: string }) {
  const best = backtest?.methods[0];
  const hasHistory = Boolean(backtest?.enough_history && best);
  return (
    <section aria-label="The dataset in numbers" className="grid h-[108px] shrink-0 grid-cols-5 items-stretch border-b border-hair p-[18px_24px]">
      <Kpi first value={meta ? <CountUp value={meta.dataset_size} /> : dash} label="startups in the dataset" />
      <Kpi value={meta ? <CountUp value={meta.sectors} delay={0.05} /> : dash} label="sectors" />
      <Kpi value={meta ? <CountUp value={meta.countries} delay={0.1} /> : dash} label="countries" />
      {hasHistory && best ? (
        <Kpi
          tone="gold"
          value={
            <>
              <CountUp value={best.found} delay={0.15} /> of {best.total}
            </>
          }
          label={`past ${fundName} deals found by the model`}
        />
      ) : (
        <Kpi
          tone="subtle"
          value={dash}
          label={backtest || backtestMissing ? `Not enough history to test on past ${fundName} deals` : `past ${fundName} deals found by the model`}
        />
      )}
      <Kpi
        last
        tone="sage"
        value={backtest && backtest.score_seconds > 0 ? <><CountUp value={backtest.score_seconds} decimals={backtest.score_seconds < 1 ? 2 : 1} delay={0.2} />s</> : dash}
        label={`to score all ${meta ? formatCount(meta.dataset_size) : ""} for a fund`}
      />
    </section>
  );
}
