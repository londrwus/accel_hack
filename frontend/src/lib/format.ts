// Small display helpers shared by pages. Keep labels from the API as-is (fields ending in _label).

/** 134 -> "2:14" (feed timestamps). */
export function formatElapsed(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** 134 -> "2m 14s" (status chip "Working · 2m 14s"). */
export function formatDuration(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  const m = Math.floor(s / 60);
  return m > 0 ? `${m}m ${s % 60}s` : `${s % 60}s`;
}

/** 4821 -> "#4821", 193 -> "#0193", null -> "". */
export function formatRowId(rowId: number | null | undefined): string {
  return rowId == null ? "" : `#${String(rowId).padStart(4, "0")}`;
}

/** 0.33 -> "33%". */
export function formatShare(share: number): string {
  return `${Math.round(share * 100)}%`;
}

/** 10412 -> "10,412". */
export function formatCount(n: number): string {
  return n.toLocaleString("en-GB");
}

/** Gold for picks at or above 80% fit (Deal Flow rule). */
export function isStrongFit(fit: number): boolean {
  return fit >= 80;
}

export interface StageView {
  /** "Seed", or "–" when the stage isn't known. */
  label: string;
  /** Worked out from the latest funding round rather than reported (shown as a subtle "estimated"). */
  estimated: boolean;
}

const ESTIMATED = /\s*[(\[]?\s*(?:estimated|est\.?)\s*[)\]]?\s*$/i;

/** "Seed (estimated)" -> {label: "Seed", estimated: true}; "Unknown" -> {label: "–"}. Also honours an optional
 *  `stage_estimated: true` on the company (see shared/contract.md, "Stage labels"). */
export function stageView(company: { stage: string | null | undefined; stage_estimated?: unknown }): StageView {
  const raw = (company.stage ?? "").trim();
  const estimated = company.stage_estimated === true || ESTIMATED.test(raw);
  const label = raw.replace(ESTIMATED, "").trim();
  if (!label || label.toLowerCase() === "unknown") return { label: "–", estimated: false };
  return { label, estimated };
}
