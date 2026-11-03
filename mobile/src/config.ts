import Constants from 'expo-constants';

const extra = (Constants.expoConfig?.extra ?? {}) as {
  apiUrl?: string;
  pushConfigured?: boolean;
  eas?: { projectId?: string };
};

/** The server this build talks to unless the person changes it on the sign-in screen. */
export const DEFAULT_API_URL = (extra.apiUrl || 'https://zargar-desk.tail97d481.ts.net').replace(/\/+$/, '');

/** True when the build carries google-services.json (Firebase): push can register. */
export const PUSH_CONFIGURED = !!extra.pushConfigured;

/** The EAS project id — the Expo push token is minted against it. */
export const EAS_PROJECT_ID: string | undefined =
  extra.eas?.projectId ?? (Constants as any).easConfig?.projectId ?? undefined;

export const APP_VERSION: string = Constants.expoConfig?.version ?? '0.0.0';

/** Android notification channels. Importance and sound are fixed once a channel is
 *  created on a device, and the server names these ids — keep both sides in step. */
export const CHANNELS = [
  { id: 'approvals', name: 'Approval cards', description: 'A tip is waiting for your approve or decline', importance: 'high' },
  { id: 'trades', name: 'Trades', description: 'Entries, fills, stops and exits', importance: 'high' },
  { id: 'alerts', name: 'Alerts', description: 'Plan alerts and the morning report', importance: 'default' },
  { id: 'critical', name: 'Critical', description: 'Kill switch, incidents and system problems', importance: 'max' },
] as const;
