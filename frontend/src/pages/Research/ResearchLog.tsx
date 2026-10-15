import { AnimatePresence, motion } from "motion/react";
import { Link } from "react-router-dom";
import { Asterisk } from "lucide-react";
import type { AgentEvent, PlanStep } from "@/lib/types";
import { formatElapsed } from "@/lib/format";
import { cn } from "@/lib/utils";
import { agentLabel, concernsOf, currentStep, displayTag, planProgress, tagTone, type TagTone } from "./feed";

const EASE = [0.22, 1, 0.36, 1] as const;

const TAG_CLASS: Record<TagTone, string> = {
  gold: "bg-gold text-ink",
  warning: "bg-warning-soft text-warning",
  danger: "bg-warning-soft text-danger",
  sage: "bg-accent-soft text-accent",
  grey: "bg-chip text-ink",
};

export interface ResearchLogProps {
  rows: AgentEvent[];
  liveSeqs: Set<number>;
  /** The latest working note (a tool call or step) when it isn't a log row itself. */
  now: AgentEvent | null;
  plan: PlanStep[] | null;
  animate: boolean;
  /** Shown when the Partner panel is closed. */
  onShowPartner?: () => void;
}

/** Left side of the Research page: "Research log" header, step counter, progress bar and the live feed. */
export function ResearchLog({ rows, liveSeqs, now, plan, animate, onShowPartner }: ResearchLogProps) {
  const step = plan ? currentStep(plan) : 0;
  const progress = plan ? planProgress(plan) : 0;
  return (
    <section className="flex h-full min-w-0 flex-1 flex-col overflow-hidden bg-panel">
      <div className="flex shrink-0 flex-col gap-[14px] p-[18px_24px_0_24px]">
        <div className="flex items-end justify-between">
          <h2 className="m-0 whitespace-nowrap text-[18px] font-normal tracking-[-0.3px] text-ink">Research log</h2>
          <div className="flex items-center gap-[8px]">
            {onShowPartner && (
              <button
                type="button"
                onClick={onShowPartner}
                className="mr-[4px] inline-flex items-center gap-[6px] text-[13px] tracking-[0.1px] text-muted hover:text-ink"
              >
                <Asterisk size={14} />
                Show Partner
              </button>
            )}
            <span className="whitespace-nowrap text-[14px] tracking-[0.2px] text-subtle">Step:</span>
            <span className="whitespace-nowrap rounded-full bg-chip p-[4px_10px] text-[14px] tracking-[0.2px] text-ink tabular-nums">
              {plan ? `${step} of ${plan.length}` : "Planning"}
            </span>
          </div>
        </div>
        <div className="h-[3px] w-full bg-[#1A18170F]">
          <motion.div
            className="h-full bg-accent"
            initial={false}
            animate={{ width: `${progress * 100}%` }}
            transition={{ duration: animate ? 0.8 : 0, ease: EASE }}
          />
        </div>
      </div>

      <ol className="m-0 flex min-h-0 flex-1 list-none flex-col overflow-y-auto p-[9px_12px_8px]" aria-live="polite">
        <AnimatePresence initial={false}>
          {now && (
            <motion.li
              key={`now-${now.seq}`}
              layout="position"
              initial={animate ? { opacity: 0, y: -8 } : false}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, transition: { duration: 0.15 } }}
              transition={{ duration: 0.45, ease: EASE }}
              className="-mb-px flex shrink-0 items-start gap-[16px] rounded-[12px] border-b border-[#1A18170F] bg-surface p-[14px_12px]"
            >
              <span className="w-[36px] shrink-0 font-mono text-[12px] tracking-[0.2px] text-subtle">{formatElapsed(now.elapsed_s)}</span>
              <span className={cn("w-[100px] shrink-0 text-[15px] tracking-[0.2px] text-predicted", animate && "research-shimmer")}>
                {agentLabel(now)}
              </span>
              <span className="flex-1 text-[15px]/[23px] tracking-[0.2px] text-muted">
                {now.message.replace(/\.$/, "")}
                <span className="research-dots" aria-hidden>
                  …
                </span>
              </span>
            </motion.li>
          )}
          {rows.map((e) => (
            <LogRow key={e.seq} event={e} live={liveSeqs.has(e.seq) && animate} />
          ))}
        </AnimatePresence>
        {rows.length === 0 && !now && (
          <li className="p-[14px_12px] text-[15px] tracking-[0.2px] text-subtle">The analyst team is getting ready…</li>
        )}
      </ol>
    </section>
  );
}

function LogRow({ event: e, live }: { event: AgentEvent; live: boolean }) {
  const highlight = e.tag === "New match";
  const tag = displayTag(e);
  const concerns = concernsOf(e);
  return (
    <motion.li
      layout="position"
      initial={live ? { opacity: 0, y: -8 } : false}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, height: 0, paddingTop: 0, paddingBottom: 0, transition: { duration: 0.3, ease: EASE } }}
      transition={{ duration: 0.5, ease: EASE }}
      className="-mb-px flex shrink-0 items-start gap-[16px] overflow-hidden rounded-[12px] border-b border-[#1A18170F] p-[14px_12px]"
    >
      <span className="w-[36px] shrink-0 font-mono text-[12px] tracking-[0.2px] text-subtle">{formatElapsed(e.elapsed_s)}</span>
      <span className={cn("w-[100px] shrink-0 text-[15px] tracking-[0.2px]", highlight ? "text-predicted" : "text-subtle")}>
        {agentLabel(e)}
      </span>
      <span className={cn("flex-1 text-[15px]/[23px] tracking-[0.2px] text-ink", highlight && "font-medium")}>
        {e.message}
        {typeof e.data?.company_id === "string" && e.data.company_id && (
          <Link
            to={`/companies/${encodeURIComponent(e.data.company_id)}`}
            className="ml-[8px] whitespace-nowrap text-[13px] font-normal text-accent hover:underline"
          >
            View company →
          </Link>
        )}
        {concerns.length > 0 && (
          <ul className="m-0 mt-[6px] flex list-none flex-col gap-[4px] p-0">
            {concerns.map((c) => (
              <li key={c} className="flex items-start gap-[8px] text-[14px]/[21px] text-muted">
                <span aria-hidden className="mt-[9px] size-[4px] shrink-0 rounded-full bg-warning" />
                {c}
              </li>
            ))}
          </ul>
        )}
      </span>
      {tag && (
        <motion.span
          initial={live ? { scale: 0.8, opacity: 0 } : false}
          animate={{ scale: 1, opacity: 1 }}
          transition={{ delay: live ? 0.25 : 0, duration: 0.3, ease: EASE }}
          className={cn("shrink-0 whitespace-nowrap rounded-full p-[3px_10px] text-[12px] tracking-[0.2px]", TAG_CLASS[tagTone(tag)])}
          title={tag === "Ignored" ? "This page had text aimed at an AI. It was treated as information only." : undefined}
        >
          {tag}
        </motion.span>
      )}
    </motion.li>
  );
}
