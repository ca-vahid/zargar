import { router } from 'expo-router';
import { useEffect, useMemo, useState } from 'react';
import { Pressable, View } from 'react-native';

import { api } from '@/api/endpoints';
import type { ArmedSummary, Ledger, Portfolio, Position } from '@/api/types';
import { AreaSpark, DayBars, Heading, Hero, Meter, RangeBar, Sparkline, SymbolBadge } from '@/components/graphics';
import { CurrencySwitch } from '@/components/Header';
import { planFor, PositionRow } from '@/components/PositionRow';
import { Card, Delta, Empty, Pill, Row, Screen, Skeleton, SkeletonRows, styles, Tabs, Txt } from '@/components/ui';
import { useConvert, useCurrency } from '@/hooks/useCurrency';
import { usePoll } from '@/hooks/usePoll';
import { useWorkspace } from '@/hooks/useWorkspace';
import { dayMove, dayMovePct, GROUP_LABEL, groupOf, visibleBooks, workspaceOf } from '@/lib/books';
import type { Point } from '@/lib/chart';
import { clock, money, pct, price, shortDate, signedMoney, titleCase } from '@/lib/format';
import { marketClock, newYorkTime } from '@/lib/market';
import { sumSeries } from '@/lib/range';
import { watchSymbol } from '@/live/socket';
import { useStore } from '@/store';
import { radius, space, useTheme } from '@/theme';

type Pane = 'overview' | 'positions' | 'plans' | 'activity';
type Curves = Record<string, Point[]>;
type Convert = ReturnType<typeof useConvert>;
const INDEX_FUNDS: { symbol: string; name: string }[] = [
  { symbol: 'SPY', name: 'S&P 500' }, { symbol: 'QQQ', name: 'Nasdaq 100' }, { symbol: 'IWM', name: 'Small caps' },
];

/** The US market's clock, re-read twice a minute. */
function MarketLine() {
  const t = useTheme();
  const session = useStore((s) => s.quotes.SPY?.session);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 30000);
    return () => clearInterval(timer);
  }, []);
  const m = marketClock(newYorkTime(now), session);
  const ink = m.state === 'open' ? t.up : m.state === 'closed' ? t.text3 : t.warn;
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8, flex: 1 }} accessibilityLabel={`${m.title}, ${m.detail}`}>
      <View style={{ width: 9, height: 9, borderRadius: 5, backgroundColor: ink }} />
      <Txt style={{ fontWeight: '700' }}>{m.title}</Txt>
      {!!m.detail && <Txt v="small" dim numberOfLines={1} style={{ flexShrink: 1 }}>{m.detail}</Txt>}
    </View>
  );
}

/** One group of accounts as a headline: what it is worth now and how today has gone.
 *  The total and today's move come from the live account values the app already holds,
 *  so they are on screen at once; the banked / riding split arrives from the ledger. */
function HeroCard({ label, books, curves, ledger, conv }: {
  label: string; books: Portfolio[]; curves: Curves | null; ledger: Ledger | null | undefined; conv: Convert;
}) {
  const t = useTheme();
  const cur = conv(0, books[0]?.baseCurrency).cur;
  const total = books.reduce((sum, b) => sum + (conv(b.equity ?? b.cash, b.baseCurrency).value ?? 0), 0);
  const anchored = books.length > 0 && books.every((b) => b.dayStart != null && b.equity != null);
  const start = anchored ? books.reduce((sum, b) => sum + (conv(b.dayStart, b.baseCurrency).value ?? 0), 0) : null;
  const move = start == null ? null : total - start;
  const movePct = start ? ((move as number) / Math.abs(start)) * 100 : null;
  // the day's curve of the whole group; only when every account has one, so it never shows a part as the whole
  const day = useMemo(() => {
    if (!curves || !books.length || !books.every((b) => (curves[b.id]?.length ?? 0) > 1)) return [];
    const scaled = books.map((b) => {
      const k = conv(1, b.baseCurrency).value ?? 1;
      return curves[b.id].map(([ts, v]) => [ts, v * k] as Point);
    });
    return [...sumSeries(scaled).map((p) => p[1]), total];
  }, [curves, books, conv, total]);
  const split = ledger && (Math.abs(ledger.banked) > 0.005 || Math.abs(ledger.riding) > 0.005 || ledger.sinceStart != null);
  const lcur = ledger?.currency ?? cur;
  return (
    <Hero>
      <Txt v="label" color={t.accent}>{label}</Txt>
      <Txt v="hero" num>{money(total, cur)}</Txt>
      {move != null
        ? <Delta value={move} text={`${signedMoney(move, cur)}  ${pct(movePct)}  today`} />
        : <Txt v="small" dim>Today's move is not known yet</Txt>}
      <View style={{ marginTop: space.sm }}>
        {day.length > 1 ? <AreaSpark values={day} baseline={start} /> : <View style={{ height: 56, justifyContent: 'center' }}>{curves == null && <Skeleton height={36} />}</View>}
      </View>
      {(split || ledger === undefined) && (
        <View style={{ flexDirection: 'row', gap: space.xl, marginTop: space.sm, minHeight: 36 }}>
          {ledger ? (
            <>
              <View><Txt v="small" dim>Banked</Txt><Delta value={ledger.banked} text={signedMoney(ledger.banked, lcur)} /></View>
              <View><Txt v="small" dim>Riding</Txt><Delta value={ledger.riding} text={signedMoney(ledger.riding, lcur)} /></View>
              {ledger.sinceStart != null && <View><Txt v="small" dim>Since start</Txt><Delta value={ledger.sinceStart} text={signedMoney(ledger.sinceStart, lcur)} /></View>}
            </>
          ) : <Skeleton height={30} width="70%" />}
        </View>
      )}
    </Hero>
  );
}

/** One index fund's day: is the market up or down, without leaving the home screen. */
function IndexTile({ symbol, name }: { symbol: string; name: string }) {
  const t = useTheme();
  const quote = useStore((s) => s.quotes[symbol]);
  const px = quote ? quote.regPrice || quote.last : null;
  const base = quote?.prevClose || null;
  const move = px && base ? ((px - base) / base) * 100 : null;
  return (
    <Pressable onPress={() => router.navigate({ pathname: '/chart/[symbol]', params: { symbol, name } })}
      accessibilityRole="button" accessibilityLabel={`${name}: ${move == null ? 'no price yet' : pct(move)}`} android_ripple={{ color: t.surface3 }}
      style={{ flex: 1, backgroundColor: t.surface, borderRadius: radius.md, borderWidth: 1, borderColor: t.line, padding: space.md, gap: 2 }}>
      <Txt v="small" dim numberOfLines={1}>{name}</Txt>
      <Txt num style={{ fontWeight: '700' }}>{px ? price(px) : '—'}</Txt>
      <Delta v="small" value={move} text={move == null ? '—' : pct(move)} />
    </Pressable>
  );
}

function BookRow({ book, curve, last, conv }: { book: Portfolio; curve: Point[] | undefined; last: boolean; conv: Convert }) {
  const values = useMemo(() => {
    const v = (curve ?? []).map((p) => p[1]);
    return book.equity != null ? [...v, book.equity] : v;
  }, [curve, book.equity]);
  const eq = conv(book.equity ?? book.cash, book.baseCurrency);
  const move = conv(dayMove(book), book.baseCurrency).value;
  return (
    <Row last={last}
      onPress={() => { useStore.getState().set({ selectedBook: book.id }); router.navigate('/portfolio'); }}
      left={book.name} sub={GROUP_LABEL[groupOf(book)]}
      right={<View style={{ flexDirection: 'row', alignItems: 'center', gap: space.md }}>
        <Sparkline values={values} up={move == null ? undefined : move >= 0} />
        <View style={{ alignItems: 'flex-end', minWidth: 96 }}>
          <Txt num>{money(eq.value, eq.cur)}</Txt>
          <Delta v="small" value={move} text={`${signedMoney(move, eq.cur)}  ${pct(dayMovePct(book))}`} />
        </View>
      </View>} />
  );
}

/** A holding as one line with a bar for how far it is up or down, relative to the others. */
function MoverRow({ pos, bookName, scale, last, conv }: { pos: Position; bookName: string; scale: number; last: boolean; conv: Convert }) {
  const t = useTheme();
  const gain = conv(pos.unrealizedPnl, pos.currency);
  const v = pos.unrealizedPnl ?? 0;
  return (
    <Pressable onPress={() => router.navigate({ pathname: '/chart/[symbol]', params: { symbol: pos.option?.underlying ?? pos.symbol, entry: String(pos.avgCost), name: pos.option?.short ?? pos.symbol } })}
      android_ripple={{ color: t.surface3 }} style={{ paddingVertical: space.sm, gap: 6, borderBottomWidth: last ? 0 : 0.5, borderBottomColor: t.line }}>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: space.sm }}>
        <SymbolBadge symbol={pos.option?.underlying ?? pos.symbol} size={30} />
        <View style={{ flex: 1 }}>
          <Txt v="head" numberOfLines={1}>{pos.option?.short ?? pos.symbol}</Txt>
          <Txt v="small" dim numberOfLines={1}>{bookName}</Txt>
        </View>
        <View style={{ alignItems: 'flex-end' }}>
          <Delta value={v} text={signedMoney(gain.value, gain.cur)} />
          <Delta v="small" value={v} text={pct(pos.unrealizedPnlPct)} />
        </View>
      </View>
      <Meter value={scale ? Math.abs(v) / scale : 0} color={v >= 0 ? t.upFill : t.downFill} height={4} />
    </Pressable>
  );
}

function PositionsView({ holdings, bookOf, conv }: { holdings: Position[]; bookOf: (id: string) => Portfolio | undefined; conv: Convert }) {
  const managed = usePoll(() => api.managedPositions('open'), 30000, [], 'managed:open');
  const total = holdings.reduce((sum, p) => sum + (conv(p.unrealizedPnl, p.currency).value ?? 0), 0);
  const cur = conv(0, holdings[0]?.currency).cur;
  return (
    <View style={{ gap: space.sm }}>
      <Heading icon="trending-up-outline" title={`Open positions · ${holdings.length}`}
        right={holdings.length ? <Delta v="small" value={total} text={`${signedMoney(total, cur)} unrealized`} /> : undefined} />
      <Card>
        {holdings.length === 0 && <Empty text="Nothing is held in this workspace right now." />}
        {holdings.map((p, i) => (
          <PositionRow key={`${p.portfolioId}:${p.symbol}`} pos={p} plan={planFor(managed.data, p)} plansKnown={managed.data != null}
            own={bookOf(p.portfolioId)?.baseCurrency ?? 'USD'} bookName={bookOf(p.portfolioId)?.name} last={i === holdings.length - 1} />
        ))}
      </Card>
    </View>
  );
}

function PlansView({ s, watching, inTrade }: { s: ArmedSummary | null; watching: ArmedSummary['watching']; inTrade: ArmedSummary['inTrade'] }) {
  const t = useTheme();
  if (!s) return <Card><SkeletonRows rows={5} /></Card>;
  const near = [...watching].sort((a, b) => Math.abs(a.nearest?.distancePct ?? 99) - Math.abs(b.nearest?.distancePct ?? 99));
  return (
    <>
      {inTrade.length > 0 && (
        <View style={{ gap: space.sm }}>
          <Heading icon="flash-outline" title={`Plans in a trade · ${inTrade.length}`}
            right={<Txt v="small" color={t.accent} onPress={() => router.navigate('/armed')}>Manage</Txt>} />
          <Card>
            {inTrade.map((x, i) => {
              const entry = x.underlyingEntry ?? x.entry;
              return (
                <View key={`${x.runId}-${x.triggerId}`} style={{ gap: 6, paddingBottom: i === inTrade.length - 1 ? 0 : space.md }}>
                  <Row last
                    onPress={() => router.navigate({ pathname: '/chart/[symbol]', params: { symbol: x.symbol, entry: String(entry), stop: String(x.stop), target: x.nextTarget != null ? String(x.nextTarget) : '' } })}
                    left={<View style={styles.wrap}><SymbolBadge symbol={x.symbol} size={34} /><Txt v="head">{x.symbol}</Txt><Pill kind={x.direction === 'short' ? 'bad' : 'ok'} text={x.direction} /></View>}
                    sub={`${x.account ?? ''} · stop ${price(x.stop)}${x.nextTarget != null ? ` · target ${price(x.nextTarget)}` : ''}`}
                    right={<Delta value={x.unrealizedPnl} text={signedMoney(x.unrealizedPnl)} />}
                    rightSub={x.unrealizedR != null ? `${x.unrealizedR >= 0 ? '+' : ''}${x.unrealizedR.toFixed(2)} R` : undefined} />
                  <RangeBar stop={x.stop} entry={entry} now={x.lastPrice} target={x.nextTarget} />
                </View>
              );
            })}
          </Card>
        </View>
      )}
      <View style={{ gap: space.sm }}>
        <Heading icon="eye-outline" title={`Waiting for their price · ${watching.length}`}
          right={<Txt v="small" color={t.accent} onPress={() => router.navigate('/armed')}>All plans</Txt>} />
        <Card>
          {watching.length === 0 && <Empty text="No plans are waiting in this workspace." />}
          {near.slice(0, 15).map((w, i, all) => {
            const away = w.nearest.distancePct != null ? Math.abs(w.nearest.distancePct) : null;
            return (
              <Pressable key={w.runId} android_ripple={{ color: t.surface3 }}
                onPress={() => router.navigate({ pathname: '/chart/[symbol]', params: { symbol: w.symbol, entry: String(w.nearest.entry), stop: String(w.nearest.stop), target: w.nearest.targets?.[0] != null ? String(w.nearest.targets[0]) : '' } })}
                style={{ paddingVertical: space.sm, gap: 6, borderBottomWidth: i === all.length - 1 ? 0 : 0.5, borderBottomColor: t.line }}>
                <View style={{ flexDirection: 'row', alignItems: 'center', gap: space.sm }}>
                  <SymbolBadge symbol={w.symbol} size={30} />
                  <View style={{ flex: 1 }}>
                    <View style={styles.wrap}><Txt v="head">{w.symbol}</Txt>{!!w.grade && <Pill kind="accent" text={w.grade} />}{w.stale && <Pill kind="warn" text="stale" />}</View>
                    <Txt v="small" dim numberOfLines={1}>{titleCase(w.nearest.kind)} at {price(w.nearest.entry)} · {w.account ?? ''}</Txt>
                  </View>
                  <View style={{ alignItems: 'flex-end' }}>
                    <Txt num>{price(w.lastPrice)}</Txt>
                    <Txt v="small" dim num>{away != null ? `${away.toFixed(2)}% away` : ''}</Txt>
                  </View>
                </View>
                {/* fuller = closer to its entry price; anything 5% or more away reads empty */}
                {away != null && <Meter value={1 - Math.min(away, 5) / 5} color={away < 1 ? t.accent : t.text3} height={4} />}
              </Pressable>
            );
          })}
          {watching.length > 15 && <Txt v="small" dim style={{ paddingTop: space.sm }}>Showing the 15 closest of {watching.length}.</Txt>}
        </Card>
      </View>
      {s.stoppedToday.length > 0 && (
        <View style={{ gap: space.sm }}>
          <Heading icon="stop-circle-outline" title={`Finished today · ${s.stoppedToday.length}`} />
          <Card>
            {s.stoppedToday.slice(0, 12).map((x, i, all) => (
              <Row key={`${x.runId}-${i}`} last={i === all.length - 1} left={x.symbol} sub={x.reason}
                right={x.realizedPnl != null ? <Delta value={x.realizedPnl} text={signedMoney(x.realizedPnl)} /> : undefined}
                rightSub={x.at ? clock(x.at) : undefined} />
            ))}
          </Card>
        </View>
      )}
    </>
  );
}

export default function HomeScreen() {
  const t = useTheme();
  const ws = useWorkspace();
  const currency = useCurrency();
  const conv = useConvert();
  const halt = useStore((s) => s.halt);
  const broker = useStore((s) => s.broker);
  const portfolios = useStore((s) => s.portfolios);
  const positionsMap = useStore((s) => s.positions);
  const allProposals = useStore((s) => s.proposals);
  const armedBump = useStore((s) => s.armedBump);
  const synced = useStore((s) => s.synced);
  const [view, setView] = useState<Pane>('overview');

  const books = useMemo(() => visibleBooks(portfolios, ws), [portfolios, ws]);
  const ids = books.map((b) => b.id).join(',');
  // the groups that get a headline: real money and the paper account are never summed
  const groups = useMemo(() => (ws === 'practice'
    ? [{ scope: undefined as string | undefined, label: 'Practice', books }]
    : [{ scope: 'real', label: 'Real money', books: books.filter((b) => b.kind === 'live') },
       { scope: 'paper', label: 'Paper account', books: books.filter((b) => b.kind === 'paper') }].filter((g) => g.books.length > 0)),
  [ws, books]);
  const scopes = groups.map((g) => g.scope ?? '').join(',');

  const summary = usePoll(() => api.armedSummary(), 30000, [], 'armed:summary');
  // every account's day curve in ONE request round, shared by the headline and the list
  const curves = usePoll<Curves>(
    async () => {
      const list = await Promise.all(books.map((b) => api.equity(b.id, { since: Date.now() - 24 * 3600e3, points: 48 }).catch(() => [] as Point[])));
      return Object.fromEntries(books.map((b, i) => [b.id, list[i]]));
    }, 300000, [ids], `curves:${ids}`);
  // the ledger is the slow one (about a second): nothing above waits for it
  const ledgers = usePoll<(Ledger | null)[]>(
    () => Promise.all(groups.map((g) => api.ledger(ws, g.scope, 30, currency).catch(() => null))),
    120000, [ws, scopes, currency], `ledgers:${ws}:${scopes}:${currency}`);

  useEffect(() => { for (const f of INDEX_FUNDS) watchSymbol(f.symbol); }, []);
  // a plan fired, filled or stopped: re-pull shortly after instead of waiting for the tick
  const refresh = summary.refresh;
  useEffect(() => {
    if (!armedBump) return;
    const timer = setTimeout(refresh, 1500);
    return () => clearTimeout(timer);
  }, [armedBump, refresh]);

  const proposals = useMemo(
    () => allProposals.filter((p) => workspaceOf(portfolios.find((b) => b.id === p.portfolioId)?.kind) === ws),
    [allProposals, portfolios, ws]);
  const holdings = useMemo(() => {
    const mineIds = new Set(books.map((b) => b.id));
    return Object.values(positionsMap).filter((p) => mineIds.has(p.portfolioId) && Math.abs(p.qty) > 1e-9)
      .sort((a, b) => Math.abs(b.unrealizedPnl ?? 0) - Math.abs(a.unrealizedPnl ?? 0));
  }, [positionsMap, books]);
  const bookOf = (id: string) => books.find((b) => b.id === id);
  // the summary covers every book; show this workspace's share of it
  const mine = <T extends { workspace?: string | null }>(list: T[]) => list.filter((x) => workspaceOf(x.workspace) === ws);
  const s: ArmedSummary | null = summary.data;
  const inTrade = s ? mine(s.inTrade) : [];
  const watching = s ? mine(s.watching) : [];
  const attention = s ? mine(s.attention) : [];
  const bookHalts = Object.keys(halt.books ?? {}).length;
  const moverScale = Math.max(0, ...holdings.map((p) => Math.abs(p.unrealizedPnl ?? 0)));
  const refreshAll = () => { summary.refresh(); curves.refresh(); ledgers.refresh(); };

  return (
    <Screen onRefresh={refreshAll} refreshing={summary.refreshing}>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: space.sm }}>
        <MarketLine />
        <CurrencySwitch />
      </View>
      {(halt.engaged || (broker && !broker.feedConnected) || (ws === 'live' && broker?.ibkrConnected === false) || bookHalts > 0 || s?.windowOpenNow) && (
        <View style={styles.wrap}>
          {halt.engaged && <Pill kind="bad" text={`Halted${halt.reason ? `: ${halt.reason}` : ''}`} />}
          {broker && !broker.feedConnected && <Pill kind="bad" text="Prices down" />}
          {ws === 'live' && broker?.ibkrConnected === false && <Pill kind="bad" text="IBKR disconnected" />}
          {bookHalts > 0 && <Pill kind="warn" text={`${bookHalts} book${bookHalts > 1 ? 's' : ''} at loss limit`} />}
          {s?.windowOpenNow && !halt.engaged && <Pill kind="accent" text="Entry window open" />}
        </View>
      )}

      {groups.length === 0 && <Card><Empty text={synced ? 'No funded accounts in this workspace.' : 'Waiting for the server…'} /></Card>}
      {groups.map((g, i) => (
        <HeroCard key={g.label} label={g.label} books={g.books} curves={curves.data} conv={conv}
          ledger={ledgers.data ? ledgers.data[i] : ledgers.error ? null : undefined} />
      ))}

      {(proposals.length > 0 || attention.length > 0) && (
        <Card style={{ borderColor: t.accent }}>
          <Heading icon="hand-left-outline" title="Needs you" />
          {proposals.length > 0 && (
            <Row last={!attention.length} onPress={() => router.navigate('/tips')}
              left={`${proposals.length} approval card${proposals.length > 1 ? 's' : ''} waiting`}
              sub={proposals.slice(0, 4).map((p) => p.symbol).join(' · ')}
              right={<Txt color={t.accent} style={{ fontWeight: '700' }}>Review</Txt>} />
          )}
          {attention.map((a, i, all) => (
            <Row key={a.runId} last={i === all.length - 1} onPress={() => router.navigate('/armed')}
              left={<View style={styles.wrap}><SymbolBadge symbol={a.symbol} size={30} /><Txt v="head">{a.symbol}</Txt><Pill kind="warn" text="Attention" /></View>}
              sub={a.reasons.join(' · ')} />
          ))}
        </Card>
      )}

      <Tabs compact value={view} onChange={setView} options={[
        { key: 'overview', label: 'Overview' },
        { key: 'positions', label: 'Positions', badge: holdings.length },
        { key: 'plans', label: 'Plans', badge: s ? watching.length + inTrade.length : undefined },
        { key: 'activity', label: 'Activity' },
      ]} />

      {view === 'overview' && (
        <>
          <View style={{ gap: space.sm }}>
            <Heading icon="globe-outline" title="The market today" />
            <View style={{ flexDirection: 'row', gap: space.sm }}>
              {INDEX_FUNDS.map((f) => <IndexTile key={f.symbol} symbol={f.symbol} name={f.name} />)}
            </View>
          </View>

          <View style={{ gap: space.sm }}>
            <Heading icon="wallet-outline" title="Accounts today" />
            <Card>
              {books.length === 0 && <Empty text={synced ? 'No funded books in this workspace.' : 'Waiting for the server…'} />}
              {books.map((b, i) => <BookRow key={b.id} book={b} curve={curves.data?.[b.id]} conv={conv} last={i === books.length - 1} />)}
            </Card>
          </View>

          {holdings.length > 0 && (
            <View style={{ gap: space.sm }}>
              <Heading icon="podium-outline" title="Biggest gains and losses now"
                right={holdings.length > 5 ? <Txt v="small" color={t.accent} onPress={() => setView('positions')}>All {holdings.length}</Txt> : undefined} />
              <Card>
                {holdings.slice(0, 5).map((p, i, all) => (
                  <MoverRow key={`${p.portfolioId}:${p.symbol}`} pos={p} bookName={bookOf(p.portfolioId)?.name ?? ''} scale={moverScale} conv={conv} last={i === all.length - 1} />
                ))}
              </Card>
            </View>
          )}

          {groups.map((g, i) => {
            const l = ledgers.data?.[i];
            const days = l ? [...l.days].sort((a, b) => (a.date < b.date ? -1 : 1)).slice(-10) : [];
            if (ledgers.data && days.length === 0) return null;
            return (
              <View key={g.label} style={{ gap: space.sm }}>
                <Heading icon="bar-chart-outline" title={`Closed trades by day${groups.length > 1 ? ` · ${g.label}` : ''}`}
                  right={<Txt v="small" color={t.accent} onPress={() => router.navigate('/ledger')}>Money</Txt>} />
                <Card>
                  {l ? <DayBars items={days.map((d) => ({ label: shortDate(`${d.date}T12:00:00`), value: d.realized }))} format={(v) => signedMoney(v, l.currency ?? 'USD')} />
                    : <Skeleton height={104} round={radius.md} />}
                </Card>
              </View>
            );
          })}
        </>
      )}

      {view === 'positions' && <PositionsView holdings={holdings} bookOf={bookOf} conv={conv} />}

      {view === 'plans' && <PlansView s={s} watching={watching} inTrade={inTrade} />}

      {view === 'activity' && (
        <View style={{ gap: space.sm }}>
          <Heading icon="time-outline" title="What happened today"
            right={<Txt v="small" color={t.accent} onPress={() => router.navigate('/alerts')}>Alerts</Txt>} />
          <Card>
            {!s && <SkeletonRows rows={5} />}
            {s && s.timeline.length === 0 && <Empty text="Nothing has happened yet today." />}
            {s && s.timeline.slice(0, 30).map((e, i, all) => (
              <Row key={`${e.ts}-${e.runId}-${i}`} last={i === all.length - 1}
                left={<Txt><Txt style={{ fontWeight: '700' }}>{e.symbol}</Txt>  {titleCase(e.kind)}</Txt>}
                sub={e.text}
                right={<Txt v="small" dim num>{clock(e.ts)}</Txt>}
                rightSub={e.pnl != null ? <Delta v="small" value={e.pnl} text={signedMoney(e.pnl)} /> : undefined} />
            ))}
          </Card>
        </View>
      )}
      {!s && summary.error && <Txt color={t.down}>{summary.error}</Txt>}
    </Screen>
  );
}
