import type { UniverseRow } from "@/lib/types";
import { formatRowId } from "@/lib/format";

function cell(v: string | number | null | undefined): string {
  const s = v == null ? "" : String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

/** Download the rows loaded on screen as a CSV (client-side, no backend call). */
export function downloadUniverseCsv(rows: UniverseRow[], fundId: string | undefined) {
  const header = ["Row", "Company", "What it does", "Sector", "Country", "City", "Stage", "Founded", "Website", "Fit %"];
  const body = rows.map(({ company: c, fit }) => [
    formatRowId(c.row_id),
    c.name,
    c.one_liner,
    c.sector,
    c.country,
    c.city,
    c.stage,
    c.founded,
    c.website,
    fit,
  ]);
  const csv = [header, ...body].map((r) => r.map(cell).join(",")).join("\r\n");
  const url = URL.createObjectURL(new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = fundId ? `startups-${fundId}.csv` : "startups.csv";
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
