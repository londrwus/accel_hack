import { useEffect, useRef, useState, type FormEvent } from "react";
import { AnimatePresence, motion } from "motion/react";
import { ArrowUp, Asterisk, ChevronDown, Circle, CircleCheck, LoaderCircle, SlidersHorizontal, Sunrise, X } from "lucide-react";
import type { PlanStep, SectorShare } from "@/lib/types";
import { DataCard } from "@/components/DataCard";
import { Button } from "@/components/Button";
import { cn } from "@/lib/utils";
import { QuestionBlock, type AskChat } from "./AskChat";

const EASE = [0.22, 1, 0.36, 1] as const;

export interface PartnerPanelProps {
  task: string;
  plan: PlanStep[] | null;
  answer: string | null;
  /** Extra line once the run is over (the Partner's final message). */
  closing: string | null;
  fundName: string;
  sectors: SectorShare[] | null;
  sinceLastRun: string | null;
  animate: boolean;
  verbose: boolean;
  onToggleVerbose: () => void;
  onClose: () => void;
  /** "Ask the team" chat (questions answered by the routed agents). */
  chat: AskChat;
  suggestions: string[];
}

/** Right panel: the Partner (orchestrator) with the request, its plan, a plain answer and the fund's sector mix. */
export function PartnerPanel(p: PartnerPanelProps) {
  const [planOpen, setPlanOpen] = useState(true);
  const [draft, setDraft] = useState("");
  const bottom = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const answered = p.chat.items.filter((q) => q.status !== "working").length;
  useEffect(() => {
    const box = bottom.current?.parentElement;
    if (!p.chat.items.length || !box) return;
    const go = () => box.scrollTo({ top: box.scrollHeight });
    go();
    const ts = [150, 700, 1500].map((ms) => setTimeout(go, ms)); // after layout and the answer's fade-in
    return () => ts.forEach(clearTimeout);
  }, [p.chat.items.length, answered]);
  const [saved, setSaved] = useState(false);

  const submit = (ev: FormEvent) => {
    ev.preventDefault();
    const q = draft.trim();
    if (!q || p.chat.busy) return;
    void p.chat.ask(q);
    setDraft("");
  };

  return (
    <aside className="-ml-px flex h-full min-h-0 w-[401px] shrink-0 flex-col overflow-hidden border-l border-hair">
      <div className="-mb-px flex h-[49px] shrink-0 items-center gap-[10px] border-b border-hair px-[18px] pt-px">
        <Asterisk size={18} className="text-ink" />
        <span className="flex-1 text-[16px] tracking-[0.1px] text-ink">Ask the team</span>
        <button
          type="button"
          onClick={p.onToggleVerbose}
          aria-pressed={p.verbose}
          title={p.verbose ? "Show only the main updates in the log" : "Show every step in the log"}
          className={cn("flex text-muted hover:text-ink", p.verbose && "text-predicted")}
        >
          <SlidersHorizontal size={16} />
        </button>
        <button type="button" onClick={p.onClose} title="Close" aria-label="Close the Partner panel" className="flex text-muted hover:text-ink">
          <X size={16} />
        </button>
      </div>

      <div className="flex min-h-0 flex-1 flex-col gap-[12px] overflow-y-auto p-[15px_18px_6px_18px] [&>*]:shrink-0">
        <Bubble>{p.task}</Bubble>

        <button
          type="button"
          onClick={() => setPlanOpen((o) => !o)}
          aria-expanded={planOpen}
          className="flex w-fit items-center gap-[4px] text-[13px] tracking-[0.1px] text-muted hover:text-ink"
        >
          {p.plan ? `Thought process · ${p.plan.length} steps` : "Thought process · planning"}
          <ChevronDown size={14} className={cn("transition-transform duration-200", !planOpen && "-rotate-90")} />
        </button>

        <AnimatePresence initial={false}>
          {planOpen && p.plan && (
            <motion.ol
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.3, ease: EASE }}
              className="m-0 -ml-px flex shrink-0 list-none flex-col gap-[5px] overflow-hidden border-l-2 border-hair pl-[12px]"
            >
              {p.plan.map((s) => (
                <PlanRow key={s.label} step={s} animate={p.animate} />
              ))}
            </motion.ol>
          )}
        </AnimatePresence>

        {p.answer && (
          <motion.p
            key={p.answer}
            initial={p.animate ? { opacity: 0, y: 6 } : false}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, ease: EASE }}
            className="m-0 text-[14px]/[22px] tracking-[0.1px] text-ink"
          >
            {p.answer}
          </motion.p>
        )}

        {p.closing && (
          <motion.p
            initial={p.animate ? { opacity: 0, y: 6 } : false}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, ease: EASE }}
            className="m-0 text-[14px]/[22px] tracking-[0.1px] text-ink"
          >
            {p.closing}
          </motion.p>
        )}

        {p.sectors && p.sectors.length > 0 && (
          <motion.div
            initial={p.animate ? { opacity: 0, y: 12 } : false}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, ease: EASE }}
            className="-mt-px shrink-0"
          >
            <DataCard
              title={`What ${p.fundName} invests in`}
              segments={p.sectors.map((s) => ({ label: s.name, share: s.share, color: s.color, value: s.count }))}
              footer={saved ? "Saved to the fund profile" : "Save to the fund profile"}
              onAction={() => setSaved(true)}
            />
          </motion.div>
        )}

        {p.sinceLastRun && (
          <div className="flex shrink-0 items-center gap-[10px] rounded-[12px] bg-predicted-soft p-[10px_12px]">
            <Sunrise size={15} className="shrink-0 text-predicted" />
            <span className="text-[13px] tracking-[0.1px] text-ink">{p.sinceLastRun}</span>
          </div>
        )}


        {p.chat.items.map((q) => (
          <QuestionBlock key={q.id} q={q} events={p.chat.live[q.id] ?? []} animate={p.animate} />
        ))}
        {p.chat.error && <p className="m-0 text-[13px] tracking-[0.1px] text-warning">{p.chat.error}</p>}
        <div ref={bottom} />
      </div>

      {!p.chat.busy && p.chat.items.length < 3 && (
        <div className="flex shrink-0 flex-wrap gap-[6px] px-[14px] pt-[8px]">
          {p.suggestions.map((sug) => (
            <button
              key={sug}
              type="button"
              onClick={() => {
                setDraft(sug); // fills the input; the question is sent only on Enter / Send
                inputRef.current?.focus();
              }}
              className="rounded-full bg-chip p-[4px_10px] text-left text-[12px] tracking-[0.1px] text-muted transition-colors hover:text-ink"
            >
              {sug}
            </button>
          ))}
        </div>
      )}
      <form onSubmit={submit} className="shrink-0 p-[14px]">
        <div className="flex items-center rounded-[14px] bg-panel p-[10px_8px_10px_14px] shadow-card hairline focus-within:outline-sage">
          <input
            ref={inputRef}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder={p.chat.busy ? "The team is working on it…" : "Ask the team anything…"}
            aria-label="Ask the team anything"
            className="min-w-0 flex-1 bg-transparent text-[14px] tracking-[0.1px] text-ink outline-none placeholder:text-subtle"
          />
          <Button type="submit" variant="gold" size="icon" icon={ArrowUp} aria-label="Send" />
        </div>
      </form>
    </aside>
  );
}

function Bubble({ children }: { children: string }) {
  return (
    <div className="flex shrink-0 justify-end">
      <div className="max-w-[248px] rounded-[14px] bg-shell p-[9px_14px] text-[14px]/[20px] tracking-[0.1px] text-ink hairline">
        {children}
      </div>
    </div>
  );
}

function PlanRow({ step, animate }: { step: PlanStep; animate: boolean }) {
  const icon =
    step.status === "done" ? (
      <CircleCheck size={14} className="text-accent" />
    ) : step.status === "working" ? (
      <LoaderCircle size={14} className={cn("text-predicted", animate && "animate-[spin_2.4s_linear_infinite]")} />
    ) : (
      <Circle size={14} className="text-[#1A181733]" />
    );
  return (
    <li className="flex items-center gap-[8px]">
      <motion.span
        key={step.status}
        initial={animate ? { scale: 0.5, opacity: 0 } : false}
        animate={{ scale: 1, opacity: 1 }}
        transition={{ duration: 0.35, ease: EASE }}
        className="flex"
      >
        {icon}
      </motion.span>
      <span className={cn("whitespace-nowrap text-[13px] tracking-[0.1px] transition-colors duration-500", step.status === "waiting" ? "text-subtle" : "text-ink")}>
        {step.label}
      </span>
    </li>
  );
}
