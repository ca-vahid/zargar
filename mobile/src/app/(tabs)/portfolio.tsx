import { router } from 'expo-router';
import { useMemo, useState } from 'react';
import { View } from 'react-native';

import { api } from '@/api/endpoints';
import type { ManagedPosition, Order, Portfolio, Position } from '@/api/types';
import { LineChart } from '@/components/LineChart';
import { Async, Button, Card, Chips, Delta, Empty, Pill, Row, Screen, Section, styles, Txt } from '@/components/ui';
import { usePoll } from '@/hooks/usePoll';
import { runAction } from '@/lib/actions';
import { dayMove, dayMovePct, GROUP_LABEL, groupOf, visibleBooks } from '@/lib/books';
import type { Point } from '@/lib/chart';
import { dayTime, money, pct, price, qty, signedMoney } from '@/lib/format';
import { useStore } from '@/store';
import { space, useTheme } from '@/theme';

type Range = '1D' | '1W' | '1M' | '3M' | 'All';
const RANGE_MS: Record<Range, number | null> = {
  '1D': 24 * 3600e3, '1W': 7 * 24 * 3600e3, '1M': 31 * 24 * 3600e3, '3M': 92 * 24 * 3600e3, All: null,
};

/** The stop and next target the position manager holds for a symbol in a book. */
function planFor(managed: ManagedPosition[] | null, pos: Position) {
  const m = (managed ?? []).find((x) => x.portfolioId === pos.portfolioId
    && (x.symbol === pos.symbol || x.legs.some((l) => l.symbol === pos.symbol)));
  if (!m) return null;
  const targets: number[] = m.policy?.ladder?.targets ?? [];
  return { id: m.id, stop: m.state?.stop ?? null, venueStop: m.venueStopAt ?? null, entry: m.entry,
    target: targets[m.state?.trimsDone ?? 0] ?? null, status: m.status, held: m.sessionsHeld };
}

export default function PortfolioScreen() {
  const t = useTheme();
  const portfolios = useStore((s) => s.portfolios);
  const positionsMap = useStore((s) => s.positions);
  const ordersMap = useStore((s) => s.openOrders);
  const selected = useStore((s) => s.selectedBook);
  const pauses = useStore((s) => s.halt.pauses);
  const lossHalts = useStore((s) => s.halt.books);
  const [range, setRange] = useState<Range>('1D');
  const [showResearch, setShowResearch] = useState(false);

  const books = useMemo(() => visibleBooks(portfolios, showResearch), [portfolios, showResearch]);
  const book: Portfolio | undefined = books.find((b) => b.id === selected) ?? books[0];
  const bookId = book?.id ?? '';
  const cur = book?.baseCurrency ?? 'USD';

  const equity = usePoll<Point[]>(
    () => (bookId ? api.equity(bookId, { since: RANGE_MS[range] ? Date.now() - (RANGE_MS[range] as number) : undefined, points: 300 }) : Promise.resolve([])),
    60000, [bookId, range]);
  const managed = usePoll(() => api.managedPositions('open'), 30000);
  const fills = usePoll(() => (bookId ? api.executions(bookId, 15) : Promise.resolve([])), 60000, [bookId]);

  const positions = useMemo(
    () => Object.values(positionsMap).filter((p) => p.portfolioId === bookId && Math.abs(p.qty) > 1e-9)
      .sort((a, b) => Math.abs(b.marketValue ?? 0) - Math.abs(a.marketValue ?? 0)),
    [positionsMap, bookId]);
  const orders = useMemo(
    () => Object.values(ordersMap).filter((o) => o.portfolioId === bookId).sort((a, b) => (a.createdAt < b.createdAt ? 1 : -1)),
    [ordersMap, bookId]);

  if (!book) return <Screen><Empty text="No books yet — waiting for the server." /></Screen>;

  // the live point is appended so the curve's right edge is the number in the headline
  const series: Point[] = equity.data && book.equity != null ? [...equity.data, [Date.now(), book.equity]] : equity.data ?? [];
  const paused = pauses?.[book.id];
  const lossHalt = lossHalts?.[book.id];
  const refreshAll = () => { equity.refresh(); managed.refresh(); fills.refresh(); };

  const togglePause = () => {
    if (paused) {
      void runAction(
        { title: `Resume entries on ${book.name}?`, body: `It was paused for: ${paused.reason}`, confirmLabel: 'Resume', secure: true },
        () => api.unpauseBook(book.id), `${book.name}: entries resumed`);
    } else {
      void runAction(
        { title: `Pause entries on ${book.name}?`, body: 'No new entries on this book until you resume it. Open positions keep their stops and exits still work. Other books are untouched.',
          confirmLabel: 'Pause entries', danger: true, secure: true },
        () => api.pauseBook(book.id, 'paused from the phone'), `${book.name}: entries paused`);
    }
  };

  // only an unfilled BUY can be cancelled from the phone: that takes risk off. Stops and
  // targets are the position manager's, and cancelling one would leave a position bare.
  const cancelEntry = (o: Order) => runAction(
    { title: `Cancel this ${o.symbol} buy order?`, lines: [['Order', `Buy ${qty(o.qty)} ${o.orderType}`], ['Price', price(o.limitPrice ?? o.stopPrice)]],
      confirmLabel: 'Cancel order', danger: true, secure: true },
    () => api.cancelOrder(o.id), `${o.symbol}: cancel sent`);

  return (
    <Screen onRefresh={refreshAll} refreshing={equity.refreshing || managed.refreshing}>
      <Chips value={book.id} onChange={(id) => useStore.getState().set({ selectedBook: id })}
        options={books.map((b) => ({ key: b.id, label: b.name }))} />

      <View style={{ gap: 2 }}>
        <View style={styles.wrap}>
          <Txt v="label" faint>{GROUP_LABEL[groupOf(book)]}</Txt>
          {paused && <Pill kind="warn" text="Entries paused" />}
          {lossHalt && <Pill kind="bad" text="At loss limit" />}
        </View>
        <Txt v="hero" num>{money(book.equity ?? book.cash, cur)}</Txt>
        <Delta value={dayMove(book)} text={`${signedMoney(dayMove(book), cur)}  ${pct(dayMovePct(book))} today`} />
      </View>

      <Card>
        <Async state={equity}>
          {() => (
            <LineChart points={series} baseline={range === '1D' ? book.dayStart ?? null : null} baselineLabel="yesterday's close"
              format={(v) => money(v, cur)} formatTime={(ts) => dayTime(ts)} emptyText="Not enough history for this range yet" />
          )}
        </Async>
        <Chips value={range} onChange={setRange} options={(Object.keys(RANGE_MS) as Range[]).map((k) => ({ key: k, label: k }))} />
      </Card>

      <Section title={`Positions · ${positions.length}`} right={<Txt v="small" dim num>Cash {money(book.cash, cur)}</Txt>}>
        <Card>
          {positions.length === 0 && <Empty text="No open positions in this book." />}
          {positions.map((p, i) => {
            const plan = planFor(managed.data, p);
            const label = p.option?.short ?? p.symbol;
            return (
              <Row key={p.symbol} last={i === positions.length - 1}
                onPress={() => router.navigate({ pathname: '/chart/[symbol]', params: {
                  symbol: p.option?.underlying ?? p.symbol, entry: plan ? String(plan.entry) : String(p.avgCost),
                  stop: plan?.stop != null ? String(plan.stop) : '', target: plan?.target != null ? String(plan.target) : '',
                  positionId: plan?.id ?? '', name: label } })}
                left={<View style={styles.wrap}><Txt v="head">{label}</Txt>{plan?.status === 'closing' && <Pill kind="warn" text="closing" />}{plan?.status === 'attention' && <Pill kind="bad" text="attention" />}</View>}
                sub={`${qty(p.qty)} @ ${price(p.avgCost)}${plan?.stop != null ? ` · stop ${price(plan.stop)}` : ' · no stop on record'}${plan?.target != null ? ` · target ${price(plan.target)}` : ''}`}
                right={<Txt num>{money(p.marketValue, p.currency ?? cur)}</Txt>}
                rightSub={<Delta v="small" value={p.unrealizedPnl} text={`${signedMoney(p.unrealizedPnl, p.currency ?? cur)}  ${pct(p.unrealizedPnlPct)}`} />} />
            );
          })}
        </Card>
      </Section>

      <Section title={`Working orders · ${orders.length}`}>
        <Card>
          {orders.length === 0 && <Empty text="No orders are working in this book." />}
          {orders.map((o, i) => (
            <Row key={o.id} last={i === orders.length - 1} onPress={o.side === 'BUY' ? () => void cancelEntry(o) : undefined}
              left={`${o.side === 'BUY' ? 'Buy' : 'Sell'} ${qty(o.qty)} ${o.option?.short ?? o.symbol}`}
              sub={`${o.orderType === 'STP' ? 'Stop' : o.orderType === 'LMT' ? 'Limit' : o.orderType} ${price(o.stopPrice ?? o.limitPrice)} · ${o.tif} · ${o.status.toLowerCase()}`}
              right={<Txt v="small" dim num>{dayTime(o.createdAt)}</Txt>} />
          ))}
        </Card>
      </Section>

      <Section title="Recent fills">
        <Card>
          <Async state={fills} empty="No fills in this book yet.">
            {(list) => list.slice(0, 12).map((e, i, all) => (
              <Row key={e.id} last={i === all.length - 1}
                left={`${e.side === 'BUY' ? 'Bought' : 'Sold'} ${qty(e.qty)} ${e.symbol}`}
                sub={`at ${price(e.price)}${e.commission ? ` · fee ${money(e.commission, cur)}` : ''}`}
                right={<Txt v="small" dim num>{dayTime(e.ts)}</Txt>} />
            ))}
          </Async>
        </Card>
      </Section>

      <View style={{ gap: space.sm }}>
        <Button kind="plain" label={paused ? 'Resume entries on this book' : 'Pause entries on this book'} onPress={togglePause} />
        <Txt v="small" color={t.accent} style={{ textAlign: 'center', paddingVertical: space.sm }}
          onPress={() => setShowResearch((v) => !v)}>
          {showResearch ? 'Hide research books' : 'Show research books'}
        </Txt>
      </View>
    </Screen>
  );
}
