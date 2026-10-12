import { useEffect, useState } from 'react';
import { Switch, View } from 'react-native';

import { api } from '@/api/endpoints';
import { canLock } from '@/auth/lock';
import { setLockEnabled, signOut } from '@/auth/session';
import { CurrencySwitch } from '@/components/Header';
import { Button, Card, Row, Screen, Section, Txt } from '@/components/ui';
import { APP_VERSION } from '@/config';
import { runAction } from '@/lib/actions';
import { fetchUpdate, restartIntoUpdate, updateInfo } from '@/lib/updates';
import { disablePush, enablePush, pushState, type PushState } from '@/notifications/push';
import { useStore } from '@/store';
import { useTheme } from '@/theme';

export default function SettingsScreen() {
  const t = useTheme();
  const user = useStore((s) => s.user);
  const apiUrl = useStore((s) => s.apiUrl);
  const lockEnabled = useStore((s) => s.lockEnabled);
  const exitOnly = useStore((s) => s.settings['mobile.exit_only']);
  const [push, setPush] = useState<PushState | null>(null);
  const [lockable, setLockable] = useState(false);
  const [busy, setBusy] = useState(false);
  const [checking, setChecking] = useState(false);
  const upd = updateInfo();
  const toast = useStore.getState().toast;

  useEffect(() => {
    void pushState().then(setPush);
    void canLock().then(setLockable);
  }, []);

  const togglePush = async (on: boolean) => {
    setBusy(true);
    try {
      const next = on ? await enablePush() : await disablePush();
      setPush(next);
      if (next.status === 'unavailable') toast('error', next.why);
    } catch (e: any) {
      toast('error', e?.message ? String(e.message) : 'Could not change notifications');
    } finally {
      setBusy(false);
    }
  };

  const testPush = async () => {
    try {
      const res = await api.pushTest();
      toast(res.sent ? 'ok' : 'info', res.sent ? 'Test notification sent' : 'The server has no device to send to');
    } catch (e: any) {
      toast('error', e?.message ? String(e.message) : 'Test failed');
    }
  };

  return (
    <Screen>
      <Section title="Notifications">
        <Card>
          <Row last={push?.status !== 'on'} left="Notify this phone"
            sub={push?.status === 'unavailable' ? push.why : 'Approval cards, fills and stops, alerts, and the kill switch'}
            right={<Switch value={push?.status === 'on'} disabled={busy || push == null || push.status === 'unavailable'}
              onValueChange={(v) => void togglePush(v)} trackColor={{ true: t.accent, false: t.surface3 }} />} />
          {push?.status === 'on' && <Button small kind="plain" label="Send a test notification" onPress={() => void testPush()} />}
        </Card>
      </Section>

      <Section title="Display">
        <Card>
          <Row last left="Show money in" sub="Totals, gains and losses. Share prices stay in the stock's own currency." right={<CurrencySwitch />} />
        </Card>
      </Section>

      <Section title="Security">
        <Card>
          <Row left="Lock the app" sub={lockable ? 'Ask for fingerprint or PIN when you come back after two minutes' : 'Set a screen lock on this phone to use this'}
            right={<Switch value={lockEnabled} disabled={!lockable}
              onValueChange={(v) => void setLockEnabled(v).then((ok) => { if (!ok) toast('error', 'This phone has no screen lock set'); })}
              trackColor={{ true: t.accent, false: t.surface3 }} />} />
          <Row last left="Entries from this phone"
            sub={<Txt v="small" dim>{exitOnly === false
              ? 'The server allows new manual orders from phones. This app still offers none.'
              : 'The server refuses new manual orders from phones on real and paper accounts. Approving a card, halting, pausing and exits all work.'}</Txt>}
            right={<Txt dim>{exitOnly === false ? 'Allowed' : 'Exit only'}</Txt>} />
        </Card>
        <Txt v="small" faint>Approving a card, the kill switch, pausing a book and closing a position always ask for your fingerprint or PIN.</Txt>
      </Section>

      <Section title="Account">
        <Card>
          <Row left="Signed in as" right={<Txt dim>{user?.email || '—'}</Txt>} />
          <Row left="Server" right={<Txt dim style={{ maxWidth: 210 }} numberOfLines={1}>{apiUrl.replace(/^https?:\/\//, '')}</Txt>} />
          <Row last left="App version"
            sub={upd.enabled ? (upd.embedded ? 'Running the installed build' : `Running update ${(upd.id ?? '').slice(0, 8)}`) : 'Over-the-air updates are off in this build'}
            right={<Txt dim num>{APP_VERSION}</Txt>} />
        </Card>
        {upd.enabled && (
          <Button small kind="plain" label="Check for an update" busy={checking}
            onPress={() => { setChecking(true); void fetchUpdate().then((ready) => { setChecking(false); if (ready) void restartIntoUpdate(); else toast('info', 'You have the latest version'); }); }} />
        )}
        <View>
          <Button kind="plain" label="Sign out"
            onPress={() => void runAction(
              { title: 'Sign out?', body: 'You will sign in with Google again next time. To change the server address, sign out first.', confirmLabel: 'Sign out', danger: true },
              async () => { await disablePush().catch(() => {}); await signOut(); }, 'Signed out')} />
        </View>
      </Section>
    </Screen>
  );
}
