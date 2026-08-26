# Sign-in (SSO)

Zargar can move real money, so the API is closed the moment sign-in is
configured. Today: **Sign in with Google**, restricted to an allow list of
emails. Microsoft and Office 365 appear on the login screen greyed out
("coming soon") and are not wired yet.

## How it works

1. The login page loads Google Identity Services and shows the official button.
2. Google returns an **ID token** (a signed JWT) for the account you picked.
3. `POST /api/auth/google` verifies it server-side: signature against Google's
   published keys (JWKS), audience = your OAuth client id, issuer =
   accounts.google.com, `email_verified` = true — and then the real gate:
   **the email must be in `ZARGAR_GOOGLE_ALLOWED_EMAILS`.** Anyone else gets a
   403 even with a perfectly valid Google account. Sign-ins are journaled
   (`AuthSignIn`).
4. You get a **session**: an HS256 JWT signed with a server secret, set as an
   HttpOnly `zargar_session` cookie (30 days, `Secure` on HTTPS) and also
   returned in the body so the WebSocket `?token=` and download links keep
   working. The allow list is checked on every request, so removing an email
   ends its sessions immediately.
5. `ZARGAR_AUTH_TOKEN` (static bearer / `?token=`) keeps working for scripts and
   the CLI tools. With neither the token nor a Google client id set, the API
   is open — local development only; the server refuses to bind a non-loopback
   host in that state.

## Set it up (one time, ~5 minutes)

1. **Google Cloud Console** → https://console.cloud.google.com/apis/credentials
   (any project; create one called "zargar" if you like).
2. If asked, configure the **OAuth consent screen**: User type *External*,
   app name "Zargar", your email as support/developer contact, no scopes
   needed beyond the defaults (`openid`, `email`, `profile`). Publishing
   status can stay *Testing* — add `visper@gmail.com` under **Test users**.
3. **Create Credentials → OAuth client ID → Web application**, name "Zargar
   web". Add **Authorized JavaScript origins** for every origin you open the
   app from — exactly, scheme + host + port, no path:
   - `http://localhost:8420`
   - `http://127.0.0.1:8420`
   - `http://localhost:5173` (Vite dev)
   - `https://<machine>.<tailnet>.ts.net` (the phone link from
     `docs/MOBILE-ACCESS.md`, once you have it)
   No redirect URIs are needed (the button uses the popup/ID-token flow).
4. Copy the **Client ID** (`…apps.googleusercontent.com`) into `backend/.env`:
   ```
   ZARGAR_GOOGLE_CLIENT_ID=1234567890-abc.apps.googleusercontent.com
   ZARGAR_GOOGLE_ALLOWED_EMAILS=visper@gmail.com
   # optional: ZARGAR_SESSION_SECRET=<random>  (else generated once and kept in settings)
   # optional: ZARGAR_SESSION_DAYS=30
   ```
5. Restart (`scripts\start.ps1`). Open the app → the login screen → **Sign in
   with Google** → pick visper@gmail.com. Settings → Trading & risk shows
   "Signed in as …" with a Sign out; the phone's More sheet shows it too.

Google's client-side script (`accounts.google.com/gsi/client`) must be
reachable from the browser — the login screen says so if it isn't.

## Adding more people / later providers

- More Google accounts: extend `ZARGAR_GOOGLE_ALLOWED_EMAILS` (comma-separated)
  and restart. Everyone has full access — there are no roles yet.
- Microsoft / Office 365: the login page already lists them as disabled
  providers (`AuthService.providers()`); wiring them means an Entra ID app
  registration and verifying its ID tokens the same way (`login.microsoftonline.com`
  JWKS, tenant/issuer checks). Same session mechanism afterwards.
- Sign everyone out at once: set/rotate `ZARGAR_SESSION_SECRET` and restart.
