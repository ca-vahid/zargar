import Ionicons from '@expo/vector-icons/Ionicons';
import { router } from 'expo-router';
import { useState } from 'react';
import { Pressable, TextInput, View } from 'react-native';

import { Button, Card, Txt } from '@/components/ui';
import { Screen } from '@/components/ui';
import { APP_VERSION } from '@/config';
import { useStore } from '@/store';
import { radius, space, useTheme } from '@/theme';

type IconName = keyof typeof Ionicons.glyphMap;

export default function MoreScreen() {
  const t = useTheme();
  const user = useStore((s) => s.user);
  const liveAlerts = useStore((s) => s.liveAlerts.length);
  const questions = useStore((s) => s.attention.questions.length);
  const [symbol, setSymbol] = useState('');
  const clean = symbol.trim().toUpperCase();
  const chart = () => clean && router.navigate({ pathname: '/chart/[symbol]', params: { symbol: clean } });

  const item = (icon: IconName, ink: string, label: string, sub: string, href: string, last = false, note?: string) => (
    <Pressable key={href} onPress={() => router.navigate(href as any)} accessibilityRole="button" accessibilityLabel={label} android_ripple={{ color: t.surface3 }}
      style={{ flexDirection: 'row', alignItems: 'center', gap: space.md, paddingVertical: space.md, borderBottomWidth: last ? 0 : 0.5, borderBottomColor: t.line }}>
      <View style={{ width: 40, height: 40, borderRadius: radius.md, backgroundColor: `${ink}22`, alignItems: 'center', justifyContent: 'center' }}>
        <Ionicons name={icon} size={21} color={ink} />
      </View>
      <View style={{ flex: 1, gap: 2 }}>
        <Txt v="head">{label}</Txt>
        <Txt v="small" dim numberOfLines={2}>{sub}</Txt>
      </View>
      {!!note && (
        <View style={{ backgroundColor: t.accent, borderRadius: 999, minWidth: 20, paddingHorizontal: 6, alignItems: 'center' }}>
          <Txt v="small" color={t.onAccent} style={{ fontWeight: '700' }}>{note}</Txt>
        </View>
      )}
      <Ionicons name="chevron-forward" size={18} color={t.text3} />
    </Pressable>
  );

  return (
    <Screen>
      <Card>
        <Txt v="label" faint>Open a chart</Txt>
        <View style={{ flexDirection: 'row', gap: space.sm }}>
          <TextInput value={symbol} onChangeText={setSymbol} placeholder="Symbol, e.g. SPY" placeholderTextColor={t.text3}
            autoCapitalize="characters" autoCorrect={false} maxLength={10} accessibilityLabel="Symbol" onSubmitEditing={chart}
            style={{ flex: 1, backgroundColor: t.surface2, color: t.text, borderRadius: radius.sm, paddingHorizontal: space.md, fontSize: 15, minHeight: 46 }} />
          <Button label="Chart" disabled={!clean} onPress={chart} />
        </View>
      </Card>

      <Card style={{ paddingVertical: space.sm }}>
        {item('help-circle-outline', t.accent, 'Questions for you', 'What Claude asked, and what you answered', '/questions', false, questions ? String(questions) : undefined)}
        {item('notifications-outline', t.warn, 'Alerts', 'What the desk flagged, newest first', '/alerts', false, liveAlerts ? String(liveAlerts) : undefined)}
        {item('cash-outline', t.up, 'Money', 'What each workspace made and lost, in plain numbers', '/ledger')}
        {item('telescope-outline', t.series, 'Research', 'Company notes, the Scout screen and the Scout agent', '/research', true)}
      </Card>

      <Card style={{ paddingVertical: space.sm }}>
        {item('pulse-outline', t.series3, 'System', 'Server, brokers, price feed and tip intake', '/system')}
        {item('settings-outline', t.text2, 'Settings', 'Notifications, app lock, updates, sign out', '/settings', true)}
      </Card>

      <Txt v="small" faint style={{ textAlign: 'center' }}>
        {user?.email ? `${user.email} · ` : ''}App {APP_VERSION}
      </Txt>
    </Screen>
  );
}
