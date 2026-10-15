import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { AnimatePresence, MotionConfig } from "motion/react";
import { ArrowDownWideNarrow, Download, ListFilter, Plus, Scale } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/Button";
import { Segmented } from "@/components/Segmented";
import { ApiError, getDeals } from "@/lib/api";
import { FundEmptyState } from "@/components/FundEmptyState";
import { useApi } from "@/lib/useApi";
import { gated, useActiveFundId, useFund, useFundGate } from "@/lib/fund";
import type { DealFlowItem, DealStatus } from "@/lib/types";
import { DealHeadRow, DealRow } from "./DealFlow/DealRow";
import { MenuButton } from "./DealFlow/MenuButton";
import { downloadDealsCsv } from "./DealFlow/exportCsv";

type StatusFilter = "all" | DealStatus;
type SortOrder = "fit" | "recent";

const SORTS: { value: SortOrder; label: string }[] = [
  { value: "fit", label: "Best fit first" },
  { value: "recent", label: "Newest first" },
];

/** "2h" / "1d" / "1w" -> hours, for "Newest first". Unknown labels sort last. */
function seenHours(label: string): number {
  const m = /^(\d+)\s*([mhdw])/.exec(label.trim());
  if (!m) return Number.POSITIVE_INFINITY;
  const n = Number(m[1]);
  return n * { m: 1 / 60, h: 1, d: 24, w: 168 }[m[2] as "m" | "h" | "d" | "w"];
}

function sortDeals(items: DealFlowItem[], order: SortOrder): DealFlowItem[] {
  const out = [...items];
  if (order === "recent") out.sort((a, b) => seenHours(a.seen_label) - seenHours(b.seen_label) || b.fit - a.fit);
  else out.sort((a, b) => b.fit - a.fit || a.rank - b.rank);
  return out;
}

/** 2 · Deal Flow: the next deals, ranked by fit, with the signals behind each one. */
export default function DealFlow() {
  const fund = useFund();
  const fundId = useActiveFundId();
  const fundName = fund?.fund.id === fundId ? fund.fund.name : "this fund";

  const [status, setStatus] = useState<StatusFilter>("all");
  const [sector, setSector] = useState<string>("all");
  const [sort, setSort] = useState<SortOrder>("fit");
  // The top row starts highlighted (as in the design). Click a row to open "why it fits".
  // `?open=<company id>` deep-links straight to a row's "why it fits" (e.g. from the Market Map).
  const [params] = useSearchParams();
  const openParam = params.get("open");
  const [selectedId, setSelectedId] = useState<string | null>(openParam);
  const [expandedId, setExpandedId] = useState<string | null>(openParam);

  const gate = useFundGate();
  const { data, error, loading } = useApi(
    () =>
      gated(gate, () => getDeals({
        fund_id: fundId,
        status: status === "all" ? undefined : status,
        sector: sector === "all" ? undefined : sector,
        sort: "fit",
      })),
    [fundId, status, sector, gate],
  );
  // Unfiltered list, only to know which sectors exist.
  const all = useApi(
    () => gated(gate, () => getDeals({ fund_id: fundId, sort: "fit" })),
    [fundId, gate],
  );

  const sectors = useMemo(() => {
    const names = new Set((all.data?.items ?? []).map((d) => d.company.sector));
    return [...names].sort();
  }, [all.data]);

  const items = useMemo(() => sortDeals(data?.items ?? [], sort), [data, sort]);
  const counts = data?.counts ?? all.data?.counts;
  const total = counts ? (status === "all" ? counts.all : counts[status]) : 0;
  const activeId = selectedId && items.some((d) => d.company.id === selectedId) ? selectedId : items[0]?.company.id;

  const toggle = (id: string) => {
    setSelectedId(id);
    setExpandedId((cur) => (cur === id ? null : id));
  };

  return (
    <MotionConfig reducedMotion="user">
      <PageHeader
        title="Deal Flow"
        subtitle={`Startups that fit ${fundName}, ranked by fit, with the signals behind each one`}
        actions={
          <>
            <Button
              icon={Download}
              disabled={items.length === 0}
              onClick={() => downloadDealsCsv(items, fundId ?? "fund")}
            >
              Export
            </Button>
            <Button variant="gold" icon={Plus} to="/universe">
              Add company
            </Button>
          </>
        }
      />

      {all.error instanceof ApiError && all.error.status === 404 ? (
        <FundEmptyState what="deal flow" />
      ) : (
      <>
      <div className="box-border flex h-[63px] shrink-0 items-center justify-between px-[24px]">
        <Segmented<StatusFilter>
          aria-label="Filter by status"
          value={status}
          onChange={(v) => {
            setStatus(v);
            setExpandedId(null);
          }}
          options={[
            { value: "all", label: "All", count: counts?.all },
            { value: "new", label: "New", count: counts?.new },
            { value: "under_review", label: "Under review", count: counts?.under_review },
            { value: "passed", label: "Passed", count: counts?.passed },
          ]}
        />
        <div className="flex items-center gap-[8px]">
          <MenuButton
            icon={ListFilter}
            aria-label="Filter by sector"
            label={`Sector: ${sector === "all" ? "All" : sector}`}
            value={sector}
            onChange={(v) => {
              setSector(v);
              setExpandedId(null);
            }}
            options={[{ value: "all", label: "All sectors" }, ...sectors.map((s) => ({ value: s, label: s }))]}
          />
          <MenuButton
            icon={ArrowDownWideNarrow}
            aria-label="Sort"
            label={SORTS.find((s) => s.value === sort)!.label}
            value={sort}
            onChange={setSort}
            options={SORTS}
          />
        </div>
      </div>

      <div className="flex min-h-0 flex-1 flex-col overflow-auto px-[12px]">
        <DealHeadRow />
        {error && !data ? (
          <p className="m-0 p-[24px_12px] text-[13px] text-danger">Couldn't load the deal flow: {error.message}</p>
        ) : items.length === 0 && !loading ? (
          <p className="m-0 p-[24px_12px] text-[13px] text-muted">No startups match this filter yet.</p>
        ) : (
          <AnimatePresence>
            {items.map((d, i) => (
              <DealRow
                key={d.company.id}
                deal={d}
                index={i}
                fundName={fundName}
                selected={d.company.id === activeId}
                expanded={d.company.id === expandedId}
                onToggle={() => toggle(d.company.id)}
              />
            ))}
          </AnimatePresence>
        )}
      </div>

      <footer className="box-border flex h-[40px] shrink-0 items-center justify-between border-t border-hair p-[12px_24px]">
        <div className="flex items-center gap-[6px] text-[12px] text-subtle">
          <Scale size={13} aria-hidden />
          Scored on public data only. Founder gender, age and ethnicity are never used.
        </div>
        <span className="text-[12px] text-subtle">
          Showing {items.length} of {total}
        </span>
      </footer>
      </>
      )}
    </MotionConfig>
  );
}
