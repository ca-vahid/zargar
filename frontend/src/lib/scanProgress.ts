/** Pure bookkeeping for the EM scan / analyst-check panel's polling (2026-09-16).
 *
 *  The panel once sat at "73/114 · 0 working · 0 queued · ~2.1 h left" for hours on a batch the server had long
 *  finished, while hammering the engine: its list window was pushed out by another technique's research runs
 *  (379 in three hours), so every 3 s tick fetched up to 40 FULL runs (50–90 KB each) and was then restarted
 *  by the next arrival before it could record anything. These helpers make the loop converge:
 *  - a run is OPEN until a poll has seen it in a terminal status; terminal runs are never fetched again;
 *  - a run the list cannot show gets a bounded number of direct looks (a few per tick) and is then UNRESOLVED —
 *    counted, shown, and never asked for again;
 *  - the batch is FINISHED when nothing is open. */
export type ScanRow = { status: string } | undefined;

export const MAX_MISSES = 3;
export const STRAGGLERS_PER_TICK = 8;
export const FULL_FETCH_CONCURRENCY = 4;

export function isTerminal(row: ScanRow): boolean {
  return !!row && row.status !== "running";
}

export function isUnresolved(id: string, misses: Record<string, number>, maxMisses = MAX_MISSES): boolean {
  return (misses[id] ?? 0) >= maxMisses;
}

/** ids still worth asking the server about: not terminal and not given up on. */
export function openIds(ids: string[], rows: Record<string, ScanRow>, misses: Record<string, number>, maxMisses = MAX_MISSES): string[] {
  return ids.filter((id) => !isTerminal(rows[id]) && !isUnresolved(id, misses, maxMisses));
}

/** open ids the list window did not show, a bounded slice per tick. */
export function pickStragglers(open: string[], found: Record<string, unknown>, misses: Record<string, number>,
                               perTick = STRAGGLERS_PER_TICK, maxMisses = MAX_MISSES): string[] {
  return open.filter((id) => !found[id] && !isUnresolved(id, misses, maxMisses)).slice(0, perTick);
}

/** every id is terminal or unresolved -> the batch is finished (an empty batch never is). */
export function scanFinished(ids: string[], rows: Record<string, ScanRow>, misses: Record<string, number>, maxMisses = MAX_MISSES): boolean {
  return ids.length > 0 && openIds(ids, rows, misses, maxMisses).length === 0;
}
