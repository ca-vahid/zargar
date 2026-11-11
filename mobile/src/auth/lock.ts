import * as LocalAuthentication from 'expo-local-authentication';
import { Platform } from 'react-native';

/** Fingerprint / face, falling back to the phone's own PIN or pattern.
 *
 *  Returns true when the person proved it is them. A phone with no screen lock at
 *  all has nothing to check against: that returns `fallback` (true for the in-app
 *  confirm, which the person has already tapped; the caller decides). */
export async function verifyPerson(reason: string, fallback = true): Promise<boolean> {
  if (Platform.OS === 'web') return fallback;
  try {
    const level = await LocalAuthentication.getEnrolledLevelAsync();
    if (level === LocalAuthentication.SecurityLevel.NONE) return fallback;
    const res = await LocalAuthentication.authenticateAsync({
      promptMessage: reason,
      cancelLabel: 'Cancel',
      disableDeviceFallback: false,
    });
    return !!res.success;
  } catch {
    return false;
  }
}

/** Whether the phone has any screen lock the app could ask for. */
export async function canLock(): Promise<boolean> {
  if (Platform.OS === 'web') return false;
  try {
    return (await LocalAuthentication.getEnrolledLevelAsync()) !== LocalAuthentication.SecurityLevel.NONE;
  } catch {
    return false;
  }
}
