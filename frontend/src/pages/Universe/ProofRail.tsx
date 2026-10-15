import { useEffect, useRef, useState, type ReactNode } from "react";
import { AnimatePresence, motion } from "motion/react";
import { ArrowRight, Check, ChevronDown, History } from "lucide-react";
import { cn } from "@/lib/utils";
import { formatShare } from "@/lib/format";
import type { Backtest } from "@/lib/types";
import { EASE } from "./motion";

function Heading({ children }: { children: ReactNode }) {
  return <h2 className="m-0 text-[17px] font-normal tracking-[-0.2px] text-ink">{children}</h2>;
}

function Rule() {
  return <div className="h-px w-full shrink-0 bg-hair" />;
}

/** One method bar: "Bellwether model · 16 of 20" over a 10px track. The first (our model) is gold. */
function MethodBar({ label, found, total, ours, index }: { label: string; found: number; total: number; ours: boolean; index: number }) {
  const share = total > 0 ? Math.min(1, found / total) : 0;
  return (
    <div className="flex w-full flex-col gap-[5px]">
      <div className="flex w-full justify-between text-[13px] tracking-[0.1px]">
        <span className={ours ? "text-ink" : "text-muted"}>{label}</span>
        <span className={cn("font-medium", ours ? "text-predicted" : "text-competitor")}>
          {found} of {total}
        </span>
      </div>
      <div className="h-[10px] w-full rounded-[3px] bg-track" role="img" aria-label={`${label}: found ${found} of ${total}`}>
        <motion.div
          className={cn("h-full origin-left rounded-[3px]", ours ? "bg-predicted" : "bg-competitor")}
          style={{ width: `${share * 100}%` }}
          initial={{ scaleX: 0 }}
          animate={{ scaleX: 1 }}
          transition={{ duration: 0.9, delay: 0.25 + index * 0.12, ease: EASE }}
        />
      </div>
    </div>
  );
}

export interface FundChoice {
  id: string;
  name: string;
}

/** Small text menu next to the backtest heading: which fund's past deals the test was run on. */
function FundPicker({ funds, value, onPick }: { funds: FundChoice[]; value: string | null; onPick: (id: string) => void }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);
  const current = funds.find((f) => f.id === value);
  if (funds.length < 2) return null;
  return (
    <div ref={ref} className="relative shrink-0">
      <button
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={`Backtest for ${current?.name ?? "this fund"}. Pick another fund`}
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-[4px] whitespace-nowrap rounded-[8px] p-[3px_6px] text-[13px] tracking-[0.1px] text-muted transition-colors hover:bg-track hover:text-ink"
      >
        {current?.name ?? "Pick a fund"}
        <ChevronDown size={13} className={cn("transition-transform duration-200", open && "rotate-180")} aria-hidden />
      </button>
      <AnimatePresence>
        {open && (
          <motion.ul
            role="listbox"
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.16, ease: EASE }}
            className="absolute right-0 top-[calc(100%+6px)] z-30 m-0 flex min-w-[200px] list-none flex-col gap-[2px] rounded-[12px] bg-panel p-[4px] shadow-[0_8px_24px_#1A18171F] hairline"
          >
            {funds.map((f) => (
              <li key={f.id}>
                <button
                  type="button"
                  role="option"
                  aria-selected={f.id === value}
                  onClick={() => {
                    onPick(f.id);
                    setOpen(false);
                  }}
                  className={cn(
                    "flex w-full items-center justify-between gap-[12px] whitespace-nowrap rounded-[8px] p-[7px_10px] text-left text-[13px] transition-colors hover:bg-track",
                    f.id === value ? "text-ink" : "text-muted",
                  )}
                >
                  {f.name}
                  {f.id === value && <Check size={14} className="text-accent" aria-hidden />}
                </button>
              </li>
            ))}
          </motion.ul>
        )}
      </AnimatePresence>
    </div>
  );
}

interface BacktestSectionProps {
  backtest: Backtest | null;
  fundName: string;
  missing: boolean;
  failed: Error | null;
  funds: FundChoice[];
  fundId: string | null;
  onPickFund: (id: string) => void;
  withResults: FundChoice[];
}

function BacktestSection({ backtest, fundName, missing, failed, funds, fundId, onPickFund, withResults }: BacktestSectionProps) {
  const ok = backtest && backtest.enough_history && backtest.methods.length > 0;
  return (
    <section className="flex w-full shrink-0 flex-col gap-[10px]">
      <div className="flex w-full items-center justify-between gap-[12px]">
        <Heading>Does it work? The backtest</Heading>
        <FundPicker funds={funds} value={fundId} onPick={onPickFund} />
      </div>
      {ok ? (
        <>
          <p className="m-0 w-full text-[13px] leading-[19px] tracking-[0.1px] text-muted">
            We hid {fundName}’s last {backtest.held_out} deals, trained on everything before them, and asked each method to find them in its
            top {backtest.top_percent}%.
          </p>
          {backtest.methods.map((m, i) => (
            <MethodBar key={m.label} label={m.label} found={m.found} total={m.total} ours={i === 0} index={i} />
          ))}
        </>
      ) : backtest || missing ? (
        <div className="flex w-full items-start gap-[10px] rounded-[12px] bg-surface p-[12px_14px] hairline">
          <History size={16} className="mt-[1px] shrink-0 text-muted" aria-hidden />
          <div className="flex min-w-0 flex-col gap-[3px]">
            <span className="text-[13px] font-medium tracking-[0.1px] text-ink">
              {backtest ? "Not enough history for this fund" : "No backtest yet for this fund"}
            </span>
            <span className="text-[13px] leading-[19px] tracking-[0.1px] text-muted">
              {backtest
                ? `Our dataset has too few of ${fundName}’s past deals with a date for a fair test. We only show results from a real backtest, never estimates.`
                : `The test for ${fundName} hasn’t finished yet. We only show results from a real backtest, never estimates.`}
            </span>
            {withResults.length > 0 && (
              <div className="flex flex-col items-start gap-[4px] pt-[6px]">
                <span className="text-[12px] tracking-[0.1px] text-subtle">See a fund with results:</span>
                {withResults.map((f) => (
                  <button
                    key={f.id}
                    type="button"
                    onClick={() => onPickFund(f.id)}
                    className="inline-flex items-center gap-[6px] text-[13px] font-medium tracking-[0.1px] text-accent hover:underline"
                  >
                    {f.name}
                    <ArrowRight size={13} aria-hidden />
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      ) : failed ? (
        <p className="m-0 text-[13px] leading-[19px] tracking-[0.1px] text-muted">Couldn’t load the backtest. {failed.message}</p>
      ) : (
        <div className="flex flex-col gap-[10px]" aria-hidden>
          <div className="h-[38px] w-full animate-pulse rounded-[6px] bg-track" />
          <div className="h-[30px] w-full animate-pulse rounded-[6px] bg-track" />
          <div className="h-[30px] w-full animate-pulse rounded-[6px] bg-track" />
        </div>
      )}
    </section>
  );
}

/** Feature weights: segmented bar (2px gaps, a little empty track at the end like the design) + legend. */
function WeightsSection({ backtest }: { backtest: Backtest }) {
  const weights = backtest.feature_weights;
  const gaps = Math.max(0, weights.length - 1) * 2;
  return (
    <section className="flex w-full shrink-0 flex-col gap-[10px]">
      <Heading>What the score depends on</Heading>
      <div className="flex h-[10px] w-full gap-[2px] overflow-hidden rounded-[3px]">
        {weights.map((w, i) => (
          <motion.div
            key={w.label}
            title={`${w.label}: ${formatShare(w.share)}`}
            className="h-full shrink-0 origin-left"
            style={{ width: `calc((100% - ${gaps + 10}px) * ${w.share})`, background: w.color }}
            initial={{ scaleX: 0, opacity: 0 }}
            animate={{ scaleX: 1, opacity: 1 }}
            transition={{ duration: 0.6, delay: 0.45 + i * 0.08, ease: EASE }}
          />
        ))}
      </div>
      {weights.map((w) => (
        <div key={w.label} className="flex w-full items-center gap-[10px] text-[13px] tracking-[0.1px]">
          <span className="size-[7px] shrink-0 rounded-[2px]" style={{ background: w.color }} />
          <span className="flex-1 text-ink">{w.label}</span>
          <span className="font-medium text-ink">{formatShare(w.share)}</span>
        </div>
      ))}
    </section>
  );
}

function CardRow({ k, children, gap = 10 }: { k: string; children: ReactNode; gap?: number }) {
  return (
    <div className="flex items-start" style={{ gap }}>
      <span className="w-[80px] shrink-0 pt-[3px] text-[13px] tracking-[0.1px] text-subtle">{k}</span>
      <div className="flex min-w-0 flex-1 flex-wrap" style={{ gap: 6 }}>
        {children}
      </div>
    </div>
  );
}

function Pill({ small, children }: { small?: boolean; children: ReactNode }) {
  return (
    <span
      title={typeof children === "string" ? children : undefined}
      className={cn(
        "inline-block w-fit min-w-0 max-w-full truncate whitespace-nowrap rounded-full bg-chip tracking-[0.1px]",
        small ? "p-[3px_9px] text-[12px] text-muted" : "p-[3px_10px] text-[13px] text-ink",
      )}
    >
      {children}
    </span>
  );
}

function ModelCardSection({ backtest }: { backtest: Backtest }) {
  const m = backtest.model_card;
  return (
    <section className="flex w-full shrink-0 flex-col gap-[10px]">
      <Heading>Model card</Heading>
      <CardRow k="Trained on:">
        <Pill>{m.trained_on}</Pill>
      </CardRow>
      <CardRow k="Data:">
        <Pill>{m.data}</Pill>
      </CardRow>
      <CardRow k="Method:">
        <Pill>{m.method}</Pill>
      </CardRow>
      <CardRow k="Retrains:">
        <Pill>{m.retrains}</Pill>
      </CardRow>
      <CardRow k="Never used:" gap={6}>
        {m.never_used.map((f) => (
          <span key={f} title={`The model never sees ${f.toLowerCase()}`}>
            <Pill small>{f}</Pill>
          </span>
        ))}
      </CardRow>
    </section>
  );
}

/** Right rail (no boxes): backtest bars · feature weights · model card. */
export function ProofRail({
  backtest,
  fundName,
  missing,
  error,
  funds,
  fundId,
  onPickFund,
  withResults,
}: {
  backtest: Backtest | null;
  /** The fund the backtest is about (the picked one). */
  fundName: string;
  /** No backtest file for this fund (404). */
  missing: boolean;
  error: Error | null;
  /** Funds the picker offers; the first is the current fund. */
  funds: FundChoice[];
  fundId: string | null;
  onPickFund: (id: string) => void;
  /** Other funds with real backtest results, offered when this one has too little history. */
  withResults: FundChoice[];
}) {
  return (
    <aside
      aria-label="Proof that the model works"
      className="flex w-[400px] shrink-0 flex-col gap-[22px] overflow-auto border-l border-hair p-[20px_24px]"
    >
      <BacktestSection
        backtest={backtest}
        fundName={fundName}
        missing={missing}
        failed={error}
        funds={funds}
        fundId={fundId}
        onPickFund={onPickFund}
        withResults={withResults}
      />
      {backtest && (
        <>
          {backtest.enough_history && backtest.feature_weights.length > 0 && (
            <>
              <Rule />
              <WeightsSection backtest={backtest} />
            </>
          )}
          <Rule />
          <ModelCardSection backtest={backtest} />
        </>
      )}
    </aside>
  );
}
