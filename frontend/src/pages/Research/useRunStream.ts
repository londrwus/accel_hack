import { useEffect, useRef, useState } from "react";
import type { AgentEvent } from "@/lib/types";
import { isRunFinished, streamRunEvents } from "@/lib/api";

export interface StreamOptions {
  /** Mock: deliver everything up to this many seconds at once (0 = watch the run from the start). */
  startAt: number;
  /** Mock replay speed (1 = the recorded gaps). */
  speed: number;
  /** Freeze at `startAt`: no further events, clock stops (used for design screenshots). */
  paused: boolean;
  /** Bump to restart the stream for the same run id ("Run again"). */
  restartKey: number;
}

export interface RunStream {
  events: AgentEvent[];
  /** seq -> arrived live */
  liveSeqs: Set<number>;
  finished: boolean;
  failed: boolean;
  lostConnection: boolean;
  /** Seconds into the run, ticking between events while it runs. */
  elapsed: number;
}

/** Events that arrive within this window of the first one are the replayed history: no slide-in. */
const HISTORY_WINDOW_MS = 400;

/** Subscribes to GET /api/runs/{id}/events (or the mock replay) and keeps a ticking run clock. */
export function useRunStream(runId: string | null, { startAt, speed, paused, restartKey }: StreamOptions): RunStream {
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [liveSeqs, setLiveSeqs] = useState<Set<number>>(() => new Set());
  const [finished, setFinished] = useState(false);
  const [lostConnection, setLostConnection] = useState(false);
  const [now, setNow] = useState(() => performance.now());
  const last = useRef<{ elapsed: number; at: number }>({ elapsed: 0, at: performance.now() });

  useEffect(() => {
    setEvents([]);
    setLiveSeqs(new Set());
    setFinished(false);
    setLostConnection(false);
    last.current = { elapsed: 0, at: performance.now() };
    if (!runId) return; // still working out which run to show
    let firstAt: number | null = null;

    const close = streamRunEvents(
      runId,
      {
        onEvent: (e) => {
          if (paused && e.elapsed_s > startAt) return;
          const t = performance.now();
          firstAt ??= t;
          last.current = { elapsed: e.elapsed_s, at: t };
          setLostConnection(false);
          setEvents((prev) => [...prev, e]);
          if (t - firstAt > HISTORY_WINDOW_MS) setLiveSeqs((prev) => new Set(prev).add(e.seq));
          if (isRunFinished(e)) setFinished(true);
        },
        onDone: () => setFinished(true),
        onError: () => setLostConnection(true),
      },
      { startAt, speed, liveSpeed: speed },
    );
    return close;
  }, [runId, startAt, speed, paused, restartKey]);

  const running = !finished && !paused && events.length > 0;
  useEffect(() => {
    if (!running) return;
    const id = setInterval(() => setNow(performance.now()), 1000);
    return () => clearInterval(id);
  }, [running]);

  const failed = events.some((e) => e.agent === "Partner" && e.type === "error");
  const lastEvent = last.current;
  const elapsed = running ? lastEvent.elapsed + (Math.max(0, now - lastEvent.at) / 1000) * (speed || 1) : lastEvent.elapsed;

  return { events, liveSeqs, finished, failed, lostConnection, elapsed };
}
