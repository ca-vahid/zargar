import { Pressable, View } from 'react-native';

import { api } from '../api/endpoints';
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

export function HeaderRight() {
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', gap: space.md, marginRight: space.lg }}>
      <ConnDot />
      <HaltButton />
    </View>
  );
}
