import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Play } from "lucide-react";
import { createRun } from "@/lib/api";
import { useActiveFundId, useActiveFundSummary, useFund, useFundRefresh } from "@/lib/fund";
import { Button } from "./Button";

/** Shown on a page when the active fund has no results yet. "Run Bellwether on this fund" starts a live run. */
export function FundEmptyState({ what }: { what: string }) {
  const navigate = useNavigate();
  const fundId = useActiveFundId();
  const summary = useActiveFundSummary();
  const fundRes = useFund();
  const refresh = useFundRefresh();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fund = fundRes?.fund.id === fundId ? fundRes.fund : null;
  const name = fund?.name ?? summary?.name ?? "this fund";
  const url = fund?.url ?? summary?.url ?? null;
  const runId = summary?.latest_run_id ?? null;

  const run = async () => {
    if (!url || busy) return;
    setBusy(true);
    setError(null);
    try {
      const created = await createRun({ fund_url: url, task: null });
      refresh();
      navigate(`/research?run=${encodeURIComponent(created.run_id)}&fund=${encodeURIComponent(created.fund_id)}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn’t start the run. Please try again.");
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-0 flex-1 items-start justify-center overflow-auto p-[24px]">
      <div className="mt-[48px] flex w-[480px] max-w-full flex-col items-start gap-[12px] rounded-[16px] bg-panel p-[24px] shadow-card hairline">
        <h2 className="m-0 text-[20px] font-normal tracking-[-0.2px] text-ink">Nothing for {name} yet</h2>
        <p className="m-0 text-[14px] leading-[22px] tracking-[0.1px] text-muted">
          Bellwether hasn’t finished reading this fund, so there’s no {what} to show. A run reads the fund’s website,
          maps its portfolio and ranks the next deals. It takes a few minutes and you can watch it work.
        </p>
        <div className="flex items-center gap-[8px] pt-[4px]">
          <Button variant="gold" icon={Play} onClick={run} disabled={!url || busy}>
            {busy ? "Starting…" : "Run Bellwether on this fund"}
          </Button>
          {runId && (
            <Button onClick={() => navigate(`/research?run=${encodeURIComponent(runId)}&fund=${encodeURIComponent(fundId)}`)}>
              See the latest run
            </Button>
          )}
        </div>
        {error && (
          <p role="alert" className="m-0 text-[13px] text-muted">
            {error}
          </p>
        )}
      </div>
    </div>
  );
}
