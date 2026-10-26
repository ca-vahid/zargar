import Ionicons from '@expo/vector-icons/Ionicons';
import { router } from 'expo-router';
import { useState } from 'react';
import { TextInput, View } from 'react-native';

import { Button, Card, Row, Screen, Txt } from '@/components/ui';
import { APP_VERSION } from '@/config';
import { useStore } from '@/store';
import { radius, space, useTheme } from '@/theme';

type IconName = keyof typeof Ionicons.glyphMap;

export default function MoreScreen() {
  const t = useTheme();
  const user = useStore((s) => s.user);
  const liveAlerts = useStore((s) => s.liveAlerts.length);
  const [symbol, setSymbol] = useState('');
  const clean = symbol.trim().toUpperCase();

  const item = (icon: IconName, label: string, sub: string, href: string, last = false) => (
    <Row key={href} last={last} onPress={() => router.navigate(href as any)}
      left={<View style={{ flexDirection: 'row', alignItems: 'center', gap: space.md }}>
        <Ionicons name={icon} size={20} color={t.text2} />
        <Txt v="head">{label}</Txt>
      </View>}
      sub={sub}
      right={<Ionicons name="chevron-forward" size={18} color={t.text3} />} />
  );

  return (
    <Screen>
      <Card>
        <Txt v="label" faint>Open a chart</Txt>
        <View style={{ flexDirection: 'row', gap: space.sm }}>
          <TextInput value={symbol} onChangeText={setSymbol} placeholder="Symbol, e.g. SPY" placeholderTextColor={t.text3}
            autoCapitalize="characters" autoCorrect={false} maxLength={10} accessibilityLabel="Symbol"
            onSubmitEditing={() => clean && router.navigate({ pathname: '/chart/[symbol]', params: { symbol: clean } })}
            style={{ flex: 1, backgroundColor: t.surface2, color: t.text, borderRadius: radius.sm, paddingHorizontal: space.md, fontSize: 15, minHeight: 46 }} />
          <Button label="Chart" disabled={!clean} onPress={() => router.navigate({ pathname: '/chart/[symbol]', params: { symbol: clean } })} />
        </View>
      </Card>

      <Card>
        {item('notifications-outline', 'Alerts', liveAlerts ? `${liveAlerts} new since you opened the app` : 'What the desk flagged, newest first', '/alerts')}
        {item('flash-outline', 'Armed plans', 'Every plan waiting for its level, and the ones in a trade', '/armed')}
        {item('cash-outline', 'Money', 'What each workspace made and lost, in plain numbers', '/ledger')}
        {item('pulse-outline', 'System', 'Server, brokers, price feed and tip intake', '/system')}
        {item('settings-outline', 'Settings', 'Notifications, app lock, server address, sign out', '/settings', true)}
      </Card>

      <Txt v="small" faint style={{ textAlign: 'center' }}>
        {user?.email ? `${user.email} · ` : ''}App {APP_VERSION}
      </Txt>
    </Screen>
  );
}
