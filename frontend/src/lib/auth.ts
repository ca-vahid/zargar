import { api, setAuthToken } from "./api";
import { reconnectWS } from "./ws";
import { useStore } from "../store";

/** Sign this browser out: end the server session (cookie), forget the WS token,
 *  drop the live connection, and let the App gate show the sign-in screen.
 *  Other devices keep their own sessions. */
export async function signOut(): Promise<void> {
  try { await api.authLogout(); } catch { /* the cookie may already be gone — sign out locally anyway */ }
  setAuthToken("");
  try { localStorage.removeItem("zargar_token"); } catch { /* private mode */ }
  try { (window as any).google?.accounts?.id?.disableAutoSelect?.(); } catch { /* GSI not loaded */ }
  useStore.getState().setAuth({ user: null, required: true, checked: true });
  reconnectWS();
}
