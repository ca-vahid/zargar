import { router } from 'expo-router';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { View } from 'react-native';

import { api } from '@/api/endpoints';
import type { Order, Portfolio } from '@/api/types';
import { AccountPicker } from '@/components/AccountPicker';
import { DateRangeSheet } from '@/components/DateRangeSheet';
import { CurrencySwitch } from '@/components/Header';
import { LineChart } from '@/components/LineChart';
import { planFor, PositionRow } from '@/components/PositionRow';
import { Async, Button, Card, Chips, Delta, Empty, Pill, Row, Screen, Section, Skeleton, styles, Txt } from '@/components/ui';
import { useCurrency } from '@/hooks/useCurrency';
import { usePoll } from '@/hooks/usePoll';
import { useWorkspace } from '@/hooks/useWorkspace';
import { runAction } from '@/lib/actions';
import { dayMove, dayMovePct, GROUP_LABEL, groupOf, visibleBooks } from '@/lib/books';
import type { Point } from '@/lib/chart';
import { dayTime, money, pct, price, qty, shortDate, signedMoney } from '@/lib/format';
import { rateFor } from '@/lib/fx';
import { clip, RANGE_KEYS, type RangeKey, rangeStats, rangeWords, type Span, spanChip, spanFor, spanLabel } from '@/lib/range';
import { useStore } from '@/store';
import { space } from '@/theme';

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <View style={{ flex: 1 }}>
      <Txt v="small" faint>{label}</Txt>
      <Txt v="small" num>{value}</Txt>
    </View>
  );
}

export default function PortfolioScreen() {
  const ws = useWorkspace();
  const usdCad = useStore((s) => s.quotes['USDCAD=X']?.last ?? null);
  const portfolios = useStore((s) => s.portfolios);
  const positionsMap = useStore((s) => s.positions);
  const ordersMap = useStore((s) => s.openOrders);
  const selected = useStore((s) => s.selectedBook);
  const pauses = useStore((s) => s.halt.pauses);
  const lossHalts = useStore((s) => s.halt.books);
  const [range, setRange] = useState<RangeKey>('1D');
  const [custom, setCustom] = useState<Span | null>(null);
  const [choosing, setChoosing] = useState(false);
  const [picked, setPicked] = useState<Point | null>(null);
  const [showResearch, setShowResearch] = useState(false);

  const books = useMemo(() => visibleBooks(portfolios, ws, showResearch), [portfolios, ws, showResearch]);
  const book: Portfolio | undefined = books.find((b) => b.id === selected) ?? books[0];
  const bookId = book?.id ?? '';
  const own = book?.baseCurrency ?? 'USD';
  // totals follow the chosen display currency; with no live rate they stay in the book's own
  const display = useCurrency();
  const rate = rateFor(usdCad, own, display);
  const cur = rate == null ? own : display;
  const k = rate ?? 1;

  // the window is fixed when a range is chosen, so the same question is asked on every refresh
  const span = useMemo(() => spanFor(range, Date.now(), custom), [range, custom]);
  const rangeId = `${range}:${custom?.from ?? ''}:${custom?.to ?? ''}`;
  const equity = usePoll<Point[]>(
    () => (bookId ? api.equity(bookId, { since: span.from ?? undefined, points: span.to == null ? 300 : 900 }) : Promise.resolve([])),
    60000, [bookId, rangeId], `equity:${bookId}:${rangeId}`);
  const managed = usePoll(() => api.managedPositions('open'), 30000, [], 'managed:open');
  const fills = usePoll(() => (bookId ? api.executions(bookId, 15) : Promise.resolve([])), 60000, [bookId], `fills:${bookId}`);
  useEffect(() => { setPicked(null); }, [bookId, rangeId]);

  const positions = useMemo(
    () => Object.values(positionsMap).filter((p) => p.portfolioId === bookId && Math.abs(p.qty) > 1e-9)
      .sort((a, b) => Math.abs(b.marketValue ?? 0) - Math.abs(a.marketValue ?? 0)),
    [positionsMap, bookId]);
  const orders = useMemo(
    () => Object.values(ordersMap).filter((o) => o.portfolioId === bookId).sort((a, b) => (a.createdAt < b.createdAt ? 1 : -1)),
    [ordersMap, bookId]);

  // the curve in the display currency (its shape is the book's own, only the scale changes);
  // a window that runs up to now ends on the live value, so its right edge is the headline
  const liveEquity = book?.equity ?? null;
  const series = useMemo<Point[]>(() => {
    const inside = clip(equity.data ?? [], span);
    const withNow: Point[] = span.to == null && liveEquity != null && equity.data ? [...inside, [Date.now(), liveEquity]] : inside;
    return k === 1 ? withNow : withNow.map(([ts, v]) => [ts, v * k]);
  }, [equity.data, span, liveEquity, k]);

  const moneyIn = useCallback((v: number) => money(v, cur), [cur]);
  const timeOf = useCallback((ts: number) => dayTime(ts), []);
  const axisOf = useCallback((ts: number) => (range === '1D' || range === '1W' ? dayTime(ts) : shortDate(ts)), [range]);

  if (!book) return <Screen><Empty text={ws === 'live' ? 'No funded live or paper account yet.' : 'No practice books yet — waiting for the server.'} /></Screen>;

  // the day view measures from the server's day-start anchor; every other window from its first record
  const dayAnchor = range === '1D' && book.dayStart != null ? book.dayStart * k : null;
  const stats = rangeStats(series, dayAnchor);
  const headline = picked ? picked[1] : span.to == null ? (book.equity ?? book.cash) * k : stats?.end ?? null;
  const change = picked && stats ? picked[1] - stats.start : stats ? stats.change : range === '1D' ? (dayMove(book) ?? 0) * k : null;
  const changePct = picked && stats ? (stats.start ? ((picked[1] - stats.start) / Math.abs(stats.start)) * 100 : null)
    : stats ? stats.pct : range === '1D' ? dayMovePct(book) : null;
  const words = picked ? `at ${dayTime(picked[0])}` : rangeWords(range, span, Date.now(), stats?.firstTs);
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

  const pickRange = (key: RangeKey) => {
    if (key === 'Custom') setChoosing(true);
    else setRange(key);
  };

  return (
    <Screen onRefresh={refreshAll} refreshing={equity.refreshing || managed.refreshing}>
      <AccountPicker books={books} selected={book} onSelect={(id) => useStore.getState().set({ selectedBook: id })}
        footer={ws === 'practice' ? (
          <Button small kind="plain" label={showResearch ? 'Hide research books' : 'Show research books'}
            onPress={() => setShowResearch((v) => !v)} style={{ marginTop: space.sm }} />
        ) : undefined} />

      <View style={{ gap: 2 }}>
        <View style={styles.wrap}>
          <Txt v="label" faint>{GROUP_LABEL[groupOf(book)]}</Txt>
          {paused && <Pill kind="warn" text="Entries paused" />}
          {lossHalt && <Pill kind="bad" text="At loss limit" />}
          <View style={{ flex: 1 }} />
          <CurrencySwitch />
        </View>
        {headline != null
          ? <Txt v="hero" num>{money(headline, cur)}</Txt>
          : equity.data ? <Txt v="hero" num dim>—</Txt> : <Skeleton height={30} width="55%" style={{ marginVertical: 4 }} />}
        {change != null
          ? <Delta value={change} text={`${signedMoney(change, cur)}  ${pct(changePct)}  ${words}`} />
          : equity.data ? <Txt dim>No record for {spanLabel(span, Date.now())}</Txt> : <Skeleton height={14} width="45%" style={{ marginVertical: 3 }} />}
        {span.to != null && !picked && <Txt v="small" faint>Value at the end of {spanLabel(span, Date.now())}. Now: {money((book.equity ?? book.cash) * k, cur)}.</Txt>}
        {cur !== own && <Txt v="small" faint>Held in {own}; shown at {usdCad?.toFixed(4)} USD/CAD.</Txt>}
      </View>

      <Card>
        <Async state={equity} height={200}>
          {() => (
            <LineChart points={series} baseline={dayAnchor ?? (range === '1D' ? null : stats?.start ?? null)}
              baselineLabel={range === '1D' ? "yesterday's close" : 'where this period started'}
              format={moneyIn} formatTime={timeOf} axis={axisOf} onPick={setPicked} emptyText="Not enough history for these dates yet" />
          )}
        </Async>
        <Chips value={range} onChange={pickRange}
          options={RANGE_KEYS.map((key) => ({ key, label: key === 'Custom' ? (range === 'Custom' ? spanChip(span, Date.now()) : 'Custom…') : key }))} />
        {stats && series.length > 1 && (
          <View style={{ flexDirection: 'row', gap: space.md, marginTop: space.xs }}>
            <Stat label="Started at" value={money(stats.start, cur)} />
            <Stat label="High" value={money(stats.high, cur)} />
            <Stat label="Low" value={money(stats.low, cur)} />
          </View>
        )}
      </Card>
      <DateRangeSheet visible={choosing} value={range === 'Custom' ? custom : null} onClose={() => setChoosing(false)}
        onApply={(next) => { setCustom(next); setRange('Custom'); }} />

      <Section title={`Positions · ${positions.length}`} right={<Txt v="small" dim num>Cash {money(book.cash * k, cur)}</Txt>}>
        <Card>
          {positions.length === 0 && <Empty text="No open positions in this book." />}
          {positions.map((p, i) => (
            <PositionRow key={p.symbol} pos={p} plan={planFor(managed.data, p)} plansKnown={managed.data != null} own={own} last={i === positions.length - 1} />
          ))}
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
                sub={`at ${price(e.price)}${e.commission ? ` · fee ${money(e.commission, own)}` : ''}`}
                right={<Txt v="small" dim num>{dayTime(e.ts)}</Txt>} />
            ))}
          </Async>
        </Card>
      </Section>

      <View style={{ gap: space.sm }}>
        <Button kind="plain" label={paused ? 'Resume entries on this book' : 'Pause entries on this book'} onPress={togglePause} />
      </View>
    </Screen>
  );
}
