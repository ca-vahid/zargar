import AsyncStorage from '@react-native-async-storage/async-storage';
import * as SecureStore from 'expo-secure-store';
import { Platform } from 'react-native';

// The session token is the only secret the app holds. On a phone it lives in the
// Android Keystore (expo-secure-store); the web preview used for development keeps
// it in sessionStorage. Everything else (server address, preferences) is plain.
const TOKEN_KEY = 'zargar.session';

export async function loadToken(): Promise<string | null> {
  try {
    if (Platform.OS === 'web') return globalThis.sessionStorage?.getItem(TOKEN_KEY) ?? null;
    return await SecureStore.getItemAsync(TOKEN_KEY);
  } catch {
    return null;
  }
}

export async function saveToken(token: string | null): Promise<void> {
  try {
    if (Platform.OS === 'web') {
      if (token) globalThis.sessionStorage?.setItem(TOKEN_KEY, token);
      else globalThis.sessionStorage?.removeItem(TOKEN_KEY);
      return;
    }
    if (token) await SecureStore.setItemAsync(TOKEN_KEY, token);
    else await SecureStore.deleteItemAsync(TOKEN_KEY);
  } catch {
    /* a failed write only means signing in again next launch */
  }
}

export async function loadPref<T>(key: string, fallback: T): Promise<T> {
  try {
    const raw = await AsyncStorage.getItem(`zargar.${key}`);
    return raw == null ? fallback : (JSON.parse(raw) as T);
  } catch {
    return fallback;
  }
}

export async function savePref(key: string, value: unknown): Promise<void> {
  try {
    await AsyncStorage.setItem(`zargar.${key}`, JSON.stringify(value));
  } catch {
    /* preferences are best effort */
  }
}
