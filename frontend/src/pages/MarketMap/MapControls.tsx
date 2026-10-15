import { useEffect, useRef, useState } from "react";
import { Crosshair, Search, X } from "lucide-react";
import { getUniverse } from "@/lib/api";
import type { GraphNode } from "@/lib/types";
import { FilterMenu } from "../Universe/FilterMenu";

export interface MapControlsProps {
  sectors: string[];
  countries: string[];
  stages: string[];
  sector?: string;
  country?: string;
  stage?: string;
  limit: number;
  center?: string;
  centerLabel?: string;
  fundId?: string;
  nodes: GraphNode[];
  onChange: (patch: { sector?: string; country?: string; stage?: string; limit?: number; center?: string }) => void;
}

/** Toolbar under the header: filters, how many picks, and "Centre on…" any company. */
export function MapControls(p: MapControlsProps) {
  return (
    <div className="flex h-[52px] shrink-0 items-center gap-[8px] border-b border-hair px-[24px]">
      <FilterMenu label="Sector" anyLabel="Any sector" options={p.sectors} value={p.sector} onChange={(v) => p.onChange({ sector: v })} />
      <FilterMenu label="Country" anyLabel="Any country" options={p.countries} value={p.country} onChange={(v) => p.onChange({ country: v })} />
      <FilterMenu label="Stage" anyLabel="Any stage" options={p.stages} value={p.stage} onChange={(v) => p.onChange({ stage: v })} />
      <label className="ml-[8px] flex items-center gap-[8px] whitespace-nowrap text-[13px] text-muted">
        Show
        <input
          type="range"
          min={10}
          max={50}
          step={5}
          value={p.limit}
          onChange={(e) => p.onChange({ limit: Number(e.target.value) })}
          className="w-[110px] accent-[var(--color-accent)]"
          aria-label="Number of picks"
        />
        <span className="w-[56px] font-mono text-[12px] text-ink">{p.limit} picks</span>
      </label>
      <div className="flex-1" />
      <CenterSearch {...p} />
    </div>
  );
}

type Hit = { id: string; name: string; hint: string };

function CenterSearch({ center, centerLabel, fundId, nodes, onChange }: MapControlsProps) {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<Hit[]>([]);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return setHits([]);
    const local: Hit[] = nodes
      .filter((n) => n.company_id && n.label.toLowerCase().includes(needle))
      .map((n) => ({ id: n.company_id!, name: n.label, hint: n.kind === "portfolio" ? "We own it" : "On the map" }));
    setHits(local.slice(0, 8));
    const t = setTimeout(() => {
      getUniverse({ q: needle, page_size: 8, fund_id: fundId })
        .then((r) => {
          const seen = new Set(local.map((h) => h.id));
          const more = r.items
            .filter((u) => !seen.has(u.company.id))
            .map((u) => ({ id: u.company.id, name: u.company.name, hint: u.company.sector }));
          setHits([...local, ...more].slice(0, 8));
        })
        .catch(() => {});
    }, 250);
    return () => clearTimeout(t);
  }, [q, nodes, fundId]);

  useEffect(() => {
    const onDown = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, []);

  if (center) {
    return (
      <div className="flex items-center gap-[6px] rounded-full bg-accent-soft p-[5px_6px_5px_12px] text-[13px] text-ink">
        <Crosshair size={14} className="text-accent" aria-hidden />
        Centred on <b className="font-medium">{centerLabel ?? center}</b>
        <button
          type="button"
          onClick={() => onChange({ center: undefined })}
          className="flex size-[22px] items-center justify-center rounded-full text-muted hover:bg-bg hover:text-ink"
          aria-label="Stop centring"
        >
          <X size={13} />
        </button>
      </div>
    );
  }

  return (
    <div ref={ref} className="relative">
      <div className="flex h-[34px] w-[260px] items-center gap-[8px] rounded-[10px] border border-hair bg-bg px-[10px]">
        <Search size={14} className="text-subtle" aria-hidden />
        <input
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          placeholder="Centre on any company…"
          className="min-w-0 flex-1 bg-transparent text-[13px] text-ink outline-none placeholder:text-subtle"
          aria-label="Centre the map on a company"
        />
      </div>
      {open && hits.length > 0 && (
        <ul className="absolute right-0 top-[38px] z-30 m-0 w-[300px] list-none rounded-[12px] border border-hair bg-bg p-[4px] shadow-lg">
          {hits.map((h) => (
            <li key={h.id}>
              <button
                type="button"
                onClick={() => {
                  setOpen(false);
                  setQ("");
                  onChange({ center: h.id });
                }}
                className="flex w-full items-center justify-between gap-[8px] rounded-[8px] p-[7px_10px] text-left text-[13px] text-ink hover:bg-panel"
              >
                <span className="truncate">{h.name}</span>
                <span className="shrink-0 text-[12px] text-subtle">{h.hint}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
