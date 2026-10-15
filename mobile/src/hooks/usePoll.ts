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

// The last answer to each named question. A screen that has shown something once
// shows it again at once and refreshes underneath, instead of going blank and
// spinning every time a book, a range or a tab changes.
const cache = new Map<string, unknown>();
const remember = (key: string, value: unknown) => {
  if (cache.size > 300) cache.clear();
  cache.set(key, value);
};
export const clearPollCache = () => cache.clear();

/** Fetch when the screen is shown, again every `everyMs` while it stays on screen and
 *  the app is in the foreground, and whenever a value in `deps` changes. A failed
 *  refresh keeps the last good data on screen and reports the error beside it.
 *  `cacheKey` names the question: its last answer is shown while the new one loads. */
export function usePoll<T>(fetcher: () => Promise<T>, everyMs: number, deps: unknown[] = [], cacheKey?: string): Polled<T> {
  const focused = useIsFocused();
  const [data, setData] = useState<T | null>(() => (cacheKey ? (cache.get(cacheKey) as T | undefined) ?? null : null));
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(data == null);
  const [refreshing, setRefreshing] = useState(false);
  const fn = useRef(fetcher);
  fn.current = fetcher;
  const named = useRef(cacheKey);
  named.current = cacheKey;
  const seq = useRef(0);

  const run = useCallback(async (byHand: boolean) => {
    const mine = ++seq.current;
    const name = named.current;
    if (byHand) setRefreshing(true);
    try {
      const res = await fn.current();
      if (name) remember(name, res); // still the right answer to ITS question
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

  // a different question (another book, another range): show its last answer if there
  // is one, otherwise drop the old answer rather than show it under the wrong name
  const first = useRef(true);
  useEffect(() => {
    if (first.current) { first.current = false; return; }
    const known = cacheKey ? (cache.get(cacheKey) as T | undefined) ?? null : null;
    setData(known);
    setError(null);
    setLoading(known == null);
  }, [key, cacheKey]);

  return { data, error, loading, refreshing, refresh: useCallback(() => { void run(true); }, [run]) };
}
