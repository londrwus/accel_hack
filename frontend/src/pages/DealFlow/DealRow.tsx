import type { KeyboardEvent } from "react";
import { Link } from "react-router-dom";
import { AnimatePresence, motion } from "motion/react";
import { ArrowRight, Building2, Check, Network } from "lucide-react";
import { CompanyLogo } from "@/components/CompanyLogo";
import { DealStatusBadge } from "@/components/Badge";
import { SignalChip } from "@/components/SignalChip";
import { Button } from "@/components/Button";
import { cn } from "@/lib/utils";
import { isStrongFit, stageView } from "@/lib/format";
import type { DealFlowItem } from "@/lib/types";
import { FitCell, FitPartBar } from "./FitBar";

const EASE = [0.22, 1, 0.36, 1] as const;

/** Column widths from the design (row padding 12, gap 14). Signals takes the rest. */
export const COLS = {
  company: "w-[250px]",
  sector: "w-[90px]",
  stage: "w-[76px]",
  fit: "w-[96px]",
  signals: "min-w-0 flex-1",
  seen: "w-[50px]",
  status: "w-[100px]",
} as const;

export function DealHeadRow() {
  const h = "shrink-0 whitespace-nowrap text-[12px] tracking-[0.3px] text-subtle";
  return (
    <div className="box-border flex h-[36px] w-full shrink-0 items-start gap-[14px] border-y border-hair bg-row p-[10px_12px]">
      <span className={cn(h, COLS.company)}>Company</span>
      <span className={cn(h, COLS.sector)}>Sector</span>
      <span className={cn(h, COLS.stage)}>Stage</span>
      <span className={cn(h, COLS.fit)}>Fit</span>
      <span className={cn(h, COLS.signals)}>Signals</span>
      <span className={cn(h, COLS.seen)}>Seen</span>
      <span className={cn(h, COLS.status)}>Status</span>
    </div>
  );
}

interface DealRowProps {
  deal: DealFlowItem;
  index: number;
  selected: boolean;
  expanded: boolean;
  fundName: string;
  onToggle: () => void;
}

/** One ranked startup. Click to select it and open "why it fits". Passed rows are faded. */
export function DealRow({ deal, index, selected, expanded, fundName, onToggle }: DealRowProps) {
  const { company } = deal;
  const passed = deal.status === "passed";
  const delay = Math.min(index, 12) * 0.035;

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onToggle();
    }
  };

  return (
    <motion.div
      layout="position"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.45, delay, ease: EASE }}
      className={cn(
        "w-full shrink-0",
        selected ? "rounded-[10px] bg-shell" : "border-b border-hair",
      )}
    >
      <div
        role="button"
        tabIndex={0}
        aria-expanded={expanded}
        aria-label={`${company.name}, ${deal.fit}% fit. Show why it fits`}
        onClick={onToggle}
        onKeyDown={onKeyDown}
        className={cn(
          "box-border flex w-full cursor-pointer items-center gap-[14px] p-[12px] outline-none transition-colors focus-visible:ring-2 focus-visible:ring-sage",
          selected ? "h-[59px] rounded-[10px]" : "h-[58px] rounded-[10px] hover:bg-[#1A181705]",
          passed && "opacity-60",
        )}
      >
        <div className={cn("flex shrink-0 items-center gap-[10px]", COLS.company)}>
          <CompanyLogo name={company.name} logo={company.logo} size={32} radius={8} />
          <div className="flex min-w-0 flex-col gap-[1px]">
            <Link
              to={`/companies/${encodeURIComponent(company.id)}`}
              onClick={(e) => e.stopPropagation()}
              className="truncate text-[14px] font-medium text-ink hover:underline"
            >
              {company.name}
            </Link>
            <span className="truncate text-[12px] text-subtle">{company.one_liner}</span>
          </div>
        </div>
        <span className={cn("shrink-0 whitespace-nowrap text-[13px] text-muted", COLS.sector)}>{company.sector}</span>
        <StageCell company={company} />
        <FitCell fit={deal.fit} delay={delay} />
        <div className={cn("flex items-center gap-[6px] overflow-hidden", COLS.signals)}>
          {deal.signals.map((s) => (
            <SignalChip key={s.label} signal={s} to={`/companies/${encodeURIComponent(company.id)}`} />
          ))}
        </div>
        <span className={cn("shrink-0 whitespace-nowrap font-mono text-[13px] text-subtle", COLS.seen)}>
          {deal.seen_label}
        </span>
        <div className={cn("flex shrink-0 items-center", COLS.status)}>
          <DealStatusBadge status={deal.status} />
        </div>
      </div>

      <AnimatePresence initial={false}>
        {expanded && (
          <motion.div
            key="why"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.32, ease: EASE }}
            className="overflow-hidden"
          >
            <DealWhy deal={deal} fundName={fundName} />
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}

/** Stage, with a quiet "estimated" underneath when it was worked out from the latest round rather than reported. */
function StageCell({ company }: { company: DealFlowItem["company"] }) {
  const stage = stageView(company);
  return (
    <span className={cn("flex shrink-0 flex-col whitespace-nowrap text-[13px] text-muted", COLS.stage)}>
      {stage.label}
      {stage.estimated && (
        <span className="text-[11px] leading-[14px] tracking-[0.2px] text-subtle" title="Worked out from the latest funding round, not reported by the company">
          estimated
        </span>
      )}
    </span>
  );
}

/** The expanded part of a row: plain-English reasons, the fit breakdown, and next steps. */
function DealWhy({ deal, fundName }: { deal: DealFlowItem; fundName: string }) {
  const strong = isStrongFit(deal.fit);
  return (
    <div className="flex gap-[40px] p-[2px_12px_16px_54px]">
      <div className="flex min-w-0 flex-1 flex-col gap-[8px]">
        <span className="text-[12px] tracking-[0.3px] text-subtle">Why it fits {fundName}</span>
        <ul className="m-0 flex list-none flex-col gap-[6px] p-0">
          {deal.why.map((w, i) => (
            <motion.li
              key={w}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.35, delay: 0.08 + i * 0.06, ease: EASE }}
              className="flex items-start gap-[8px] text-[13px] text-ink"
            >
              <span className="mt-[2px] flex size-[16px] shrink-0 items-center justify-center rounded-full bg-accent-soft">
                <Check size={10} className="text-accent" aria-hidden />
              </span>
              {w}
            </motion.li>
          ))}
        </ul>
      </div>
      {deal.fit_parts.length > 0 && (
        <div className="flex shrink-0 flex-col gap-[8px]">
          <span className="text-[12px] tracking-[0.3px] text-subtle">What the score is made of</span>
          <div className="flex flex-col gap-[8px] pt-[2px]">
            {deal.fit_parts.map((p) => (
              <FitPartBar key={p.label} label={p.label} value={p.value} strong={strong} />
            ))}
          </div>
        </div>
      )}
      <div className="flex shrink-0 flex-col items-end justify-end gap-[8px]">
        {deal.memo_id && (
          <Button variant="gold" size="sm" iconRight={ArrowRight} to={`/memos/${deal.memo_id}`}>
            Read the memo
          </Button>
        )}
        <Button variant="white" size="sm" icon={Building2} to={`/companies/${encodeURIComponent(deal.company.id)}`}>
          Company page
        </Button>
        <Button variant="white" size="sm" icon={Network} to="/map">
          See on the map
        </Button>
      </div>
    </div>
  );
}
