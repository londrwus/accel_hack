import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { AnimatePresence, MotionConfig, motion } from "motion/react";
import { Download, RotateCw } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/Button";
import { Badge } from "@/components/Badge";
import { ApiError, BACKTEST_FUNDS, getBacktest } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import { useActiveFundId, useActiveFundSummary, useFund, useFunds } from "@/lib/fund";
import { KpiStrip } from "./Universe/KpiStrip";
import { DataTable, type TableFilters, type UniverseSort } from "./Universe/DataTable";
import { ProofRail } from "./Universe/ProofRail";
import { useUniverseRows } from "./Universe/useUniverseRows";
import { downloadUniverseCsv } from "./Universe/csv";
import { EASE } from "./Universe/motion";

/** "y-combinator" -> "Y Combinator" (a fund we have no name for). */
function titleCase(id: string): string {
  return id.split("-").map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(" ");
}

/** "LocalGlobe" -> "LG", "Haatch" -> "H". Used in the "Fit for LG" column. */
function fundInitials(name: string): string {
  const caps = name.match(/[A-Z]/g);
  return caps && caps.length > 0 ? caps.join("").slice(0, 3) : name.slice(0, 2).toUpperCase();
}

/** Gold "Retrain model" with an honest note: retraining runs on Modal, there is no manual trigger wired up yet. */
function RetrainButton({ retrains }: { retrains: string | null }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);
  return (
    <div ref={ref} className="relative">
      <Button variant="gold" icon={RotateCw} aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        Retrain model
      </Button>
      <AnimatePresence>
        {open && (
          <motion.div
            role="status"
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.16, ease: EASE }}
            className="absolute right-0 top-[calc(100%+6px)] z-30 w-[280px] rounded-[12px] bg-panel p-[12px_14px] text-[13px] leading-[19px] tracking-[0.1px] text-muted shadow-[0_8px_24px_#1A18171F] hairline"
          >
            <span className="font-medium text-ink">Training runs on Modal.</span> The model retrains {retrains ? retrains.toLowerCase() : "every night"}{" "}
            with the latest data, then re-runs the backtest. A manual retrain isn’t connected in this build yet.
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

const FILTER_KEYS = ["sector", "country", "stage", "founded"] as const;

/** 7 · Startup Universe: the proof page. The dataset (searchable, paged) on the left, backtest + model card on the right. */
export default function Universe() {
  const fundRes = useFund();
  const activeId = useActiveFundId();
  const summary = useActiveFundSummary();
  const allFunds = useFunds();
  const fund = summary
    ? { id: summary.id, name: summary.name }
    : fundRes?.fund.id === activeId
      ? fundRes.fund
      : { id: activeId, name: titleCase(activeId) };
  const fundName = fund.name;
  const [params, setParams] = useSearchParams();

  // Search box is local (instant typing); the URL (?q=) follows after a short pause and drives the fetch.
  const urlQ = params.get("q") ?? "";
  const [search, setSearch] = useState(urlQ);
  useEffect(() => setSearch((s) => (s.trim() === urlQ ? s : urlQ)), [urlQ]);
  useEffect(() => {
    if (search.trim() === urlQ) return;
    const t = setTimeout(() => {
      setParams(
        (p) => {
          const next = new URLSearchParams(p);
          if (search.trim()) next.set("q", search.trim());
          else next.delete("q");
          return next;
        },
        { replace: true },
      );
    }, 250);
    return () => clearTimeout(t);
  }, [search, urlQ, setParams]);

  const filters: TableFilters = useMemo(() => {
    const founded = Number(params.get("founded"));
    return {
      sector: params.get("sector") ?? undefined,
      country: params.get("country") ?? undefined,
      stage: params.get("stage") ?? undefined,
      founded: Number.isFinite(founded) && founded > 0 ? founded : undefined,
    };
  }, [params]);

  const setFilters = (f: TableFilters) =>
    setParams(
      (p) => {
        const next = new URLSearchParams(p);
        for (const k of FILTER_KEYS) {
          const v = f[k];
          if (v === undefined || v === "") next.delete(k);
          else next.set(k, String(v));
        }
        return next;
      },
      { replace: true },
    );

  const sortParam = params.get("sort");
  const sort = (["fit", "name", "founded", "funding"] as const).find((s) => s === sortParam) as UniverseSort | undefined;
  const setSort = (v: UniverseSort | undefined) =>
    setParams(
      (p) => {
        const next = new URLSearchParams(p);
        if (v) next.set("sort", v);
        else next.delete("sort");
        return next;
      },
      { replace: true },
    );

  const table = useUniverseRows({ q: urlQ.trim() || undefined, ...filters, fund_id: activeId, sort });
  const hasFit = table.rows.some((r) => r.fit != null);

  // Which fund's backtest the right rail shows: ?backtest=<fund id>, default the current fund.
  const fundChoices = useMemo(() => {
    const seen = new Map<string, string>();
    seen.set(fund.id, fund.name);
    for (const f of allFunds) if (!seen.has(f.id)) seen.set(f.id, f.name);
    for (const f of fundRes?.covered_funds ?? []) if (!seen.has(f.id)) seen.set(f.id, f.name);
    for (const f of BACKTEST_FUNDS) if (!seen.has(f.id)) seen.set(f.id, f.name);
    return [...seen].map(([id, name]) => ({ id, name }));
  }, [fund.id, fund.name, allFunds, fundRes?.covered_funds]);
  const btFundId = params.get("backtest") ?? activeId;
  const btFundName = fundChoices.find((f) => f.id === btFundId)?.name ?? (btFundId ? titleCase(btFundId) : fundName);
  const pickBacktestFund = (id: string) =>
    setParams(
      (p) => {
        const next = new URLSearchParams(p);
        if (id === activeId) next.delete("backtest");
        else next.set("backtest", id);
        return next;
      },
      { replace: true },
    );

  const bt = useApi(() => (btFundId ? getBacktest(btFundId) : Promise.resolve(null)), [btFundId]);
  const backtestMissing = bt.error instanceof ApiError && bt.error.status === 404;
  // Ignore an answer for the previously picked fund while the new one loads.
  const backtest = bt.data && bt.data.fund_id === btFundId ? bt.data : null;
  const hasResults = Boolean(backtest?.enough_history && backtest.methods.length > 0);

  // When this fund can't be tested, offer the funds that have real results (checked once, in the background).
  const needOthers = Boolean(btFundId) && !bt.loading && !hasResults;
  const others = useApi(
    () =>
      needOthers
        ? Promise.all(
            BACKTEST_FUNDS.filter((f) => f.id !== btFundId).map((f) =>
              getBacktest(f.id).then(
                (b) => (b.enough_history && b.methods.length > 0 ? f : null),
                () => null,
              ),
            ),
          ).then((list) => list.filter((f): f is { id: string; name: string } => f !== null))
        : Promise.resolve([]),
    [needOthers, btFundId],
  );

  const status = hasResults && backtest ? (
    <Badge tone="sage" size="md" dot>
      Model trained on {backtest.model_card.trained_on} · {backtest.trained_label}
    </Badge>
  ) : backtest ? (
    <Badge tone="grey" size="md" dot>
      Not enough history
    </Badge>
  ) : backtestMissing ? (
    <Badge tone="grey" size="md" dot>
      No backtest yet
    </Badge>
  ) : null;

  return (
    <MotionConfig reducedMotion="user">
      <PageHeader
        title="Startup Universe"
        subtitle="Every startup Bellwether can recommend, and proof of how the model scores them"
        actions={
          <>
            {status}
            <Button icon={Download} disabled={table.rows.length === 0} onClick={() => downloadUniverseCsv(table.rows, activeId)}>
              Download CSV
            </Button>
            <RetrainButton retrains={backtest?.model_card.retrains ?? null} />
          </>
        }
      />
      <KpiStrip meta={table.meta} backtest={backtest} backtestMissing={backtestMissing || Boolean(bt.error)} fundName={btFundName} />
      <div className="flex min-h-0 flex-1">
        <DataTable
          rows={table.rows}
          total={table.total}
          meta={table.meta}
          loading={table.loading}
          page={table.page}
          done={table.done}
          error={table.error}
          fitLabel={`Fit for ${summary?.initials ?? fundInitials(fund.name)}`}
          search={search}
          onSearch={setSearch}
          filters={filters}
          onFilter={setFilters}
          options={table.options}
          onLoadMore={table.loadMore}
          sort={sort}
          onSort={setSort}
          hasFit={hasFit}
        />
        <ProofRail
          backtest={backtest}
          fundName={btFundName}
          missing={backtestMissing}
          error={backtestMissing ? null : bt.error}
          funds={fundChoices}
          fundId={btFundId}
          onPickFund={pickBacktestFund}
          withResults={others.data ?? []}
        />
      </div>
    </MotionConfig>
  );
}
