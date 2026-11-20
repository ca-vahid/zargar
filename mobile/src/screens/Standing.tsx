import Ionicons from '@expo/vector-icons/Ionicons';
import { type ReactNode, useEffect, useMemo, useState } from 'react';
import { ActivityIndicator, Pressable, View } from 'react-native';

import { api } from '@/api/endpoints';
import { DelegationCard } from '@/components/Delegation';
import { BrokerBadge, EmptyArt, Heading, SymbolBadge } from '@/components/graphics';
import { Button, Card, Pill, Problem, Screen, SkeletonRows, styles, Txt } from '@/components/ui';
import { type BookBroker, useBrokers } from '@/hooks/useBrokers';
import { useStanding } from '@/hooks/useStanding';
import { runAction } from '@/lib/actions';
import { clock, price, qty } from '@/lib/format';
import { useBooks } from '@/hooks/useBooks';
import { newYorkDate, newYorkTime } from '@/lib/market';
import {
  armedByText, dayLabel, exitsText, groupPlans, guardText, isOpen, isRunning, minutesToTrigger, orderLine, preflightText, priceSign, sizeText,
  STATUS_LABEL, type StandingOrder, type StandingPlan, type StandingPreflight, statusTone, waitText, whenText,
} from '@/lib/standing';
import { useStore } from '@/store';
import { radius, space, useTheme } from '@/theme';

const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
/** The phone's own day and time a number of minutes from now: "Mon 07:45". */
function localAt(now: number, minutes: number): string {
  const d = new Date(now + minutes * 60000);
  return `${d.toDateString() === new Date(now).toDateString() ? 'today' : DAYS[d.getDay()]} ${clock(d.getTime())}`;
}

/** Where a book's orders go, as a pill: real money is the one that must never be missed. */
function MoneyPill({ kind }: { kind?: string }) {
  if (kind === 'live') return <Pill solid kind="bad" text="REAL MONEY" />;
  if (kind === 'paper') return <Pill kind="dim" text="Paper" />;
  return <Pill kind="dim" text="Practice" />;
}

function Line({ icon, text, color }: { icon: keyof typeof Ionicons.glyphMap; text: string; color?: string }) {
  const t = useTheme();
  return (
    <View style={{ flexDirection: 'row', gap: 6, alignItems: 'flex-start' }}>
      <Ionicons name={icon} size={14} color={color ?? t.text3} style={{ marginTop: 2 }} />
      <Txt v="small" color={color} dim={!color} style={{ flex: 1 }}>{text}</Txt>
    </View>
  );
}

/** One order as a step on its plan's timeline: when, what, the price guard, and where it stands. */
function OrderStep({ o, last, account, at, today, now, busy, preflight, history, onCheck, onDisarm, onCancel }: {
  o: StandingOrder; last: boolean; account?: string; at: ReturnType<typeof newYorkTime>; today: string | null; now: number; busy: boolean;
  preflight?: StandingPreflight; history?: boolean; onCheck: () => void; onDisarm: () => void; onCancel: () => void;
}) {
  const t = useTheme();
  const tone = statusTone(o.status);
  const ink = tone === 'ok' ? t.up : tone === 'bad' ? t.down : tone === 'warn' ? t.warn : t.text3;
  const wait = o.status === 'armed' || o.status === 'draft' ? minutesToTrigger(o, at, today) : null;
  const by = armedByText(o);
  const exits = exitsText(o);
  return (
    <View style={{ flexDirection: 'row', gap: space.md }}>
      <View style={{ alignItems: 'center', width: 14 }}>
        <View style={{ width: 12, height: 12, borderRadius: 6, marginTop: 5, borderWidth: 2, borderColor: ink, backgroundColor: o.status === 'draft' ? 'transparent' : ink }} />
        {!last && <View style={{ flex: 1, width: 2, backgroundColor: t.line, marginTop: 4 }} />}
      </View>
      <View style={{ flex: 1, gap: 6, paddingBottom: last ? 0 : space.lg }}>
        <View style={styles.rowBetween}>
          <Txt v="small" faint num style={{ fontWeight: '700', letterSpacing: 0.4 }}>{whenText(o).toUpperCase()}</Txt>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
            {isRunning(o.status) && <ActivityIndicator size="small" color={t.warn} />}
            <Pill kind={tone} text={STATUS_LABEL[o.status] ?? o.status} />
          </View>
        </View>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: space.sm }}>
          <Pill solid kind={o.side === 'BUY' ? 'ok' : 'bad'} text={o.side} />
          <SymbolBadge symbol={o.symbol} size={28} />
          <Txt v="head">{o.symbol}</Txt>
          <Txt dim num style={{ flexShrink: 1 }} numberOfLines={1}>{sizeText(o)}</Txt>
        </View>
        {!!account && <Line icon="business-outline" text={account} />}
        <Line icon="shield-checkmark-outline" text={`${guardText(o)} · limit within ${o.slippagePct}% of the quote`} />
        {!!exits && <Line icon="flag-outline" text={`After it fills: ${exits}`} />}
        {!!by && <Line icon="key-outline" color={t.accent} text={by} />}
        {wait != null && !history && (
          <Line icon="time-outline" text={wait <= 0 ? 'Its window is open now' : `Can fire ${waitText(wait)} · ${localAt(now, wait)} your time`} />
        )}
        {o.filledQty > 0 && <Line icon="checkmark-circle" color={t.up} text={`Filled ${qty(o.filledQty)} at ${priceSign(o.symbol)}${price(o.avgFillPrice)}`} />}
        {o.attempts.length > 1 && isOpen(o.status) && <Line icon="repeat-outline" text={`Re-priced ${o.attempts.length - 1} time${o.attempts.length > 2 ? 's' : ''}`} />}
        {!!o.lastError && o.status !== 'done' && (o.status === 'failed'
          ? <Line icon="warning" color={t.down} text={o.lastError} />
          : isOpen(o.status) && <Line icon="hourglass-outline" text={/^waiting/i.test(o.lastError) ? o.lastError.replace(/^w/, 'W').replace(/(\d{4}-\d{2}-\d{2})/, (d) => dayLabel(d)) : `Waiting: ${o.lastError}`} />)}
        {preflight && <Line icon={preflight.ok ? 'checkmark-circle-outline' : 'close-circle-outline'} color={preflight.ok ? t.up : t.down}
          text={`Check: ${preflightText(preflight)}`} />}
        {!history && isOpen(o.status) && (
          <View style={{ flexDirection: 'row', gap: space.sm, marginTop: 2 }}>
            <Button small kind="plain" label="Check" disabled={busy} onPress={onCheck} style={{ flex: 1 }} />
            {o.status === 'armed' && <Button small kind="plain" label="Disarm" disabled={busy} onPress={onDisarm} style={{ flex: 1 }} />}
            <Button small kind="plain" label="Cancel" disabled={busy} onPress={onCancel} style={{ flex: 1 }} />
          </View>
        )}
      </View>
    </View>
  );
}

export function StandingScreen({ header }: { header?: ReactNode }) {
  const t = useTheme();
  const brokerOf = useBrokers();
  const [fast, setFast] = useState(false);
  const { list, orders, counts, elsewhere, allowLive, delegations, ws } = useStanding(fast ? 4000 : 15000);
  const books = useBooks(ws);
  const [busy, setBusy] = useState(false);
  const [preflight, setPreflight] = useState<Record<string, StandingPreflight>>({});
  const [showHistory, setShowHistory] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 30000);
    return () => clearInterval(timer);
  }, []);

  const plans = useMemo(() => groupPlans(orders ?? []), [orders]);
  const at = newYorkTime(now);
  const today = newYorkDate(now);
  // while an order is being sent or is working, follow it closely
  const running = counts.working > 0;
  useEffect(() => { setFast(running); }, [running]);

  const next = useMemo(() => {
    let best: { o: StandingOrder; wait: number } | null = null;
    for (const o of orders ?? []) {
      if (o.status !== 'armed') continue;
      const wait = minutesToTrigger(o, at, today);
      if (wait != null && (!best || wait < best.wait)) best = { o, wait };
    }
    return best;
  }, [orders, at, today]);

  const act = async (ask: Parameters<typeof runAction>[0], fn: () => Promise<unknown>, done: string) => {
    setBusy(true);
    const ok = await runAction(ask, fn, done);
    setBusy(false);
    if (ok) list.refresh();
  };

  const check = async (o: StandingOrder) => {
    setBusy(true);
    try {
      const res = await api.standingPreflight(o.id);
      setPreflight((p) => ({ ...p, [o.id]: res }));
    } catch (e: any) {
      useStore.getState().toast('error', e?.message ? String(e.message) : 'The check did not run');
    }
    setBusy(false);
  };

  const arm = (plan: StandingPlan, accounts: BookBroker[]) => {
    const drafts = plan.rows.filter((r) => r.status === 'draft');
    const first = plan.rows[0];
    const real = accounts.some((a) => a.kind === 'live');
    const n = drafts.length;
    return act(
      { title: `${real ? 'REAL MONEY — arm' : 'Arm'} ${n} order${n > 1 ? 's' : ''}?`,
        body: `The app places ${n > 1 ? 'them' : 'it'} on ${n > 1 ? 'their triggers' : 'its trigger'}, inside your price guard${real ? ', with real money' : ''}.`
          + (real && !allowLive ? ' The real-money switch is off: armed orders wait until you turn it on.' : ''),
        lines: drafts.map((d, i) => [`${i + 1}. ${whenText(d)}`, orderLine(d)] as [string, string]),
        confirmLabel: n > 1 ? `Arm ${n} orders` : 'Arm order', danger: real, secure: true },
      () => (first.planId && first.planArmConfirm
        ? api.standingArmPlan(first.planId, first.planArmConfirm) : api.standingArm(first.id, first.armConfirm)),
      `${n} order${n > 1 ? 's' : ''} armed`);
  };

  const disarm = (o: StandingOrder) => act(
    { title: `Disarm ${o.side === 'BUY' ? 'buy' : 'sell'} ${o.symbol}?`, body: 'It goes back to a draft and will not fire until you arm it again.', confirmLabel: 'Disarm' },
    () => api.standingDisarm(o.id), `${o.symbol}: disarmed`);

  const cancel = (o: StandingOrder) => act(
    { title: `Cancel ${o.side === 'BUY' ? 'buy' : 'sell'} ${o.symbol}?`,
      body: isRunning(o.status) ? 'An order is working at the broker: the app cancels it there. Anything already filled stays filled.' : 'This order is removed from the plan for good.',
      confirmLabel: 'Cancel order', danger: true, secure: isRunning(o.status) },
    () => api.standingCancel(o.id), `${o.symbol}: cancelled`);

  const toggleLive = () => act(
    allowLive
      ? { title: 'Turn real money off?', body: 'Armed orders on real accounts stop firing and wait. Orders already at a broker are not touched.', confirmLabel: 'Turn off' }
      : { title: 'Allow real-money orders?', body: 'Armed standing orders on your real accounts will trade when their trigger fires.', confirmLabel: 'Allow real money', danger: true, secure: true },
    () => api.setStandingAllowLive(!allowLive), allowLive ? 'Real money: off' : 'Real money: on');

  const renderPlan = (plan: StandingPlan, history = false) => {
    const first = plan.rows[0];
    const accounts = [...new Map(plan.rows.map((r) => [r.portfolioId, brokerOf(r.portfolioId)])).values()];
    const drafts = plan.rows.filter((r) => r.status === 'draft').length;
    const tone = statusTone(plan.status);
    const edge = history ? t.line : tone === 'warn' ? t.warn : tone === 'bad' ? t.down : tone === 'ok' ? t.up : t.line;
    return (
      <Card key={plan.key} style={{ borderLeftWidth: 4, borderLeftColor: edge, gap: space.md, opacity: history ? 0.75 : 1 }}>
        <View style={{ flexDirection: 'row', gap: space.md, alignItems: 'center' }}>
          <View style={{ flexDirection: 'row', gap: 4 }}>
            {accounts.map((a) => <BrokerBadge key={a.name} name={a.broker} logoUrl={a.logoUrl} size={34} />)}
          </View>
          <View style={{ flex: 1, gap: 2 }}>
            <Txt v="head" numberOfLines={2}>{first.planId ? first.planName : orderLine(first)}</Txt>
            <Txt v="small" dim numberOfLines={1}>{accounts.map((a) => a.name).join(' · ')}</Txt>
          </View>
        </View>
        <View style={styles.wrap}>
          <Pill kind={tone} text={STATUS_LABEL[plan.status] ?? plan.status} />
          {accounts.some((a) => a.kind === 'live') ? <MoneyPill kind="live" /> : <MoneyPill kind={accounts[0]?.kind} />}
          <Txt v="small" faint>until {first.expiresOn}</Txt>
        </View>
        <View>
          {plan.rows.map((o, i) => (
            <OrderStep key={o.id} o={o} last={i === plan.rows.length - 1} account={accounts.length > 1 ? brokerOf(o.portfolioId).name : undefined} at={at} today={today} now={now} busy={busy} preflight={preflight[o.id]} history={history}
              onCheck={() => void check(o)} onDisarm={() => void disarm(o)} onCancel={() => void cancel(o)} />
          ))}
        </View>
        {!history && drafts > 0 && (
          <Button label={first.planId ? `Arm plan (${drafts} order${drafts > 1 ? 's' : ''})` : 'Arm order'} disabled={busy}
            onPress={() => void arm(plan, accounts)} />
        )}
      </Card>
    );
  };

  return (
    <Screen onRefresh={list.refresh} refreshing={list.refreshing}>
      {header}
      {orders == null && (list.error ? <Problem error={list.error} onRetry={list.refresh} /> : <Card><SkeletonRows rows={5} /></Card>)}
      {orders != null && (
        <>
          <View style={{ flexDirection: 'row', gap: space.sm }}>
            {([['Drafts', counts.draft, t.text2], ['Armed', counts.armed, t.warn], ['Working', counts.working, t.accent], ['Failed', counts.failed, t.down]] as const).map(([label, n, ink]) => (
              <View key={label} style={{ flex: 1, backgroundColor: t.surface, borderRadius: radius.md, borderWidth: 1, borderColor: t.line, paddingVertical: space.md, alignItems: 'center', gap: 2 }}>
                <Txt v="title" num color={n ? ink : t.text3}>{n}</Txt>
                <Txt v="small" dim>{label}</Txt>
              </View>
            ))}
          </View>

          {next && (
            <Card style={{ flexDirection: 'row', alignItems: 'center', gap: space.md }}>
              <View style={{ width: 38, height: 38, borderRadius: 19, backgroundColor: `${t.warn}22`, alignItems: 'center', justifyContent: 'center' }}>
                <Ionicons name="alarm-outline" size={20} color={t.warn} />
              </View>
              <View style={{ flex: 1, gap: 2 }}>
                <Txt v="small" dim>Next to fire</Txt>
                <Txt style={{ fontWeight: '700' }}>{orderLine(next.o)}</Txt>
                <Txt v="small" dim>{next.wait <= 0 ? 'Its window is open now' : `${waitText(next.wait)} · ${localAt(now, next.wait)} your time (${next.o.notBefore ?? '09:30'} ET)`}</Txt>
              </View>
            </Card>
          )}

          {ws === 'live' && <Pressable onPress={() => { if (!busy) void toggleLive(); }} accessibilityRole="button"
            accessibilityLabel={allowLive ? 'Real money is on. Turn it off' : 'Real money is off. Turn it on'}
            style={{ flexDirection: 'row', alignItems: 'center', gap: space.md, borderRadius: radius.lg, borderWidth: 1, padding: space.lg,
              borderColor: allowLive ? t.downFill : t.line, backgroundColor: allowLive ? `${t.downFill}1f` : t.surface }}>
            <Ionicons name={allowLive ? 'lock-open' : 'lock-closed'} size={22} color={allowLive ? t.down : t.text3} />
            <View style={{ flex: 1, gap: 2 }}>
              <Txt style={{ fontWeight: '700' }} color={allowLive ? t.down : t.text}>{allowLive ? 'Real money is ON' : 'Real money is off'}</Txt>
              <Txt v="small" dim>{allowLive
                ? 'Armed orders on your real accounts trade when their trigger fires.'
                : 'Armed orders on real accounts wait until you turn this on.'}</Txt>
            </View>
            <Txt v="small" color={t.accent} style={{ fontWeight: '700' }}>{allowLive ? 'Turn off' : 'Turn on'}</Txt>
          </Pressable>}

          {ws === 'live' && <DelegationCard delegations={delegations} books={books} onChanged={list.refresh} />}

          {list.error && <Txt v="small" color={t.down}>Not refreshed: {list.error}</Txt>}

          {plans.open.length === 0
            ? <EmptyArt text={elsewhere > 0
                ? `${elsewhere} open standing order${elsewhere > 1 ? 's are' : ' is'} in the ${ws === 'live' ? 'Practice' : 'Live'} workspace. Switch at the top to see ${elsewhere > 1 ? 'them' : 'it'}.`
                : `No open standing orders in ${ws === 'live' ? 'Live' : 'Practice'}. Tell Claude your plan on the desk — the orders appear here for you to arm.`} />
            : (
              <View style={{ gap: space.sm }}>
                <Heading icon="list-outline" title={`Open plans · ${plans.open.length}`} />
                <View style={{ gap: space.lg }}>{plans.open.map((p) => renderPlan(p))}</View>
              </View>
            )}

          {plans.closed.length > 0 && (
            <View style={{ gap: space.md }}>
              <Button small kind="plain" label={`${showHistory ? 'Hide' : 'Show'} history (${plans.closed.length})`} onPress={() => setShowHistory((v) => !v)} />
              {showHistory && plans.closed.map((p) => renderPlan(p, true))}
            </View>
          )}
        </>
      )}
    </Screen>
  );
}
