import { Pressable, View } from 'react-native';

import { api } from '../api/endpoints';
import { setCurrency, useCurrency } from '../hooks/useCurrency';
import { setWorkspace, useWorkspace } from '../hooks/useWorkspace';
import { runAction } from '../lib/actions';
import { useStore } from '../store';
import { space, useTheme } from '../theme';
import { Txt } from './ui';

/** Live-link dot: green = streaming, amber = reconnecting, red = offline. */
export function ConnDot() {
  const t = useTheme();
  const conn = useStore((s) => s.conn);
  const color = conn === 'live' ? t.up : conn === 'connecting' ? t.warn : t.down;
  const label = conn === 'live' ? 'Live' : conn === 'connecting' ? 'Connecting' : 'Offline';
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }} accessibilityLabel={`Connection: ${label}`}>
      <View style={{ width: 8, height: 8, borderRadius: 4, backgroundColor: color }} />
      {conn !== 'live' && <Txt v="small" dim>{label}</Txt>}
    </View>
  );
}

/** The kill switch, on every screen. Engaging stops every new entry on every book;
 *  exits keep working. Releasing it is the same button. */
export function HaltButton() {
  const t = useTheme();
  const engaged = useStore((s) => s.halt.engaged);
  const reason = useStore((s) => s.halt.reason);
  const press = () => {
    if (engaged) {
      void runAction(
        { title: 'Release the kill switch?', body: `Trading resumes on every book.${reason ? ` It was engaged for: ${reason}` : ''}`,
          confirmLabel: 'Release', secure: true },
        () => api.resume(),
        'Kill switch released',
      );
    } else {
      void runAction(
        { title: 'Stop all trading?', body: 'No new entries on any book until you release it. Open positions keep their stops and exits still work.',
          confirmLabel: 'HALT', danger: true, secure: true },
        () => api.halt('phone'),
        'Kill switch engaged',
      );
    }
  };
  return (
    <Pressable onPress={press} accessibilityRole="button" accessibilityLabel={engaged ? 'Release the kill switch' : 'Halt all trading'}
      hitSlop={8}
      style={{ borderRadius: 6, paddingHorizontal: 10, paddingVertical: 6, borderWidth: 1.5,
        borderColor: t.downFill, backgroundColor: engaged ? t.downFill : 'transparent' }}>
      <Txt v="small" color={engaged ? '#ffffff' : t.down} style={{ fontWeight: '800', letterSpacing: 0.8 }}>
        {engaged ? 'HALTED' : 'HALT'}
      </Txt>
    </Pressable>
  );
}

/** Live | Practice — changes only what is on screen, never where orders go. */
export function WorkspaceSwitch() {
  const t = useTheme();
  const ws = useWorkspace();
  const seg = (key: 'live' | 'practice', label: string) => {
    const on = ws === key;
    return (
      <Pressable key={key} onPress={() => setWorkspace(key)} accessibilityRole="button" accessibilityState={{ selected: on }}
        accessibilityLabel={`${label} workspace`} hitSlop={4}
        style={{ paddingHorizontal: 11, paddingVertical: 6, borderRadius: 999, backgroundColor: on ? t.accent : 'transparent' }}>
        <Txt v="small" color={on ? t.onAccent : t.text2} style={{ fontWeight: on ? '800' : '600' }}>{label}</Txt>
      </Pressable>
    );
  };
  return (
    <View style={{ flexDirection: 'row', borderRadius: 999, borderWidth: 1, borderColor: t.line, backgroundColor: t.surface, padding: 2 }}>
      {seg('live', 'Live')}
      {seg('practice', 'Practice')}
    </View>
  );
}

/** USD | CAD for money totals. Share prices stay in the stock's own currency. */
export function CurrencySwitch() {
  const t = useTheme();
  const cur = useCurrency();
  const seg = (key: 'USD' | 'CAD') => {
    const on = cur === key;
    return (
      <Pressable key={key} onPress={() => setCurrency(key)} accessibilityRole="button" accessibilityState={{ selected: on }}
        accessibilityLabel={`Show money in ${key}`} hitSlop={6}
        style={{ paddingHorizontal: 10, paddingVertical: 4, borderRadius: 999, backgroundColor: on ? t.surface3 : 'transparent' }}>
        <Txt v="small" color={on ? t.text : t.text3} style={{ fontWeight: on ? '800' : '600' }}>{key}</Txt>
      </Pressable>
    );
  };
  return (
    <View style={{ flexDirection: 'row', borderRadius: 999, borderWidth: 1, borderColor: t.line, padding: 2, alignSelf: 'flex-start' }}>
      {seg('USD')}
      {seg('CAD')}
    </View>
  );
}

export function HeaderRight({ workspace }: { workspace?: boolean }) {
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', gap: space.md, marginRight: space.lg }}>
      {workspace && <WorkspaceSwitch />}
      <ConnDot />
      <HaltButton />
    </View>
  );
}
