import type { DealFlowItem } from "@/lib/types";

const STATUS_LABEL = { new: "New", under_review: "Under review", passed: "Passed" } as const;

function cell(v: string | number | null | undefined): string {
  const s = v == null ? "" : String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

/** Download the rows on screen as a CSV (client-side, no backend call). */
export function downloadDealsCsv(items: DealFlowItem[], fundId: string) {
  const header = ["Rank", "Company", "What it does", "Sector", "Stage", "Fit %", "Signals", "Why it fits", "Seen", "Status", "Dataset row"];
  const rows = items.map((d) => [
    d.rank,
    d.company.name,
    d.company.one_liner,
    d.company.sector,
    d.company.stage,
    d.fit,
    d.signals.map((s) => s.label).join("; "),
    d.why.join("; "),
    d.seen_label,
    STATUS_LABEL[d.status],
    d.company.row_id,
  ]);
  const csv = [header, ...rows].map((r) => r.map(cell).join(",")).join("\r\n");
  const url = URL.createObjectURL(new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = `deal-flow-${fundId}.csv`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
