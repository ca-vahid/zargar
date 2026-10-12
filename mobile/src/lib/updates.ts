import { Platform } from 'react-native';

type U = typeof import('expo-updates');
const lib = (): U => require('expo-updates') as U;

export interface UpdateInfo { enabled: boolean; channel: string | null; id: string | null; embedded: boolean }

/** Which code the app is running: the one inside the APK or a later over-the-air update. */
export function updateInfo(): UpdateInfo {
  if (Platform.OS === 'web' || __DEV__) return { enabled: false, channel: null, id: null, embedded: true };
  try {
    const u = lib();
    return { enabled: u.isEnabled, channel: u.channel ?? null, id: u.updateId ?? null, embedded: u.isEmbeddedLaunch };
  } catch {
    return { enabled: false, channel: null, id: null, embedded: true };
  }
}

/** Ask Expo whether a newer bundle exists for this build and download it.
 *  Returns true when one is downloaded and waiting for a restart. Never throws:
 *  a phone with no signal just keeps running what it has. */
export async function fetchUpdate(): Promise<boolean> {
  if (Platform.OS === 'web' || __DEV__) return false;
  try {
    const u = lib();
    if (!u.isEnabled) return false;
    const check = await u.checkForUpdateAsync();
    if (!check.isAvailable) return false;
    const got = await u.fetchUpdateAsync();
    return !!got.isNew;
  } catch {
    return false;
  }
}

export async function restartIntoUpdate(): Promise<void> {
  try {
    await lib().reloadAsync();
  } catch {
    /* the update applies on the next cold start anyway */
  }
}
