import { Image } from 'expo-image';
import { useState } from 'react';
import { KeyboardAvoidingView, Platform, Pressable, ScrollView, TextInput, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { SignInCancelled } from '@/auth/google';
import { setApiUrl, signInWithGoogle, signInWithToken } from '@/auth/session';
import { APP_VERSION } from '@/config';
import { useStore } from '@/store';
import { radius, space, useTheme } from '@/theme';

import { Button, Txt } from './ui';

export function LoginScreen() {
  const t = useTheme();
  const insets = useSafeAreaInsets();
  const apiUrl = useStore((s) => s.apiUrl);
  const [busy, setBusy] = useState<'google' | 'token' | 'server' | null>(null);
  const [error, setError] = useState<string | null>(null);
  // the web preview has no Google sign-in, so its token field starts open
  const [advanced, setAdvanced] = useState(Platform.OS === 'web');
  const [token, setToken] = useState('');
  const [server, setServer] = useState(apiUrl);
  const [serverNote, setServerNote] = useState<string | null>(null);

  const run = async (kind: 'google' | 'token' | 'server', fn: () => Promise<void>) => {
    setBusy(kind);
    setError(null);
    try {
      await fn();
    } catch (e: any) {
      if (!(e instanceof SignInCancelled)) setError(e?.message ? String(e.message) : 'Sign-in failed');
    } finally {
      setBusy(null);
    }
  };

  const input = {
    backgroundColor: t.surface2, color: t.text, borderRadius: radius.sm, paddingHorizontal: space.md,
    paddingVertical: 10, fontSize: 14,
  } as const;

  return (
    <KeyboardAvoidingView style={{ flex: 1, backgroundColor: t.bg }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <ScrollView keyboardShouldPersistTaps="handled"
        contentContainerStyle={{ flexGrow: 1, justifyContent: 'center', padding: space.xl, paddingTop: insets.top + space.xl, gap: space.lg }}>
        <View style={{ alignItems: 'center', gap: space.md, marginBottom: space.lg }}>
          <Image source={require('../../assets/images/splash-icon.png')} style={{ width: 88, height: 88 }} contentFit="contain" />
          <Txt v="hero">Zargar</Txt>
          <Txt dim>Your trading desk, on your phone</Txt>
        </View>

        {Platform.OS !== 'web' && (
          <Button label="Sign in with Google" busy={busy === 'google'} disabled={!!busy}
            onPress={() => run('google', signInWithGoogle)} />
        )}
        {!!error && <Txt color={t.down} accessibilityRole="alert">{error}</Txt>}

        <Pressable onPress={() => setAdvanced((v) => !v)} accessibilityRole="button" hitSlop={8}>
          <Txt v="small" color={t.accent}>{advanced ? 'Hide other options' : 'Other options'}</Txt>
        </Pressable>

        {advanced && (
          <View style={{ gap: space.lg }}>
            <View style={{ gap: space.sm }}>
              <Txt v="label" faint>Session token</Txt>
              <Txt v="small" dim>
                For a build whose Google setup is not finished. Mint one on the server with
                {' '}python -m zargar.tools.mint_session and paste it here.
              </Txt>
              <TextInput value={token} onChangeText={setToken} placeholder="Paste the token" placeholderTextColor={t.text3}
                autoCapitalize="none" autoCorrect={false} secureTextEntry style={input} accessibilityLabel="Session token" />
              <Button kind="plain" label="Sign in with token" busy={busy === 'token'} disabled={!!busy || !token.trim()}
                onPress={() => run('token', () => signInWithToken(token))} />
            </View>
            <View style={{ gap: space.sm }}>
              <Txt v="label" faint>Server address</Txt>
              <TextInput value={server} onChangeText={(v) => { setServer(v); setServerNote(null); }} placeholder="https://…" placeholderTextColor={t.text3}
                autoCapitalize="none" autoCorrect={false} keyboardType="url" style={input} accessibilityLabel="Server address" />
              <Button kind="plain" label="Check and save" busy={busy === 'server'} disabled={!!busy || server.trim() === apiUrl}
                onPress={() => run('server', async () => { await setApiUrl(server); setServerNote('Saved — the server answered'); })} />
              {!!serverNote && <Txt v="small" color={t.up}>{serverNote}</Txt>}
            </View>
          </View>
        )}

        <Txt v="small" faint style={{ textAlign: 'center', marginTop: space.lg }}>App {APP_VERSION} · {apiUrl.replace(/^https?:\/\//, '')}</Txt>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}
