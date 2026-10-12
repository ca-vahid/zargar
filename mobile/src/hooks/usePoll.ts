import { useIsFocused } from 'expo-router';
import { useCallback, useEffect, useRef, useState } from 'react';
import { AppState } from 'react-native';

export interface Polled<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  /** true only while a pull-to-refresh the person started is in flight */
  refreshing: boolean;
  refresh: () => void;
}

/** Fetch when the screen is shown, again every `everyMs` while it stays on screen and
 *  the app is in the foreground, and whenever a value in `deps` changes. A failed
 *  refresh keeps the last good data on screen and reports the error beside it. */
export function usePoll<T>(fetcher: () => Promise<T>, everyMs: number, deps: unknown[] = []): Polled<T> {
  const focused = useIsFocused();
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const fn = useRef(fetcher);
  fn.current = fetcher;
  const seq = useRef(0);

  const run = useCallback(async (byHand: boolean) => {
    const mine = ++seq.current;
    if (byHand) setRefreshing(true);
    try {
      const res = await fn.current();
      if (mine !== seq.current) return; // a newer request superseded this one
      setData(res);
      setError(null);
    } catch (e: any) {
      if (mine !== seq.current) return;
      setError(e?.message ? String(e.message) : 'Something went wrong');
    } finally {
      if (mine === seq.current) {
        setLoading(false);
        setRefreshing(false);
      }
    }
  }, []);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  const key = JSON.stringify(deps);
  useEffect(() => {
    if (!focused) return;
    void run(false);
    if (!everyMs) return;
    const timer = setInterval(() => {
      if (AppState.currentState === 'active') void run(false);
    }, everyMs);
    const sub = AppState.addEventListener('change', (s) => { if (s === 'active') void run(false); });
    return () => { clearInterval(timer); sub.remove(); };
  }, [focused, everyMs, key, run]);

  // a different question (another book, another range): drop the old answer
  useEffect(() => { setData(null); setLoading(true); }, [key]);

  return { data, error, loading, refreshing, refresh: useCallback(() => { void run(true); }, [run]) };
}
