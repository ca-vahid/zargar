import * as Device from 'expo-device';
import { router } from 'expo-router';
import { Platform } from 'react-native';

import { ApiError } from '../api/client';
import { api } from '../api/endpoints';
import { loadPref, savePref } from '../auth/storage';
import { CHANNELS, EAS_PROJECT_ID, PUSH_CONFIGURED } from '../config';
import { routeForWebPath } from '../lib/links';

type N = typeof import('expo-notifications');
const lib = (): N => require('expo-notifications') as N;

export type PushState =
  | { status: 'on'; token: string }
  | { status: 'off' }
  | { status: 'unavailable'; why: string };

/** Channels must exist before a token is requested, and a message naming a channel
 *  the phone does not have is silently dropped — so this runs on every launch. */
export async function ensureChannels(): Promise<void> {
  if (Platform.OS !== 'android') return;
  const N = lib();
  const level = { high: N.AndroidImportance.HIGH, default: N.AndroidImportance.DEFAULT, max: N.AndroidImportance.MAX } as const;
  for (const c of CHANNELS) {
    await N.setNotificationChannelAsync(c.id, {
      name: c.name,
      description: c.description,
      importance: level[c.importance],
      vibrationPattern: c.importance === 'default' ? undefined : [0, 250, 150, 250],
      lockscreenVisibility: N.AndroidNotificationVisibility.PRIVATE,
    });
  }
}

/** Show notifications while the app is open, and open the right screen on a tap. */
export function bindNotifications(): () => void {
  if (Platform.OS === 'web') return () => {};
  const N = lib();
  N.setNotificationHandler({
    handleNotification: async () => ({ shouldShowBanner: true, shouldShowList: true, shouldPlaySound: true, shouldSetBadge: false }),
  });
  const open = (data: any) => {
    const target = routeForWebPath(typeof data?.url === 'string' ? data.url : null);
    // let the navigator mount first when the tap launched the app
    setTimeout(() => router.navigate(target as any), 50);
  };
  const sub = N.addNotificationResponseReceivedListener((r) => open(r.notification.request.content.data));
  const last = N.getLastNotificationResponse();
  if (last) {
    open(last.notification.request.content.data);
    N.clearLastNotificationResponse();
  }
  return () => sub.remove();
}

export async function pushState(): Promise<PushState> {
  if (Platform.OS === 'web') return { status: 'unavailable', why: 'Notifications are set up in the installed app' };
  if (!PUSH_CONFIGURED) return { status: 'unavailable', why: 'This build was made without google-services.json' };
  const token = await loadPref<string | null>('pushToken', null);
  return token ? { status: 'on', token } : { status: 'off' };
}

/** Ask permission, get this phone's Expo push token and hand it to the server. */
export async function enablePush(): Promise<PushState> {
  if (Platform.OS === 'web') return { status: 'unavailable', why: 'Notifications are set up in the installed app' };
  if (!PUSH_CONFIGURED) return { status: 'unavailable', why: 'This build was made without google-services.json' };
  if (!Device.isDevice) return { status: 'unavailable', why: 'An emulator cannot receive push notifications' };
  if (!EAS_PROJECT_ID) return { status: 'unavailable', why: 'The build has no EAS project id (run `eas init`)' };
  const N = lib();
  await ensureChannels();
  let perm = await N.getPermissionsAsync();
  if (!perm.granted && perm.canAskAgain) perm = await N.requestPermissionsAsync();
  if (!perm.granted) return { status: 'unavailable', why: 'Notifications are turned off for Zargar in Android settings' };
  const token = (await N.getExpoPushTokenAsync({ projectId: EAS_PROJECT_ID })).data;
  try {
    await api.pushRegister(token, Device.modelName ?? 'Android phone');
  } catch (e) {
    if (e instanceof ApiError && (e.status === 404 || e.status === 405)) {
      return { status: 'unavailable', why: 'The server does not accept phone notifications yet (backend update pending)' };
    }
    throw e;
  }
  await savePref('pushToken', token);
  return { status: 'on', token };
}

export async function disablePush(): Promise<PushState> {
  const token = await loadPref<string | null>('pushToken', null);
  if (token) {
    try { await api.pushUnregister(token); } catch { /* the server prunes dead tokens itself */ }
  }
  await savePref('pushToken', null);
  return { status: 'off' };
}
