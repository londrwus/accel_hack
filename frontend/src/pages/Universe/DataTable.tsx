import { useEffect, useRef, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "motion/react";
import { FileSpreadsheet, Search, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { formatCount, formatRowId, isStrongFit, stageView } from "@/lib/format";
import type { UniverseRow } from "@/lib/types";
import { FilterMenu } from "./FilterMenu";
import { EASE } from "./motion";
import type { DatasetMeta, FilterOptions } from "./useUniverseRows";

// Column widths from the design (Pencil export), tightened to fit the extra "Raised" column; 10px gaps.
const COLS = ["w-[48px]", "w-[176px]", "w-[80px]", "w-[64px]", "w-[68px]", "w-[52px]", "w-[56px]", "w-[92px]"] as const;

export type UniverseSort = "fit" | "name" | "founded" | "funding";
const SORT_LABELS: Record<UniverseSort, string> = {
  fit: "Best fit first",
  name: "Name A–Z",
  founded: "Newest first",
  funding: "Most raised first",
};

/** 1250000000 -> "$1.3B", 2500000 -> "$2.5M". */
function formatMoney(usd: number | null | undefined): string {
  if (!usd) return "—";
  const fmt = (n: number, unit: string) => `$${n >= 10 ? Math.round(n) : Math.round(n * 10) / 10}${unit}`;
  if (usd >= 1e9) return fmt(usd / 1e9, "B");
  if (usd >= 1e6) return fmt(usd / 1e6, "M");
  if (usd >= 1e3) return fmt(usd / 1e3, "K");
  return `$${Math.round(usd)}`;
}
const ROW = "flex w-full items-center gap-[10px] border-b border-hair";

export interface TableFilters {
  sector?: string;
  country?: string;
  stage?: string;
  founded?: number;
}

function HeadCell({ i, children }: { i: number; children: ReactNode }) {
  return (
    <div role="columnheader" className={cn(COLS[i], "shrink-0 whitespace-nowrap text-[12px] tracking-[0.3px] text-subtle")}>
      {children}
    </div>
  );
}

function TextCell({ i, mono, children }: { i: number; mono?: boolean; children: ReactNode }) {
  return (
    <div role="cell" className={cn(COLS[i], "shrink-0 truncate text-[13px] tracking-[0.1px] text-muted", mono && "font-mono")}>
      {children}
    </div>
  );
}

function FitCell({ fit, delay }: { fit: number | null; delay: number }) {
  if (fit == null) {
    return (
      <div role="cell" className={cn(COLS[7], "shrink-0 text-[14px] text-subtle")} title="Not scored for this fund yet">
        —
      </div>
    );
  }
  const strong = isStrongFit(fit);
  return (
    <div role="cell" className={cn(COLS[7], "flex shrink-0 items-center gap-[8px]")}>
      <span className={cn("text-[14px] font-medium tracking-[0.1px]", strong ? "text-predicted" : "text-ink")}>{fit}%</span>
      <span className="h-[4px] w-[44px] shrink-0 rounded-[2px] bg-[#1A18170F]">
        <motion.span
          className={cn("block h-full origin-left rounded-[2px]", strong ? "bg-predicted" : "bg-competitor")}
          style={{ width: Math.round((44 * Math.max(0, Math.min(100, fit))) / 100) }}
          initial={{ scaleX: 0 }}
          animate={{ scaleX: 1 }}
          transition={{ duration: 0.7, delay: delay + 0.15, ease: EASE }}
        />
      </span>
    </div>
  );
}

function SkeletonRows() {
  return (
    <>
      {Array.from({ length: 8 }, (_, i) => (
        <div key={i} className={cn(ROW, "h-[57px] px-[12px]")} aria-hidden>
          <span className={cn(COLS[0], "h-[12px] shrink-0 animate-pulse rounded-[4px] bg-track")} />
          <span className="flex w-[176px] shrink-0 flex-col gap-[6px]">
            <span className="h-[14px] w-[140px] animate-pulse rounded-[4px] bg-track" />
            <span className="h-[11px] w-[170px] animate-pulse rounded-[4px] bg-track" />
          </span>
          <span className="h-[12px] w-[300px] animate-pulse rounded-[4px] bg-track" />
        </div>
      ))}
    </>
  );
}

export interface DataTableProps {
  rows: UniverseRow[];
  total: number | null;
  meta: DatasetMeta | null;
  loading: boolean;
  /** Last page loaded; 0 while the first page for new filters is on its way. */
  page: number;
  done: boolean;
  error: Error | null;
  fitLabel: string;
  search: string;
  onSearch: (q: string) => void;
  filters: TableFilters;
  onFilter: (f: TableFilters) => void;
  options: FilterOptions;
  onLoadMore: () => void;
  /** undefined = the default order (best fit when scored, else dataset order). */
  sort: UniverseSort | undefined;
  onSort: (s: UniverseSort | undefined) => void;
  /** The active fund has fit scores, so "Best fit first" is offered. */
  hasFit: boolean;
}

/** Left side: search + filters, the dataset table (loads more rows as you scroll) and the source footer. */
export function DataTable({ rows, total, meta, loading, page, done, error, fitLabel, search, onSearch, filters, onFilter, options, onLoadMore, sort, onSort, hasFit }: DataTableProps) {
  const navigate = useNavigate();
  const scrollRef = useRef<HTMLDivElement>(null);
  const sentinelRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  // Next page when the bottom of the table scrolls into view.
  useEffect(() => {
    const el = sentinelRef.current;
    if (!el || done) return;
    const io = new IntersectionObserver((entries) => entries.some((e) => e.isIntersecting) && onLoadMore(), {
      root: scrollRef.current,
      rootMargin: "200px",
    });
    io.observe(el);
    return () => io.disconnect();
  }, [done, onLoadMore, rows.length]);

  const filtered = Boolean(search.trim() || filters.sector || filters.country || filters.stage || filters.founded);
  const refreshing = loading && page === 0 && rows.length > 0;
  const size = meta ? formatCount(meta.dataset_size) : null;

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      {/* Toolbar */}
      <div className="flex shrink-0 flex-wrap items-center gap-[8px] p-[14px_24px]">
        <label className="flex w-[240px] shrink-0 cursor-text items-center gap-[10px] rounded-[12px] bg-track p-[9px_12px] focus-within:outline-2 focus-within:outline-sage">
          <Search size={16} className="shrink-0 text-subtle" aria-hidden />
          <input
            ref={searchRef}
            type="search"
            value={search}
            onChange={(e) => onSearch(e.target.value)}
            onKeyDown={(e) => e.key === "Escape" && onSearch("")}
            placeholder={size ? `Search ${size} startups` : "Search startups"}
            aria-label="Search startups by name or what they do"
            className="h-[18px] min-w-0 flex-1 border-0 bg-transparent p-0 text-[14px] leading-[18px] tracking-[0.1px] text-ink outline-none placeholder:text-subtle [&::-webkit-search-cancel-button]:hidden"
          />
          {search && (
            <button
              type="button"
              aria-label="Clear search"
              onClick={() => {
                onSearch("");
                searchRef.current?.focus();
              }}
              className="-my-[2px] shrink-0 text-subtle hover:text-ink"
            >
              <X size={14} />
            </button>
          )}
        </label>
        <FilterMenu label="Sector" anyLabel="Any sector" options={options.sector} value={filters.sector} onChange={(v) => onFilter({ ...filters, sector: v })} />
        <FilterMenu label="Country" anyLabel="Any country" options={options.country} value={filters.country} onChange={(v) => onFilter({ ...filters, country: v })} />
        <FilterMenu label="Stage" anyLabel="Any stage" options={options.stage} value={filters.stage} onChange={(v) => onFilter({ ...filters, stage: v })} />
        <FilterMenu label="Founded" anyLabel="Any year" options={options.founded} value={filters.founded} onChange={(v) => onFilter({ ...filters, founded: v })} />
        <FilterMenu<UniverseSort>
          label="Sort"
          idleLabel={hasFit ? "Sort: best fit" : "Sort: dataset order"}
          anyLabel={hasFit ? "Best fit first" : "Dataset order"}
          options={["name", "founded", "funding"]}
          value={sort === "fit" ? undefined : sort}
          onChange={onSort}
          format={(v) => SORT_LABELS[v]}
        />
        <span className="ml-auto shrink-0 whitespace-nowrap text-[13px] tracking-[0.1px] text-muted" aria-live="polite">
          {total == null
            ? ""
            : filtered
              ? `${formatCount(total)} of ${size ?? formatCount(total)} companies match`
              : `${formatCount(total)} companies`}
        </span>
      </div>

      {/* Table */}
      <div ref={scrollRef} className="min-h-0 flex-1 overflow-auto px-[12px]">
        <div role="table" aria-label="Startups in the dataset" aria-busy={loading} className="min-w-[720px]">
          <div role="rowgroup" className="sticky top-0 z-10 bg-panel">
            <div role="row" className={cn(ROW, "h-[36px] border-t bg-row px-[12px]")}>
              <HeadCell i={0}>Row</HeadCell>
              <HeadCell i={1}>Company</HeadCell>
              <HeadCell i={2}>Sector</HeadCell>
              <HeadCell i={3}>Country</HeadCell>
              <HeadCell i={4}>Stage</HeadCell>
              <HeadCell i={5}>Founded</HeadCell>
              <HeadCell i={6}>Raised</HeadCell>
              <HeadCell i={7}>{fitLabel}</HeadCell>
            </div>
          </div>
          <div role="rowgroup" className={cn("transition-opacity duration-200", refreshing && "opacity-50 delay-200")}>
            {rows.length === 0 && loading && <SkeletonRows />}
            {rows.map(({ company: c, fit, funding_usd }, i) => {
              const delay = Math.min(i, 12) * 0.035;
              return (
                <motion.div
                  key={c.id}
                  role="row"
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.4, delay, ease: EASE }}
                  tabIndex={0}
                  aria-label={`Open ${c.name}`}
                  onClick={() => navigate(`/companies/${encodeURIComponent(c.id)}`)}
                  onKeyDown={(e) => e.key === "Enter" && navigate(`/companies/${encodeURIComponent(c.id)}`)}
                  className={cn(ROW, "h-[57px] cursor-pointer px-[12px] transition-colors hover:bg-surface focus-visible:bg-surface focus-visible:outline-none")}
                >
                  <div role="cell" className={cn(COLS[0], "shrink-0 font-mono text-[12px] tracking-[0.1px] text-subtle")}>
                    {formatRowId(c.row_id)}
                  </div>
                  <div role="cell" className={cn(COLS[1], "flex shrink-0 flex-col gap-[1px]")}>
                    <span className="truncate text-[14px] font-medium tracking-[0.1px] text-ink" title={c.name}>
                      {c.name}
                    </span>
                    <span className="truncate text-[12px] tracking-[0.1px] text-subtle" title={c.one_liner}>
                      {c.one_liner}
                    </span>
                  </div>
                  <TextCell i={2}>{c.sector}</TextCell>
                  <TextCell i={3}>{c.country ?? "–"}</TextCell>
                  <TextCell i={4}>{stageView(c).label}</TextCell>
                  <TextCell i={5} mono>
                    {c.founded ?? "—"}
                  </TextCell>
                  <TextCell i={6} mono>
                    {formatMoney(funding_usd)}
                  </TextCell>
                  <FitCell fit={fit} delay={delay} />
                </motion.div>
              );
            })}
            {!loading && !error && rows.length === 0 && (
              <div className="flex flex-col items-start gap-[4px] p-[20px_12px]">
                <span className="text-[14px] font-medium text-ink">No startups match</span>
                <span className="text-[13px] text-muted">Try a different search or clear a filter.</span>
              </div>
            )}
            {error && (
              <div className="flex flex-col items-start gap-[4px] p-[20px_12px]" role="alert">
                <span className="text-[14px] font-medium text-ink">Couldn’t load the dataset</span>
                <span className="text-[13px] text-muted">{error.message}</span>
              </div>
            )}
          </div>
          {!done && rows.length > 0 && <div ref={sentinelRef} className="h-px" aria-hidden />}
          {loading && page > 0 && <div className="p-[12px] text-[12px] text-subtle">Loading more…</div>}
        </div>
      </div>

      {/* Footer */}
      <div className="flex shrink-0 items-center justify-between gap-[16px] border-t border-hair p-[12px_24px] text-[12px] tracking-[0.1px] text-subtle">
        <div className="flex min-w-0 items-center gap-[6px]">
          <FileSpreadsheet size={13} className="shrink-0" aria-hidden />
          <span className="truncate">
            Source: data/companies.csv{size ? ` · ${size} rows` : ""} · every memo claim links back to a row ID
          </span>
        </div>
        <span className="shrink-0 whitespace-nowrap" aria-live="polite">
          {total == null ? "" : `Showing ${formatCount(rows.length)} of ${formatCount(total)}${filtered ? " matches" : ""}`}
        </span>
      </div>
    </div>
  );
}
