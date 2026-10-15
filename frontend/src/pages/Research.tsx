import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { MotionConfig } from "motion/react";
import { RotateCw, Share } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/Button";
import { Badge } from "@/components/Badge";
import { createRun, DEMO_RUN_ID, getRun, USE_MOCKS } from "@/lib/api";
import { DEMO_FUND_ID, useActiveFundId, useFund, useFundLoading, useFundRefresh } from "@/lib/fund";
import { FundEmptyState } from "@/components/FundEmptyState";
import { useApi } from "@/lib/useApi";
import { formatDuration } from "@/lib/format";
import { AgentStrip } from "./Research/AgentStrip";
import { ResearchLog } from "./Research/ResearchLog";
import { PartnerPanel } from "./Research/PartnerPanel";
import { useRunStream } from "./Research/useRunStream";
import { useAskChat } from "./Research/AskChat";
import type { AgentEvent } from "@/lib/types";
import { DESIGN_MOMENT_S, isLogRow, logRows, planState, teamState, workerCounts } from "./Research/feed";
import "./Research/research.css";

/**
 * /research — "What is the analyst team doing right now?"
 * URL options:
 *   ?run=<id>   watch that run from the start (Landing / "Run now" / "Run again" land here)
 *   no ?run     open the fund's latest run; in mock mode at the design moment (2:14), then keep streaming
 *   ?at=<s>     mock: open at this many seconds in
 *   ?speed=<x>  mock replay speed
 *   ?paused     freeze at the opening moment (design screenshots)
 */
export default function Research() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const fundCtx = useFund();
  const fundLoading = useFundLoading();
  const refreshFund = useFundRefresh();

  const runParam = params.get("run");
  // Live: without ?run, wait for GET /api/fund to say which run is the latest before opening a stream.
  const activeFundId = useActiveFundId();
  const ctxMatches = fundCtx?.fund.id === activeFundId;
  const latestRunId = ctxMatches ? (fundCtx?.latest_run_id ?? null) : null;
  const runId =
    runParam ??
    latestRunId ??
    (USE_MOCKS || (activeFundId === DEMO_FUND_ID && !fundLoading) ? DEMO_RUN_ID : null);
  // A fund that has never been run: offer to run it instead of replaying the demo fund's run.
  const neverRun = !USE_MOCKS && !runParam && !fundLoading && ctxMatches && !latestRunId && activeFundId !== DEMO_FUND_ID;
  const startAt = runParam ? 0 : Number(params.get("at") ?? DESIGN_MOMENT_S) || 0;
  const speed = Number(params.get("speed") ?? 1) || 1;
  const paused = params.has("paused");
  const animate = !paused;

  const [restartKey, setRestartKey] = useState(0);
  const [partnerOpen, setPartnerOpen] = useState(true);
  const [verbose, setVerbose] = useState(false);
  const [starting, setStarting] = useState(false);
  const [copied, setCopied] = useState(false);

  const stream = useRunStream(runId, { startAt, speed, paused, restartKey });
  const { finished } = stream;
  // Question events ("Ask the team") arrive on their own stream once the run's stream has closed: merge by seq.
  const [extra, setExtra] = useState<AgentEvent[]>([]);
  useEffect(() => setExtra([]), [runId, restartKey]);
  const events = useMemo(() => {
    if (extra.length === 0) return stream.events;
    const seen = new Set(stream.events.map((e) => e.seq));
    return [...stream.events, ...extra.filter((e) => !seen.has(e.seq))].sort((a, b) => a.seq - b.seq);
  }, [stream.events, extra]);
  const lastSeq = events.at(-1)?.seq ?? 0;
  const addEvent = useMemo(() => (e: AgentEvent) => setExtra((xs) => (xs.some((x) => x.seq === e.seq) ? xs : [...xs, e])), []);
  const chat = useAskChat(USE_MOCKS ? null : runId, activeFundId ?? null, lastSeq, addEvent);

  const team = useMemo(() => teamState(events), [events]);
  const workers = useMemo(() => workerCounts(events), [events]);
  const plan = useMemo(() => planState(events), [events]);
  const rows = useMemo(() => logRows(events, verbose), [events, verbose]);
  const lastEvent = events.at(-1) ?? null;
  const nowLine = !finished && !verbose && lastEvent && !isLogRow(lastEvent) ? lastEvent : null;

  // The fund's thesis is ready once Thesis reports back; the Partner's answer and the sector card appear then.
  const thesisReady =
    finished || events.some((e) => e.agent === "Thesis" && (e.type === "finding" || e.type === "handoff" || e.type === "done"));

  // Snapshot for the text around the feed (task, fund, summary). Refetched when the thesis lands and when the run ends.
  const { data: run } = useApi(
    () => (runId ? getRun(runId).catch(() => null) : Promise.resolve(null)),
    [runId, restartKey, thesisReady, finished],
  );

  // Keep the sidebar's watch card (progress ring, next update) in step: refresh it as plan steps finish and when the run ends.
  // Debounced, so the burst of replayed history on connect costs one request.
  const stepsDone = plan?.filter((p) => p.status === "done").length ?? 0;
  const synced = useRef<string | null>(null);
  useEffect(() => {
    if (!runId || events.length === 0) return;
    const key = `${runId}:${stepsDone}:${finished}`;
    if (key === synced.current) return;
    const t = setTimeout(() => {
      synced.current = key;
      refreshFund();
    }, 600);
    return () => clearTimeout(t);
  }, [runId, stepsDone, finished, events.length, refreshFund]);

  const fund = run?.fund ?? fundCtx?.fund ?? null;
  const fundName = fund?.name ?? "the fund";
  const task = run?.task ?? `Find ${fundName}’s next 10 deals and write a memo for the best one`;
  const latestPartnerLine =
    [...events].reverse().find((e) => e.agent === "Partner" && (e.type === "plan" || e.type === "step"))?.message ?? null;
  const answer = (thesisReady && run?.partner_summary) || latestPartnerLine;
  const closing = finished ? ([...events].reverse().find((e) => e.agent === "Partner" && e.type === "done")?.message ?? null) : null;
  const sectors = thesisReady ? (fund?.dna?.sectors ?? null) : null;

  // The run's #1 deal, as Deal Flow ranks it (by fit).
  const topPick =
    [...(run?.shortlist ?? [])].sort((a, b) => b.fit - a.fit || a.rank - b.rank)[0]?.company.name ?? null;
  const suggestions = [
    topPick ? `Who are ${topPick}’s competitors?` : "Who are Northbeam’s competitors?",
    topPick ? `Find more companies like ${topPick}, our best pick` : "Find more companies like our best pick",
    "What changed this week?",
  ];

  const elapsed = stream.elapsed;
  const minutes = Math.floor(elapsed / 60);
  const subtitle = finished
    ? `Your analyst team’s research on ${fundName} · finished in ${formatDuration(elapsed)}`
    : `Your analyst team at work on ${fundName} · started ${minutes < 1 ? "just now" : `${minutes} min ago`}`;

  const status = stream.lostConnection ? (
    <Badge tone="warning" size="md" dot>
      Reconnecting…
    </Badge>
  ) : stream.failed ? (
    <Badge tone="warning" size="md" dot>
      Stopped · {formatDuration(elapsed)}
    </Badge>
  ) : finished ? (
    <Badge tone="sage" size="md">
      Finished · {formatDuration(elapsed)}
    </Badge>
  ) : (
    <Badge tone="sage" size="md" dot>
      Working · {formatDuration(elapsed)}
    </Badge>
  );

  const runAgain = async () => {
    setStarting(true);
    try {
      const created = await createRun({ fund_url: fund?.url ?? "https://localglobe.vc", task: null, force: true });
      navigate(`/research?run=${encodeURIComponent(created.run_id)}&fund=${encodeURIComponent(created.fund_id)}`);
      setRestartKey((k) => k + 1);
    } finally {
      setStarting(false);
    }
  };

  const share = async () => {
    try {
      await navigator.clipboard.writeText(window.location.href);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      /* clipboard blocked: nothing to do */
    }
  };

  return (
    <MotionConfig reducedMotion="user">
      <PageHeader
        title="Research"
        subtitle={subtitle}
        actions={
          <>
            {!neverRun && status}
            <Button icon={Share} onClick={share}>
              {copied ? "Link copied" : "Share"}
            </Button>
            <Button variant="gold" icon={RotateCw} onClick={runAgain} disabled={starting}>
              Run again
            </Button>
          </>
        }
      />
      {neverRun ? (
        <FundEmptyState what="research" />
      ) : (
      <>
      <AgentStrip team={team} animate={animate} workers={workers} />
      <div className="flex min-h-0 flex-1 flex-row">
        <ResearchLog
          rows={rows}
          liveSeqs={stream.liveSeqs}
          now={nowLine}
          plan={plan}
          animate={animate}
          onShowPartner={partnerOpen ? undefined : () => setPartnerOpen(true)}
        />
        {partnerOpen && (
          <PartnerPanel
            task={task}
            plan={plan}
            answer={answer}
            closing={closing}
            fundName={fundName}
            sectors={sectors}
            sinceLastRun={thesisReady ? (run?.since_last_run ?? null) : null}
            animate={animate}
            verbose={verbose}
            onToggleVerbose={() => setVerbose((v) => !v)}
            onClose={() => setPartnerOpen(false)}
            chat={chat}
            suggestions={suggestions}
          />
        )}
      </div>
      </>
      )}
    </MotionConfig>
  );
}
