import { useEffect, useState, type DependencyList } from "react";

export interface ApiState<T> {
  data: T | null;
  error: Error | null;
  loading: boolean;
}

/** Run an api.ts fetcher on mount (and when deps change). Ignores stale responses.
 *  const { data, error, loading } = useApi(() => getDeals({ status }), [status]); */
export function useApi<T>(fetcher: () => Promise<T>, deps: DependencyList = []): ApiState<T> {
  const [state, setState] = useState<ApiState<T>>({ data: null, error: null, loading: true });
  useEffect(() => {
    let alive = true;
    setState((s) => ({ ...s, loading: true, error: null }));
    fetcher().then(
      (data) => alive && setState({ data, error: null, loading: false }),
      (error: Error) => alive && setState({ data: null, error, loading: false }),
    );
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return state;
}
