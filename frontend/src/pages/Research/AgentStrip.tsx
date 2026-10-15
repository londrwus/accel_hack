import { motion } from "motion/react";
import { Check, TriangleAlert } from "lucide-react";
import type { AgentName, AgentState } from "@/lib/types";
import { cn } from "@/lib/utils";
import { AGENTS } from "./feed";


const STATE_LABEL: Record<AgentState, string> = {
  waiting: "waiting",
  working: "working",
  done: "done",
  error: "stopped",
};

/** "Analyst team" row: one chip per agent. Working = white chip + gold dot, done = ✓, waiting = faded. */
export function AgentStrip({ team, animate, workers = {} }: {
  team: Record<AgentName, AgentState>;
  animate: boolean;
  workers?: Partial<Record<AgentName, number>>;
}) {
  return (
    <div className="-mb-px flex h-[58px] shrink-0 items-center gap-[8px] overflow-x-auto border-b border-hair px-[24px]">
      <span className="whitespace-nowrap text-[13px] tracking-[0.1px] text-subtle">Analyst team</span>
      {AGENTS.map((name) => (
        <AgentChip key={name} name={name} state={team[name]} animate={animate} workers={workers[name] ?? 0} />
      ))}
    </div>
  );
}

function AgentChip({ name, state, animate, workers }: { name: AgentName; state: AgentState; animate: boolean; workers: number }) {
  const working = state === "working";
  return (
    <motion.div
      layout
      title={`${name}${workers > 1 ? ` (${workers} workers in parallel)` : ""}: ${STATE_LABEL[state]}`}
      className={cn(
        "flex shrink-0 items-center gap-[7px] rounded-full p-[5px_10px_5px_6px] transition-[background-color,opacity,box-shadow] duration-500",
        working ? "bg-panel shadow-nav hairline" : "bg-track",
        state === "waiting" && "opacity-55",
      )}
    >
      <span
        className={cn(
          "flex size-[20px] items-center justify-center rounded-[10px] text-[11px] transition-colors duration-500",
          working ? "bg-predicted-soft text-predicted" : state === "error" ? "bg-warning-soft text-warning" : "bg-accent-soft text-accent",
        )}
      >
        {name[0]}
      </span>
      <span className={cn("whitespace-nowrap text-[13px] tracking-[0.1px] text-ink", working && animate && "research-shimmer")}>
        {name}
      </span>
      {workers > 1 && (
        <span className="rounded-full bg-chip p-[0px_6px] text-[11px] tracking-[0.1px] text-muted" aria-label={`${workers} workers`}>
          ×{workers}
        </span>
      )}
      {working && (
        <motion.span
          className="size-[6px] rounded-full bg-gold"
          animate={animate ? { opacity: [1, 0.35, 1] } : undefined}
          transition={animate ? { duration: 2, repeat: Infinity, ease: "easeInOut" } : undefined}
        />
      )}
      {state === "done" && (
        <motion.span initial={animate ? { scale: 0.4, opacity: 0 } : false} animate={{ scale: 1, opacity: 1 }} className="flex">
          <Check size={13} className="text-accent" aria-label="done" />
        </motion.span>
      )}
      {state === "error" && <TriangleAlert size={13} className="text-warning" aria-label="stopped" />}
    </motion.div>
  );
}
