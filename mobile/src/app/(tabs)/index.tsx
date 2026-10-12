import { router } from 'expo-router';
import { useEffect, useMemo } from 'react';
import { View } from 'react-native';

import { api } from '@/api/endpoints';
import type { ArmedSummary } from '@/api/types';
import { Async, Card, Delta, Empty, Pill, Row, Screen, Section, styles, Txt } from '@/components/ui';
import { usePoll } from '@/hooks/usePoll';
import { dayMove, dayMovePct, GROUP_LABEL, groupOf, visibleBooks } from '@/lib/books';
import { clock, money, pct, price, signedMoney, titleCase } from '@/lib/format';
import { useStore } from '@/store';
import { space, useTheme } from '@/theme';

const WINDOW_LABEL: Record<string, string> = {
  open: 'Opening window', close: 'Closing window', midday: 'Midday', pre: 'Pre-market', post: 'After hours', closed: 'Market closed',
};

export default function NowScreen() {
  const t = useTheme();
  const halt = useStore((s) => s.halt);
  const broker = useStore((s) => s.broker);
  const portfolios = useStore((s) => s.portfolios);
  const proposals = useStore((s) => s.proposals);
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

  const books = useMemo(() => visibleBooks(portfolios), [portfolios]);
  const s = summary.data;
  const bookHalts = Object.keys(halt.books ?? {}).length;

  return (
    <Screen onRefresh={summary.refresh} refreshing={summary.refreshing}>
      <View style={styles.wrap}>
        {halt.engaged
          ? <Pill kind="bad" text={`Halted${halt.reason ? `: ${halt.reason}` : ''}`} />
          : <Pill kind="ok" text="Trading on" />}
        {s && <Pill text={WINDOW_LABEL[s.window] ?? titleCase(s.window)} kind={s.windowOpenNow ? 'accent' : 'dim'} />}
        {broker && <Pill kind={broker.feedConnected ? 'ok' : 'bad'} text={broker.feedConnected ? 'Prices live' : 'Prices down'} />}
        {broker?.ibkrConnected != null && <Pill kind={broker.ibkrConnected ? 'ok' : 'bad'} text={broker.ibkrConnected ? 'IBKR connected' : 'IBKR disconnected'} />}
        {bookHalts > 0 && <Pill kind="warn" text={`${bookHalts} book${bookHalts > 1 ? 's' : ''} at loss limit`} />}
      </View>

      {(proposals.length > 0 || (s?.attention.length ?? 0) > 0) && (
        <Section title="Needs you">
          <Card>
            {proposals.length > 0 && (
              <Row last={!s?.attention.length} onPress={() => router.navigate('/tips')}
                left={`${proposals.length} approval card${proposals.length > 1 ? 's' : ''} waiting`}
                sub={proposals.slice(0, 4).map((p) => p.symbol).join(' · ')}
                right={<Txt color={t.accent}>Review</Txt>} />
            )}
            {(s?.attention ?? []).map((a, i, all) => (
              <Row key={a.runId} last={i === all.length - 1} onPress={() => router.navigate('/armed')}
                left={<View style={styles.wrap}><Txt v="head">{a.symbol}</Txt><Pill kind="warn" text="Attention" /></View>}
                sub={a.reasons.join(' · ')} />
            ))}
          </Card>
        </Section>
      )}

      <Section title="Today">
        <Card>
          {!synced && books.length === 0 ? <Empty text="Waiting for the server…" /> : null}
          {books.map((b, i) => (
            <Row key={b.id} last={i === books.length - 1}
              onPress={() => { useStore.getState().set({ selectedBook: b.id }); router.navigate('/portfolio'); }}
              left={b.name} sub={GROUP_LABEL[groupOf(b)]}
              right={<Txt num>{money(b.equity ?? b.cash, b.baseCurrency)}</Txt>}
              rightSub={<Delta v="small" value={dayMove(b)} text={`${signedMoney(dayMove(b), b.baseCurrency)}  ${pct(dayMovePct(b))}`} />} />
          ))}
        </Card>
      </Section>

      <Async state={summary}>
        {(sum: ArmedSummary) => (
          <>
            <Section title={`In a trade · ${sum.inTrade.length}`}>
              <Card>
                {sum.inTrade.length === 0 && <Empty text="No plan is in a trade right now." />}
                {sum.inTrade.map((x, i) => (
                  <Row key={`${x.runId}-${x.triggerId}`} last={i === sum.inTrade.length - 1}
                    onPress={() => router.navigate({ pathname: '/chart/[symbol]', params: { symbol: x.symbol, entry: String(x.underlyingEntry ?? x.entry), stop: String(x.stop), target: x.nextTarget != null ? String(x.nextTarget) : '' } })}
                    left={<View style={styles.wrap}><Txt v="head">{x.symbol}</Txt><Pill kind={x.direction === 'short' ? 'bad' : 'ok'} text={x.direction} /></View>}
                    sub={`${x.account ?? ''} · stop ${price(x.stop)}${x.nextTarget != null ? ` · next target ${price(x.nextTarget)}` : ''}`}
                    right={<Delta value={x.unrealizedPnl} text={signedMoney(x.unrealizedPnl)} />}
                    rightSub={x.unrealizedR != null ? `${x.unrealizedR >= 0 ? '+' : ''}${x.unrealizedR.toFixed(2)} R` : undefined} />
                ))}
                {sum.inTrade.length > 0 && (
                  <Txt v="small" color={t.accent} style={{ paddingTop: space.sm }}
                    onPress={() => router.navigate('/armed')}>Manage in Armed plans</Txt>
                )}
              </Card>
            </Section>

            <Section title={`Watching · ${sum.counts.watching}`}
              right={<Txt v="small" color={t.accent} onPress={() => router.navigate('/armed')}>All plans</Txt>}>
              <Card>
                {sum.watching.length === 0 && <Empty text="No plans are armed." />}
                {[...sum.watching]
                  .sort((a, b) => Math.abs(a.nearest?.distancePct ?? 99) - Math.abs(b.nearest?.distancePct ?? 99))
                  .slice(0, 6)
                  .map((w, i, all) => (
                    <Row key={w.runId} last={i === all.length - 1}
                      onPress={() => router.navigate({ pathname: '/chart/[symbol]', params: { symbol: w.symbol, entry: String(w.nearest.entry), stop: String(w.nearest.stop), target: w.nearest.targets?.[0] != null ? String(w.nearest.targets[0]) : '' } })}
                      left={<View style={styles.wrap}><Txt v="head">{w.symbol}</Txt>{!!w.grade && <Pill text={w.grade} />}{w.stale && <Pill kind="warn" text="stale" />}</View>}
                      sub={`${titleCase(w.nearest.kind)} at ${price(w.nearest.entry)} · ${w.account ?? ''}`}
                      right={<Txt num>{price(w.lastPrice)}</Txt>}
                      rightSub={w.nearest.distancePct != null ? `${Math.abs(w.nearest.distancePct).toFixed(2)}% away` : undefined} />
                  ))}
              </Card>
            </Section>

            <Section title="Latest">
              <Card>
                {sum.timeline.length === 0 && <Empty text="Nothing has happened yet today." />}
                {sum.timeline.slice(0, 8).map((e, i, all) => (
                  <Row key={`${e.ts}-${e.runId}-${i}`} last={i === all.length - 1}
                    left={<Txt><Txt style={{ fontWeight: '700' }}>{e.symbol}</Txt>  {titleCase(e.kind)}</Txt>}
                    sub={e.text}
                    right={<Txt v="small" dim num>{clock(e.ts)}</Txt>}
                    rightSub={e.pnl != null ? <Delta v="small" value={e.pnl} text={signedMoney(e.pnl)} /> : undefined} />
                ))}
              </Card>
            </Section>
          </>
        )}
      </Async>
    </Screen>
  );
}
