import Ionicons from '@expo/vector-icons/Ionicons';
import { Tabs } from 'expo-router/js-tabs';
import type { ColorValue } from 'react-native';

import { HeaderRight } from '@/components/Header';
import { useStore } from '@/store';
import { useTheme } from '@/theme';

type IconName = keyof typeof Ionicons.glyphMap;
const icon = (name: IconName) => ({ color, size }: { color: ColorValue; size: number }) => <Ionicons name={name} size={size} color={color as string} />;

export default function TabsLayout() {
  const t = useTheme();
  const pending = useStore((s) => s.proposals.length);
  return (
    <Tabs
      screenOptions={{
        headerStyle: { backgroundColor: t.bg },
        headerTintColor: t.text,
        headerShadowVisible: false,
        headerTitleStyle: { fontWeight: '700' },
        headerRight: () => <HeaderRight />,
        sceneStyle: { backgroundColor: t.bg },
        tabBarStyle: { backgroundColor: t.surface, borderTopColor: t.line },
        tabBarActiveTintColor: t.accent,
        tabBarInactiveTintColor: t.text3,
      }}>
      <Tabs.Screen name="index" options={{ title: 'Now', tabBarIcon: icon('pulse') }} />
      <Tabs.Screen name="portfolio" options={{ title: 'Portfolio', tabBarIcon: icon('wallet-outline') }} />
      <Tabs.Screen name="tips" options={{ title: 'Tips', tabBarIcon: icon('chatbubble-ellipses-outline'), tabBarBadge: pending || undefined }} />
      <Tabs.Screen name="research" options={{ title: 'Research', tabBarIcon: icon('search-outline') }} />
      <Tabs.Screen name="more" options={{ title: 'More', tabBarIcon: icon('ellipsis-horizontal') }} />
    </Tabs>
  );
}
