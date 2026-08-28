"""Grab YOUR Discord user token from the local desktop app (Windows).

The Discord desktop app keeps your session token in its Local Storage
(leveldb), encrypted with AES-GCM under a key that is itself DPAPI-protected
to your Windows user account. This reads it the same way Discord does — so you
never have to pull it from DevTools again. It works ONLY as the same Windows
user that installed Discord (DPAPI is user-bound; that is a feature, not a
bug), and touches nothing over the network.

⚠️  The output is account-access-equivalent — the same thing malware steals.
Never share it, never paste it anywhere but ZARGAR_DISCORD_TOKEN on this
machine. This is for the experimental gateway intake (docs/techniques/tip/
INTAKE-PLAN.md) — your own account, your own machine.

Usage (from backend/):
  .venv/Scripts/python -m zargar.tools.discord_token           # print the token
  .venv/Scripts/python -m zargar.tools.discord_token --check   # + validate it live
  .venv/Scripts/python -m zargar.tools.discord_token --export  # PowerShell $env line

  # feed the gateway directly (PowerShell):
  $env:ZARGAR_DISCORD_TOKEN = (python -m zargar.tools.discord_token)
  python -m zargar.tools.discord_gateway --from-bots-only --ingest
"""
from __future__ import annotations

import argparse
import base64
import ctypes
import ctypes.wintypes as wt
import json
import os
import re
import sys
from pathlib import Path

# Discord writes encrypted tokens behind this marker in leveldb.
TOKEN_RE = re.compile(rb"dQw4w9WgXcQ:([^\"\\]+)")
# release channel -> AppData\Roaming folder
CHANNELS = ["discord", "discordptb", "discordcanary", "discorddevelopment"]


def _dpapi_decrypt(blob: bytes) -> bytes:
    """CryptUnprotectData via ctypes — no pywin32 dependency."""
    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def to_blob(b: bytes) -> DATA_BLOB:
        buf = ctypes.create_string_buffer(b, len(b))
        return DATA_BLOB(len(b), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))

    out = DATA_BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(to_blob(blob)), None, None, None, None, 0, ctypes.byref(out)):
        raise OSError("CryptUnprotectData failed (are you the same Windows user?)")
    n = out.cbData
    buf = ctypes.create_string_buffer(n)
    ctypes.memmove(buf, out.pbData, n)
    ctypes.windll.kernel32.LocalFree(out.pbData)
    return buf.raw


def _master_key(base: Path) -> bytes:
    state = json.loads((base / "Local State").read_text(encoding="utf-8"))
    enc = base64.b64decode(state["os_crypt"]["encrypted_key"])
    if enc[:5] != b"DPAPI":
        raise ValueError("unexpected key prefix (not DPAPI)")
    return _dpapi_decrypt(enc[5:])


def _decrypt_token(enc_b64: bytes, key: bytes) -> str | None:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    try:
        data = base64.b64decode(enc_b64)
    except Exception:
        return None
    if data[:3] != b"v10" and data[:3] != b"v11":
        return None
    nonce, ct = data[3:15], data[15:]
    try:
        return AESGCM(key).decrypt(nonce, ct, None).decode("utf-8", "replace")
    except Exception:
        return None


def grab_token(channel: str | None = None) -> str:
    """Return the newest decryptable token from the local Discord app, or raise."""
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise RuntimeError("APPDATA not set — this tool is Windows-only")
    channels = [channel] if channel else CHANNELS
    tried, found = [], []
    for ch in channels:
        base = Path(appdata) / ch
        ldb = base / "Local Storage" / "leveldb"
        if not (base / "Local State").exists() or not ldb.exists():
            continue
        tried.append(ch)
        key = _master_key(base)
        for f in sorted(ldb.glob("*.ldb")) + sorted(ldb.glob("*.log")):
            try:
                raw = f.read_bytes()
            except OSError:
                continue
            for m in TOKEN_RE.finditer(raw):
                tok = _decrypt_token(m.group(1), key)
                if tok and tok.count(".") >= 2:      # user tokens are 3 dot-parts
                    found.append((f.stat().st_mtime, tok))
    if not found:
        raise RuntimeError(
            f"no token found (checked: {tried or 'none installed'}). "
            "Is Discord logged in? Close Discord and retry if the leveldb is locked.")
    # newest file wins; dedupe
    found.sort(reverse=True)
    seen = set()
    for _, tok in found:
        if tok not in seen:
            return tok
    return found[0][1]


def _check(token: str) -> dict:
    import httpx
    r = httpx.get("https://discord.com/api/v10/users/@me",
                  headers={"Authorization": token}, timeout=15)
    if r.status_code != 200:
        raise RuntimeError(f"token rejected by Discord ({r.status_code})")
    return r.json()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--channel", choices=CHANNELS, help="force a specific Discord build")
    p.add_argument("--check", action="store_true", help="validate against users/@me")
    p.add_argument("--export", action="store_true",
                   help="print a PowerShell $env line instead of the bare token")
    a = p.parse_args()
    try:
        token = grab_token(a.channel)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(2)
    if a.check:
        try:
            me = _check(token)
            print(f"# valid: {me.get('username')} (id {me.get('id')})", file=sys.stderr)
        except Exception as exc:
            print(f"# check failed: {exc}", file=sys.stderr)
            sys.exit(3)
    if a.export:
        print(f'$env:ZARGAR_DISCORD_TOKEN = "{token}"')
    else:
        print(token)


if __name__ == "__main__":
    main()
