import { SkeletonRows } from "@/components/Skeleton";
import { MotionConfig } from "motion/react";
import { Download, FileText } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/Button";
import { ApiError, getPortfolio } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import { gated, useActiveFundId, useFund, useFundGate } from "@/lib/fund";
import { FundEmptyState } from "@/components/FundEmptyState";
import type { PortfolioResponse } from "@/lib/types";
import { KpiStrip } from "./Portfolio/KpiStrip";
import { Board } from "./Portfolio/Board";

function download(filename: string, text: string, type: string) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

const csvCell = (v: string | null | undefined) => `"${(v ?? "").replace(/"/g, '""')}"`;

/** The companies on the board as a CSV (one row per company). */
function exportCsv(data: PortfolioResponse) {
  const rows = [["Company", "What they do", "Stage", "Group", "Signals", "Sources", "Updated"]];
  for (const col of data.columns) {
    for (const item of col.items) {
      rows.push([
        item.company.name,
        item.company.one_liner ?? "",
        item.company.stage ?? "",
        col.title,
        item.signals.map((s) => s.label).join("; "),
        item.signals.map((s) => s.source_url ?? "").filter(Boolean).join(" "),
        item.updated_label ?? "",
      ]);
    }
  }
  download(`portfolio-${data.fund_id}.csv`, rows.map((r) => r.map(csvCell).join(",")).join("\n"), "text/csv");
}

/** A plain-text weekly summary a partner can edit before sending to LPs. Nothing is sent automatically. */
function weeklyReport(data: PortfolioResponse, fundName: string) {
  const k = data.kpis;
  const lines = [
    `${fundName}: weekly portfolio report (draft)`,
    "",
    `${k.companies_backed} companies backed · ${k.invested} invested to date`,
    `${k.likely_to_raise} likely to raise soon · ${k.need_attention} need attention · ${k.new_signals_this_week} new signals this week`,
  ];
  for (const col of data.columns) {
    lines.push("", `${col.title} (${col.count})`, col.blurb);
    for (const item of col.items) {
      const signals = item.signals.map((s) => s.label + (s.source_url ? ` [${s.source_url}]` : "")).join("; ");
      lines.push(`- ${item.company.name}: ${signals}`);
    }
    if (col.more > 0) lines.push(`- and ${col.more} more`);
  }
  lines.push("", "Draft written by Bellwether from public data. A partner reviews it before it goes out.");
  download(`weekly-lp-report-${data.fund_id}.txt`, lines.join("\n"), "text/plain");
}

export default function Portfolio() {
  const fundId = useActiveFundId();
  const fundRes = useFund();
  const fundName = fundRes?.fund.id === fundId ? fundRes.fund.name : "this fund";
  const gate = useFundGate();
  const { data, error, loading } = useApi(() => gated(gate, () => getPortfolio(fundId)), [fundId, gate]);
  const empty = error instanceof ApiError && error.status === 404;

  return (
    <MotionConfig reducedMotion="user">
      <PageHeader
        title="Portfolio"
        subtitle={`Every company ${fundName} has backed, grouped by what needs your attention`}
        actions={
          <>
            <Button variant="white" icon={Download} disabled={!data} onClick={() => data && exportCsv(data)}>
              Export
            </Button>
            <Button variant="gold" icon={FileText} disabled={!data} onClick={() => data && weeklyReport(data, fundName)}>
              Weekly LP report
            </Button>
          </>
        }
      />
      {empty ? (
        <FundEmptyState what="portfolio" />
      ) : data ? (
        <>
          <KpiStrip kpis={data.kpis} />
          <Board columns={data.columns} />
        </>
      ) : (
        <div className="min-h-0 flex-1 p-[24px] text-[14px] text-muted">
          {loading ? <SkeletonRows rows={8} label="Loading the portfolio" /> : `Couldn't load the portfolio. ${error?.message ?? ""}`}
        </div>
      )}
    </MotionConfig>
  );
}
