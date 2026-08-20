"""SnapTrade connectivity self-test and connection manager.

Requires personal API credentials in backend/.env:

    ZARGAR_SNAPTRADE_CLIENT_ID=...
    ZARGAR_SNAPTRADE_CONSUMER_KEY=...

Usage (from backend/):

    .venv/bin/python -m zargar.tools.snaptrade_check             # status + connections + accounts
    .venv/bin/python -m zargar.tools.snaptrade_check --upgrade   # re-auth URLs to upgrade
                                                                 # read-only connections to trade

Read-only against your brokerage accounts: never places orders. --upgrade only
generates SnapTrade Connection Portal URLs; you complete the broker login in
the browser yourself.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import hmac
import json
import sys
import time
import webbrowser

import httpx

from ..config import get_config

BASE = "https://api.snaptrade.com"
GREEN = "\033[1;32m✓\033[0m"
RED = "\033[1;31m✗\033[0m"
WARN = "\033[1;33m!\033[0m"


class SnapTradeClient:
    """Minimal signed client for SnapTrade personal-account auth.

    Personal API keys identify the user directly, so userId/userSecret are
    omitted everywhere (per docs/personal-vs-commercial).
    """

    def __init__(self, client_id: str, consumer_key: str):
        self._client_id = client_id
        self._consumer_key = consumer_key

    def _sign(self, path: str, query: str, body: dict | None) -> str:
        payload = {"content": body, "path": path, "query": query}
        data = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        digest = hmac.new(self._consumer_key.encode(), data.encode(), hashlib.sha256).digest()
        return base64.b64encode(digest).decode()

    async def request(self, method: str, path: str, body: dict | None = None):
        query = f"clientId={self._client_id}&timestamp={int(time.time())}"
        headers = {"Signature": self._sign(path, query, body)}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.request(
                method, f"{BASE}{path}?{query}", headers=headers,
                json=body if body is not None else None)
        if resp.status_code >= 400:
            raise RuntimeError(f"{method} {path} -> {resp.status_code}: {resp.text[:300]}")
        return resp.json()


async def run(upgrade: bool, open_browser: bool) -> int:
    cfg = get_config()
    if not cfg.snaptrade_client_id or not cfg.snaptrade_consumer_key:
        print(f"{RED} SnapTrade credentials missing.")
        print("   Dashboard → API Key page → create a personal client ID + consumer key,")
        print("   then add to backend/.env:")
        print("     ZARGAR_SNAPTRADE_CLIENT_ID=...")
        print("     ZARGAR_SNAPTRADE_CONSUMER_KEY=...")
        return 1

    st = SnapTradeClient(cfg.snaptrade_client_id, cfg.snaptrade_consumer_key)

    try:
        connections = await st.request("GET", "/api/v1/authorizations")
    except RuntimeError as exc:
        print(f"{RED} Could not list connections: {exc}")
        if "401" in str(exc) or "signature" in str(exc).lower():
            print("   Check that the consumer key matches the client ID (both from the")
            print("   dashboard API Key page) and that your system clock is accurate.")
        return 1

    print(f"{GREEN} Credentials valid — {len(connections)} connection(s)")
    read_only = []
    for conn in connections:
        name = (conn.get("brokerage") or {}).get("display_name") or "?"
        ctype = conn.get("type", "?")
        disabled = conn.get("disabled", False)
        status = f"{RED} DISABLED" if disabled else f"{GREEN} active"
        print(f"   {status}  {name:<16} type={ctype:<10} id={conn.get('id')}")
        if not disabled and ctype != "trade":
            read_only.append(conn)

    try:
        accounts = await st.request("GET", "/api/v1/accounts")
        for acct in accounts:
            bal = (acct.get("balance") or {}).get("total") or {}
            amount, currency = bal.get("amount"), bal.get("currency", "")
            total = f"{amount:,.2f} {currency}" if isinstance(amount, (int, float)) else "n/a"
            print(f"{GREEN} Account: {acct.get('name') or acct.get('number'):<28} "
                  f"{acct.get('institution_name', ''):<16} balance {total}")
    except RuntimeError as exc:
        print(f"{WARN} Could not list accounts: {exc}")

    if not upgrade:
        if read_only:
            print(f"\n{WARN} {len(read_only)} connection(s) are not trade-enabled. Re-run with"
                  " --upgrade to generate re-authorization URLs.")
        return 0

    if not read_only:
        print(f"\n{GREEN} All active connections are already trade-enabled.")
        return 0

    print(f"\nGenerating trade re-authorization URLs ({len(read_only)}) …")
    failures = 0
    for conn in read_only:
        name = (conn.get("brokerage") or {}).get("display_name") or "?"
        try:
            login = await st.request("POST", "/api/v1/snapTrade/login", {
                "reconnect": conn["id"],
                "connectionType": "trade",
            })
        except RuntimeError as exc:
            print(f"{RED} {name}: {exc}")
            failures += 1
            continue
        uri = login.get("redirectURI")
        if not uri:
            print(f"{RED} {name}: no redirectURI in response: {json.dumps(login)[:200]}")
            failures += 1
            continue
        print(f"{GREEN} {name}: open this URL and re-login to grant trade access:")
        print(f"   {uri}")
        if open_browser:
            webbrowser.open(uri)

    print(f"\nAfter completing the browser logins, re-run this tool — every")
    print(f"connection should show type=trade.")
    return 1 if failures else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Zargar ↔ SnapTrade connectivity check")
    parser.add_argument("--upgrade", action="store_true",
                        help="generate re-auth URLs upgrading read-only connections to trade")
    parser.add_argument("--no-browser", action="store_true",
                        help="print upgrade URLs without opening a browser")
    args = parser.parse_args()
    try:
        code = asyncio.run(run(args.upgrade, open_browser=not args.no_browser))
    except KeyboardInterrupt:
        code = 130
    sys.exit(code)


if __name__ == "__main__":
    main()
