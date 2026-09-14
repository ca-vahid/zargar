import type { ArmedPlan } from '../types';

export const cleanAttentionText = (s: string) => s.replace(/\\u2014/gi, '—').replace(/\\u2013/gi, '–');
const names: Record<string, string> = {bounce:'Support entry', breakout:'Breakout entry', reject:'Resistance entry', breakdown:'Breakdown entry', retest:'Retest entry'};

export function setupDescription(kind?: string, entry?: number, label?: string | null, id?: string) {
  const name = label && label !== id ? label : kind ? names[kind] || kind.replaceAll('_',' ') : 'Plan issue';
  return `${name}${Number.isFinite(entry) ? ` at ${Number(entry).toFixed(2)}` : ''}`;
}

export function attentionItems(a: ArmedPlan) {
  return (a.attentionReasons ?? []).map(raw => {
    const text = cleanAttentionText(raw);
    const match = /^([^:]+):\s*(.*)$/.exec(text);
    const trigger = a.triggers?.find(t => t.id === match?.[1]);
    const trade = a.trades?.find(t => t.triggerId === match?.[1]);
    const kind = trigger?.kind || trade?.kind;
    const entry = trigger?.entry ?? trade?.entry;
    const setup = setupDescription(kind, entry, trigger?.label, trigger?.id);
    // Only an explicit refused, unfilled attempt earns no-position reassurance.
    // Unknown submissions, partial fills and protection errors remain actionable.
    const blocked = !!trade && trade.status === 'failed' && trade.filledQty === 0 && trade.remaining === 0
      && !/unknown|uncertain|unresolved|timeout|timed out|ambiguous|connection|network/i.test(text)
      && /resulting position [\d.]+% of equity exceeds [\d.]+%|gross exposure would be [\d.]+% of equity \(max [\d.]+%\)|insufficient (?:cash|buying power)|REJECTED_RISK/i.test(match?.[2] || text);
    return {raw: text, reference: match?.[1], setup: trigger || trade ? setup : 'Plan issue', blocked,
      reason: (trigger || trade ? match?.[2] || text : text).replace(/^fire produced nothing\s*[—–-]\s*/i, 'Entry was not placed: ')
        .replace(/resulting position ([\d.]+)% of equity exceeds ([\d.]+)%/i, 'position size after this order would be $1% of account equity, above the $2% limit')};
  });
}

export function attentionSummary(a: ArmedPlan) {
  const items = attentionItems(a);
  const held = (a.openPositions ?? 0) > 0 || (a.trades ?? []).some(t => t.remaining > 0);
  const pending = (a.trades ?? []).some(t => ['fired','proposal','working','submitting'].includes(t.status));
  const notice = !held && !pending && items.length > 0 && items.every(i => i.blocked);
  return {items, held, notice, title: notice ? 'Entry blocked — no action required' : held ? 'Position needs review' : 'Execution needs review',
    next: notice ? 'These entry attempts were rejected with no fills. No sell action is needed. Review planned position size before a future setup; this notice is not an instruction to retry or increase limits.'
      : held ? 'This plan still reports exposure. Review the position, orders and protection below before deciding what to do.'
      : 'Check the order status and details below. A failed or uncertain attempt is not proof that no money moved; do not submit a duplicate order.'};
}
