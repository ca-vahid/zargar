"""Discord DM alert auto-intake via Windows toast notifications (POC).

HOW IT WORKS — and why it is ToS-clean: Discord's desktop app delivers every
DM (the alert-room "blue section" DM alerts included) to Windows as a toast
notification. Windows exposes delivered toasts through the OS
`UserNotificationListener` API. This tool polls that listener, filters for
Discord's app id, and posts each NEW toast's text into Zargar's ingest
pipeline (extraction → verification → shadow books → analyst) exactly as if
you had pasted it. No Discord API, no user-token automation, no self-bot —
the never-list stands. It reads what Discord already showed *you*, on *your*
machine. (Proven 2026-08-28: listener access + full title/body text.)

Prereqs (one-time):
  pip install winrt-runtime "winrt-Windows.UI.Notifications" \
      "winrt-Windows.UI.Notifications.Management" "winrt-Windows.Foundation" \
      "winrt-Windows.Foundation.Collections" "winrt-Windows.ApplicationModel"
  - Windows Settings > Privacy & security > Notifications >
    "Let apps access notifications" must be ON (the first run prompts).
  - Discord desktop running + logged in, DM notifications enabled
    (User Settings > Notifications > Enable Desktop Notifications).
  - Focus assist / do-not-disturb OFF for alerts to be delivered as toasts.

Usage (from backend/):
  .venv/Scripts/python -m zargar.tools.discord_watch --dry          # log only
  .venv/Scripts/python -m zargar.tools.discord_watch                # log + ingest
  ZARGAR_SESSION=$(python -m zargar.tools.mint_session)             # if auth is on

Every toast (matched or not) is appended to the JSONL log so we can learn the
exact shape of the OWLS embed DMs before trusting the filter.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import sys
from pathlib import Path

API_DEFAULT = "http://127.0.0.1:8420"
POLL_SECONDS = 3.0


def _need_winrt():
    try:
        from winrt.windows.ui.notifications import (            # noqa: F401
            KnownNotificationBindings, NotificationKinds)
        from winrt.windows.ui.notifications.management import (  # noqa: F401
            UserNotificationListener)
    except ImportError as exc:
        print(f"winrt packages missing ({exc}).\nInstall:\n  pip install winrt-runtime "
              '"winrt-Windows.UI.Notifications" "winrt-Windows.UI.Notifications.Management" '
              '"winrt-Windows.Foundation" "winrt-Windows.Foundation.Collections" '
              '"winrt-Windows.ApplicationModel"')
        sys.exit(2)


def _toast_dict(n) -> dict:
    from winrt.windows.ui.notifications import KnownNotificationBindings
    app_id, app_name = "", ""
    try:
        ai = n.app_info
        app_id = str(getattr(ai, "app_user_model_id", "") or "")
        app_name = str(ai.display_info.display_name)
    except Exception:
        pass
    texts: list[str] = []
    try:
        binding = n.notification.visual.get_binding(KnownNotificationBindings.toast_generic)
        if binding is not None:
            texts = [str(t.text) for t in binding.get_text_elements()]
    except Exception:
        pass
    created = None
    try:
        created = n.creation_time.isoformat()
    except Exception:
        pass
    return {"id": int(n.id), "appId": app_id, "appName": app_name,
            "createdAt": created, "texts": texts}


async def watch(api: str, token: str, log_path: Path, app_filter: str,
                dry: bool, once: bool) -> None:
    _need_winrt()
    import httpx
    from winrt.windows.ui.notifications import NotificationKinds
    from winrt.windows.ui.notifications.management import (
        UserNotificationListener, UserNotificationListenerAccessStatus as Access)

    listener = UserNotificationListener.current
    status = await listener.request_access_async()
    if status != Access.ALLOWED:
        print(f"notification access not granted ({status}) — enable it in Windows "
              "Settings > Privacy & security > Notifications")
        sys.exit(2)

    seen: set[int] = set()
    # prime with what's already in the Action Center so only NEW toasts ingest
    for n in await listener.get_notifications_async(NotificationKinds.TOAST):
        seen.add(int(n.id))
    print(f"watching (primed {len(seen)} existing toasts; filter appId~'{app_filter}'; "
          f"{'DRY RUN' if dry else 'posting to ' + api})")

    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with httpx.AsyncClient(timeout=30) as http:
        while True:
            try:
                toasts = await listener.get_notifications_async(NotificationKinds.TOAST)
            except Exception as exc:
                print(f"listener error: {exc}")
                await asyncio.sleep(POLL_SECONDS * 5)
                continue
            for n in toasts:
                nid = int(n.id)
                if nid in seen:
                    continue
                seen.add(nid)
                t = _toast_dict(n)
                with log_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(t) + "\n")
                blob = " | ".join(t["texts"])
                matched = app_filter.lower() in (t["appId"] + " " + t["appName"]).lower()
                print(f"[{dt.datetime.now():%H:%M:%S}] {'MATCH' if matched else 'other'} "
                      f"{t['appName'] or t['appId'] or '?'}: {blob[:120]}")
                if not matched or dry or not t["texts"]:
                    continue
                # title = sender/channel (the source hint), body = the alert
                text = "\n".join(t["texts"])
                try:
                    r = await http.post(f"{api}/api/ingest/manual", headers=headers, json={
                        "text": text, "source_name": "auto",
                        "subject": f"discord toast: {t['texts'][0][:80]}"})
                    out = r.json() if r.status_code == 200 else {"error": r.text[:200]}
                    n_sig = len(out.get("signals") or [])
                    print(f"    -> ingest {r.status_code}: {n_sig} signal(s) "
                          f"{out.get('source') or ''} {out.get('error') or ''}")
                except Exception as exc:
                    print(f"    -> ingest failed: {exc}")
            if once:
                return
            await asyncio.sleep(POLL_SECONDS)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--api", default=os.environ.get("ZARGAR_API", API_DEFAULT))
    p.add_argument("--token", default=os.environ.get("ZARGAR_SESSION", ""))
    p.add_argument("--log", default="discord_toasts.jsonl",
                   help="JSONL capture of EVERY toast (for studying alert shapes)")
    p.add_argument("--filter", default="discord",
                   help="substring of the app id/name to ingest (default: discord)")
    p.add_argument("--dry", action="store_true", help="log toasts, never post")
    p.add_argument("--once", action="store_true", help="one poll pass, then exit")
    a = p.parse_args()
    asyncio.run(watch(a.api, a.token, Path(a.log), a.filter, a.dry, a.once))


if __name__ == "__main__":
    main()
