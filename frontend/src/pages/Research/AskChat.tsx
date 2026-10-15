import { Fragment, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { motion } from "motion/react";
import { Check, CircleHelp, Globe, Database } from "lucide-react";
import type { AgentEvent, AgentName, AskSource, QuestionItem } from "@/lib/types";
import { askTeam, followQuestion, getQuestion, getQuestions } from "@/lib/api";
import { Chip } from "@/components/Chip";
import { cn } from "@/lib/utils";

const EASE = [0.22, 1, 0.36, 1] as const;

export interface AskChat {
  items: QuestionItem[];
  /** question id -> its events so far (for the live persona chips) */
  live: Record<string, AgentEvent[]>;
  ask: (q: string) => Promise<void>;
  busy: boolean;
  error: string | null;
}

/** Chat state for "Ask the team": history from SQLite, a POST per question, and the run's SSE for the live steps. */
export function useAskChat(runId: string | null, fundId: string | null, lastSeq: number, onEvent: (e: AgentEvent) => void): AskChat {
  const [items, setItems] = useState<QuestionItem[]>([]);
  const [live, setLive] = useState<Record<string, AgentEvent[]>>({});
  const [error, setError] = useState<string | null>(null);
  const closers = useRef<(() => void)[]>([]);
  const seqRef = useRef(lastSeq);
  seqRef.current = lastSeq;
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;

  const follow = useCallback(
    (run: string, qid: string, after: number) => {
      const close = followQuestion(run, after, qid, (e) => {
        onEventRef.current(e);
        const id = (e.data as { question_id?: string }).question_id;
        if (!id) return;
        setLive((l) => (l[id]?.some((x) => x.seq === e.seq) ? l : { ...l, [id]: [...(l[id] ?? []), e] }));
        if (e.type === "answer" && id === qid) {
          getQuestion(qid)
            .then((q) => setItems((xs) => xs.map((x) => (x.id === qid ? q : x))))
            .catch(() => {});
        }
      });
      closers.current.push(close);
    },
    [],
  );

  useEffect(() => {
    setItems([]);
    setLive({});
    if (!fundId) return;
    let stop = false;
    getQuestions(fundId)
      .then((r) => {
        if (stop) return;
        setItems(r.items);
        // A question still being answered (e.g. after a refresh): keep following it.
        for (const q of r.items) if (q.status === "working") follow(q.run_id, q.id, 0);
      })
      .catch(() => {});
    return () => {
      stop = true;
      closers.current.forEach((c) => c());
      closers.current = [];
    };
  }, [fundId, follow]);

  const ask = async (question: string) => {
    if (!runId) return;
    setError(null);
    try {
      const after = seqRef.current;
      const created = await askTeam(runId, question);
      const now = new Date().toISOString();
      setItems((xs) => [
        ...xs,
        { id: created.question_id, run_id: created.run_id, fund_id: fundId ?? "", question, status: "working", personas: [],
          answer: null, sources: [], company_ids: [], companies: [], unsure: false, asked_at: now, answered_at: null },
      ]);
      follow(created.run_id, created.question_id, created.run_id === runId ? after : 0);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't send the question.");
    }
  };

  const busy = items.some((q) => q.status === "working");
  return { items, live, ask, busy, error };
}

/** One question and its answer: user bubble, persona chips with live status, the cited answer. */
export function QuestionBlock({ q, events, animate }: { q: QuestionItem; events: AgentEvent[]; animate: boolean }) {
  const personas = useMemo(() => {
    const routed = events.find((e) => e.type === "handoff");
    const to = (routed?.data as { to?: AgentName[] } | undefined)?.to;
    return (Array.isArray(to) && to.length ? to : q.personas) as AgentName[];
  }, [events, q.personas]);
  const doneSet = new Set(events.filter((e) => e.type === "done").map((e) => e.agent));
  const working = q.status === "working";
  const latest = working ? [...events].reverse().find((e) => e.type === "tool" || e.type === "finding" || e.type === "step") : null;

  return (
    <div className="flex shrink-0 flex-col gap-[8px]">
      <Bubble>{q.question}</Bubble>
      {personas.length > 0 && (
        <div className="flex flex-wrap items-center gap-[6px]">
          {personas.map((p) => {
            const state = !working || doneSet.has(p) ? "done" : "working";
            return (
              <span
                key={p}
                title={`${p}: ${state}`}
                className={cn(
                  "flex items-center gap-[6px] rounded-full p-[3px_9px_3px_4px] text-[12px] tracking-[0.1px] text-ink",
                  state === "working" ? "bg-panel shadow-nav hairline" : "bg-track",
                )}
              >
                <span
                  className={cn(
                    "flex size-[16px] items-center justify-center rounded-[8px] text-[10px]",
                    state === "working" ? "bg-predicted-soft text-predicted" : "bg-accent-soft text-accent",
                  )}
                >
                  {state === "done" ? <Check size={10} /> : p[0]}
                </span>
                <span className={cn(state === "working" && animate && "research-shimmer")}>{p}</span>
              </span>
            );
          })}
        </div>
      )}
      {working ? (
        <p className={cn("m-0 text-[13px] tracking-[0.1px] text-muted", animate && "research-shimmer")}>
          {latest ? latest.message : "The Partner is reading your question…"}
        </p>
      ) : (
        <motion.div
          initial={animate ? { opacity: 0, y: 6 } : false}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.45, ease: EASE }}
          className="flex flex-col gap-[8px]"
        >
          <Markdown text={q.answer ?? ""} sources={q.sources} />
          {q.unsure && q.status === "answered" && (
            <span className="flex items-center gap-[6px] text-[12px] tracking-[0.1px] text-warning">
              <CircleHelp size={13} /> The team isn’t sure about this. Check the sources.
            </span>
          )}
          {q.companies.length > 0 && (
            <div className="flex flex-wrap gap-[6px]">
              {q.companies.map((c) => (
                <Link
                  key={c.id}
                  to={`/companies/${encodeURIComponent(c.id)}`}
                  className="rounded-full bg-predicted-soft p-[3px_10px] text-[12px] tracking-[0.1px] text-ink transition-opacity hover:opacity-80"
                >
                  {c.name} →
                </Link>
              ))}
            </div>
          )}
          {q.sources.length > 0 && (
            <div className="flex flex-wrap gap-[5px]">
              {q.sources.map((s, i) => (
                <SourceLink key={i} n={i + 1} s={s} />
              ))}
            </div>
          )}
        </motion.div>
      )}
    </div>
  );
}

function SourceLink({ n, s }: { n: number; s: AskSource }) {
  const label = `${n} · ${s.label}`;
  if (s.url)
    return (
      <Chip size="xs" icon={Globe} href={s.url} title={s.url}>
        {label}
      </Chip>
    );
  if (s.company_id)
    return (
      <Link to={`/companies/${encodeURIComponent(s.company_id)}`} className="transition-opacity hover:opacity-80">
        <Chip size="xs" icon={Database}>
          {label}
        </Chip>
      </Link>
    );
  return (
    <Chip size="xs" icon={Database}>
      {label}
    </Chip>
  );
}

/** Tiny markdown: paragraphs, "- " bullets, **bold**, and [n] citations as small superscripts. */
function Markdown({ text, sources }: { text: string; sources: AskSource[] }) {
  const blocks: ReactNode[] = [];
  let list: string[] = [];
  const flush = () => {
    if (list.length)
      blocks.push(
        <ul key={blocks.length} className="m-0 flex list-disc flex-col gap-[3px] pl-[18px]">
          {list.map((l, i) => (
            <li key={i}>{inline(l, sources)}</li>
          ))}
        </ul>,
      );
    list = [];
  };
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (/^[-*•]\s+/.test(line)) list.push(line.replace(/^[-*•]\s+/, ""));
    else {
      flush();
      if (line) blocks.push(<p key={blocks.length} className="m-0">{inline(line.replace(/^#+\s*/, ""), sources)}</p>);
    }
  }
  flush();
  return <div className="flex flex-col gap-[6px] text-[14px]/[22px] tracking-[0.1px] text-ink">{blocks}</div>;
}

function inline(text: string, sources: AskSource[]): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*|\[\d+\])/g).map((part, i) => {
    const bold = /^\*\*(.+)\*\*$/.exec(part);
    if (bold) return <strong key={i} className="font-medium">{bold[1]}</strong>;
    const cite = /^\[(\d+)\]$/.exec(part);
    if (cite) {
      const s = sources[Number(cite[1]) - 1];
      const sup = <sup className="ml-[1px] text-[10px] text-predicted">{cite[1]}</sup>;
      return s?.url ? (
        <a key={i} href={s.url} target="_blank" rel="noreferrer" title={s.label}>
          {sup}
        </a>
      ) : (
        <Fragment key={i}>{sup}</Fragment>
      );
    }
    return <Fragment key={i}>{part}</Fragment>;
  });
}

export function Bubble({ children }: { children: string }) {
  return (
    <div className="flex shrink-0 justify-end">
      <div className="max-w-[248px] rounded-[14px] bg-shell p-[9px_14px] text-[14px]/[20px] tracking-[0.1px] text-ink hairline">
        {children}
      </div>
    </div>
  );
}
