import type { Portfolio } from '../api/types';

export type BookGroup = 'real' | 'paper' | 'practice' | 'research';

/** What the screens show: Live = real venues (real accounts and the broker's paper
 *  account); Practice = the app's own simulator and its research books. The same split
 *  as the web app (frontend/src/lib/workspace.ts) — it is a VIEW and routes nothing. */
export type Workspace = 'live' | 'practice';
export function workspaceOf(kind: string | null | undefined): Workspace {
  return kind === 'live' || kind === 'paper' ? 'live' : 'practice';
}

/** Real money, the broker's paper account, our own simulated books, and the
 *  per-source research books — never summed across groups. */
export function groupOf(p: Pick<Portfolio, 'kind'>): BookGroup {
  if (p.kind === 'live') return 'real';
  if (p.kind === 'paper') return 'paper';
  if (p.kind === 'shadow') return 'research';
  return 'practice';
}

export const GROUP_LABEL: Record<BookGroup, string> = {
  real: 'Real money',
  paper: 'Paper',
  practice: 'Practice',
  research: 'Research',
};

const ORDER: BookGroup[] = ['real', 'paper', 'practice', 'research'];

/** An account the broker lists but that holds nothing: no cash, no value. */
const isEmpty = (p: Portfolio) => Math.abs(p.equity ?? 0) < 0.005 && Math.abs(p.cash ?? 0) < 0.005;

/** The books of one workspace a person follows day to day: nothing archived, nothing
 *  empty, research books only when asked for (then last). */
export function visibleBooks(all: Portfolio[], workspace: Workspace, includeResearch = false): Portfolio[] {
  return all
    .filter((p) => workspaceOf(p.kind) === workspace && !p.archived && !isEmpty(p) && (includeResearch || p.kind !== 'shadow'))
    .sort((a, b) => ORDER.indexOf(groupOf(a)) - ORDER.indexOf(groupOf(b)) || a.name.localeCompare(b.name));
}

/** Today's move in the book's own currency: live equity against the server's
 *  day-start anchor (the previous session's close). Null when either is unknown. */
export function dayMove(p: Pick<Portfolio, 'equity' | 'dayStart'>): number | null {
  if (p.equity == null || p.dayStart == null) return null;
  return p.equity - p.dayStart;
}

export function dayMovePct(p: Pick<Portfolio, 'equity' | 'dayStart'>): number | null {
  const m = dayMove(p);
  if (m == null || !p.dayStart) return null;
  return (m / p.dayStart) * 100;
}
