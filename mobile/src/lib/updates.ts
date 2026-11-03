import { Platform } from 'react-native';

type U = typeof import('expo-updates');
const lib = (): U => require('expo-updates') as U;

export interface UpdateInfo {
  enabled: boolean; channel: string | null; id: string | null; embedded: boolean;
  /** when the running code was published (or the APK built) */
  publishedAt: Date | null;
}

/** Which code the app is running: the one inside the APK or a later over-the-air update. */
export function updateInfo(): UpdateInfo {
  const off: UpdateInfo = { enabled: false, channel: null, id: null, embedded: true, publishedAt: null };
  if (Platform.OS === 'web' || __DEV__) return off;
  try {
    const u = lib();
    return { enabled: u.isEnabled, channel: u.channel ?? null, id: u.updateId ?? null, embedded: u.isEmbeddedLaunch,
      publishedAt: u.createdAt ?? null };
  } catch {
    return off;
  }
}

/** The answer to "is there anything newer?". `failed` is kept apart from `latest`: a phone
 *  that could not reach the update server must never be told it is up to date. */
export type UpdateCheck =
  | { state: 'latest' }
  | { state: 'ready'; publishedAt: Date | null }
  | { state: 'failed'; why: string }
  | { state: 'off' };

export async function checkUpdate(): Promise<UpdateCheck> {
  if (Platform.OS === 'web' || __DEV__) return { state: 'off' };
  try {
    const u = lib();
    if (!u.isEnabled) return { state: 'off' };
    const check = await u.checkForUpdateAsync();
    if (!check.isAvailable) return { state: 'latest' };
    const got = await u.fetchUpdateAsync();
    if (!got.isNew) return { state: 'latest' };
    const raw = (got.manifest as { createdAt?: string } | undefined)?.createdAt;
    return { state: 'ready', publishedAt: raw ? new Date(raw) : null };
  } catch (e: any) {
    return { state: 'failed', why: e?.message ? String(e.message) : 'No connection to the update server' };
  }
}

/** Ask Expo whether a newer bundle exists for this build and download it.
 *  Returns true when one is downloaded and waiting for a restart. Never throws:
 *  a phone with no signal just keeps running what it has. */
export async function fetchUpdate(): Promise<boolean> {
  return (await checkUpdate()).state === 'ready';
}

export async function restartIntoUpdate(): Promise<void> {
  try {
    await lib().reloadAsync();
  } catch {
    /* the update applies on the next cold start anyway */
  }
}
