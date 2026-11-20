import { useCallback, useEffect, useState } from 'react';
import { View } from 'react-native';

import { verifyPerson } from '@/auth/lock';
import { signOut } from '@/auth/session';
import { useStore } from '@/store';
import { space, useTheme } from '@/theme';

import { Button, Txt } from './ui';

/** Shown instead of the app when the lock is on and the phone has been away. */
export function LockScreen() {
  const t = useTheme();
  const [busy, setBusy] = useState(false);
  const unlock = useCallback(async () => {
    setBusy(true);
    // no screen lock on the phone any more: nothing to check, so do not trap the person
    const ok = await verifyPerson('Unlock Zargar', true);
    setBusy(false);
    if (ok) useStore.getState().set({ locked: false });
  }, []);
  useEffect(() => { void unlock(); }, [unlock]);
  return (
    <View style={{ flex: 1, backgroundColor: t.bg, alignItems: 'center', justifyContent: 'center', padding: space.xl, gap: space.lg }}>
      <Txt v="title">Zargar is locked</Txt>
      <Button label="Unlock" busy={busy} onPress={unlock} style={{ alignSelf: 'stretch' }} />
      <Button kind="plain" label="Sign out" onPress={() => void signOut()} style={{ alignSelf: 'stretch' }} />
    </View>
  );
}
