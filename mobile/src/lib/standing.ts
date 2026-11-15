// Standing orders: the person's own order plans (drafted on the desk, armed by the person,
// executed by the server). Pure helpers — the screen and the home card share them.

export interface StandingAttempt { n: number; qty: number; limit: number; status?: string }
export interface StandingOrder {
  id: string; planId: string | null; planName: string | null; planArmConfirm: string | null;
  portfolioId: string; symbol: string; side: 'BUY' | 'SELL'; qty: number | null; budget: number | null;
  trigger: string; notBefore: string | null; expiresOn: string; maxPrice: number | null; minPrice: number | null;
  slippagePct: number; takeProfitPct: number | null; stopLossPct: number | null; status: string;
  note: string | null; lastError: string | null; filledQty: number; avgFillPrice: number | null;
  attempts: StandingAttempt[]; armConfirm: string; positionId: string | null;
}
export interface StandingList { orders: StandingOrder[]; allowLive: boolean }
export interface StandingPreflight {
  ok: boolean; why?: string; reason?: string; limit?: number; qty?: number; notional?: number;
  failedChecks?: { name: string; detail: string }[];
}
export interface StandingPlan { key: string; rows: StandingOrder[]; status: string }

const OPEN = new Set(['draft', 'armed', 'placing', 'working']);
const RUNNING = new Set(['placing', 'working']);
export const isOpen = (status: string) => OPEN.has(status);
export const isRunning = (status: string) => RUNNING.has(status);

export const STATUS_LABEL: Record<string, string> = {
  draft: 'Draft', armed: 'Armed', placing: 'Sending', working: 'Working', done: 'Filled', failed: 'Failed',
  cancelled: 'Cancelled', expired: 'Expired',
};
export type StatusTone = 'dim' | 'warn' | 'ok' | 'bad';
export const statusTone = (status: string): StatusTone =>
  (status === 'done' ? 'ok' : status === 'failed' ? 'bad' : status === 'armed' || RUNNING.has(status) ? 'warn' : 'dim');

/** One word for a whole plan: the most urgent state any of its orders is in. */
export function planStatus(rows: Pick<StandingOrder, 'status'>[]): string {
  if (rows.some((r) => RUNNING.has(r.status))) return 'working';
  if (rows.some((r) => r.status === 'armed')) return 'armed';
  if (rows.some((r) => r.status === 'draft')) return 'draft';
  if (rows.some((r) => r.status === 'failed')) return 'failed';
  if (rows.every((r) => r.status === 'done')) return 'done';
  return rows.every((r) => r.status === 'cancelled') ? 'cancelled' : 'expired';
}

/** Orders grouped into their plans (a lone order is its own plan), each in firing order. */
export function groupPlans(orders: StandingOrder[]): { open: StandingPlan[]; closed: StandingPlan[] } {
  const by = new Map<string, StandingOrder[]>();
  for (const o of orders) {
    const key = o.planId ?? `single:${o.id}`;
    by.set(key, [...(by.get(key) ?? []), o]);
  }
  const all = [...by.entries()].map(([key, rows]) => ({
    key, rows: [...rows].sort((a, b) => (a.notBefore ?? '').localeCompare(b.notBefore ?? '')), status: planStatus(rows),
  }));
  return { open: all.filter((p) => p.rows.some((r) => OPEN.has(r.status))), closed: all.filter((p) => !p.rows.some((r) => OPEN.has(r.status))) };
}

const amount = (v: number) => v.toLocaleString('en-US', { maximumFractionDigits: 2 });
const share = (n: number) => `${amount(n)} share${n === 1 ? '' : 's'}`;

export const sizeText = (o: Pick<StandingOrder, 'qty' | 'budget'>) =>
  (o.qty ? share(o.qty) : `up to $${amount(o.budget ?? 0)}`);
export const whenText = (o: Pick<StandingOrder, 'trigger' | 'notBefore'>) =>
  (o.trigger === 'listing' ? 'When it starts trading' : o.trigger === 'at' ? `From ${o.notBefore} ET` : 'At the next open');
/** A Canadian listing (.TO, .V, .NE, .CN) is priced in Canadian dollars. */
export const priceSign = (symbol: string) => (/\.(TO|V|NE|CN)$/i.test(symbol) ? 'C$' : '$');
export const guardText = (o: Pick<StandingOrder, 'side' | 'maxPrice' | 'minPrice' | 'symbol'>) => (o.side === 'BUY'
  ? (o.maxPrice ? `Pay at most ${priceSign(o.symbol)}${o.maxPrice.toFixed(2)}` : 'No price cap')
  : (o.minPrice ? `Sell at ${priceSign(o.symbol)}${o.minPrice.toFixed(2)} or better` : 'No price floor'));
export const exitsText = (o: Pick<StandingOrder, 'takeProfitPct' | 'stopLossPct'>) =>
  [o.takeProfitPct ? `take profit +${o.takeProfitPct}%` : '', o.stopLossPct ? `stop −${o.stopLossPct}%` : ''].filter(Boolean).join(' · ');
export const orderLine = (o: StandingOrder) => `${o.side === 'BUY' ? 'Buy' : 'Sell'} ${sizeText(o)} of ${o.symbol}`;

export function preflightText(p: StandingPreflight): string {
  if (p.ok) return `Would send ${p.qty ?? '?'} at ${p.limit ?? '?'}${p.notional != null ? ` (${amount(p.notional)} in all)` : ''}`;
  return p.why || p.reason || (p.failedChecks ?? []).map((c) => c.detail || c.name).join('; ') || 'The checks did not pass';
}

const OPEN_MIN = 9 * 60 + 30;
const CLOSE_MIN = 16 * 60;

/** Minutes until an armed order's trigger can next fire (0 = its window is open now),
 *  from the New York weekday and minute of the day. Null when it has no clock trigger
 *  or the time is unknown. Weekends are skipped; exchange holidays are not known here. */
export function minutesToTrigger(
  o: Pick<StandingOrder, 'trigger' | 'notBefore'>, at: { weekday: number; minutes: number } | null,
): number | null {
  if (!at || o.trigger === 'listing') return null;
  let target = OPEN_MIN;
  if (o.trigger === 'at') {
    const m = /^(\d{1,2}):(\d{2})$/.exec(o.notBefore ?? '');
    if (!m) return null;
    target = Math.max(OPEN_MIN, Number(m[1]) * 60 + Number(m[2]));
  }
  const weekdayOpen = at.weekday >= 1 && at.weekday <= 5;
  if (weekdayOpen && at.minutes < CLOSE_MIN) return Math.max(0, target - at.minutes);
  let days = 1;
  while ([0, 6].includes((at.weekday + days) % 7)) days += 1;
  return days * 1440 + target - at.minutes;
}

export function waitText(minutes: number): string {
  if (minutes <= 0) return 'window open now';
  const d = Math.floor(minutes / 1440);
  const h = Math.floor((minutes % 1440) / 60);
  const m = Math.round(minutes % 60);
  if (d > 0) return `in ${d} d ${h} h`;
  if (h > 0) return m ? `in ${h} h ${m} min` : `in ${h} h`;
  return `in ${Math.max(1, m)} min`;
}

/** The numbers the home card and the screen's summary show. */
export function standingCounts(orders: StandingOrder[]) {
  const open = orders.filter((o) => OPEN.has(o.status));
  return {
    draft: open.filter((o) => o.status === 'draft').length,
    armed: open.filter((o) => o.status === 'armed').length,
    working: open.filter((o) => RUNNING.has(o.status)).length,
    // an armed order that says why it is waiting is normal; a failed one needs a look
    failed: orders.filter((o) => o.status === 'failed').length,
    open: open.length,
  };
}
