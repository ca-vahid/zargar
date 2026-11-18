import Ionicons from '@expo/vector-icons/Ionicons';
import { useState } from 'react';
import { TextInput, View } from 'react-native';

import { api } from '../api/endpoints';
import type { Portfolio } from '../api/types';
import { runAction } from '../lib/actions';
import { dayTime, money } from '../lib/format';
import type { StandingDelegation } from '../lib/standing';
import { radius, space, useTheme } from '../theme';
import { Meter } from './graphics';
import { Button, Card, Chips, Txt } from './ui';

type Span = 'today' | '3d' | '7d';
const HOURS: Record<Span, number> = { today: 0, '3d': 72, '7d': 168 };

/** "You're free to arm": the person's time-boxed go-ahead for Claude to arm plans itself.
 *  The server enforces the window, the accounts and both money caps on every such arm, and
 *  never lets it touch the real-money switch, risk limits or the kill switch. */
export function DelegationCard({ delegations, books, onChanged }: { delegations: StandingDelegation[]; books: Portfolio[]; onChanged: () => void }) {
  const t = useTheme();
  const active = delegations.find((d) => d.active);
  const [open, setOpen] = useState(false);
  const [span, setSpan] = useState<Span>('today');
  const [perBuy, setPerBuy] = useState('');
  const [total, setTotal] = useState('');
  const [busy, setBusy] = useState(false);
  const real = books.filter((b) => b.kind === 'live');
  const names = (ids: string[]) => ids.map((id) => books.find((b) => b.id === id)?.name ?? id.slice(0, 6)).join(' · ');

  if (active) {
    const used = active.maxTotalNotional ? active.committed / active.maxTotalNotional : 0;
    return (
      <Card style={{ borderColor: t.accent, gap: space.sm }}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: space.sm }}>
          <Ionicons name="key" size={18} color={t.accent} />
          <Txt style={{ fontWeight: '700', flex: 1 }}>Claude may arm for you</Txt>
          <Txt v="small" color={t.accent} style={{ fontWeight: '700' }} onPress={() => {
            if (busy) return;
            setBusy(true);
            void runAction({ title: 'Stop the delegation?', body: 'Claude can no longer arm plans itself. Orders already armed carry on.', confirmLabel: 'Stop it' },
              () => api.standingRevoke(active.id), 'Delegation stopped').then((ok) => { setBusy(false); if (ok) onChanged(); });
          }}>Stop</Txt>
        </View>
        <Txt v="small" dim>Until {dayTime(active.endsAt)} · {names(active.portfolioIds)}</Txt>
        <Txt v="small" dim num>Up to {money(active.maxOrderNotional)} a buy · {money(active.committed)} of {money(active.maxTotalNotional)} used</Txt>
        <Meter value={used} height={4} />
      </Card>
    );
  }

  const per = Number(perBuy.replace(/[^0-9.]/g, ''));
  const tot = Number(total.replace(/[^0-9.]/g, ''));
  const valid = per > 0 && tot >= per && real.length > 0;
  const give = () => {
    const end = new Date();
    if (span === 'today') end.setHours(23, 59, 0, 0);
    else end.setTime(end.getTime() + HOURS[span] * 3600e3);
    setBusy(true);
    void runAction(
      { title: 'REAL MONEY — let Claude arm plans?',
        body: 'Claude may arm standing plans itself (your chat plans, fixes of failed orders, Scout ideas) inside these limits. It cannot change the real-money switch, risk limits or the kill switch, and you are told of every arm.',
        lines: [['Until', dayTime(end.getTime())], ['Accounts', real.map((b) => b.name).join(', ')], ['Most per buy', money(per)], ['Most in total', money(tot)]],
        confirmLabel: 'Delegate', danger: true, secure: true },
      () => api.standingDelegate({ portfolioIds: real.map((b) => b.id), endsAt: end.toISOString().replace('Z', '+00:00'), maxOrderNotional: per, maxTotalNotional: tot }),
      'Claude may arm for you').then((ok) => { setBusy(false); if (ok) { setOpen(false); onChanged(); } });
  };
  const input = { flex: 1, backgroundColor: t.surface2, color: t.text, borderRadius: radius.sm, paddingHorizontal: space.md, fontSize: 15, minHeight: 44 } as const;

  return (
    <Card style={{ gap: space.md }}>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: space.sm }}>
        <Ionicons name="key-outline" size={18} color={t.text3} />
        <View style={{ flex: 1 }}>
          <Txt style={{ fontWeight: '700' }}>You arm every plan yourself</Txt>
          <Txt v="small" dim>Away for a while? Let Claude arm for you, inside limits you set.</Txt>
        </View>
        <Txt v="small" color={t.accent} style={{ fontWeight: '700' }} onPress={() => setOpen((v) => !v)}>{open ? 'Close' : 'Set up'}</Txt>
      </View>
      {open && (
        <>
          <Chips value={span} onChange={setSpan} options={[{ key: 'today', label: 'Until tonight' }, { key: '3d', label: '3 days' }, { key: '7d', label: '1 week' }]} />
          <View style={{ flexDirection: 'row', gap: space.sm }}>
            <TextInput value={perBuy} onChangeText={setPerBuy} placeholder="Most per buy, $" placeholderTextColor={t.text3} keyboardType="numeric" accessibilityLabel="Most per buy" style={input} />
            <TextInput value={total} onChangeText={setTotal} placeholder="Most in total, $" placeholderTextColor={t.text3} keyboardType="numeric" accessibilityLabel="Most in total" style={input} />
          </View>
          <Txt v="small" faint>{real.length ? `Covers ${real.map((b) => b.name).join(', ')}. Sells are not limited; a buy with no price limit is never armed for you.` : 'No real account to cover.'}</Txt>
          <Button label="Delegate arming" disabled={busy || !valid} onPress={give} />
        </>
      )}
    </Card>
  );
}
