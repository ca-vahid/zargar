import { Platform } from 'react-native';

export class SignInCancelled extends Error {}

/** Run Google's native sign-in and return the ID token for our own server.
 *
 *  `webClientId` is the server's OAuth client id (GET /api/auth/config): the token's
 *  audience must be the WEB client, which is exactly what the server already checks.
 *  The Android OAuth client (package name + signing SHA-1) is never named in code —
 *  Google matches it from the app's signature. A mismatch there is the usual cause of
 *  the "DEVELOPER_ERROR" failure (README, "Getting it onto a phone"). */
export async function googleIdToken(webClientId: string): Promise<string> {
  if (Platform.OS === 'web') throw new Error('Google sign-in runs in the installed app; use a session token here');
  // required lazily: the native module does not exist in the web preview
  const mod = require('@react-native-google-signin/google-signin') as typeof import('@react-native-google-signin/google-signin');
  const { GoogleSignin, isErrorWithCode, statusCodes } = mod;
  GoogleSignin.configure({ webClientId, offlineAccess: false });
  try {
    await GoogleSignin.hasPlayServices({ showPlayServicesUpdateDialog: true });
    const res = await GoogleSignin.signIn();
    if (res.type !== 'success') throw new SignInCancelled('Sign-in cancelled');
    const idToken = res.data.idToken;
    if (!idToken) throw new Error('Google returned no ID token — check the web client id on the server');
    return idToken;
  } catch (e: any) {
    if (e instanceof SignInCancelled) throw e;
    if (isErrorWithCode(e)) {
      if (e.code === statusCodes.SIGN_IN_CANCELLED) throw new SignInCancelled('Sign-in cancelled');
      if (e.code === statusCodes.IN_PROGRESS) throw new Error('Sign-in is already open');
      if (e.code === statusCodes.PLAY_SERVICES_NOT_AVAILABLE) throw new Error('Google Play services are not available on this phone');
      if (String(e.code) === '10' || /DEVELOPER_ERROR/i.test(String(e.message))) {
        throw new Error("Google refused this build (DEVELOPER_ERROR): the Android OAuth client's package name or SHA-1 does not match this app's signing key");
      }
    }
    throw e instanceof Error ? e : new Error(String(e));
  }
}

export async function googleSignOut(): Promise<void> {
  if (Platform.OS === 'web') return;
  try {
    const { GoogleSignin } = require('@react-native-google-signin/google-signin') as typeof import('@react-native-google-signin/google-signin');
    await GoogleSignin.signOut();
  } catch {
    /* nothing to sign out of */
  }
}
