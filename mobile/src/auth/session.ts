import { ApiError, configureClient } from '../api/client';
import { api } from '../api/endpoints';
import { DEFAULT_API_URL } from '../config';
import { bindAppState, connectSocket, disconnectSocket } from '../live/socket';
import { useStore } from '../store';
import { googleIdToken, googleSignOut } from './google';
import { canLock } from './lock';
import { loadPref, loadToken, savePref, saveToken } from './storage';

const store = () => useStore.getState();

function signedOutLocally() {
  disconnectSocket();
  configureClient({ token: null });
  void saveToken(null);
  store().reset();
  store().set({ token: null, user: null });
}

/** Start-up: restore the server address and the session, then check it still holds. */
export async function boot(): Promise<void> {
  const apiUrl = (await loadPref<string>('apiUrl', DEFAULT_API_URL)) || DEFAULT_API_URL;
  const lockEnabled = (await loadPref<boolean>('lock', false)) && (await canLock());
  const token = await loadToken();
  configureClient({ baseUrl: apiUrl, token, onUnauthorized: signedOutLocally });
  bindAppState();
  const workspace = await loadPref<'live' | 'practice' | null>('workspace', null);
  const currency = (await loadPref<string>('currency', 'USD')) === 'CAD' ? 'CAD' : 'USD';
  store().set({ apiUrl, lockEnabled, workspace, currency, locked: lockEnabled && !!token });
  if (token) {
    try {
      const me = await api.authMe();
      if (me.user) {
        store().set({ token, user: me.user });
        connectSocket();
      } else {
        signedOutLocally();
      }
    } catch (e) {
      // unreachable server: keep the session and let the screens show "cannot reach";
      // a real 401 has already signed us out through onUnauthorized
      if (!(e instanceof ApiError) || e.status !== 401) {
        store().set({ token, user: { email: '' } });
        connectSocket();
      }
    }
  }
  store().set({ booted: true });
}

async function accept(token: string) {
  configureClient({ token });
  const me = await api.authMe();
  if (!me.user) throw new Error('The server did not accept that session');
  await saveToken(token);
  store().set({ token, user: me.user, locked: false });
  connectSocket();
}

export async function signInWithGoogle(): Promise<void> {
  const cfg = await api.authConfig();
  if (!cfg.googleClientId) throw new Error('This server has no Google sign-in configured');
  const credential = await googleIdToken(cfg.googleClientId);
  const res = await api.authGoogle(credential);
  await accept(res.token);
}

/** Fallback for a build whose Google setup is not finished: paste a session token
 *  minted on the server (`python -m zargar.tools.mint_session`). */
export async function signInWithToken(raw: string): Promise<void> {
  const token = raw.trim();
  if (!token) throw new Error('Paste a session token first');
  try {
    await accept(token);
  } catch (e) {
    configureClient({ token: null });
    throw e;
  }
}

export async function signOut(): Promise<void> {
  await googleSignOut();
  signedOutLocally();
}

export async function setApiUrl(url: string): Promise<void> {
  const clean = url.trim().replace(/\/+$/, '');
  if (!/^https?:\/\//i.test(clean)) throw new Error('The address must start with https://');
  configureClient({ baseUrl: clean });
  await api.health(); // throws when nothing answers there
  await savePref('apiUrl', clean);
  store().set({ apiUrl: clean });
}

export async function setLockEnabled(on: boolean): Promise<boolean> {
  const ok = on ? await canLock() : true;
  if (!ok) return false;
  await savePref('lock', on);
  store().set({ lockEnabled: on });
  return true;
}
