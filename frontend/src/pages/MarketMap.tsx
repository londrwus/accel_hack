import { useCallback, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Download, FileText } from "lucide-react";
import { Button } from "@/components/Button";
import { Segmented } from "@/components/Segmented";
import { ApiError, getMap } from "@/lib/api";
import { gated, useActiveFundId, useFundGate } from "@/lib/fund";
import { FundEmptyState } from "@/components/FundEmptyState";
import { formatCount } from "@/lib/format";
import type { DealFlowItem, MapQuery, MapResponse, MapView } from "@/lib/types";
import { useApi } from "@/lib/useApi";
import { MapCanvas } from "./MarketMap/MapCanvas";
import { ShortlistPanel } from "./MarketMap/ShortlistPanel";
import { MapControls } from "./MarketMap/MapControls";

const VIEWS: { value: MapView; label: string }[] = [
  { value: "portfolio", label: "Around the portfolio" },
  { value: "theme", label: "By theme" },
  { value: "new", label: "New ground" },
  { value: "competition", label: "Competition" },
];
const MAP_KEYS = ["view", "center", "sector", "country", "stage", "limit"] as const;

const memoHref = (item: DealFlowItem) => `/memos/${item.memo_id ?? item.company.id}`;

/** /map: where our companies, their rivals and our next deals sit. */
export default function MarketMap() {
  const fundId = useActiveFundId();
  const gate = useFundGate();
  const [params, setParams] = useSearchParams();
  const view = (params.get("view") as MapView) || "portfolio";
  const q: MapQuery = {
    view,
    center: params.get("center") || undefined,
    sector: params.get("sector") || undefined,
    country: params.get("country") || undefined,
    stage: params.get("stage") || undefined,
    limit: Number(params.get("limit")) || 10,
  };
  const key = MAP_KEYS.map((k) => params.get(k) ?? "").join("|");
  const { data: fresh, error } = useApi(() => gated(gate, () => getMap(fundId, q)), [fundId, gate, key]);
  // Keep the last map on screen while the next one loads (no blank flash between views).
  const [last, setLast] = useState<MapResponse | null>(null);
  if (fresh && fresh !== last) setLast(fresh);
  const data = fresh ?? last;
  const update = (patch: Partial<Record<(typeof MAP_KEYS)[number], string | number | undefined>>) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        for (const [k, v] of Object.entries(patch)) {
          if (v === undefined || v === "" || (k === "view" && v === "portfolio") || (k === "limit" && v === 10)) next.delete(k);
          else next.set(k, String(v));
        }
        return next;
      },
      { replace: true },
    );
  const [picked, setPicked] = useState<string | null>(null);

  const selectedId = picked ?? data?.shortlist[0]?.company.id ?? null;
  const selected = data?.shortlist.find((s) => s.company.id === selectedId) ?? data?.shortlist[0];

  return (
    <>
      {/* Header: title · segmented filter (centred by justify-between) · Export + Read memo */}
      <header className="flex h-[84px] shrink-0 items-center justify-between border-b border-hair px-[24px]">
        <div className="flex min-w-0 flex-col gap-[2px]">
          <h1 className="m-0 whitespace-nowrap text-[22px] font-normal tracking-[-0.3px] text-ink">Market Map</h1>
          <div className="max-w-[380px] truncate whitespace-nowrap text-[13px] tracking-[0.1px] text-subtle" title={data?.note ?? undefined}>
            {data?.note ?? "Click a gold dot to see why Bellwether picked it"}
          </div>
        </div>
        <Segmented
          aria-label="Show on the map"
          options={VIEWS}
          value={q.center ? null : view}
          onChange={(v) => update({ view: v, center: undefined })}
          className="[&>button]:px-[14px]"
        />
        <div className="flex shrink-0 items-center gap-[8px]">
          <Button variant="white" icon={Download} onClick={() => data && exportMap(data)} disabled={!data}>
            Export
          </Button>
          <Button variant="gold" icon={FileText} to={selected ? memoHref(selected) : "/memos"}>
            Read memo
          </Button>
        </div>
      </header>

      <MapControls
        sectors={data?.sectors ?? []}
        countries={data?.countries ?? []}
        stages={data?.stages ?? []}
        sector={q.sector}
        country={q.country}
        stage={q.stage}
        limit={q.limit ?? 10}
        center={q.center}
        centerLabel={data?.center_id === q.center ? data?.nodes.find((n) => n.company_id === q.center)?.label : undefined}
        fundId={fundId}
        nodes={data?.nodes ?? []}
        onChange={update}
      />
      <div className="flex min-h-0 flex-1">
        {error instanceof ApiError && error.status === 404 ? (
          <FundEmptyState what="market map" />
        ) : error ? (
          <div className="flex flex-1 items-center justify-center p-[24px] text-[14px] text-muted">
            Couldn't load the market map: {error.message}
          </div>
        ) : data ? (
          <MapBody data={data} selectedId={selectedId} onSelect={setPicked} />
        ) : (
          <div className="flex-1" aria-busy="true" />
        )}
      </div>
    </>
  );
}

function MapBody({
  data,
  selectedId,
  onSelect,
}: {
  data: MapResponse;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const names = useMemo(() => new Map(data.nodes.map((n) => [n.company_id ?? n.id, n.label])), [data.nodes]);
  const nameOf = useCallback((id: string) => names.get(id) ?? id, [names]);
  const fundName = data.nodes.find((n) => n.kind === "fund")?.label ?? "the fund";

  return (
    <>
      <MapCanvas
        key={data.center_id ?? "all"} // a fresh canvas per view/centre: edges draw in from scratch, never stuck half-way
        nodes={data.nodes}
        edges={data.edges}
        filter="all"
        selectedId={selectedId}
        onSelectPick={onSelect}
      />
      <ShortlistPanel
        fundName={fundName}
        items={data.shortlist}
        pickedFrom={formatCount(data.picked_from)}
        updatedLabel={data.updated_label}
        mixLabel={data.mix_label}
        selectedId={selectedId}
        onSelect={onSelect}
        nameOf={nameOf}
        memoHref={memoHref}
      />
    </>
  );
}

/** Download the map as a CSV a partner can open in a spreadsheet. */
function exportMap(data: MapResponse) {
  const byId = new Map(data.nodes.map((n) => [n.id, n]));
  const role = { fund: "Centre", portfolio: "Already owns", competitor: "Competitor", pick: "Next pick", theme: "Theme" } as const;
  const links = (id: string) =>
    data.edges
      .filter((e) => e.source === id || e.target === id)
      .map((e) => byId.get(e.source === id ? e.target : e.source)?.label ?? "")
      .filter(Boolean)
      .join("; ");
  const esc = (v: string | number | null) => {
    const s = v == null ? "" : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const rows = [
    ["Company", "Role", "Fit %", "Linked to"],
    ...data.nodes.map((n) => [n.label, role[n.kind], n.fit, links(n.id)]),
  ];
  const csv = rows.map((r) => r.map(esc).join(",")).join("\n");
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = `market-map-${data.fund_id}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}
