import { useEffect, useState } from "react";
import { animate, useReducedMotion } from "motion/react";
import { cn } from "@/lib/utils";
import type { PortfolioKpis } from "@/lib/types";

const EASE = [0.22, 1, 0.36, 1] as const;

/** Counts a number up from 0 once. Keeps any prefix/suffix ("£38M" -> "£" 38 "M"). */
function CountUp({ value }: { value: string | number }) {
  const reduce = useReducedMotion();
  const text = String(value);
  const match = text.match(/^(\D*)(\d+(?:\.\d+)?)(.*)$/);
  const target = match ? Number(match[2]) : 0;
  const decimals = match?.[2].includes(".") ? match[2].split(".")[1].length : 0;
  const [shown, setShown] = useState(reduce || !match ? target : 0);

  useEffect(() => {
    if (reduce || !match) {
      setShown(target);
      return;
    }
    const controls = animate(0, target, { duration: 0.8, ease: EASE, onUpdate: setShown });
    return () => controls.stop();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target, reduce]);

  if (!match) return <>{text}</>;
  return (
    <>
      {match[1]}
      {shown.toFixed(decimals)}
      {match[3]}
    </>
  );
}

interface Kpi {
  value: string | number;
  label: string;
  color: string;
}

/** Box-less KPI row with hairline dividers between the five numbers. */
export function KpiStrip({ kpis }: { kpis: PortfolioKpis }) {
  const items: Kpi[] = [
    { value: kpis.companies_backed, label: "companies backed", color: "text-ink" },
    { value: kpis.invested, label: "invested to date", color: "text-ink" },
    { value: kpis.likely_to_raise, label: "likely to raise soon", color: "text-predicted" },
    { value: kpis.need_attention, label: "need attention", color: "text-danger" },
    { value: kpis.new_signals_this_week, label: "new signals this week", color: "text-accent" },
  ];
  return (
    <section
      aria-label="Portfolio at a glance"
      className="-mt-px grid shrink-0 grid-cols-5 items-start border-b border-hair p-[18px_24px]"
    >
      {items.map((k, i) => (
        <div
          key={k.label}
          className={cn(
            "flex h-[55px] min-w-0 flex-col gap-[2px]",
            i === 0 ? "pr-[20px]" : "px-[20px]",
            i < items.length - 1 && "border-r border-hair",
          )}
        >
          <div className={cn("whitespace-nowrap text-[28px] tracking-[-0.5px]", k.color)}>
            <CountUp value={k.value} />
          </div>
          <div className="whitespace-nowrap text-[13px] tracking-[0.1px] text-muted">{k.label}</div>
        </div>
      ))}
    </section>
  );
}
