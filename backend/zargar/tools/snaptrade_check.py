"""SnapTrade connectivity self-test and connection manager.

Requires personal API credentials in backend/.env:

    ZARGAR_SNAPTRADE_CLIENT_ID=...
    ZARGAR_SNAPTRADE_CONSUMER_KEY=...

Usage (from backend/):

    .venv/bin/python -m zargar.tools.snaptrade_check              # status + connections + accounts
    .venv/bin/python -m zargar.tools.snaptrade_check --upgrade    # re-auth URL to upgrade the next
                                                                  # read-only connection to trade
    .venv/bin/python -m zargar.tools.snaptrade_check --balances   # raw balances payloads (JSON)
    .venv/bin/python -m zargar.tools.snaptrade_check --positions  # raw positions payloads (JSON)

Read-only against your brokerage accounts: never places orders. --upgrade only
generates SnapTrade Connection Portal URLs; you complete the broker login in
the browser yourself. The raw dump modes exist to verify SnapTrade's actual
field shapes per broker before the sync service trusts them.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import webbrowser

from ..brokers.snaptrade import SnapTradeClient, SnapTradeError, SnapTradeUnknownOutcome
from ..config import get_config

GREEN = "\033[1;32m✓\033[0m"
RED = "\033[1;31m✗\033[0m"
WARN = "\033[1;33m!\033[0m"


async def run(upgrade: bool, open_browser: bool, dump: str | None) -> int:
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
        return await _run(st, upgrade, open_browser, dump)
    finally:
        await st.aclose()


async def _run(st: SnapTradeClient, upgrade: bool, open_browser: bool, dump: str | None) -> int:
    try:
        connections = await st.request("GET", "/api/v1/authorizations")
    except (SnapTradeError, SnapTradeUnknownOutcome) as exc:
        print(f"{RED} Could not list connections: {exc}")
        if isinstance(exc, SnapTradeError) and exc.status == 401:
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
    except (SnapTradeError, SnapTradeUnknownOutcome) as exc:
        print(f"{WARN} Could not list accounts: {exc}")
        accounts = []
    for acct in accounts:
        bal = (acct.get("balance") or {}).get("total") or {}
        amount, currency = bal.get("amount"), bal.get("currency", "")
        if isinstance(currency, dict):
            currency = currency.get("code", "")
        total = f"{amount:,.2f} {currency}" if isinstance(amount, (int, float)) else "n/a"
        print(f"{GREEN} Account: {acct.get('name') or acct.get('number'):<28} "
              f"{acct.get('institution_name', ''):<16} balance {total}")

    if dump:
        for acct in accounts:
            aid = acct.get("id")
            print(f"\n=== {acct.get('institution_name')} {acct.get('name')} ({aid}) — {dump} ===")
            try:
                payload = await st.request("GET", f"/api/v1/accounts/{aid}/{dump}")
                print(json.dumps(payload, indent=2, default=str)[:4000])
            except (SnapTradeError, SnapTradeUnknownOutcome) as exc:
                print(f"{RED} {exc}")
        return 0

    if not upgrade:
        if read_only:
            print(f"\n{WARN} {len(read_only)} connection(s) are not trade-enabled. Re-run with"
                  " --upgrade to generate a re-authorization URL.")
        return 0

    if not read_only:
        print(f"\n{GREEN} All active connections are already trade-enabled.")
        return 0

    # One connection per run: portal tokens are session-bound, so a second URL
    # generated in the same run dies the moment the first login completes.
    conn = read_only[0]
    name = (conn.get("brokerage") or {}).get("display_name") or "?"
    print(f"\nGenerating trade re-authorization URL for {name} …")
    try:
        login = await st.request("POST", "/api/v1/snapTrade/login", {
            "reconnect": conn["id"],
            "connectionType": "trade",
        })
    except (SnapTradeError, SnapTradeUnknownOutcome) as exc:
        print(f"{RED} {name}: {exc}")
        return 1
    uri = login.get("redirectURI")
    if not uri:
        print(f"{RED} {name}: no redirectURI in response: {json.dumps(login)[:200]}")
        return 1
    print(f"{GREEN} {name}: open this URL and re-login to grant trade access:")
    print(f"   {uri}")
    if open_browser:
        webbrowser.open(uri)

    remaining = len(read_only) - 1
    print(f"\nAfter completing the browser login, re-run this tool"
          + (f" — {remaining} more connection(s) still need upgrading."
             if remaining else " to verify type=trade."))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Zargar ↔ SnapTrade connectivity check")
    parser.add_argument("--upgrade", action="store_true",
                        help="generate a re-auth URL upgrading a read-only connection to trade")
    parser.add_argument("--no-browser", action="store_true",
                        help="print upgrade URLs without opening a browser")
    parser.add_argument("--balances", action="store_true",
                        help="dump raw per-account balances payloads (read-only)")
    parser.add_argument("--positions", action="store_true",
                        help="dump raw per-account positions payloads (read-only)")
    args = parser.parse_args()
    dump = "balances" if args.balances else "positions" if args.positions else None
    try:
        code = asyncio.run(run(args.upgrade, open_browser=not args.no_browser, dump=dump))
    except KeyboardInterrupt:
        code = 130
    sys.exit(code)


if __name__ == "__main__":
    main()
