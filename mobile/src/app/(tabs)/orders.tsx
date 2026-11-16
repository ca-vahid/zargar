import { useLocalSearchParams } from 'expo-router';
import { type ReactNode, useEffect, useMemo, useState } from 'react';

import { api } from '@/api/endpoints';
import type { Order } from '@/api/types';
import { EmptyArt } from '@/components/graphics';
import { Card, Pill, Row, Screen, styles, Tabs, Txt } from '@/components/ui';
import { useBooks } from '@/hooks/useBooks';
import { useWorkspace } from '@/hooks/useWorkspace';
import { runAction } from '@/lib/actions';
import { dayTime, price, qty } from '@/lib/format';
import { ArmedScreen } from '@/screens/Armed';
import { StandingScreen } from '@/screens/Standing';
import { useStore } from '@/store';
import { View } from 'react-native';

type Tab = 'standing' | 'plans' | 'broker';
const isTab = (v: unknown): v is Tab => v === 'standing' || v === 'plans' || v === 'broker';

/** Every order resting at a broker right now, across this workspace's accounts. */
function AtBroker({ header }: { header: ReactNode }) {
  const ws = useWorkspace();
  const books = useBooks(ws, true);
  const ordersMap = useStore((s) => s.openOrders);
  const orders = useMemo(() => {
    const names = new Map(books.map((b) => [b.id, b.name]));
    return Object.values(ordersMap).filter((o) => names.has(o.portfolioId))
      .sort((a, b) => (a.createdAt < b.createdAt ? 1 : -1)).map((o) => ({ o, book: names.get(o.portfolioId) ?? '' }));
  }, [ordersMap, books]);

  // only an unfilled BUY can be cancelled from the phone: that takes risk off. Stops and
  // targets are the position manager's, and cancelling one would leave a position bare.
  const cancel = (o: Order) => runAction(
    { title: `Cancel this ${o.symbol} buy order?`, lines: [['Order', `Buy ${qty(o.qty)} ${o.orderType}`], ['Price', price(o.limitPrice ?? o.stopPrice)]],
      confirmLabel: 'Cancel order', danger: true, secure: true },
    () => api.cancelOrder(o.id), `${o.symbol}: cancel sent`);

  return (
    <Screen>
      {header}
      {orders.length === 0
        ? <EmptyArt text={`No order is resting at a broker in ${ws === 'live' ? 'Live' : 'Practice'} right now. Stops, targets and unfilled entries show here.`} />
        : (
          <Card>
            {orders.map(({ o, book }, i) => (
              <Row key={o.id} last={i === orders.length - 1} onPress={o.side === 'BUY' ? () => void cancel(o) : undefined}
                left={<View style={styles.wrap}>
                  <Pill solid kind={o.side === 'BUY' ? 'ok' : 'bad'} text={o.side} />
                  <Txt v="head">{o.option?.short ?? o.symbol}</Txt>
                  <Txt dim num>{qty(o.qty)}</Txt>
                </View>}
                sub={`${o.orderType === 'STP' ? 'Stop' : o.orderType === 'LMT' ? 'Limit' : o.orderType} ${price(o.stopPrice ?? o.limitPrice)} · ${o.tif} · ${o.status.toLowerCase()} · ${book}`}
                right={<Txt v="small" dim num>{dayTime(o.createdAt)}</Txt>} />
            ))}
            <Txt v="small" faint style={{ paddingTop: 8 }}>Tap an unfilled buy to cancel it. Stops and targets are managed by the desk.</Txt>
          </Card>
        )}
    </Screen>
  );
}

/** Everything that can trade without another tap: your standing orders, the desk's armed
 *  plans, and what is resting at a broker. */
export default function OrdersScreen() {
  const params = useLocalSearchParams<{ tab?: string }>();
  const [tab, setTab] = useState<Tab>(isTab(params.tab) ? params.tab : 'standing');
  // a notification or a Home card names the view to open
  useEffect(() => { if (isTab(params.tab)) setTab(params.tab); }, [params.tab]);
  // counted for the workspace on screen, like everything else on this tab
  const ws = useWorkspace();
  const books = useBooks(ws, true);
  const ordersMap = useStore((s) => s.openOrders);
  const atBroker = useMemo(() => {
    const ids = new Set(books.map((b) => b.id));
    return Object.values(ordersMap).filter((o) => ids.has(o.portfolioId)).length;
  }, [ordersMap, books]);
  const badge = useStore((s) => s.standingBadge);

  const header = (
    <Tabs value={tab} onChange={setTab} options={[
      { key: 'standing', label: 'Standing', badge: badge || undefined },
      { key: 'plans', label: 'Armed plans' },
      { key: 'broker', label: atBroker ? `At broker · ${atBroker}` : 'At broker' },
    ]} />
  );
  if (tab === 'plans') return <ArmedScreen header={header} />;
  if (tab === 'broker') return <AtBroker header={header} />;
  return <StandingScreen header={header} />;
}
