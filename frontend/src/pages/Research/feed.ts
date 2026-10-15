// Pure helpers that turn the AgentEvent stream into what the Research page shows.
// Everything is derived from the events alone, so a replayed run and a live run look the same.

import type { AgentEvent, AgentName, AgentState, PlanStep } from "@/lib/types";
import { isRunFinished } from "@/lib/api";

export const AGENTS: AgentName[] = ["Partner", "Reader", "Thesis", "Market", "Mapper", "Deal Finder", "Analyst", "Critic", "Enricher"];

/** Where the page opens on a plain visit in mock mode: 2:14 into the demo run (the design moment). */
export const DESIGN_MOMENT_S = 134;

type Data = Record<string, unknown>;

const isRetry = (e: AgentEvent) => e.type === "warning" && (e.tag === "Retrying" || typeof (e.data as Data).attempt === "number");

/**
 * Research log rows, newest first.
 * - `tool` and `step` events are the agents' working notes, not log rows (they show as the "now" line instead).
 * - An agent's own untagged `done` shows as a tick in the team strip and the plan, not as a row.
 * - The Partner's hand-offs show as agents lighting up in the team strip.
 * - A retry warning is folded away once the same agent reports `recovered` (the Recovered row replaces it).
 * `verbose` shows every event.
 */
export function logRows(events: AgentEvent[], verbose = false): AgentEvent[] {
  if (verbose) return [...events].reverse();
  const recoveredAfter = new Set<string>();
  const rows: AgentEvent[] = [];
  for (let i = events.length - 1; i >= 0; i--) {
    const e = events[i];
    if (e.type === "recovered") recoveredAfter.add(e.agent);
    if (isLogRow(e) && !(isRetry(e) && recoveredAfter.has(e.agent))) rows.push(e);
  }
  return rows;
}

export function isLogRow(e: AgentEvent): boolean {
  if (e.type === "tool" || e.type === "step") return false;
  if (e.type === "done" && !e.tag && concernsOf(e).length === 0) return false;
  if (e.type === "handoff" && e.agent === "Partner") return false;
  return true;
}

function targets(e: AgentEvent): string[] {
  const to = (e.data as Data).to;
  if (typeof to === "string") return [to];
  if (Array.isArray(to)) return to.filter((t): t is string => typeof t === "string");
  return [];
}

/** Agent strip: waiting until an agent's first event; working while it acts; done after its `done`,
 *  after it hands its work on, or after a fallback finished its task (`recovered`). */
export function teamState(events: AgentEvent[]): Record<AgentName, AgentState> {
  const s = Object.fromEntries(AGENTS.map((a) => [a, "waiting"])) as Record<AgentName, AgentState>;
  let finished = false;
  for (const e of events) {
    const a = e.agent;
    if (!(a in s)) continue;
    if (isRunFinished(e)) finished = true;
    if (e.type === "error") s[a] = "error";
    else if (e.type === "answer") s[a] = "done";
    else if (e.type === "done") s[a] = a === "Partner" && !(e.data as Data).run_done ? "working" : "done";
    else if (e.type === "handoff") {
      s[a] = a === "Partner" ? "working" : "done";
      for (const t of targets(e)) if (t in s && s[t as AgentName] !== "error") s[t as AgentName] = "working";
    } else if (e.type === "recovered") s[a] = a === "Partner" ? "working" : "done";
    else s[a] = "working";
  }
  if (finished) for (const a of AGENTS) if (s[a] === "working") s[a] = "done";
  return s;
}

/** "Thought process" checklist: steps from the Partner's `plan` event, ticked by data.plan_step / plan_status. */
export function planState(events: AgentEvent[]): PlanStep[] | null {
  let labels: string[] | null = null;
  const status = new Map<number, "working" | "done">();
  let finished = false;
  for (const e of events) {
    const d = e.data as Data;
    if (e.type === "plan" && Array.isArray(d.steps)) labels = d.steps.map(String);
    if (typeof d.plan_step === "number" && (d.plan_status === "working" || d.plan_status === "done")) {
      status.set(d.plan_step, d.plan_status);
    }
    if (isRunFinished(e) && e.type === "done") finished = true;
  }
  if (!labels) return null;
  return labels.map((label, i) => ({ label, status: finished ? "done" : (status.get(i + 1) ?? "waiting") }));
}

/** "Step: 4 of 7" = the first step that isn't done (1-based). */
export function currentStep(plan: PlanStep[]): number {
  const i = plan.findIndex((p) => p.status !== "done");
  return i === -1 ? plan.length : i + 1;
}

/** Progress bar under the log header: done steps count fully, steps in progress count an eighth. */
export function planProgress(plan: PlanStep[]): number {
  if (plan.length === 0) return 0;
  const done = plan.filter((p) => p.status === "done").length;
  const working = plan.filter((p) => p.status === "working").length;
  return Math.min(1, (done + working / 8) / plan.length);
}

/** The Critic's worries about the memo (data.concerns on its `done` event), plain English, at most 3. */
export function concernsOf(e: AgentEvent): string[] {
  const c = (e.data as Data).concerns;
  return Array.isArray(c) ? c.filter((x): x is string => typeof x === "string" && x.trim() !== "").slice(0, 3) : [];
}

/** The chip on a log row: the event's tag, or "Ignored" for a page that tried to instruct the AI. */
export function displayTag(e: AgentEvent): string | null {
  if (e.tag) return e.tag;
  if ((e.data as Data).ignored_instructions === true) return "Ignored";
  if (concernsOf(e).length > 0) return "Concerns";
  return null;
}

export type TagTone = "gold" | "warning" | "danger" | "sage" | "grey";

/** Tag chip colours on the right of a log row. */
export function tagTone(tag: string): TagTone {
  switch (tag) {
    case "New match":
      return "gold";
    case "Recovered":
    case "Retrying":
    case "Not verified":
      return "warning";
    case "Clash":
      return "danger";
    case "Done":
    case "Changed":
      return "sage";
    case "Concerns":
      return "warning";
    default:
      return "grey"; // Plan, Hand-off
  }
}

/** "Reader #3" when the event comes from one of several parallel workers (data.worker), else the agent. */
export function agentLabel(e: AgentEvent): string {
  const w = (e.data as Data).worker;
  return typeof w === "number" ? `${e.agent} #${w}` : e.agent;
}

/** How many parallel workers each agent ran (from data.workers / data.worker), for the team strip. */
export function workerCounts(events: AgentEvent[]): Partial<Record<AgentName, number>> {
  const out: Partial<Record<AgentName, number>> = {};
  for (const e of events) {
    const d = e.data as Data;
    const n = typeof d.workers === "number" ? d.workers : typeof d.worker === "number" ? d.worker : 0;
    if (n > (out[e.agent] ?? 0)) out[e.agent] = n;
  }
  return out;
}
