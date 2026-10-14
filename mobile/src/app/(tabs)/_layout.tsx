import Ionicons from '@expo/vector-icons/Ionicons';
import { Image } from 'expo-image';
import { Tabs } from 'expo-router/js-tabs';
import { type ColorValue, View } from 'react-native';

import { HeaderRight } from '@/components/Header';
import { Txt } from '@/components/ui';
import { useWorkspace } from '@/hooks/useWorkspace';
import { workspaceOf } from '@/lib/books';
import { useStore } from '@/store';
import { useTheme } from '@/theme';

type IconName = keyof typeof Ionicons.glyphMap;
const icon = (on: IconName, off: IconName) => ({ color, size, focused }: { color: ColorValue; size: number; focused: boolean }) => (
  <Ionicons name={focused ? on : off} size={size} color={color as string} />
);

function Brand() {
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
      <Image source={require('../../../assets/images/splash-icon.png')} style={{ width: 30, height: 30 }} contentFit="contain" />
      <Txt v="title">Zargar</Txt>
    </View>
  );
}

export default function TabsLayout() {
  const t = useTheme();
  const ws = useWorkspace();
  const portfolios = useStore((s) => s.portfolios);
  const proposals = useStore((s) => s.proposals);
  // the badge counts the cards of the workspace on screen
  const pending = proposals.filter((p) => workspaceOf(portfolios.find((b) => b.id === p.portfolioId)?.kind) === ws).length;
  return (
    <Tabs
      screenOptions={{
        headerStyle: { backgroundColor: t.bg },
        headerTintColor: t.text,
        headerShadowVisible: false,
        headerTitleAlign: 'left',
        headerTitleStyle: { fontWeight: '700' },
        headerRight: () => <HeaderRight workspace />,
        sceneStyle: { backgroundColor: t.bg },
        tabBarStyle: { backgroundColor: t.surface, borderTopColor: t.line },
        tabBarActiveTintColor: t.accent,
        tabBarInactiveTintColor: t.text3,
        tabBarLabelStyle: { fontWeight: '600' },
      }}>
      <Tabs.Screen name="index" options={{ title: 'Home', headerTitle: () => <Brand />, tabBarIcon: icon('home', 'home-outline') }} />
      <Tabs.Screen name="portfolio" options={{ title: 'Portfolio', tabBarIcon: icon('wallet', 'wallet-outline') }} />
      <Tabs.Screen name="tips" options={{ title: 'Tips', tabBarIcon: icon('chatbubble-ellipses', 'chatbubble-ellipses-outline'), tabBarBadge: pending || undefined }} />
      <Tabs.Screen name="research" options={{ title: 'Research', tabBarIcon: icon('telescope', 'telescope-outline') }} />
      <Tabs.Screen name="more" options={{ title: 'More', tabBarIcon: icon('grid', 'grid-outline') }} />
    </Tabs>
  );
}