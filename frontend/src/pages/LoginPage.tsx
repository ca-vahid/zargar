import { useEffect, useRef, useState } from "react";
import { APP_VERSION } from "../changelog";
import { api, setAuthToken } from "../lib/api";
import { reconnectWS } from "../lib/ws";
import { useStore } from "../store";

declare global {
  interface Window { google?: any }
}

const GSI_SRC = "https://accounts.google.com/gsi/client";

/** The sign-in screen. Google is live (ID-token flow, verified server-side,
 * allow-listed emails only); Microsoft and Office 365 are shown greyed out
 * until they're wired up. */
export function LoginPage() {
  const auth = useStore((s) => s.auth);
  const setAuth = useStore((s) => s.setAuth);
  const theme = useStore((s) => s.settings["ui.theme"] ?? "light");
  const btnRef = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [gsiReady, setGsiReady] = useState(false);
  const clientId = auth.googleClientId;

  // load Google Identity Services once, then render the official button
  useEffect(() => {
    if (!clientId) return;
    const done = () => setGsiReady(true);
    if (window.google?.accounts?.id) { done(); return; }
    const existing = document.querySelector<HTMLScriptElement>(`script[src="${GSI_SRC}"]`);
    if (existing) { existing.addEventListener("load", done); return () => existing.removeEventListener("load", done); }
    const s = document.createElement("script");
    s.src = GSI_SRC; s.async = true; s.defer = true; s.onload = done;
    s.onerror = () => setError("Google sign-in script could not load (offline?)");
    document.head.appendChild(s);
  }, [clientId]);

  useEffect(() => {
    if (!gsiReady || !clientId || !btnRef.current || !window.google?.accounts?.id) return;
    window.google.accounts.id.initialize({
      client_id: clientId,
      callback: async (resp: { credential: string }) => {
        setBusy(true); setError(null);
        try {
          const r = await api.authGoogle(resp.credential);
          setAuthToken(r.token);              // WS ?token= and download links
          setAuth({ user: r.user, required: true });
          reconnectWS();
        } catch (e: any) {
          setError(e.message || "sign-in failed");
        } finally { setBusy(false); }
      },
      ux_mode: "popup",
      auto_select: false,
      itp_support: true,
    });
    btnRef.current.innerHTML = "";
    window.google.accounts.id.renderButton(btnRef.current, {
      type: "standard", theme: theme === "dark" ? "filled_black" : "outline", size: "large",
      text: "signin_with", shape: "pill", width: 300, logo_alignment: "left",
    });
  }, [gsiReady, clientId, theme, setAuth]);

  return (
    <div className="login">
      <div className="login-card">
        <div className="login-brand">
          <img src="/art/logo-mark.png" alt="" aria-hidden="true" />
          <div className="login-word">Zar<em>gar</em></div>
          <div className="login-tag">personal trading desk</div>
        </div>
        <div className="login-h">Sign in</div>
        <p className="login-p">Only allow-listed accounts can get in. Everything past this screen can move real money.</p>

        {clientId ? (
          <div className="login-google">
            <div ref={btnRef} className="login-gsi" aria-label="Sign in with Google" />
            {!gsiReady && !error && <div className="login-hint">loading Google…</div>}
          </div>
        ) : (
          <div className="login-disabled">
            <span className="login-prov-ic">G</span> Sign in with Google
            <small>not configured — set ZARGAR_GOOGLE_CLIENT_ID (docs/AUTH.md)</small>
          </div>
        )}

        {auth.providers.filter((p) => p.id !== "google").map((p) => (
          <button key={p.id} type="button" className="login-disabled" disabled aria-disabled="true"
            title={p.note ?? "coming soon"}>
            <span className="login-prov-ic">{p.id === "microsoft" ? "⊞" : "O"}</span>
            Sign in with {p.label}
            <small>{p.note ?? "coming soon"}</small>
          </button>
        ))}

        {busy && <div className="login-hint">checking with the server…</div>}
        {error && <div className="login-err" role="alert">{error}</div>}
        <div className="login-foot">
          Signed-in sessions last {auth.sessionDays ?? 30} days on this device. Scripts can still use the API token. · v{APP_VERSION}
        </div>
      </div>
    </div>
  );
}
