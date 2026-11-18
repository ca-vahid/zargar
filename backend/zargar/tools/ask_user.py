"""Ask the user a question through the running app (it is pushed to the phone and shown on its Home), and read the
answer. For Claude sessions and desk scripts.

  python -m zargar.tools.ask_user ask "No USD at Webull for AAPL. Convert CAD or skip the buy?" \
      --option "Convert" --option "Skip" [--detail "..."] [--wait 600]
  python -m zargar.tools.ask_user list [--open]
  python -m zargar.tools.ask_user wait <id> [--seconds 600]
  python -m zargar.tools.ask_user cancel <id>

An answer is words on the record: act on it under your own rules.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import secrets
import sys
import time

import httpx
import jwt

from zargar.config import AppConfig

from .mint_session import _secret

BASE = "http://127.0.0.1:8420"


def _token() -> str:
    config = AppConfig()
    email = next((e.strip().lower() for e in config.google_allowed_emails.split(",") if e.strip()), "")
    if not email:
        raise SystemExit("no allow-listed email (ZARGAR_GOOGLE_ALLOWED_EMAILS)")
    now = int(time.time())
    return jwt.encode({"sub": email, "name": "local tooling", "provider": "google", "iat": now, "exp": now + 3600,
                       "sid": secrets.token_hex(8)}, asyncio.run(_secret(config)), algorithm="HS256")


def _client() -> httpx.Client:
    return httpx.Client(base_url=BASE, headers={"Authorization": f"Bearer {_token()}"}, timeout=20)


def _wait(c: httpx.Client, qid: str, seconds: int) -> dict:
    end = time.time() + seconds
    while True:
        q = c.get(f"/api/questions/{qid}").json()
        if q.get("status") != "open" or time.time() >= end:
            return q
        time.sleep(5)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ask_user")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("ask")
    a.add_argument("text")
    a.add_argument("--option", action="append", default=[])
    a.add_argument("--detail")
    a.add_argument("--url")
    a.add_argument("--expires-at")
    a.add_argument("--wait", type=int, default=0, help="seconds to wait for the answer")
    ls = sub.add_parser("list")
    ls.add_argument("--open", action="store_true")
    w = sub.add_parser("wait")
    w.add_argument("id")
    w.add_argument("--seconds", type=int, default=600)
    cn = sub.add_parser("cancel")
    cn.add_argument("id")
    args = ap.parse_args(argv)

    with _client() as c:
        if args.cmd == "ask":
            r = c.post("/api/questions", json={"text": args.text, "options": args.option, "detail": args.detail,
                                               "url": args.url, "expiresAt": args.expires_at})
            if r.status_code != 200:
                print(r.text, file=sys.stderr)
                return 1
            out = r.json()
            if args.wait:
                out = _wait(c, out["id"], args.wait)
        elif args.cmd == "list":
            out = c.get("/api/questions", params={"open_only": args.open}).json()
        elif args.cmd == "wait":
            out = _wait(c, args.id, args.seconds)
        else:
            out = c.post(f"/api/questions/{args.id}/cancel").json()
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(out, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
