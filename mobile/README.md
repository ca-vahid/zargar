# Zargar for Android

A native companion to the Zargar desk, built with Expo (SDK 57, React Native 0.86).
It reads the same server as the web app and shows the things you check from a phone:
what is happening now, each book and its equity curve, positions with their stops,
orders and fills, tip approval cards, armed plans, Scout and research notes, alerts,
price charts and system status.

It is read-mostly. The actions it offers are the ones that reduce or gate risk, and
each asks for confirmation and then the phone's fingerprint or PIN:

| Action | Where |
|---|---|
| Approve or decline a tip card | Tips → Cards |
| Kill switch (halt / release) | top right of every screen |
| Pause or resume entries on one book | Portfolio |
| Close a position, sell an armed plan's trade | Chart of a position, Armed plans |
| Cancel an unfilled buy order | Portfolio → Working orders |
| Pause or resume an armed plan | Armed plans → Watching |

It offers no way to place a new manual order, and it cannot cancel a stop or a target.
Approving a card always re-runs the server's checks first and binds the approval to the
refreshed plan; a card the checks block cannot be approved here.

## Layout

```
src/app/            screens (Expo Router): (tabs)/ Now · Portfolio · Tips · Research · More,
                    plus alerts, armed, ledger, system, settings, chart/[symbol], dossier/[id]
src/api/            client.ts (HTTP), endpoints.ts (the routes used), types.ts (generated copy)
src/auth/           session.ts (boot, sign-in, sign-out), google.ts, lock.ts, storage.ts
src/live/socket.ts  the one WebSocket: snapshot on connect, reconnect with backoff
src/store.ts        zustand store fed by the socket
src/components/     ui.tsx, LineChart, CandleChart, Header (HALT), Overlays (confirm sheet)
src/lib/            format, chart geometry, books, links, actions — pure and unit-tested
src/notifications/  push.ts (channels, token, tap → screen)
```

`src/api/types.ts` is a copy of `frontend/src/types.ts`. Refresh it with
`npm run sync-types`; `npm test` fails when the two differ.

## Commands

```bash
npm install
npm run typecheck          # tsc
npm test                   # types-in-sync check + jest (31 tests)
npm run doctor             # expo-doctor
npm run export:android     # bundle the JS for Android (no native build)
npm run build:dev          # EAS development build (APK with the dev client)
npm run build:apk          # EAS release APK
```

### Browser preview

The screens run in a browser for layout work. The server only accepts browser calls
from `localhost:5173`, so the preview must use that port:

```powershell
$env:EXPO_PUBLIC_API_URL = 'http://127.0.0.1:8420'
npx expo start --web --port 5173
```

Sign in there with a session token (`python -m zargar.tools.mint_session` from
`backend/`). Google sign-in, the fingerprint prompt and push only exist in the
installed app.

## Getting it onto a phone

Done already: the Expo project (`@vahiids-team/zargar`) and the Android keystore.

1. **Google sign-in.** In Google Cloud Console, in the project that holds the web
   sign-in client, create an OAuth client of type **Android** with package
   `ca.vahid.zargar` and the keystore's SHA-1 (shown by `npx eas-cli credentials`).
   Nothing is copied back into the app: it asks the server for the web client id and
   Google matches the Android client from the app's signature. A wrong package or
   SHA-1 shows up as `DEVELOPER_ERROR` at sign-in.
2. **Build and install.** `npm run build:dev`, then open the link EAS prints on the
   phone. A development build needs `npx expo start` running on the PC; `npm run
   build:apk` makes a standalone APK.
3. **Push (optional).** Add Firebase to the same Google Cloud project, add an Android
   app for `ca.vahid.zargar`, and save `google-services.json` in this folder (it holds
   public identifiers only). Create a service-account key and upload it with
   `npx eas-cli credentials` → Android → Google Service Account (FCM V1); keep that
   key out of the repository. Rebuild, then turn on Settings → Notify this phone.

Until step 1 is done the sign-in screen's "Other options" accepts a session token.

## What needs the backend update

Three server additions are in a separate pull request (`claude/mobile-backend`):
phone push delivery (`/api/push/expo`), the alerts feed (`/api/alerts`), and binding
the phone client class to the session. Without it the app still works: Alerts falls
back to plan errors, and Settings reports that the server does not accept phone
notifications yet.

## Not verified

Nothing here has run on a real phone or emulator yet. Verified so far: typecheck, unit
tests, expo-doctor, the Android JS bundle, and every screen in the browser preview
against the live server. Untested until a device build: Google sign-in, secure
storage, the fingerprint prompt, push, chart touch gestures on a touchscreen, and the
bottom tab bar's spacing with Android's gesture bar.
