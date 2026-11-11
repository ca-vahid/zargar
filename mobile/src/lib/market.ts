// The US stock market's clock, in plain words. Pure: the caller supplies the time.

export type MarketState = 'open' | 'pre' | 'post' | 'closed';
export interface MarketClock { state: MarketState; title: string; detail: string }

const OPEN = 9 * 60 + 30;
const CLOSE = 16 * 60;
const PRE = 4 * 60;
const POST = 20 * 60;

/** Weekday (0 = Sunday) and minutes past midnight in New York, or null when the
 *  device cannot convert time zones. */
export function newYorkTime(now: number): { weekday: number; minutes: number } | null {
  try {
    const parts = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', weekday: 'short', hour: 'numeric', minute: 'numeric', hour12: false })
      .formatToParts(new Date(now));
    const get = (type: string) => parts.find((p) => p.type === type)?.value ?? '';
    const weekday = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].indexOf(get('weekday'));
    const hour = Number(get('hour')) % 24;
    const minute = Number(get('minute'));
    if (weekday < 0 || !Number.isFinite(hour) || !Number.isFinite(minute)) return null;
    return { weekday, minutes: hour * 60 + minute };
  } catch {
    return null;
  }
}

export function span(minutes: number): string {
  const m = Math.max(1, Math.round(minutes));
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  return m % 60 ? `${h} h ${m % 60} min` : `${h} h`;
}

/** Where the regular session stands. `feedSession` is what the price feed reports for
 *  a US index fund; it wins over the clock on a holiday, which the clock cannot know. */
export function marketClock(at: { weekday: number; minutes: number } | null, feedSession?: string | null): MarketClock {
  if (!at) return { state: 'closed', title: 'Market hours unknown', detail: '' };
  const { weekday, minutes } = at;
  const weekdayOpen = weekday >= 1 && weekday <= 5;
  // the next session after today's close: Friday evening and the weekend wait for Monday
  const next = weekday === 5 || weekday === 6 || weekday === 0 ? 'Monday' : 'tomorrow';
  if (weekdayOpen && minutes >= OPEN && minutes < CLOSE) {
    if (feedSession === 'closed') return { state: 'closed', title: 'Market closed', detail: 'No session today' };
    return { state: 'open', title: 'Market open', detail: `closes in ${span(CLOSE - minutes)}` };
  }
  if (weekdayOpen && minutes >= PRE && minutes < OPEN) {
    return { state: 'pre', title: 'Pre-market', detail: `opens in ${span(OPEN - minutes)}` };
  }
  if (weekdayOpen && minutes >= CLOSE && minutes < POST) {
    return { state: 'post', title: 'After hours', detail: `opens ${next} 9:30 ET` };
  }
  if (weekdayOpen && minutes < PRE) return { state: 'closed', title: 'Market closed', detail: `opens in ${span(OPEN - minutes)}` };
  return { state: 'closed', title: 'Market closed', detail: `opens ${next} 9:30 ET` };
}
