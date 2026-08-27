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
   *Install app* (Android/Chrome). The app opens on the **Dashboard** (changed
   2026-08-27; an already-installed app keeps the old `/armed` start page until it
   is removed and added to the Home Screen again — the tab bar's Now is one tap).
   (`/#token=<ZARGAR_AUTH_TOKEN>` still works as a one-time handoff for the
   static token, if you use one.)
6. Settings → Mobile → **Push notifications → Enable on this device**
   (installed app on iOS 16.4+; any Chrome on Android).


## Public access without Tailscale on the client (Funnel) — ON since 2026-08-26

`tailscale funnel --bg http://127.0.0.1:8420` publishes the same
`https://zargar-desk.tail97d481.ts.net` to the public internet through
Tailscale's relays (no ports opened on the router; TLS terminates at Tailscale).
Any browser can reach the login page; the API still needs a Google session
(allow-listed emails only) — there is no password to guess. Hardening in place:
`POST /api/auth/google` is rate-limited (10/min per client IP → 429), oversized
credentials are rejected, `/api/auth/*` + `/api/health` are the only public
routes, phones stay exit-only on real accounts. Turn it off with
`tailscale funnel --https=443 off` (Serve keeps working inside the tailnet);
`tailscale funnel status` shows the current state.

How it resolves (learned 2026-08-26): inside the tailnet the name is the node's
`100.x` address; once Funnel is on, Tailscale rewrites the **public** record to its
relay servers (`208.111.34.x`, plus AAAA) and that swap took **~15 minutes** to
reach the authoritative `ns*.dnsimple.com` servers — until then outside devices get
"could not find host" and public resolvers cache the miss for 5 more minutes. Check
with `nslookup -type=A zargar-desk.tail97d481.ts.net ns1.dnsimple.com`: relay IPs
= live, `100.x` = still propagating. Nothing to fix locally while
`tailscale serve status --json` shows `"AllowFunnel": {...: true}`.

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

## Chart gestures on the phone (Trade)

One finger drags the chart through time, two fingers pinch-zoom (never closer than
~8 bars), a tap pins that bar's O·H·L·C readout in the top-left corner, a **double-tap**
fits the last screenful again and re-follows the live edge. A vertical drag always
scrolls the page — even after a pinch. The chart opens on the last ~50 bars (sized to
the screen) and keeps sliding with new bars until you pan away from the right edge.
Implementation + the Highcharts 12 rules behind it: `frontend/src/lib/chartTouch.ts`
(built 2026-08-26 after the finger-scroll bug: `followTouchMove` had been on).

## Real-device checklist (after each mobile phase)

- [ ] Now screen loads inside 2 s on cellular; tab bar and HALT visible; no
      horizontal scroll on any tab
- [ ] Rotate to landscape on Trade: chart fills, BUY/SELL still reachable
- [ ] Trade chart: one-finger drag pans, pinch zooms, vertical drag scrolls the page,
      tap shows O·H·L·C top-left, double-tap fits back to the live edge
- [ ] Sheets close with the back gesture and never leave the page
- [ ] Keyboard up in the ticket: submit button still reachable (dvh)
- [ ] Installed app: opens on the Dashboard, status bar colour matches theme,
      app icon badge shows attention count
- [ ] Push: Settings → Mobile → Test arrives with the app closed; tapping it
      opens the deep link
- [ ] Telegram alert has the "Open in Zargar" button and it lands on the plan
