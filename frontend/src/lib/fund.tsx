import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import type { FundResponse, FundSummary } from "./types";
import { ApiError, getFund, listFunds, MOCK_DEFAULT_FUND, USE_MOCKS } from "./api";

/** The recorded demo fund, used until the person picks another one. */
export const DEMO_FUND_ID = "localglobe";
const STORAGE_KEY = "bellwether.fund";

function readStored(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

function writeStored(id: string) {
  try {
    window.localStorage.setItem(STORAGE_KEY, id);
  } catch {
    /* storage blocked: the URL still carries ?fund= */
  }
}

function initialFundId(): string {
  try {
    const fromUrl = new URLSearchParams(window.location.search).get("fund");
    if (fromUrl) return fromUrl;
  } catch {
    /* no window.location */
  }
  return readStored() || (USE_MOCKS ? MOCK_DEFAULT_FUND : DEMO_FUND_ID);
}

interface FundState {
  /** The fund picked in the sidebar (?fund=, then localStorage, then the demo fund). */
  activeId: string;
  setActive: (id: string) => void;
  data: FundResponse | null;
  /** True until GET /api/fund answers (or fails) for the active fund. */
  loading: boolean;
  /** Every fund you can switch to (GET /api/funds). */
  funds: FundSummary[];
  /** GET /api/funds has answered (or failed) at least once. */
  fundsLoaded: boolean;
  /** Re-fetch GET /api/fund and GET /api/funds without clearing what is on screen. */
  refresh: () => void;
}

const FundContext = createContext<FundState>({
  activeId: DEMO_FUND_ID,
  setActive: () => undefined,
  data: null,
  loading: true,
  funds: [],
  fundsLoaded: false,
  refresh: () => undefined,
});

/** Loads GET /api/fund for the active fund and GET /api/funds for the switcher. Must sit inside the router:
 *  it keeps `?fund=<id>` on the URL so links and reloads keep the fund. */
export function FundProvider({ children }: { children: ReactNode }) {
  const location = useLocation();
  const navigate = useNavigate();
  const [activeId, setActiveId] = useState<string>(initialFundId);
  const [data, setData] = useState<FundResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [funds, setFunds] = useState<FundSummary[]>([]);
  const [fundsLoaded, setFundsLoaded] = useState(false);
  const [version, setVersion] = useState(0);

  // URL -> state (back/forward, a pasted link, a page that navigates with ?fund=).
  const urlFund = new URLSearchParams(location.search).get("fund");
  useEffect(() => {
    if (urlFund && urlFund !== activeId) {
      setActiveId(urlFund);
      writeStored(urlFund);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [urlFund]);

  // State -> URL: sidebar links drop the query, so put ?fund= back (replace, no extra history entry).
  useEffect(() => {
    if (urlFund) return;
    const next = new URLSearchParams(location.search);
    next.set("fund", activeId);
    navigate({ pathname: location.pathname, search: `?${next.toString()}`, hash: location.hash }, { replace: true });
  }, [urlFund, activeId, location.pathname, location.search, location.hash, navigate]);

  const setActive = useCallback(
    (id: string) => {
      setActiveId(id);
      writeStored(id);
      const next = new URLSearchParams(location.search);
      next.set("fund", id);
      // Per-fund URL state (open row, a run, a backtest pick) does not carry over to another fund.
      for (const k of ["open", "run", "backtest"]) next.delete(k);
      navigate({ pathname: location.pathname, search: `?${next.toString()}` }, { replace: false });
    },
    [location.pathname, location.search, navigate],
  );

  useEffect(() => {
    let alive = true;
    setLoading(true);
    // A failed refresh keeps the last good answer on screen.
    getFund(activeId)
      .then(
        (res) => alive && setData(res),
        (err: Error) => console.warn("[fund] could not load the fund", err),
      )
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [activeId, version]);

  useEffect(() => {
    let alive = true;
    listFunds().then(
      (res) => alive && setFunds(res.items),
      (err: Error) => console.warn("[fund] could not list funds", err),
    ).finally(() => alive && setFundsLoaded(true));
    return () => {
      alive = false;
    };
  }, [version, activeId]);

  const refresh = useCallback(() => setVersion((v) => v + 1), []);
  const value = useMemo(
    () => ({ activeId, setActive, data, loading, funds, fundsLoaded, refresh }),
    [activeId, setActive, data, loading, funds, fundsLoaded, refresh],
  );
  return <FundContext.Provider value={value}>{children}</FundContext.Provider>;
}

/** The current fund (sidebar data, fund name for copy). null while loading. */
export function useFund(): FundResponse | null {
  return useContext(FundContext).data;
}

/** The id of the fund picked in the sidebar. Use this for API calls (it is known before GET /api/fund answers). */
export function useActiveFundId(): string {
  return useContext(FundContext).activeId;
}

/** Switch the active fund (URL + localStorage). */
export function useSetActiveFund(): (id: string) => void {
  return useContext(FundContext).setActive;
}

/** Every fund the sidebar can switch to. */
export function useFunds(): FundSummary[] {
  return useContext(FundContext).funds;
}

/** The active fund's row in GET /api/funds, if listed. */
export function useActiveFundSummary(): FundSummary | null {
  const { funds, activeId } = useContext(FundContext);
  return funds.find((f) => f.id === activeId) ?? null;
}

/** True until the fund has loaded. */
export function useFundLoading(): boolean {
  return useContext(FundContext).loading;
}

/** Reload GET /api/fund and GET /api/funds. */
export function useFundRefresh(): () => void {
  return useContext(FundContext).refresh;
}

/** "wait" until GET /api/funds has answered (non-demo funds), "empty" when the active fund has no results yet
 *  (pages then show the empty state without a request), else "ok". */
export type FundGate = "wait" | "empty" | "ok";
export function useFundGate(): FundGate {
  const { fundsLoaded, activeId } = useContext(FundContext);
  const s = useActiveFundSummary();
  if (activeId === DEMO_FUND_ID) return "ok";
  if (!fundsLoaded) return "wait";
  // has_results can be stale (the list was loaded before the run finished): a fund with any run is asked anyway,
  // and the page's own 404 handling shows the empty state if there really is nothing yet.
  return s && !s.has_results && !s.latest_run_id ? "empty" : "ok";
}

/** Run `fetch` only when the gate is "ok"; "empty" rejects with a 404 ApiError, "wait" stays pending. */
export function gated<T>(gate: FundGate, fetch: () => Promise<T>): Promise<T> {
  if (gate === "ok") return fetch();
  if (gate === "empty") return noResultsYet<T>();
  return new Promise<T>(() => undefined);
}

/** What a page endpoint answers for a fund with no results, without a network round trip. */
export function noResultsYet<T>(): Promise<T> {
  return Promise.reject(new ApiError(404, "Nothing for this fund yet. Start a run to fill this page."));
}
