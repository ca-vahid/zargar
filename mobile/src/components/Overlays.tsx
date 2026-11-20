import * as Haptics from 'expo-haptics';
import { useState } from 'react';
import { Modal, Platform, Pressable, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { verifyPerson } from '../auth/lock';
import { useStore } from '../store';
import { radius, space, useTheme } from '../theme';
import { Button, Txt } from './ui';

/** The one confirmation sheet. Every action that changes something on the server
 *  goes through `confirmAction()`: what will happen, in plain words, then — for
 *  anything that touches money — the phone's fingerprint or PIN. */
export function ConfirmHost() {
  const t = useTheme();
  const insets = useSafeAreaInsets();
  const req = useStore((s) => s.confirm);
  const [checking, setChecking] = useState(false);
  if (!req) return null;

  const close = (ok: boolean) => {
    useStore.getState().set({ confirm: null });
    req.resolve(ok);
  };
  const accept = async () => {
    if (req.secure) {
      setChecking(true);
      const ok = await verifyPerson(req.title);
      setChecking(false);
      if (!ok) return; // stay on the sheet: they can try again or cancel
    }
    if (Platform.OS !== 'web') void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
    close(true);
  };

  return (
    <Modal transparent animationType="slide" visible onRequestClose={() => close(false)} statusBarTranslucent>
      <Pressable style={{ flex: 1, backgroundColor: 'rgba(0,0,0,0.55)' }} onPress={() => close(false)} accessibilityLabel="Cancel" />
      <View style={{ backgroundColor: t.surface, borderTopLeftRadius: radius.lg, borderTopRightRadius: radius.lg, padding: space.xl, paddingBottom: space.xl + insets.bottom, gap: space.md }}>
        <Txt v="title">{req.title}</Txt>
        {!!req.body && <Txt dim>{req.body}</Txt>}
        {(req.lines ?? []).map(([k, v]) => (
          <View key={k} style={{ flexDirection: 'row', justifyContent: 'space-between', gap: space.md }}>
            <Txt dim>{k}</Txt>
            <Txt num style={{ flexShrink: 1, textAlign: 'right' }}>{v}</Txt>
          </View>
        ))}
        <View style={{ flexDirection: 'row', gap: space.md, marginTop: space.sm }}>
          <Button kind="plain" label="Cancel" onPress={() => close(false)} style={{ flex: 1 }} />
          <Button kind={req.danger ? 'danger' : 'primary'} label={req.confirmLabel} busy={checking} onPress={accept} style={{ flex: 1.4 }} />
        </View>
      </View>
    </Modal>
  );
}

export function ToastHost() {
  const t = useTheme();
  const insets = useSafeAreaInsets();
  const toasts = useStore((s) => s.toasts);
  if (!toasts.length) return null;
  return (
    <View pointerEvents="box-none" style={{ position: 'absolute', left: space.lg, right: space.lg, bottom: insets.bottom + 76, gap: space.sm }}>
      {toasts.map((x) => (
        <Pressable key={x.id} onPress={() => useStore.getState().dropToast(x.id)} accessibilityRole="alert"
          style={{ backgroundColor: t.surface3, borderRadius: radius.sm, padding: space.md, borderLeftWidth: 3,
            borderLeftColor: x.kind === 'error' ? t.down : x.kind === 'ok' ? t.up : t.accent }}>
          <Txt>{x.text}</Txt>
        </Pressable>
      ))}
    </View>
  );
}
