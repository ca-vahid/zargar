# Reaching Zargar from your phone

Zargar binds to `127.0.0.1:8420` by default and has no login screen: the only
gate is `ZARGAR_AUTH_TOKEN`. To use it from a phone you need (1) a network
path, (2) HTTPS (installable app, service worker, push notifications and the
clipboard all require it), and (3) the token on the phone.

## Recommended: Tailscale Serve (private, HTTPS, works on cellular)

1. Install Tailscale on the desktop and on the phone, same tailnet.
2. Sign-in must be on before exposing anything: Google SSO (`ZARGAR_GOOGLE_CLIENT_ID`
   + `ZARGAR_GOOGLE_ALLOWED_EMAILS`, see `docs/AUTH.md`) — or, for scripts only,
   `ZARGAR_AUTH_TOKEN`. Keep `ZARGAR_HOST=127.0.0.1`; Tailscale proxies to it.
   Add the `.ts.net` origin to the Google OAuth client's *Authorized JavaScript
   origins* or the Google button won't render on the phone.
3. Expose it: `tailscale serve --bg http://127.0.0.1:8420` (Tailscale ≥ 1.60 syntax).
   The first run prints a link to enable Serve/HTTPS for the tailnet — approve it once.
   Tailscale issues a real certificate for `https://<machine>.<tailnet>.ts.net`, the
   config persists, and the Windows service brings it back after reboots.
   `tailscale serve status` shows it; `tailscale serve --https=443 off` removes it.
   (Set up 2026-08-26: machine `zargar-desk` → `https://zargar-desk.tail97d481.ts.net`.)
4. In Settings → Mobile → **Phone link**, paste that origin
   (`https://<machine>.<tailnet>.ts.net`). Telegram alerts now carry an
   "Open in Zargar" button that deep-links the phone to the plan.
5. On the phone: install Tailscale, sign in with the same account, open
   `https://<machine>.<tailnet>.ts.net` and **Sign in with Google** (30-day
   session). Then Share → **Add to Home Screen** (iOS) or the browser's
   *Install app* (Android/Chrome). The app opens on the **Now** screen.
   (`/#token=<ZARGAR_AUTH_TOKEN>` still works as a one-time handoff for the
   static token, if you use one.)
6. Settings → Mobile → **Push notifications → Enable on this device**
   (installed app on iOS 16.4+; any Chrome on Android).

## Alternatives

- **LAN only:** `ZARGAR_HOST=0.0.0.0` + `ZARGAR_AUTH_TOKEN` + a local cert
  (`mkcert`) in front (Caddy/nginx) — install works; push only works while on
  the LAN.
- **Cloudflare Tunnel:** public URL — the token is the *only* thing between the
  internet and your brokerage accounts. Prefer Tailscale.

## Safety on the phone

- `mobile.exit_only` (Settings → Mobile, default **on**): a phone can HALT,
  flatten, disarm, approve proposals and SELL out of real positions, but the
  RiskGate rejects any order that would *open* real-account risk from a phone
  (`phone_entry_blocked`). Practice trading is unaffected.
- The app refuses to start bound to a non-loopback host without
  `ZARGAR_AUTH_TOKEN`.
- Settings → Mobile → **Sign out** forgets the token on that device. Rotating
  `ZARGAR_AUTH_TOKEN` (restart) signs out every device.

## Real-device checklist (after each mobile phase)

- [ ] Now screen loads inside 2 s on cellular; tab bar and HALT visible; no
      horizontal scroll on any tab
- [ ] Rotate to landscape on Trade: chart fills, BUY/SELL still reachable
- [ ] Sheets close with the back gesture and never leave the page
- [ ] Keyboard up in the ticket: submit button still reachable (dvh)
- [ ] Installed app: opens on `/armed`, status bar colour matches theme,
      app icon badge shows attention count
- [ ] Push: Settings → Mobile → Test arrives with the app closed; tapping it
      opens the deep link
- [ ] Telegram alert has the "Open in Zargar" button and it lands on the plan
