import { router } from 'expo-router';
import { useEffect, useState } from 'react';
import { View } from 'react-native';

import { api } from '@/api/endpoints';
import type { ArmedSummary } from '@/api/types';
import { Async, Button, Card, Delta, Empty, Pill, Row, Screen, Section, styles, Tabs, Txt } from '@/components/ui';
import { usePoll } from '@/hooks/usePoll';
import { runAction, sellNow } from '@/lib/actions';
import { dayTime, price, qty, signedMoney, titleCase } from '@/lib/format';
import { useStore } from '@/store';
import { space } from '@/theme';

type Tab = 'trade' | 'watching' | 'stopped';

export default function ArmedScreen() {
  const [tab, setTab] = useState<Tab>('trade');
  const summary = usePoll(() => api.armedSummary(), 20000);
  const armedBump = useStore((s) => s.armedBump);
  const refresh = summary.refresh;
  useEffect(() => {
    if (!armedBump) return;
    const timer = setTimeout(refresh, 1500);
    return () => clearTimeout(timer);
  }, [armedBump, refresh]);

  const pause = (w: ArmedSummary['watching'][number]) => {
    const paused = w.status === 'paused';
    return runAction(
      paused
        ? { title: `Resume the ${w.symbol} plan?`, body: 'It can take its entry again when the level comes.', confirmLabel: 'Resume', secure: true }
        : { title: `Pause the ${w.symbol} plan?`, body: 'It stops watching for its entry until you resume it. Nothing is sold.', confirmLabel: 'Pause' },
      () => (paused ? api.armedResume(w.runId) : api.armedPause(w.runId)),
      `${w.symbol}: ${paused ? 'resumed' : 'paused'}`,
    ).then((ok) => { if (ok) refresh(); });
  };

  return (
    <Screen onRefresh={summary.refresh} refreshing={summary.refreshing}>
      <Async state={summary}>
        {(s: ArmedSummary) => (
          <>
            <View style={styles.wrap}>
              <Pill kind="accent" text={`${s.counts.armed} armed`} />
              <Pill kind={s.counts.inTrade ? 'ok' : 'dim'} text={`${s.counts.inTrade} in a trade`} />
              {s.counts.paused > 0 && <Pill kind="warn" text={`${s.counts.paused} paused`} />}
              {s.counts.attention > 0 && <Pill kind="bad" text={`${s.counts.attention} need attention`} />}
            </View>
            <Card>
              <View style={styles.rowBetween}>
                <Txt dim>Today, armed plans</Txt>
                <Delta value={s.pnl.realized + s.pnl.unrealized} text={signedMoney(s.pnl.realized + s.pnl.unrealized)} />
              </View>
              <Txt v="small" dim num>
                Banked {signedMoney(s.pnl.realized)} · open {signedMoney(s.pnl.unrealized)}
                {s.pnl.lossLimitUsedPct != null ? ` · ${s.pnl.lossLimitUsedPct.toFixed(0)}% of the loss limit used` : ''}
              </Txt>
            </Card>

            <Tabs value={tab} onChange={setTab} options={[
              { key: 'trade', label: 'In a trade', badge: s.inTrade.length },
              { key: 'watching', label: 'Watching' },
              { key: 'stopped', label: 'Stopped today' },
            ]} />

            {tab === 'trade' && (s.inTrade.length === 0
              ? <Empty text="No plan is in a trade right now." />
              : s.inTrade.map((x) => (
                <Card key={`${x.runId}-${x.triggerId}`}>
                  <View style={styles.rowBetween}>
                    <View style={styles.wrap}>
                      <Txt v="title">{x.symbol}</Txt>
                      <Pill kind={x.direction === 'short' ? 'bad' : 'ok'} text={x.direction} />
                    </View>
                    <Delta v="head" value={x.unrealizedPnl} text={signedMoney(x.unrealizedPnl)} />
                  </View>
                  <Txt v="small" dim num>
                    {x.account ?? ''} · {qty(x.remaining)} of {qty(x.filledQty)} left{x.orderSymbol && x.orderSymbol !== x.symbol ? ` · ${x.orderSymbol}` : ''}
                  </Txt>
                  <Txt num>
                    {/* an option trade's entry is its premium; stop and targets are the share price */}
                    {x.underlyingEntry != null && x.underlyingEntry !== x.entry
                      ? `Paid ${price(x.entry)} with the shares at ${price(x.underlyingEntry)}`
                      : `In at ${price(x.entry)}`} · stop {price(x.stop)}{x.nextTarget != null ? ` · next target ${price(x.nextTarget)}` : ''}
                    {x.unrealizedR != null ? ` · ${x.unrealizedR >= 0 ? '+' : ''}${x.unrealizedR.toFixed(2)} R` : ''}
                  </Txt>
                  <View style={{ flexDirection: 'row', gap: space.sm }}>
                    <Button small kind="plain" label="Chart" style={{ flex: 1 }}
                      onPress={() => router.navigate({ pathname: '/chart/[symbol]', params: { symbol: x.symbol, entry: String(x.underlyingEntry ?? x.entry), stop: String(x.stop), target: x.nextTarget != null ? String(x.nextTarget) : '' } })} />
                    <Button small kind="danger" label="Sell now" style={{ flex: 1 }}
                      onPress={() => void sellNow(x.symbol, () => api.armedExit(x.runId, x.triggerId)).then((ok) => { if (ok) refresh(); })} />
                  </View>
                </Card>
              )))}

            {tab === 'watching' && (
              <Card>
                {s.watching.length === 0 && <Empty text="No plans are armed." />}
                {[...s.watching]
                  .sort((a, b) => Math.abs(a.nearest?.distancePct ?? 99) - Math.abs(b.nearest?.distancePct ?? 99))
                  .map((w, i, all) => (
                    <Row key={w.runId} last={i === all.length - 1} onPress={() => void pause(w)}
                      left={<View style={styles.wrap}>
                        <Txt v="head">{w.symbol}</Txt>
                        {!!w.grade && <Pill text={w.grade} />}
                        {w.status === 'paused' && <Pill kind="warn" text="paused" />}
                        {w.stale && <Pill kind="warn" text="stale price" />}
                      </View>}
                      sub={`${titleCase(w.nearest.kind)} at ${price(w.nearest.entry)}, stop ${price(w.nearest.stop)} · ${w.account ?? ''} · ${w.mode}`}
                      right={<Txt num>{price(w.lastPrice)}</Txt>}
                      rightSub={w.nearest.distancePct != null ? `${Math.abs(w.nearest.distancePct).toFixed(2)}% away` : undefined} />
                  ))}
                {s.watching.length > 0 && <Txt v="small" faint style={{ paddingTop: space.sm }}>Tap a plan to pause or resume it.</Txt>}
              </Card>
            )}

            {tab === 'stopped' && (
              <Section title={`${s.stoppedToday.length} stopped today`}>
                <Card>
                  {s.stoppedToday.length === 0 && <Empty text="No plan has stopped today." />}
                  {s.stoppedToday.map((x, i) => (
                    <Row key={x.runId} last={i === s.stoppedToday.length - 1}
                      left={x.symbol} sub={x.reason}
                      right={x.realizedPnl != null ? <Delta value={x.realizedPnl} text={signedMoney(x.realizedPnl)} /> : undefined}
                      rightSub={x.at ? dayTime(x.at) : undefined} />
                  ))}
                </Card>
              </Section>
            )}
          </>
        )}
      </Async>
    </Screen>
  );
}
