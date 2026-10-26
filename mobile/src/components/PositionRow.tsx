import { router } from 'expo-router';
import { View } from 'react-native';

import type { ManagedPosition, Position } from '../api/types';
import { useConvert } from '../hooks/useCurrency';
import { money, pct, price, qty, signedMoney } from '../lib/format';
import { useStore } from '../store';
import { space } from '../theme';
import { RangeBar, SymbolBadge } from './graphics';
import { Delta, Pill, Row, styles, Txt } from './ui';

/** The stop and next target the position manager holds for a symbol in a book. */
export function planFor(managed: ManagedPosition[] | null, pos: Position) {
  const m = (managed ?? []).find((x) => x.portfolioId === pos.portfolioId
    && (x.symbol === pos.symbol || x.legs.some((l) => l.symbol === pos.symbol)));
  if (!m) return null;
  const targets: number[] = m.policy?.ladder?.targets ?? [];
  return { id: m.id, stop: m.state?.stop ?? null, venueStop: m.venueStopAt ?? null, entry: m.entry,
    target: targets[m.state?.trimsDone ?? 0] ?? null, status: m.status, held: m.sessionsHeld };
}

/** One holding. It reads its own live price, so a tick repaints this row and
 *  nothing else on the screen. `bookName` says where it is held when a list mixes books. */
export function PositionRow({ pos, plan, own, last, bookName, plansKnown = true }: {
  pos: Position; plan: ReturnType<typeof planFor>; own: string; last: boolean; bookName?: string;
  /** false while the stops are still loading: say nothing about a stop rather than "no stop" */
  plansKnown?: boolean;
}) {
  const conv = useConvert();
  const live = useStore((s) => s.quotes[pos.symbol]?.last);
  const label = pos.option?.short ?? pos.symbol;
  const mark = live || pos.last || null;
  const value = conv(pos.marketValue, pos.currency ?? own);
  const gain = conv(pos.unrealizedPnl, pos.currency ?? own);
  const stopText = plan?.stop != null ? ` · stop ${price(plan.stop)}` : plansKnown ? ' · no stop on record' : '';
  return (
    <View style={{ gap: 4, paddingBottom: last ? 0 : space.sm }}>
      <Row last
        onPress={() => router.navigate({ pathname: '/chart/[symbol]', params: {
          symbol: pos.option?.underlying ?? pos.symbol, entry: plan ? String(plan.entry) : String(pos.avgCost),
          stop: plan?.stop != null ? String(plan.stop) : '', target: plan?.target != null ? String(plan.target) : '',
          positionId: plan?.id ?? '', name: label } })}
        left={<View style={styles.wrap}><SymbolBadge symbol={pos.option?.underlying ?? pos.symbol} size={34} /><Txt v="head">{label}</Txt>{plan?.status === 'closing' && <Pill kind="warn" text="closing" />}{plan?.status === 'attention' && <Pill kind="bad" text="attention" />}</View>}
        sub={`${bookName ? `${bookName} · ` : ''}${qty(pos.qty)} @ ${price(pos.avgCost)}${stopText}${plan?.target != null ? ` · target ${price(plan.target)}` : ''}`}
        right={<Txt num>{money(value.value, value.cur)}</Txt>}
        rightSub={<Delta v="small" value={pos.unrealizedPnl} text={`${signedMoney(gain.value, gain.cur)}  ${pct(pos.unrealizedPnlPct)}`} />} />
      {/* shares only: an option's own price is not on the share-price scale of its stop */}
      {plan && !pos.option && <RangeBar stop={plan.stop} entry={plan.entry} now={mark} target={plan.target} />}
    </View>
  );
}
