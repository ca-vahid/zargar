import { DarkTheme, DefaultTheme, ThemeProvider } from 'expo-router';
import { Stack } from 'expo-router/stack';
import * as SplashScreen from 'expo-splash-screen';
import { StatusBar } from 'expo-status-bar';
import { useEffect, useRef } from 'react';
import { ActivityIndicator, AppState, View } from 'react-native';

import { boot } from '@/auth/session';
import { HeaderRight } from '@/components/Header';
import { LockScreen } from '@/components/LockScreen';
import { LoginScreen } from '@/components/LoginScreen';
import { ConfirmHost, ToastHost } from '@/components/Overlays';
import { bindNotifications, ensureChannels } from '@/notifications/push';
import { useStore } from '@/store';
import { useTheme } from '@/theme';

void SplashScreen.preventAutoHideAsync().catch(() => {});

/** Away longer than this and the app asks for the fingerprint again (when the lock is on). */
const RELOCK_AFTER_MS = 2 * 60 * 1000;

export default function RootLayout() {
  const t = useTheme();
  const booted = useStore((s) => s.booted);
  const signedIn = useStore((s) => !!s.user);
  const locked = useStore((s) => s.locked);
  const leftAt = useRef(0);

  useEffect(() => {
    void boot().finally(() => { void SplashScreen.hideAsync().catch(() => {}); });
    void ensureChannels().catch(() => {});
  }, []);

  useEffect(() => {
    if (!signedIn) return;
    return bindNotifications();
  }, [signedIn]);

  useEffect(() => {
    const sub = AppState.addEventListener('change', (state) => {
      if (state !== 'active') {
        if (!leftAt.current) leftAt.current = Date.now();
        return;
      }
      const away = leftAt.current ? Date.now() - leftAt.current : 0;
      leftAt.current = 0;
      const s = useStore.getState();
      if (s.lockEnabled && s.user && away > RELOCK_AFTER_MS) s.set({ locked: true });
    });
    return () => sub.remove();
  }, []);

  const base = t.dark ? DarkTheme : DefaultTheme;
  const nav = { ...base, colors: { ...base.colors, background: t.bg, card: t.bg, text: t.text, border: t.line, primary: t.accent } };

  let body;
  if (!booted) {
    body = <View style={{ flex: 1, backgroundColor: t.bg, alignItems: 'center', justifyContent: 'center' }}><ActivityIndicator color={t.text3} /></View>;
  } else if (!signedIn) {
    body = <LoginScreen />;
  } else {
    body = (
      <Stack screenOptions={{ headerStyle: { backgroundColor: t.bg }, headerTintColor: t.text, headerShadowVisible: false,
        contentStyle: { backgroundColor: t.bg }, headerRight: () => <HeaderRight /> }}>
        <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
        <Stack.Screen name="alerts" options={{ title: 'Alerts' }} />
        <Stack.Screen name="armed" options={{ title: 'Armed plans' }} />
        <Stack.Screen name="ledger" options={{ title: 'Money' }} />
        <Stack.Screen name="system" options={{ title: 'System' }} />
        <Stack.Screen name="settings" options={{ title: 'Settings' }} />
        <Stack.Screen name="chart/[symbol]" options={{ title: 'Chart' }} />
        <Stack.Screen name="dossier/[id]" options={{ title: 'Research note' }} />
      </Stack>
    );
  }

  return (
    <ThemeProvider value={nav}>
      <StatusBar style={t.dark ? 'light' : 'dark'} />
      {body}
      {/* drawn OVER the navigator, which stays mounted so a notification tap can still route */}
      {booted && signedIn && locked && (
        <View style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0 }}><LockScreen /></View>
      )}
      <ConfirmHost />
      <ToastHost />
    </ThemeProvider>
  );
}
