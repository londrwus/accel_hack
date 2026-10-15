import { useState } from "react";
import { motion, useReducedMotion } from "motion/react";
import { useNavigate } from "react-router-dom";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/Badge";
import { CompanyLogo } from "@/components/CompanyLogo";
import { SignalChip } from "@/components/SignalChip";
import type { Health, PortfolioColumn, PortfolioItem } from "@/lib/types";

const EASE = [0.22, 1, 0.36, 1] as const;

/** Column colours from the design (ids stay good|watch|at_risk|exited). */
const COLUMN_TONE: Record<Health, { dot: string; count: string; faded?: boolean }> = {
  at_risk: { dot: "bg-danger", count: "bg-warning-soft text-danger" },
  watch: { dot: "bg-predicted", count: "bg-predicted-soft text-predicted" },
  good: { dot: "bg-accent", count: "bg-accent-soft text-accent" },
  exited: { dot: "bg-muted", count: "bg-chip text-muted", faded: true },
  unknown: { dot: "bg-muted", count: "bg-chip text-muted" },
};

/** "+ N more" only when it hides at least two companies (a lone "+ 1 more" isn't shown in the design). */
const MIN_MORE = 2;

function Tile({ item, delay }: { item: PortfolioItem; delay: number }) {
  const c = item.company;
  const reduce = useReducedMotion();
  const navigate = useNavigate();
  const to = `/companies/${encodeURIComponent(c.id)}`;
  return (
    <motion.article
      role="link"
      tabIndex={0}
      aria-label={`${c.name}: open the company page`}
      onClick={() => navigate(to)}
      onKeyDown={(e) => e.key === "Enter" && navigate(to)}
      initial={reduce ? false : { opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, ease: EASE, delay }}
      className="hairline flex w-full shrink-0 cursor-pointer flex-col gap-[10px] rounded-[14px] bg-panel p-[14px] shadow-[0_1px_2px_#1A18170A] outline-none transition-shadow hover:shadow-[0_2px_8px_#1A181714] focus-visible:ring-2 focus-visible:ring-sage"
    >
      <div className="flex w-full items-center gap-[10px]">
        <CompanyLogo name={c.name} logo={c.logo} size={30} radius={8} tone="sage" />
        <div className="flex min-w-0 flex-1 flex-col gap-[1px]">
          <div className="truncate text-[14px] font-medium tracking-[0.1px] text-ink">{c.name}</div>
          {c.one_liner && <div className="truncate text-[12px] tracking-[0.1px] text-subtle">{c.one_liner}</div>}
        </div>
        {c.stage && (
          <Badge tone="grey" size="xs">
            {c.stage}
          </Badge>
        )}
      </div>
      {item.signals.map((s) => (
        <SignalChip key={s.label} signal={s} variant="row" to={to} />
      ))}
      {item.updated_label && (
        <div className="whitespace-nowrap text-[11px] tracking-[0.1px] text-subtle">{item.updated_label}</div>
      )}
    </motion.article>
  );
}

function Column({ column, index }: { column: PortfolioColumn; index: number }) {
  const tone = COLUMN_TONE[column.health];
  const base = 0.15 + index * 0.06;
  const reduce = useReducedMotion();
  const [open, setOpen] = useState(false);
  const rest = column.rest ?? [];
  const canOpen = rest.length > 0;
  return (
    <section
      aria-label={column.title}
      className={cn("flex min-w-0 flex-1 basis-0 flex-col gap-[10px]", tone.faded && "opacity-70")}
    >
      <header className="flex w-full flex-col gap-[3px] p-[0px_4px_6px_4px]">
        <div className="flex w-full items-center gap-[8px]">
          <span className={cn("size-[8px] shrink-0 rounded-full", tone.dot)} aria-hidden />
          <h2 className="m-0 whitespace-nowrap text-[15px] font-medium tracking-[0.1px] text-ink">{column.title}</h2>
          <span className={cn("rounded-full p-[1px_8px] text-[12px] tracking-[0.1px]", tone.count)}>
            {column.count}
          </span>
        </div>
        <p className="m-0 w-full text-[12px] leading-[17px] tracking-[0.1px] text-subtle">{column.blurb}</p>
      </header>
      {column.items.map((item, i) => (
        <Tile key={item.company.id} item={item} delay={base + i * 0.07} />
      ))}
      {open && (
        <div className="flex max-h-[60vh] w-full flex-col gap-[10px] overflow-y-auto pr-[2px]">
          {rest.map((item) => (
            <Tile key={item.company.id} item={item} delay={0} />
          ))}
        </div>
      )}
      {(canOpen || column.more >= MIN_MORE) && (
        <motion.div
          initial={reduce ? false : { opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.4, delay: base + column.items.length * 0.07 }}
          className="flex w-full justify-center p-[8px_0px]"
        >
          {canOpen ? (
            <button
              type="button"
              onClick={() => setOpen((o) => !o)}
              aria-expanded={open}
              className="cursor-pointer whitespace-nowrap rounded-full p-[4px_10px] text-[13px] tracking-[0.1px] text-muted transition-colors hover:bg-chip hover:text-ink focus-visible:ring-2 focus-visible:ring-sage outline-none"
            >
              {open ? "Show less" : `+ ${rest.length} more`}
            </button>
          ) : (
            <span className="whitespace-nowrap text-[13px] tracking-[0.1px] text-muted">+ {column.more} more</span>
          )}
        </motion.div>
      )}
    </section>
  );
}

/** The health board: four columns grouped by what the partner should do. */
export function Board({ columns }: { columns: PortfolioColumn[] }) {
  return (
    <div className="-mt-px flex min-h-0 flex-1 items-start gap-[16px] overflow-auto bg-[#1A181703] p-[20px_24px_24px_24px]">
      {columns.map((col, i) => (
        <Column key={col.health} column={col} index={i} />
      ))}
    </div>
  );
}
