import { useState } from 'react';
import { View } from 'react-native';

import { api } from '@/api/endpoints';
import type { Ledger } from '@/api/types';
import { Async, Card, Delta, Empty, Row, Screen, Section, styles, Tabs, Txt } from '@/components/ui';
import { usePoll } from '@/hooks/usePoll';
import { money, price, qty, shortDate, signedMoney } from '@/lib/format';

type Tab = 'practice' | 'paper' | 'real';
const QUERY: Record<Tab, { workspace: 'practice' | 'live'; scope?: string }> = {
  practice: { workspace: 'practice' },
  paper: { workspace: 'live', scope: 'paper' },
  real: { workspace: 'live', scope: 'real' },
};

export default function LedgerScreen() {
  const [tab, setTab] = useState<Tab>('practice');
  const ledger = usePoll(() => api.ledger(QUERY[tab].workspace, QUERY[tab].scope, 30), 120000, [tab]);

  return (
    <Screen onRefresh={ledger.refresh} refreshing={ledger.refreshing}>
      <Tabs value={tab} onChange={setTab} options={[
        { key: 'practice', label: 'Practice' }, { key: 'paper', label: 'Paper' }, { key: 'real', label: 'Real money' },
      ]} />
      <Async state={ledger}>
        {(l: Ledger) => {
          const cur = l.currency ?? 'USD';
          const days = l.days.filter((d) => d.trips.length > 0 || d.adjustments.length > 0);
          return (
            <>
              <View style={{ gap: 2 }}>
                <Txt v="label" faint>{(l.books ?? []).join(' · ')}</Txt>
                <Txt v="hero" num>{money(l.total, cur)}</Txt>
                {l.dayMove != null && <Delta value={l.dayMove} text={`${signedMoney(l.dayMove, cur)} today`} />}
              </View>
              <Card>
                {l.sinceStart != null && (
                  <View style={styles.rowBetween}><Txt dim>Since the start</Txt><Delta value={l.sinceStart} text={signedMoney(l.sinceStart, cur)} /></View>
                )}
                <View style={styles.rowBetween}><Txt dim>Banked (closed trades, after fees)</Txt><Delta value={l.banked} text={signedMoney(l.banked, cur)} /></View>
                <View style={styles.rowBetween}><Txt dim>Riding (open positions)</Txt><Delta value={l.riding} text={signedMoney(l.riding, cur)} /></View>
                <View style={styles.rowBetween}><Txt dim>Last 30 days, closed</Txt><Delta value={l.realized} text={signedMoney(l.realized, cur)} /></View>
                {!!l.fxMissing?.length && <Txt v="small" dim>No exchange rate for {l.fxMissing.join(', ')}: those amounts are left out.</Txt>}
              </Card>

              <Section title={`Open · ${l.open.length}`}>
                <Card>
                  {l.open.length === 0 && <Empty text="Nothing is open." />}
                  {l.open.map((o, i) => (
                    <Row key={`${o.portfolio}${o.symbol}${o.inAt}`} last={i === l.open.length - 1}
                      left={o.label || o.symbol} sub={`${qty(o.qty)} @ ${price(o.inPrice)} · ${o.portfolio}`}
                      right={<Delta value={o.unrealized} text={signedMoney(o.unrealized, cur)} />}
                      rightSub={o.mark != null ? `now ${price(o.mark)}` : undefined} />
                  ))}
                </Card>
              </Section>

              <Section title="Closed trades by day">
                {days.length === 0 && <Card><Empty text="No closed trades in the last 30 days." /></Card>}
                {days.map((d) => (
                  <Card key={d.date}>
                    <View style={styles.rowBetween}>
                      <Txt v="head">{shortDate(`${d.date}T12:00:00`)}</Txt>
                      <Delta v="head" value={d.realized} text={signedMoney(d.realized, cur)} />
                    </View>
                    {d.trips.map((x, i) => (
                      <Row key={`${x.symbol}${x.outAt}${i}`} last={i === d.trips.length - 1 && d.adjustments.length === 0}
                        left={<Txt>{x.label || x.symbol}</Txt>}
                        sub={`${qty(x.qty)} · in ${price(x.inPrice)} → out ${price(x.outPrice)} · fees ${money(x.fees, cur)}${x.outReason ? ` · ${x.outReason}` : ''}`}
                        right={<Delta value={x.gain} text={signedMoney(x.gain, cur)} />} />
                    ))}
                    {d.adjustments.map((a, i) => (
                      <Row key={`${a.at}${i}`} last={i === d.adjustments.length - 1}
                        left={<Txt dim>Adjustment</Txt>} sub={a.reason}
                        right={<Delta value={a.amount} text={signedMoney(a.amount, cur)} />} />
                    ))}
                  </Card>
                ))}
              </Section>
            </>
          );
        }}
      </Async>
    </Screen>
  );
}
