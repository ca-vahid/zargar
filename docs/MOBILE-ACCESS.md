# Reaching Zargar from your phone

Zargar binds to `127.0.0.1:8420` by default and has no login screen: the only
gate is `ZARGAR_AUTH_TOKEN`. To use it from a phone you need (1) a network
path, (2) HTTPS (installable app, service worker, push notifications and the
clipboard all require it), and (3) the token on the phone.

## Recommended: Tailscale Serve (private, HTTPS, works on cellular)

1. Install Tailscale on the desktop and on the phone, same tailnet.
2. In `backend/.env`:
   ```
   ZARGAR_HOST=127.0.0.1           # keep loopback — Tailscale proxies to it
   ZARGAR_AUTH_TOKEN=<long random>  # REQUIRED before exposing anything
   ```
   Generate one: `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
3. Expose it: `tailscale serve --bg https / http://127.0.0.1:8420`
   Tailscale issues a real certificate for `https://<machine>.<tailnet>.ts.net`.
4. In Settings → Mobile → **Phone link**, paste that origin
   (`https://<machine>.<tailnet>.ts.net`). Telegram alerts now carry an
   "Open in Zargar" button that deep-links the phone to the plan.
5. On the phone open `https://<machine>.<tailnet>.ts.net/#token=<your token>`
   once — the token is stored in that browser and stripped from the address.
   Then Share → **Add to Home Screen** (iOS) or the browser's *Install app*
   (Android/Chrome). The app opens on the **Now** screen.
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
