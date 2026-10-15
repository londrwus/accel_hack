import { useEffect, useRef, useState, type DependencyList } from "react";

export interface ApiState<T> {
  data: T | null;
  error: Error | null;
  loading: boolean;
}

// Last good answer per (fetcher, deps): a revisited page shows it at once and refreshes in the background.
const lastData = new Map<string, unknown>();

function keyOf(fetcher: () => unknown, deps: DependencyList): string | null {
  try {
    return `${fetcher.toString()}|${JSON.stringify(deps)}`;
  } catch {
    return null;
  }
}

/** Run an api.ts fetcher on mount (and when deps change). Ignores stale responses. Stale-while-revalidate:
 *  cached data shows instantly (loading stays false) while a fresh copy loads.
 *  const { data, error, loading } = useApi(() => getDeals({ status }), [status]); */
export function useApi<T>(fetcher: () => Promise<T>, deps: DependencyList = []): ApiState<T> {
  const key = keyOf(fetcher, deps);
  const [state, setState] = useState<ApiState<T>>(() => {
    const cached = key !== null ? (lastData.get(key) as T | undefined) : undefined;
    return cached !== undefined ? { data: cached, error: null, loading: false } : { data: null, error: null, loading: true };
  });
  const first = useRef(true);
  useEffect(() => {
    let alive = true;
    const cached = key !== null ? (lastData.get(key) as T | undefined) : undefined;
    if (cached !== undefined) {
      if (!first.current) setState({ data: cached, error: null, loading: false });
    } else {
      setState((s) => ({ ...s, loading: true, error: null }));
    }
    first.current = false;
    fetcher().then(
      (data) => {
        if (key !== null) lastData.set(key, data);
        if (alive) setState({ data, error: null, loading: false });
      },
      (error: Error) => {
        if (key !== null) lastData.delete(key);
        if (alive) setState({ data: null, error, loading: false });
      },
    );
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return state;
}
