import { useEffect, useMemo } from 'react';

import { api } from '../api/endpoints';
import { workspaceOf } from '../lib/books';
import { newYorkDate } from '../lib/market';
import { isOpen, standingCounts, withStale } from '../lib/standing';
import { useStore } from '../store';
import { usePoll } from './usePoll';
import { useWorkspace } from './useWorkspace';

/** The person's standing orders for the workspace on screen: an order belongs to the
 *  workspace of the account it trades in, exactly like a tip card. `elsewhere` counts the
 *  open orders of the other workspace, so a screen can say where they are. */
export function useStanding(everyMs = 30000) {
  const ws = useWorkspace();
  const portfolios = useStore((s) => s.portfolios);
  const list = usePoll(() => api.standing(), everyMs, [], 'standing');
  const raw = list.data?.orders ?? null;
  const all = useMemo(() => (raw ? withStale(raw, newYorkDate(Date.now())) : null), [raw]);
  const orders = useMemo(
    () => (all ? all.filter((o) => workspaceOf(portfolios.find((b) => b.id === o.portfolioId)?.kind) === ws) : null),
    [all, portfolios, ws]);
  const counts = useMemo(() => standingCounts(orders ?? []), [orders]);
  const elsewhere = all ? all.filter((o) => isOpen(o.status)).length - counts.open : 0;
  const badge = counts.draft + counts.failed;
  useEffect(() => { if (orders) useStore.getState().set({ standingBadge: badge }); }, [orders, badge]);
  return { list, orders, counts, elsewhere, allowLive: !!list.data?.allowLive, delegations: list.data?.delegations ?? [], ws };
}
