import Ionicons from '@expo/vector-icons/Ionicons';
import { router } from 'expo-router';
import { useEffect, useMemo, useState } from 'react';
import { Pressable, View } from 'react-native';

import { api } from '@/api/endpoints';
import type { ArmedSummary, Ledger, Portfolio, Position } from '@/api/types';
import { AreaSpark, DayBars, Heading, Hero, Meter, Sparkline, SymbolBadge } from '@/components/graphics';
import { CurrencySwitch } from '@/components/Header';
import { QuestionCard } from '@/components/Questions';
import { Card, Delta, Empty, Pill, Row, Screen, Skeleton, styles, Txt } from '@/components/ui';
import { useBooks } from '@/hooks/useBooks';
import { useConvert, useCurrency } from '@/hooks/useCurrency';
import { usePoll } from '@/hooks/usePoll';
import { useStanding } from '@/hooks/useStanding';
import { setWorkspace, useWorkspace } from '@/hooks/useWorkspace';
import { dayMove, dayMovePct, GROUP_LABEL, groupOf, liftEmptyCurve, workspaceOf } from '@/lib/books';
import type { Point } from '@/lib/chart';
import { clock, money, pct, price, shortDate, signedMoney, titleCase } from '@/lib/format';
import { marketClock, newYorkDate, newYorkTime } from '@/lib/market';
import { sumSeries } from '@/lib/range';
import { minutesToTrigger, orderLine, waitText } from '@/lib/standing';
import { watchSymbol } from '@/live/socket';
import { useStore } from '@/store';
import { radius, space, useTheme } from '@/theme';

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

/** A second group of accounts (the broker's paper account beside real money): one quiet line. */
function GroupLine({ label, books, conv }: { label: string; books: Portfolio[]; conv: Convert }) {
  const cur = conv(0, books[0]?.baseCurrency).cur;
  const total = books.reduce((sum, b) => sum + (conv(b.equity ?? b.cash, b.baseCurrency).value ?? 0), 0);
  const known = books.every((b) => b.dayStart != null && b.equity != null);
  const move = known ? books.reduce((sum, b) => sum + (conv(dayMove(b), b.baseCurrency).value ?? 0), 0) : null;
  return (
    <Card onPress={() => { useStore.getState().set({ selectedBook: books[0]?.id ?? null }); router.navigate('/portfolio'); }}
      style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingVertical: space.md }}>
      <Txt v="label" dim>{label}</Txt>
      <View style={{ flexDirection: 'row', alignItems: 'baseline', gap: space.md }}>
        {move != null && <Delta v="small" value={move} text={`${signedMoney(move, cur)} today`} />}
        <Txt num style={{ fontWeight: '700' }}>{money(total, cur)}</Txt>
      </View>
    </Card>
  );
}

/** One thing waiting for the person: an icon, what it is, and the word that says what to do. */
function TodoRow({ icon, ink, title, sub, action, onPress, last }: {
  icon: keyof typeof Ionicons.glyphMap; ink: string; title: string; sub?: string; action: string; onPress: () => void; last?: boolean;
}) {
  const t = useTheme();
  return (
    <Pressable onPress={onPress} accessibilityRole="button" android_ripple={{ color: t.surface3 }}
      style={{ flexDirection: 'row', alignItems: 'center', gap: space.md, paddingVertical: space.md, borderBottomWidth: last ? 0 : 0.5, borderBottomColor: t.line }}>
      <View style={{ width: 38, height: 38, borderRadius: 19, backgroundColor: `${ink}22`, alignItems: 'center', justifyContent: 'center' }}>
        <Ionicons name={icon} size={20} color={ink} />
      </View>
      <View style={{ flex: 1, gap: 2 }}>
        <Txt style={{ fontWeight: '700' }}>{title}</Txt>
        {!!sub && <Txt v="small" dim numberOfLines={2}>{sub}</Txt>}
      </View>
      <Txt v="small" color={t.accent} style={{ fontWeight: '700' }}>{action}</Txt>
    </Pressable>
  );
}

const openOrders = (tab: 'standing' | 'plans') => router.navigate({ pathname: '/orders', params: { tab } });

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
  const [allPositions, setAllPositions] = useState(false);
  const [allActivity, setAllActivity] = useState(false);

  const books = useBooks(ws);
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
      return Object.fromEntries(books.map((b, i) => [b.id, liftEmptyCurve(list[i], b.equity)]));
    }, 300000, [ids], `curves:${ids}`);
  // the ledger is the slow one (about a second): nothing above waits for it
  const ledgers = usePoll<(Ledger | null)[]>(
    () => Promise.all(groups.map((g) => api.ledger(ws, g.scope, 30, currency).catch(() => null))),
    120000, [ws, scopes, currency], `ledgers:${ws}:${scopes}:${currency}`);

  // the person's own standing orders in this workspace: how many wait, and which fires next
  const standing = useStanding();
  const so = standing.counts;
  const nextOrder = useMemo(() => {
    const at = newYorkTime(Date.now());
    let next: { text: string; wait: number } | null = null;
    for (const o of standing.orders ?? []) {
      if (o.status !== 'armed') continue;
      const wait = minutesToTrigger(o, at, newYorkDate(Date.now()));
      if (wait != null && (!next || wait < next.wait)) next = { text: orderLine(o), wait };
    }
    return next;
  }, [standing.orders]);

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
  const planAttention = s ? mine(s.attention) : [];
  const bookHalts = Object.keys(halt.books ?? {}).length;
  const moverScale = Math.max(0, ...holdings.map((p) => Math.abs(p.unrealizedPnl ?? 0)));
  const unrealized = holdings.reduce((sum, p) => sum + (conv(p.unrealizedPnl, p.currency).value ?? 0), 0);
  const refreshAll = () => { summary.refresh(); curves.refresh(); ledgers.refresh(); standing.list.refresh(); };

  // everything that waits for the person, most urgent first
  const attention = useStore((st) => st.attention);
  const other = ws === 'live' ? 'practice' : 'live';
  const otherWaiting = attention.drafts[other] + attention.failed[other];
  const todos: { key: string; icon: keyof typeof Ionicons.glyphMap; ink: string; title: string; sub?: string; action: string; go: () => void }[] = [];
  if (so.failed > 0) todos.push({ key: 'failed', icon: 'warning', ink: t.down, title: `${so.failed} standing order${so.failed > 1 ? 's' : ''} failed`, sub: 'Open it to see the broker\'s reason.', action: 'Look', go: () => openOrders('standing') });
  if (so.draft > 0) todos.push({ key: 'draft', icon: 'alarm-outline', ink: t.accent, title: `${so.draft} standing order${so.draft > 1 ? 's' : ''} to arm`, sub: 'Drafted from your plan. They do nothing until you arm them.', action: 'Arm', go: () => openOrders('standing') });
  if (proposals.length > 0) todos.push({ key: 'cards', icon: 'chatbubble-ellipses-outline', ink: t.accent, title: `${proposals.length} tip card${proposals.length > 1 ? 's' : ''} to decide`, sub: proposals.slice(0, 4).map((p) => p.symbol).join(' · '), action: 'Review', go: () => router.navigate('/tips') });
  if (otherWaiting > 0) todos.push({ key: 'other', icon: 'swap-horizontal', ink: t.accent, title: `${otherWaiting} standing order${otherWaiting > 1 ? 's' : ''} need you in ${other === 'live' ? 'Live' : 'Practice'}`, sub: 'They belong to accounts of the other workspace.', action: 'Switch', go: () => { setWorkspace(other); openOrders('standing'); } });
  for (const a of planAttention) todos.push({ key: a.runId, icon: 'alert-circle-outline', ink: t.warn, title: `${a.symbol} plan needs attention`, sub: a.reasons.join(' · '), action: 'Open', go: () => openOrders('plans') });

  const working = so.armed + so.working;
  // today's events of this workspace: drop the ones that belong to the other side's plans
  const timeline = useMemo(() => {
    if (!s) return [];
    const other = new Set([...s.inTrade, ...s.watching].filter((x) => workspaceOf(x.workspace) !== ws).map((x) => x.runId));
    return s.timeline.filter((e) => !other.has(e.runId));
  }, [s, ws]);

  return (
    <Screen attention={false} onRefresh={refreshAll} refreshing={summary.refreshing}>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: space.sm }}>
        <MarketLine />
        <CurrencySwitch />
      </View>
      {(halt.engaged || (broker && !broker.feedConnected) || (ws === 'live' && broker?.ibkrConnected === false) || bookHalts > 0) && (
        <View style={styles.wrap}>
          {halt.engaged && <Pill solid kind="bad" text={`Halted${halt.reason ? `: ${halt.reason}` : ''}`} />}
          {broker && !broker.feedConnected && <Pill kind="bad" text="Prices down" />}
          {ws === 'live' && broker?.ibkrConnected === false && <Pill kind="bad" text="IBKR disconnected" />}
          {bookHalts > 0 && <Pill kind="warn" text={`${bookHalts} book${bookHalts > 1 ? 's' : ''} at loss limit`} />}
        </View>
      )}

      {attention.questions.map((q) => <QuestionCard key={q.id} q={q} />)}

      {todos.length > 0 && (
        <Card style={{ borderColor: t.accent, paddingVertical: space.sm }}>
          <Txt v="label" color={t.accent} style={{ paddingTop: space.sm }}>Needs you</Txt>
          {todos.map((x, i) => <TodoRow key={x.key} icon={x.icon} ink={x.ink} title={x.title} sub={x.sub} action={x.action} onPress={x.go} last={i === todos.length - 1} />)}
        </Card>
      )}

      {groups.length === 0 && <Card><Empty text={synced ? `No funded accounts in ${ws === 'live' ? 'Live' : 'Practice'}.` : 'Waiting for the server…'} /></Card>}
      {groups.map((g, i) => (i === 0
        ? <HeroCard key={g.label} label={g.label} books={g.books} curves={curves.data} conv={conv}
            ledger={ledgers.data ? ledgers.data[i] : ledgers.error ? null : undefined} />
        : <GroupLine key={g.label} label={g.label} books={g.books} conv={conv} />))}

      {(working > 0 || watching.length > 0 || inTrade.length > 0) && (
        <View style={{ gap: space.sm }}>
          <Heading icon="alarm-outline" title="Orders at work" />
          <Card style={{ paddingVertical: space.sm }}>
            {working > 0 && (
              <TodoRow icon="alarm-outline" ink={t.warn} last={!(watching.length || inTrade.length)} action="Follow" onPress={() => openOrders('standing')}
                title={`Standing orders · ${[so.working ? `${so.working} working` : '', so.armed ? `${so.armed} armed` : ''].filter(Boolean).join(' · ')}`}
                sub={nextOrder ? `Next: ${nextOrder.text} · ${waitText(nextOrder.wait)}` : undefined} />
            )}
            {(watching.length > 0 || inTrade.length > 0) && (
              <TodoRow icon="flash-outline" ink={inTrade.length ? t.up : t.text2} last action="Open" onPress={() => openOrders('plans')}
                title={`Armed plans · ${inTrade.length} in a trade · ${watching.length} watching`}
                sub={inTrade.length ? inTrade.map((x) => x.symbol).slice(0, 6).join(' · ') : 'The desk\'s own plans, waiting for their price'} />
            )}
          </Card>
        </View>
      )}

      <View style={{ gap: space.sm }}>
        <Heading icon="wallet-outline" title="Accounts today" />
        <Card>
          {books.length === 0 && <Empty text={synced ? 'No funded books in this workspace.' : 'Waiting for the server…'} />}
          {books.map((b, i) => <BookRow key={b.id} book={b} curve={curves.data?.[b.id]} conv={conv} last={i === books.length - 1} />)}
        </Card>
      </View>

      {holdings.length > 0 && (
        <View style={{ gap: space.sm }}>
          <Heading icon="podium-outline" title={`Positions · ${holdings.length}`}
            right={<Delta v="small" value={unrealized} text={`${signedMoney(unrealized, conv(0, holdings[0]?.currency).cur)} open`} />} />
          <Card>
            {(allPositions ? holdings : holdings.slice(0, 5)).map((p, i, all) => (
              <MoverRow key={`${p.portfolioId}:${p.symbol}`} pos={p} bookName={bookOf(p.portfolioId)?.name ?? ''} scale={moverScale} conv={conv} last={i === all.length - 1} />
            ))}
            {holdings.length > 5 && (
              <Txt v="small" color={t.accent} style={{ fontWeight: '700', paddingTop: space.sm }} onPress={() => setAllPositions((v) => !v)}>
                {allPositions ? 'Show the top 5' : `Show all ${holdings.length}`}
              </Txt>
            )}
          </Card>
        </View>
      )}

      <View style={{ gap: space.sm }}>
        <Heading icon="globe-outline" title="The market today" />
        <View style={{ flexDirection: 'row', gap: space.sm }}>
          {INDEX_FUNDS.map((f) => <IndexTile key={f.symbol} symbol={f.symbol} name={f.name} />)}
        </View>
      </View>

      {timeline.length > 0 && (
        <View style={{ gap: space.sm }}>
          <Heading icon="time-outline" title="What happened today"
            right={<Txt v="small" color={t.accent} onPress={() => router.navigate('/alerts')}>Alerts</Txt>} />
          <Card>
            {(allActivity ? timeline.slice(0, 40) : timeline.slice(0, 5)).map((e, i, all) => (
              <Row key={`${e.ts}-${e.runId}-${i}`} last={i === all.length - 1 && timeline.length <= 5}
                left={<Txt><Txt style={{ fontWeight: '700' }}>{e.symbol}</Txt>  {titleCase(e.kind)}</Txt>}
                sub={e.text}
                right={<Txt v="small" dim num>{clock(e.ts)}</Txt>}
                rightSub={e.pnl != null ? <Delta v="small" value={e.pnl} text={signedMoney(e.pnl)} /> : undefined} />
            ))}
            {timeline.length > 5 && (
              <Txt v="small" color={t.accent} style={{ fontWeight: '700', paddingTop: space.sm }} onPress={() => setAllActivity((v) => !v)}>
                {allActivity ? 'Show less' : `Show all ${Math.min(timeline.length, 40)}`}
              </Txt>
            )}
          </Card>
        </View>
      )}

      {groups.map((g, i) => {
        const l = ledgers.data?.[i];
        const days = l ? [...l.days].sort((a, b) => (a.date < b.date ? -1 : 1)).slice(-10) : [];
        // a group with no closed trade has nothing to chart
        if (!l || !days.some((d) => Math.abs(d.realized) > 0.005)) return null;
        return (
          <View key={g.label} style={{ gap: space.sm }}>
            <Heading icon="bar-chart-outline" title={`Closed trades by day${groups.length > 1 ? ` · ${g.label}` : ''}`}
              right={<Txt v="small" color={t.accent} onPress={() => router.navigate('/ledger')}>Money</Txt>} />
            <Card>
              <DayBars items={days.map((d) => ({ label: shortDate(`${d.date}T12:00:00`), value: d.realized }))} format={(v) => signedMoney(v, l.currency ?? 'USD')} />
            </Card>
          </View>
        );
      })}
      {!s && summary.error && <Txt v="small" color={t.down}>{summary.error}</Txt>}
    </Screen>
  );
}
