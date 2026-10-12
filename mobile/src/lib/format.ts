// Number and time formatting. Pure functions: every screen shows money the same way.

const CURRENCY_SIGN: Record<string, string> = { USD: '$', CAD: 'C$' };

function group(n: number, digits: number): string {
  const [int, frac] = Math.abs(n).toFixed(digits).split('.');
  const withCommas = int.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  return frac ? `${withCommas}.${frac}` : withCommas;
}

export function money(v: number | null | undefined, currency = 'USD', digits = 2): string {
  if (v == null || !Number.isFinite(v)) return '—';
  const sign = CURRENCY_SIGN[currency?.toUpperCase?.() ?? 'USD'] ?? '$';
  return `${v < 0 ? '−' : ''}${sign}${group(v, digits)}`;
}

/** A gain or loss: always carries its sign. */
export function signedMoney(v: number | null | undefined, currency = 'USD', digits = 2): string {
  if (v == null || !Number.isFinite(v)) return '—';
  const sign = CURRENCY_SIGN[currency?.toUpperCase?.() ?? 'USD'] ?? '$';
  return `${v > 0 ? '+' : v < 0 ? '−' : ''}${sign}${group(v, digits)}`;
}

export function pct(v: number | null | undefined, digits = 2): string {
  if (v == null || !Number.isFinite(v)) return '—';
  return `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toFixed(digits)}%`;
}

export function price(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return '—';
  return group(v, Math.abs(v) < 1 ? 4 : 2).replace(/^/, v < 0 ? '−' : '');
}

export function qty(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return '—';
  return Number.isInteger(v) ? group(v, 0) : group(v, 2);
}

/** +1 for a gain, −1 for a loss, 0 for flat or unknown — picks the colour. */
export function tone(v: number | null | undefined): 1 | 0 | -1 {
  if (v == null || !Number.isFinite(v) || Math.abs(v) < 0.005) return 0;
  return v > 0 ? 1 : -1;
}

type Stamp = string | number | null | undefined;
function toDate(ts: Stamp): Date | null {
  if (ts == null || ts === '') return null;
  // the server sends epoch seconds, epoch milliseconds and ISO strings in different places
  const d = typeof ts === 'number' ? new Date(ts < 1e12 ? ts * 1000 : ts) : new Date(ts);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function ago(ts: Stamp, now = Date.now()): string {
  const d = toDate(ts);
  if (!d) return '';
  const s = Math.max(0, Math.round((now - d.getTime()) / 1000));
  if (s < 60) return 'just now';
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return `${Math.floor(s / 86400)} d ago`;
}

const pad = (n: number) => String(n).padStart(2, '0');
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

export function clock(ts: Stamp): string {
  const d = toDate(ts);
  return d ? `${pad(d.getHours())}:${pad(d.getMinutes())}` : '';
}

export function dayTime(ts: Stamp, now = new Date()): string {
  const d = toDate(ts);
  if (!d) return '';
  const sameDay = d.toDateString() === now.toDateString();
  return sameDay ? clock(d.getTime()) : `${MONTHS[d.getMonth()]} ${d.getDate()}, ${clock(d.getTime())}`;
}

export function shortDate(ts: Stamp): string {
  const d = toDate(ts);
  return d ? `${MONTHS[d.getMonth()]} ${d.getDate()}` : '';
}

/** "in 42 min" / "expired" for an approval card's deadline. */
export function until(ts: Stamp, now = Date.now()): string {
  const d = toDate(ts);
  if (!d) return '';
  const s = Math.round((d.getTime() - now) / 1000);
  if (s <= 0) return 'expired';
  if (s < 3600) return `${Math.max(1, Math.floor(s / 60))} min left`;
  return `${Math.floor(s / 3600)} h ${Math.floor((s % 3600) / 60)} min left`;
}

export function titleCase(s: string | null | undefined): string {
  if (!s) return '';
  return s.replace(/[_-]+/g, ' ').replace(/^\w/, (c) => c.toUpperCase());
}

/** Discord source names carry decorations ("🌟｜jon-and-kian"); show the name. */
export function sourceLabel(s: string | null | undefined): string {
  if (!s) return '';
  const cut = s.split(/[｜|]/).pop() ?? s;
  return cut.trim() || s;
}
