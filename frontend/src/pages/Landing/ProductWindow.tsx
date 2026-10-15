import { useEffect, useRef, useState } from "react";
import { motion, useInView, useReducedMotion } from "motion/react";
import type { FundDNA } from "@/lib/types";
import { cn } from "@/lib/utils";
import { EASE } from "./motion";
import { Pill } from "./Pill";

interface Line {
  agent: string;
  text: string;
  highlight?: boolean;
}

/** One finished run, in plain English (the story told on the landing page). */
const LINES: Line[] = [
  { agent: "Partner", text: "Made a 7-step plan. Starting with accel.com." },
  { agent: "Reader", text: "Found 782 portfolio companies (Accel lists 780). Handing them to Thesis." },
  { agent: "Thesis", text: "Accel backs AI, cloud/SaaS, security, consumer and fintech, early and late stage, worldwide." },
  { agent: "Enricher", text: "8 workers are filling in company profiles in parallel." },
  {
    agent: "Deal Finder",
    text: "Scored 10,000 startups in 0.02 s. Strong match: Monday.com, 89% fit.",
    highlight: true,
  },
  { agent: "Mapper", text: "Market map ready: Celonis, Lovable, Scale and their closest rivals." },
  { agent: "Critic", text: "Checked the memo: 12 of 12 claims have a source." },
  { agent: "Partner", text: "Done in 1 min 56 s for about $0.20. I'll check again tomorrow at 7am." },
];

const DEAL_FINDER_INDEX = LINES.findIndex((l) => l.highlight);

const DEFAULT_DNA: Pick<FundDNA, "summary" | "stage" | "geo" | "cheque"> = {
  summary: "Backs AI, cloud/SaaS, security, consumer and fintech companies, early and late stage.",
  stage: "Seed to late stage",
  geo: "Americas, Europe, India",
  cheque: "Not stated",
};

const PICK_TEXT =
  "Work management platform for teams. Looks like Accel's SaaS portfolio. 12 sourced claims in the memo.";

const LINE_INTERVAL_MS = 520;
const TYPE_MS_PER_CHAR = 14;

function Chip({ children }: { children: string }) {
  return (
    <span className="rounded-full bg-chip p-[4px_10px] text-[14px] tracking-[0.2px] whitespace-nowrap text-ink">{children}</span>
  );
}

function KeyChip({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex items-center gap-[10px]">
      <span className="text-[14px] tracking-[0.2px] whitespace-nowrap text-subtle">{k}</span>
      <Chip>{v}</Chip>
    </div>
  );
}

/** Agent name with a soft shimmer while that agent is working. */
function AgentName({ line, working }: { line: Line; working: boolean }) {
  const color = line.highlight ? "#B8892E" : "#9A958B";
  if (!working) return <span style={{ color }}>{line.agent}</span>;
  return (
    <motion.span
      style={{
        backgroundImage: `linear-gradient(90deg, ${color} 0%, ${color} 35%, #E6D7B8 50%, ${color} 65%, ${color} 100%)`,
        backgroundSize: "250% 100%",
        WebkitBackgroundClip: "text",
        backgroundClip: "text",
        color: "transparent",
      }}
      initial={{ backgroundPosition: "100% 0" }}
      animate={{ backgroundPosition: "0% 0" }}
      transition={{ duration: 1.2, ease: "linear", repeat: Infinity }}
    >
      {line.agent}
    </motion.span>
  );
}

/**
 * The big product window on the painted band: a finished run replayed line by line (agent feed on the left,
 * Fund DNA and the #1 pick on the right). Rows keep their space while hidden so nothing jumps.
 */
export function ProductWindow({ dna, onReadMemo }: { dna?: FundDNA | null; onReadMemo: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { once: true, amount: 0.15 });
  const reduce = useReducedMotion();
  const [shown, setShown] = useState(reduce ? LINES.length : 0);
  const [typed, setTyped] = useState(reduce ? PICK_TEXT.length : 0);
  const d = DEFAULT_DNA; void dna;

  // Stream the agent lines once the window is on screen.
  useEffect(() => {
    if (!inView || reduce) return;
    let n = 0;
    let timer = 0;
    const tick = () => {
      n += 1;
      setShown(n);
      if (n < LINES.length) timer = window.setTimeout(tick, LINE_INTERVAL_MS);
    };
    timer = window.setTimeout(tick, 500);
    return () => window.clearTimeout(timer);
  }, [inView, reduce]);

  // Type the #1 pick's description once Deal Finder has found it.
  const pickFound = shown > DEAL_FINDER_INDEX;
  useEffect(() => {
    if (!pickFound || reduce) return;
    const id = window.setInterval(() => {
      setTyped((t) => {
        if (t >= PICK_TEXT.length) {
          window.clearInterval(id);
          return t;
        }
        return t + 2;
      });
    }, TYPE_MS_PER_CHAR * 2);
    return () => window.clearInterval(id);
  }, [pickFound, reduce]);

  const done = shown >= LINES.length;

  return (
    <motion.div
      ref={ref}
      initial={reduce ? false : { opacity: 0, y: 60 }}
      whileInView={{ opacity: 1, y: 0 }}
      // "some": at 1440x900 only ~39px of the window is on screen, so let it rise in and peek above the fold.
      viewport={{ once: true, amount: "some" }}
      transition={{ duration: 1, ease: EASE, delay: 0.3 }}
      className="relative flex w-[1240px] max-w-[calc(100%-32px)] shrink-0 flex-col md:h-[820px] overflow-hidden rounded-[16px] bg-surface shadow-window outline outline-1 -outline-offset-[0.5px] outline-[#1A181714]"
    >
      {/* Window bar */}
      <div className="flex h-[52px] shrink-0 items-center justify-between border-b border-[#E0DBD1] p-[12px_16px]">
        <div className="flex w-[120px] gap-[6px]">
          {[0, 1, 2].map((i) => (
            <span key={i} className="size-[10px] rounded-full bg-[#1A18171F]" />
          ))}
        </div>
        <div className="flex w-[420px] max-w-[50%] justify-center rounded-[8px] bg-chip p-[6px_0]">
          <span className="text-[12px] tracking-[0.2px] text-muted">bellwether.vc</span>
        </div>
        <div className="flex w-[120px] justify-end">
          <span className="size-[24px] rounded-full bg-sage" />
        </div>
      </div>

      <div className="flex min-h-0 flex-1 flex-col md:flex-row">
        {/* Mini feed */}
        <div className="flex min-w-0 flex-1 flex-col items-start gap-[18px] p-[24px_20px] md:p-[24px_28px]">
          <KeyChip k="Fund:" v="localglobe.vc" />
          <div className="flex items-center gap-[10px] text-[14px] tracking-[0.2px] md:whitespace-nowrap">
            <span className="text-subtle">Task:</span>
            <span className="text-ink">Find our next 10 deals and write the memo for #1</span>
          </div>
          <div className="h-px w-full shrink-0 bg-[#E0DBD1]" />
          {LINES.map((line, i) => (
            <motion.div
              key={i}
              className="flex w-full gap-[14px] text-[15px] tracking-[0.2px]"
              initial={false}
              animate={i < shown ? { opacity: 1, x: 0 } : { opacity: 0, x: 8 }}
              transition={{ duration: 0.45, ease: EASE }}
            >
              <span className="w-[88px] shrink-0 md:w-[110px]">
                <AgentName line={line} working={!done && i === shown - 1} />
              </span>
              <span className={cn("min-w-0 flex-1 leading-[23px] text-ink", line.highlight && "font-medium")}>{line.text}</span>
            </motion.div>
          ))}
          <motion.div
            className="flex items-center gap-[8px] rounded-full bg-accent-soft p-[6px_12px]"
            initial={false}
            animate={done ? { opacity: 1, y: 0 } : { opacity: 0, y: 6 }}
            transition={{ duration: 0.5, ease: EASE }}
          >
            <span className="size-[7px] rounded-full bg-accent" />
            <span className="text-[13px] tracking-[0.2px] whitespace-nowrap text-accent">9 agents · under 2 min · watching daily</span>
          </motion.div>
        </div>

        {/* Mini Fund DNA + #1 pick */}
        <div className="flex w-full shrink-0 flex-col items-start gap-[14px] border-t border-[#E0DBD1] p-[24px] md:w-[381px] md:border-t-0 md:border-l">
          <span className="text-[13px] tracking-[0.2px] text-subtle">Fund DNA</span>
          <p className="m-0 w-full text-[20px]/[27px] tracking-[-0.2px] text-ink">{d.summary}</p>
          <KeyChip k="Stage:" v={d.stage} />
          <KeyChip k="Where:" v={d.geo} />
          <KeyChip k="Cheque:" v={d.cheque} />
          <div className="h-px w-full shrink-0 bg-[#E0DBD1]" />
          <span className="text-[13px] tracking-[0.2px] text-subtle">Bellwether’s #1 pick</span>
          <motion.div
            className="flex w-full flex-col items-start gap-[10px] p-[4px_0]"
            initial={false}
            animate={pickFound ? { opacity: 1 } : { opacity: 0.35 }}
            transition={{ duration: 0.5, ease: EASE }}
          >
            <div className="flex w-full items-center justify-between tracking-[0.2px]">
              <span className="text-[19px] text-ink">Monday.com</span>
              <span className="text-[14px] text-predicted">89% fit</span>
            </div>
            <p className="m-0 w-full text-[14px]/[21px] tracking-[0.2px] text-ink" aria-label={PICK_TEXT}>
              <span aria-hidden>{PICK_TEXT.slice(0, typed)}</span>
              <span aria-hidden className="text-transparent">
                {PICK_TEXT.slice(typed)}
              </span>
            </p>
            <Pill size="sm" arrow shadow={false} onClick={onReadMemo}>
              Read the memo
            </Pill>
          </motion.div>
        </div>
      </div>
    </motion.div>
  );
}
