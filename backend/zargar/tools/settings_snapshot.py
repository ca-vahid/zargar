"""Snapshot the runtime settings that differ from the code defaults, and restore them after a reset.

    python -m zargar.tools.settings_snapshot export [--out PATH]
    python -m zargar.tools.settings_snapshot diff --snapshot PATH
    python -m zargar.tools.settings_snapshot restore --snapshot PATH [--apply]

Why (2026-09-27): the live desk runs many decided values that are NOT the code defaults (the Tips cost package,
EM's deterministic preparation with the paid review off, every desk's Practice routing). A settings reset or a
fresh database would silently fall back to the defaults. `export` reads the settings table read-only; `restore` is a
dry run unless `--apply`, and then writes ONLY the keys whose live value differs from the snapshot through
`PATCH /api/settings` (validated and journaled by the app). Secret-bearing keys are never written to the snapshot.
Default location: C:/ProgramData/Zargar/settings-snapshots/ (outside the repository; never commit a snapshot).
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

DEFAULT_DIR = Path(os.environ.get("ZARGAR_SETTINGS_SNAPSHOT_DIR", "C:/ProgramData/Zargar/settings-snapshots"))
SECRET_KEYS = ("mobile.vapid", "auth.session_secret")
SECRET_WORDS = ("secret", "token", "password", "private", "api_key")


def secret(key: str) -> bool:
    k = key.lower()
    return key in SECRET_KEYS or any(w in k for w in SECRET_WORDS)


def unwrap(value):
    value = json.loads(value) if isinstance(value, str) else value
    return value.get("v") if isinstance(value, dict) and set(value) == {"v"} else value


def differences(stored: dict, defaults: dict) -> dict:
    """Pure: the stored keys a reset would change (known keys only, secrets excluded)."""
    return {k: v for k, v in sorted(stored.items()) if k in defaults and v != defaults[k] and not secret(k)}


def digest(settings: dict) -> str:
    return hashlib.sha256(json.dumps(settings, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def changes(snapshot: dict, live: dict) -> dict:
    """Pure: keys whose live value differs from the snapshot -> the snapshot value to restore."""
    return {k: v for k, v in snapshot.items() if live.get(k) != v}


async def read_stored(database_url: str) -> dict:
    import asyncpg
    url = database_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(url, server_settings={"default_transaction_read_only": "on"})
    try:
        return {r["key"]: unwrap(r["value"]) for r in await conn.fetch("select key, value from settings")}
    finally:
        await conn.close()


def load(path: str) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if digest(data["settings"]) != data["sha256"]:
        raise SystemExit("snapshot hash mismatch - the file was edited; refusing")
    return data


async def main() -> None:
    from ..config import AppConfig
    from ..settings_service import DEFAULTS
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    ex = sub.add_parser("export"); ex.add_argument("--out")
    for name in ("diff", "restore"):
        p = sub.add_parser(name); p.add_argument("--snapshot", required=True)
    sub.choices["restore"].add_argument("--apply", action="store_true")
    sub.choices["restore"].add_argument("--api", default="http://127.0.0.1:8420")
    args = ap.parse_args()
    config = AppConfig()
    stored = await read_stored(config.database_url)
    live = differences(stored, DEFAULTS)
    if args.cmd == "export":
        from .. import __version__
        at = dt.datetime.now(dt.timezone.utc)
        out = Path(args.out) if args.out else DEFAULT_DIR / f"settings-{at:%Y%m%dT%H%M%SZ}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"version": "settings-snapshot-v1", "appVersion": __version__, "takenAt": at.isoformat(),
                                   "secretsExcluded": True, "sha256": digest(live), "settings": live}, indent=1), encoding="utf-8")
        print(f"{len(live)} non-default settings -> {out}")
        return
    snap = load(args.snapshot)
    todo = changes(snap["settings"], {k: stored.get(k, DEFAULTS.get(k)) for k in snap["settings"]})
    for k, v in todo.items():
        shown = json.dumps(v)
        print(f"  {k}: live={json.dumps(stored.get(k, DEFAULTS.get(k)))[:80]} snapshot={shown[:80]}")
    print(f"{len(todo)} keys differ from snapshot {args.snapshot} (taken {snap['takenAt']}, app {snap['appVersion']})")
    if args.cmd == "restore" and args.apply and todo:
        import httpx
        token = subprocess.run([sys.executable, "-m", "zargar.tools.mint_session", "--hours", "0.2"],
                               capture_output=True, text=True, check=True).stdout.strip()
        async with httpx.AsyncClient(base_url=args.api, headers={"Authorization": f"Bearer {token}"}, timeout=60) as c:
            r = await c.patch("/api/settings", json=todo)
            print("PATCH /api/settings", r.status_code, "" if r.status_code == 200 else r.text[:300])


if __name__ == "__main__":
    asyncio.run(main())
