import Ionicons from '@expo/vector-icons/Ionicons';
import { useEffect, useState } from 'react';
import { ActivityIndicator, View } from 'react-native';

import { APP_VERSION } from '@/config';
import { checkUpdate, restartIntoUpdate, updateInfo, type UpdateCheck } from '@/lib/updates';
import { WHATS_NEW } from '@/lib/whatsNew';
import { radius, space, useTheme } from '@/theme';
import { Button, Card, Txt } from './ui';

type IconName = keyof typeof Ionicons.glyphMap;
type Status = { state: 'idle' } | { state: 'checking' } | UpdateCheck;

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
function when(d: Date): string {
  const h = d.getHours();
  return `${MONTHS[d.getMonth()]} ${d.getDate()}, ${h % 12 || 12}:${String(d.getMinutes()).padStart(2, '0')} ${h < 12 ? 'AM' : 'PM'}`;
}
function ago(ms: number): string {
  const s = Math.round(ms / 1000);
  if (s < 45) return 'just now';
  const m = Math.round(s / 60);
  return m < 60 ? `${m} min ago` : `${Math.round(m / 60)} h ago`;
}

/** Settings → which code this phone runs, what it brought, and the way to a newer one. */
export function UpdateCard() {
  const t = useTheme();
  const info = updateInfo();
  const [status, setStatus] = useState<Status>({ state: 'idle' });
  const [checkedAt, setCheckedAt] = useState<number | null>(null);
  const [, tick] = useState(0);

  useEffect(() => { // keep "checked 2 min ago" honest
    if (checkedAt == null) return;
    const id = setInterval(() => tick((n) => n + 1), 30_000);
    return () => clearInterval(id);
  }, [checkedAt]);

  const check = async () => {
    setStatus({ state: 'checking' });
    const res = await checkUpdate();
    setStatus(res);
    setCheckedAt(Date.now());
  };

  const badge: { icon: IconName; text: string; ink: string; spin?: boolean } =
    !info.enabled || status.state === 'off' ? { icon: 'cloud-offline-outline', text: 'Updates off in this build', ink: t.text3 }
      : status.state === 'checking' ? { icon: 'sync-outline', text: 'Checking…', ink: t.text2, spin: true }
        : status.state === 'ready' ? { icon: 'arrow-down-circle', text: 'New version downloaded', ink: t.accent }
          : status.state === 'failed' ? { icon: 'alert-circle-outline', text: 'Could not check', ink: t.warn }
            : { icon: 'checkmark-circle', text: 'Up to date', ink: t.up };

  const running = info.embedded ? 'the installed build' : `update ${(info.id ?? '').slice(0, 8)}`;

  return (
    <Card style={{ gap: space.md }}>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: space.md }}>
        <View style={{ width: 48, height: 48, borderRadius: radius.md, backgroundColor: t.accent, alignItems: 'center', justifyContent: 'center' }}>
          <Txt v="title" color={t.onAccent}>Z</Txt>
        </View>
        <View style={{ flex: 1, gap: 4 }}>
          <Txt v="head">Zargar <Txt dim num>{APP_VERSION}</Txt></Txt>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
            {badge.spin ? <ActivityIndicator size="small" color={badge.ink} /> : <Ionicons name={badge.icon} size={16} color={badge.ink} />}
            <Txt v="small" color={badge.ink} style={{ fontWeight: '600' }}>{badge.text}</Txt>
          </View>
        </View>
      </View>

      <View style={{ backgroundColor: t.surface2, borderRadius: radius.md, padding: space.md, gap: 6 }}>
        <Txt v="small" dim>
          Running {running}{info.publishedAt ? `, published ${when(info.publishedAt)}` : ''}
        </Txt>
        {status.state === 'ready' && (
          <Txt v="small" color={t.accent}>
            A newer version{status.publishedAt ? ` from ${when(status.publishedAt)}` : ''} is ready. Restart to use it.
          </Txt>
        )}
        {status.state === 'failed' && <Txt v="small" color={t.warn} numberOfLines={2}>{status.why}</Txt>}
      </View>

      {!info.embedded && info.enabled && (
        <View style={{ gap: 6 }}>
          <Txt v="label" faint>What's new</Txt>
          <Txt v="body" style={{ fontWeight: '600' }}>{WHATS_NEW.title}</Txt>
          {WHATS_NEW.items.map((item) => (
            <View key={item} style={{ flexDirection: 'row', gap: space.sm }}>
              <View style={{ width: 5, height: 5, borderRadius: 3, backgroundColor: t.accent, marginTop: 7 }} />
              <Txt v="small" dim style={{ flex: 1 }}>{item}</Txt>
            </View>
          ))}
        </View>
      )}

      {info.enabled && (
        <View style={{ gap: 6 }}>
          {status.state === 'ready'
            ? <Button label="Restart to update" onPress={() => void restartIntoUpdate()} />
            : <Button kind="plain" label={status.state === 'failed' ? 'Try again' : 'Check for updates'}
                busy={status.state === 'checking'} onPress={() => void check()} />}
          <Txt v="small" faint style={{ textAlign: 'center' }}>
            {checkedAt ? `Checked ${ago(Date.now() - checkedAt)}` : 'The app also checks every time it starts'}
          </Txt>
        </View>
      )}
    </Card>
  );
}
