import { router } from 'expo-router';
import { useEffect, useMemo } from 'react';
import { View } from 'react-native';

import { api } from '@/api/endpoints';
import type { ArmedSummary, Portfolio } from '@/api/types';
import { Heading, Hero, RangeBar, Sparkline, StatTile, SymbolBadge } from '@/components/graphics';
import { Card, Delta, Empty, Pill, Row, Screen, styles, Txt } from '@/components/ui';
import { CurrencySwitch } from '@/components/Header';
import { useConvert, useCurrency } from '@/hooks/useCurrency';
import { usePoll } from '@/hooks/usePoll';
import { useWorkspace } from '@/hooks/useWorkspace';
import { dayMove, dayMovePct, GROUP_LABEL, groupOf, visibleBooks, workspaceOf } from '@/lib/books';
import { clock, money, pct, price, signedMoney, titleCase } from '@/lib/format';
import { useStore } from '@/store';
import { space, useTheme } from '@/theme';

const WINDOW_LABEL: Record<string, string> = {
  open: 'Opening window', close: 'Closing window', midday: 'Midday', pre: 'Pre-market', post: 'After hours', closed: 'Market closed',
};

/** The workspace's money in one card: what it is worth, today's move, and how much
 *  of the result is banked against still riding. Same numbers as the Money screen. */
function LedgerHero({ workspace, scope, label }: { workspace: 'practice' | 'live'; scope?: string; label: string }) {
  const t = useTheme();
  const currency = useCurrency();
  const ledger = usePoll(() => api.ledger(workspace, scope, 30, currency), 60000, [workspace, scope, currency]);
  const l = ledger.data;
  const cur = l?.currency ?? 'USD';
  return (
    <Hero>
      <Txt v="label" color={t.accent}>{label}</Txt>
      <Txt v="hero" num>{l ? money(l.total, cur) : '—'}</Txt>
      {l?.dayMove != null
        ? <Delta value={l.dayMove} text={`${signedMoney(l.dayMove, cur)} today`} />
        : ledger.error && !l ? <Txt dim>{ledger.error}</Txt> : null}
      {l && (
        <View style={{ flexDirection: 'row', gap: space.xl, marginTop: space.sm }}>
          <View>
            <Txt v="small" dim>Banked</Txt>
            <Delta value={l.banked} text={signedMoney(l.banked, cur)} />
          </View>
          <View>
            <Txt v="small" dim>Riding</Txt>
            <Delta value={l.riding} text={signedMoney(l.riding, cur)} />
          </View>
          {l.sinceStart != null && (
            <View>
              <Txt v="small" dim>Since start</Txt>
              <Delta value={l.sinceStart} text={signedMoney(l.sinceStart, cur)} />
            </View>
          )}
        </View>
      )}
    </Hero>
  );
}

function BookRow({ book, last }: { book: Portfolio; last: boolean }) {
  const curve = usePoll(() => api.equity(book.id, { since: Date.now() - 24 * 3600e3, points: 48 }), 300000, [book.id]);
  const values = useMemo(() => {
    const v = (curve.data ?? []).map((p) => p[1]);
    return book.equity != null ? [...v, book.equity] : v;
  }, [curve.data, book.equity]);
  const conv = useConvert();
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

export default function NowScreen() {
  const t = useTheme();
  const ws = useWorkspace();
  const halt = useStore((s) => s.halt);
  const broker = useStore((s) => s.broker);
  const portfolios = useStore((s) => s.portfolios);
  const allProposals = useStore((s) => s.proposals);
  const armedBump = useStore((s) => s.armedBump);
  const synced = useStore((s) => s.synced);
  const summary = usePoll(() => api.armedSummary(), 20000);

  // a plan fired, filled or stopped: re-pull shortly after instead of waiting for the tick
  const refresh = summary.refresh;
  useEffect(() => {
    if (!armedBump) return;
    const timer = setTimeout(refresh, 1500);
    return () => clearTimeout(timer);
  }, [armedBump, refresh]);

  const books = useMemo(() => visibleBooks(portfolios, ws), [portfolios, ws]);
  const proposals = useMemo(
    () => allProposals.filter((p) => workspaceOf(portfolios.find((b) => b.id === p.portfolioId)?.kind) === ws),
    [allProposals, portfolios, ws]);
  // the summary covers every book; show this workspace's share of it
  const mine = <T extends { workspace?: string | null }>(list: T[]) => list.filter((x) => workspaceOf(x.workspace) === ws);
  const s: ArmedSummary | null = summary.data;
  const inTrade = s ? mine(s.inTrade) : [];
  const watching = s ? mine(s.watching) : [];
  const attention = s ? mine(s.attention) : [];
  const bookHalts = Object.keys(halt.books ?? {}).length;
  const heroes = ws === 'practice'
    ? [{ scope: undefined as string | undefined, label: 'Practice' }]
    : [{ scope: 'real', label: 'Real money' }, { scope: 'paper', label: 'Paper account' }];

  return (
    <Screen onRefresh={summary.refresh} refreshing={summary.refreshing}>
      <View style={styles.wrap}>
        {halt.engaged
          ? <Pill kind="bad" text={`Halted${halt.reason ? `: ${halt.reason}` : ''}`} />
          : <Pill kind="ok" text="Trading on" />}
        {s && <Pill text={WINDOW_LABEL[s.window] ?? titleCase(s.window)} kind={s.windowOpenNow ? 'accent' : 'dim'} />}
        {broker && !broker.feedConnected && <Pill kind="bad" text="Prices down" />}
        {ws === 'live' && broker?.ibkrConnected === false && <Pill kind="bad" text="IBKR disconnected" />}
        {bookHalts > 0 && <Pill kind="warn" text={`${bookHalts} book${bookHalts > 1 ? 's' : ''} at loss limit`} />}
        <View style={{ flex: 1 }} />
        <CurrencySwitch />
      </View>

      {heroes.map((h) => <LedgerHero key={h.label} workspace={ws} scope={h.scope} label={h.label} />)}

      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: space.md }}>
        <StatTile icon="mail-unread-outline" label="Cards waiting" value={String(proposals.length)}
          tone={proposals.length ? 'accent' : undefined} onPress={() => router.navigate('/tips')} />
        <StatTile icon="trending-up-outline" label="In a trade" value={String(inTrade.length)}
          tone={inTrade.length ? 'ok' : undefined} onPress={() => router.navigate('/armed')} />
        <StatTile icon="eye-outline" label="Plans watching" value={String(watching.length)} onPress={() => router.navigate('/armed')} />
        <StatTile icon="warning-outline" label="Need attention" value={String(attention.length)}
          tone={attention.length ? 'warn' : undefined} onPress={() => router.navigate('/armed')} />
      </View>

      {(proposals.length > 0 || attention.length > 0) && (
        <View style={{ gap: space.sm }}>
          <Heading icon="hand-left-outline" title="Needs you" />
          <Card>
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
        </View>
      )}

      <View style={{ gap: space.sm }}>
        <Heading icon="wallet-outline" title="Books today" />
        <Card>
          {books.length === 0 && <Empty text={synced ? 'No funded books in this workspace.' : 'Waiting for the server…'} />}
          {books.map((b, i) => <BookRow key={b.id} book={b} last={i === books.length - 1} />)}
        </Card>
      </View>

      {s && (
        <>
          <View style={{ gap: space.sm }}>
            <Heading icon="trending-up-outline" title={`In a trade · ${inTrade.length}`}
              right={inTrade.length ? <Txt v="small" color={t.accent} onPress={() => router.navigate('/armed')}>Manage</Txt> : undefined} />
            <Card>
              {inTrade.length === 0 && <Empty text="No plan is in a trade right now." />}
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

          <View style={{ gap: space.sm }}>
            <Heading icon="eye-outline" title={`Closest to firing · ${watching.length} watching`}
              right={<Txt v="small" color={t.accent} onPress={() => router.navigate('/armed')}>All plans</Txt>} />
            <Card>
              {watching.length === 0 && <Empty text="No plans are armed in this workspace." />}
              {[...watching]
                .sort((a, b) => Math.abs(a.nearest?.distancePct ?? 99) - Math.abs(b.nearest?.distancePct ?? 99))
                .slice(0, 6)
                .map((w, i, all) => (
                  <Row key={w.runId} last={i === all.length - 1}
                    onPress={() => router.navigate({ pathname: '/chart/[symbol]', params: { symbol: w.symbol, entry: String(w.nearest.entry), stop: String(w.nearest.stop), target: w.nearest.targets?.[0] != null ? String(w.nearest.targets[0]) : '' } })}
                    left={<View style={styles.wrap}><SymbolBadge symbol={w.symbol} size={34} /><Txt v="head">{w.symbol}</Txt>{!!w.grade && <Pill kind="accent" text={w.grade} />}{w.stale && <Pill kind="warn" text="stale" />}</View>}
                    sub={`${titleCase(w.nearest.kind)} at ${price(w.nearest.entry)} · ${w.account ?? ''}`}
                    right={<Txt num>{price(w.lastPrice)}</Txt>}
                    rightSub={w.nearest.distancePct != null ? `${Math.abs(w.nearest.distancePct).toFixed(2)}% away` : undefined} />
                ))}
            </Card>
          </View>

          <View style={{ gap: space.sm }}>
            <Heading icon="time-outline" title="Latest" />
            <Card>
              {s.timeline.length === 0 && <Empty text="Nothing has happened yet today." />}
              {s.timeline.slice(0, 8).map((e, i, all) => (
                <Row key={`${e.ts}-${e.runId}-${i}`} last={i === all.length - 1}
                  left={<Txt><Txt style={{ fontWeight: '700' }}>{e.symbol}</Txt>  {titleCase(e.kind)}</Txt>}
                  sub={e.text}
                  right={<Txt v="small" dim num>{clock(e.ts)}</Txt>}
                  rightSub={e.pnl != null ? <Delta v="small" value={e.pnl} text={signedMoney(e.pnl)} /> : undefined} />
              ))}
            </Card>
          </View>
        </>
      )}
      {!s && summary.error && <Txt color={t.down}>{summary.error}</Txt>}
    </Screen>
  );
}
