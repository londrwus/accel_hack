import { useCallback, useEffect, useRef, useState } from "react";
import { getUniverse, type UniverseQuery } from "@/lib/api";
import type { UniverseResponse, UniverseRow } from "@/lib/types";

/** Rows per request. The mock always returns its 8 sample rows. */
export const PAGE_SIZE = 50;

export type UniverseFilters = Pick<UniverseQuery, "q" | "sector" | "country" | "stage" | "founded" | "fund_id" | "sort">;

export interface DatasetMeta {
  dataset_size: number;
  sectors: number;
  countries: number;
}

export interface FilterOptions {
  sector: string[];
  country: string[];
  stage: string[];
  founded: number[];
}

interface State {
  rows: UniverseRow[];
  total: number | null;
  page: number;
  done: boolean;
  loading: boolean;
  error: Error | null;
}

const EMPTY: State = { rows: [], total: null, page: 0, done: false, loading: true, error: null };

function addAll<T>(into: Set<T>, values: (T | null | undefined)[]) {
  let changed = false;
  for (const v of values) {
    if (v != null && v !== "" && !into.has(v)) {
      into.add(v);
      changed = true;
    }
  }
  return changed;
}

/** Paged rows of GET /api/universe. Resets when the filters change; `loadMore()` fetches the next page. */
export function useUniverseRows(filters: UniverseFilters) {
  const [state, setState] = useState<State>(EMPTY);
  const [meta, setMeta] = useState<DatasetMeta | null>(null);
  const [options, setOptions] = useState<FilterOptions>({ sector: [], country: [], stage: [], founded: [] });
  const seen = useRef({ sector: new Set<string>(), country: new Set<string>(), stage: new Set<string>(), founded: new Set<number>() });
  const reqId = useRef(0);
  const busy = useRef(false);
  const key = JSON.stringify(filters);

  const absorb = useCallback((res: UniverseResponse) => {
    setMeta({ dataset_size: res.dataset_size, sectors: res.sectors, countries: res.countries });
    // The live backend sends every value in the dataset; use that rather than what we have seen so far.
    if (res.options) {
      setOptions((cur) =>
        cur.sector.length === res.options!.sector.length && cur.country.length === res.options!.country.length
          ? cur
          : { ...res.options! },
      );
      return;
    }
    // Filter choices grow with every row we have seen (the API has no "distinct values" endpoint).
    const s = seen.current;
    const cs = res.items.map((r) => r.company);
    const changed = [
      addAll(s.sector, cs.map((c) => c.sector)),
      addAll(s.country, cs.map((c) => c.country)),
      addAll(s.stage, cs.map((c) => c.stage)),
      addAll(s.founded, cs.map((c) => c.founded)),
    ].some(Boolean);
    if (changed) {
      setOptions({
        sector: [...s.sector].sort(),
        country: [...s.country].sort(),
        stage: [...s.stage].sort(),
        founded: [...s.founded].sort((a, b) => b - a),
      });
    }
  }, []);

  const fetchPage = useCallback(
    (page: number, prev: UniverseRow[]) => {
      const id = ++reqId.current;
      busy.current = true;
      setState((st) => ({ ...st, loading: true, error: null }));
      getUniverse({ ...(JSON.parse(key) as UniverseFilters), page, page_size: PAGE_SIZE }).then(
        (res) => {
          if (id !== reqId.current) return;
          busy.current = false;
          absorb(res);
          const known = new Set(prev.map((r) => r.company.id));
          const fresh = res.items.filter((r) => !known.has(r.company.id));
          const rows = [...prev, ...fresh];
          setState({
            rows,
            total: res.total,
            page,
            // Stop when a page comes back short, adds nothing new, or we have everything.
            done: res.items.length < PAGE_SIZE || fresh.length === 0 || rows.length >= res.total,
            loading: false,
            error: null,
          });
        },
        (error: Error) => {
          if (id !== reqId.current) return;
          busy.current = false;
          setState((st) => ({ ...st, loading: false, error }));
        },
      );
    },
    [key, absorb],
  );

  useEffect(() => {
    // Keep the old rows on screen (dimmed) until the new first page arrives.
    setState((st) => ({ ...st, page: 0, done: false, loading: true, error: null }));
    fetchPage(1, []);
  }, [fetchPage]);

  const latest = useRef(state);
  latest.current = state;
  const loadMore = useCallback(() => {
    const st = latest.current;
    if (!busy.current && !st.done && !st.error && st.page > 0) fetchPage(st.page + 1, st.rows);
  }, [fetchPage]);

  return { ...state, meta, options, loadMore };
}
