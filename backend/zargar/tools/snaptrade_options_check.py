"""SnapTrade options capability probe — read-only, never places an order.

Answers "can THIS connected account trade options through SnapTrade?" per
account by calling the option-order *impact* endpoint (a broker-side
simulation: nothing is placed, nothing is reserved) with one cheap, liquid,
real contract, and by listing what SnapTrade knows about each brokerage.

Usage (from backend/):

    .venv/bin/python -m zargar.tools.snaptrade_options_check            # summary table
    .venv/bin/python -m zargar.tools.snaptrade_options_check --json     # raw payloads
    .venv/bin/python -m zargar.tools.snaptrade_options_check --underlying SPY

Findings on 2026-08-21 (see docs/OPTIONS-PLAN.md §1): Webull Canada (CASH and
MARGIN) -> supported; Wealthsimple -> SnapTrade code 1156 "Option Trade impact
is not supported for this brokerage".
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import sys

import httpx

from ..brokers.snaptrade import SnapTradeClient, SnapTradeError, SnapTradeUnknownOutcome
from ..config import get_config

GREEN = "\033[1;32m✓\033[0m"
RED = "\033[1;31m✗\033[0m"
WARN = "\033[1;33m!\033[0m"

CBOE_URL = "https://cdn.cboe.com/api/global/delayed_quotes/options/{symbol}.json"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36")


def occ_padded(root: str, expiry: dt.date, right: str, strike: float) -> str:
    """SnapTrade's 21-char OCC form: root space-padded to 6, yymmdd, C/P, strike*1000."""
    return f"{root.upper():<6}{expiry:%y%m%d}{right}{int(round(strike * 1000)):08d}"


async def cheap_contract(underlying: str) -> dict | None:
    """Nearest weekly, first OTM call with a live ask — from CBOE's free delayed chain."""
    async with httpx.AsyncClient(timeout=30, headers={"User-Agent": UA},
                                 follow_redirects=True) as http:
        r = await http.get(CBOE_URL.format(symbol=underlying.upper()))
        if r.status_code != 200:
            return None
        data = (r.json() or {}).get("data") or {}
    spot = float(data.get("current_price") or data.get("close") or 0)
    today = dt.date.today()
    best = None
    for row in data.get("options") or []:
        s = str(row.get("option") or "")
        if len(s) < 16:
            continue
        root, ymd, right, strike = s[:-15], s[-15:-9], s[-9], int(s[-8:]) / 1000
        try:
            exp = dt.date(2000 + int(ymd[:2]), int(ymd[2:4]), int(ymd[4:]))
        except ValueError:
            continue
        dte = (exp - today).days
        if right != "C" or strike <= spot or not 7 <= dte <= 45 or not row.get("ask"):
            continue
        key = (dte, strike)
        if best is None or key < best["key"]:
            best = {"key": key, "root": root, "expiry": exp, "strike": strike,
                    "bid": row.get("bid") or 0.0, "ask": row.get("ask") or 0.0,
                    "spot": spot, "cboe_symbol": s}
    return best


async def run(underlying: str, as_json: bool) -> int:
    cfg = get_config()
    if not cfg.snaptrade_client_id or not cfg.snaptrade_consumer_key:
        print(f"{RED} SnapTrade credentials missing (ZARGAR_SNAPTRADE_CLIENT_ID / _CONSUMER_KEY).")
        return 1
    st = SnapTradeClient(cfg.snaptrade_client_id, cfg.snaptrade_consumer_key)
    try:
        return await _run(st, underlying, as_json)
    finally:
        await st.aclose()


async def _run(st: SnapTradeClient, underlying: str, as_json: bool) -> int:
    out: dict = {"underlying": underlying}
    pick = await cheap_contract(underlying)
    if pick is None:
        print(f"{RED} CBOE has no usable chain for {underlying} (US listings only).")
        return 1
    sym = occ_padded(pick["root"], pick["expiry"], "C", pick["strike"])
    out["probe"] = {"occ": sym, "spot": pick["spot"], "bid": pick["bid"], "ask": pick["ask"],
                    "expiry": pick["expiry"].isoformat(), "strike": pick["strike"]}
    body = {
        "order_type": "LIMIT", "time_in_force": "Day", "price_effect": "DEBIT",
        "limit_price": f"{max(0.01, float(pick['bid'] or 0.01)):.2f}",
        "legs": [{"instrument": {"symbol": sym, "instrument_type": "OPTION"},
                  "action": "BUY_TO_OPEN", "units": 1}],
    }
    out["impact_request"] = body

    try:
        accounts = await st.request("GET", "/api/v1/accounts")
    except (SnapTradeError, SnapTradeUnknownOutcome) as exc:
        print(f"{RED} Could not list accounts: {exc}")
        return 1

    if not as_json:
        print(f"{GREEN} Probe contract: {sym!r}  (spot {pick['spot']}, bid/ask "
              f"{pick['bid']}/{pick['ask']}, exp {pick['expiry']})")
        print("   Impact = broker-side simulation; nothing is placed or reserved.\n")

    out["accounts"] = []
    code = 0
    for acct in accounts or []:
        aid = str(acct.get("id") or "")
        label = f"{acct.get('institution_name', '?'):<18} {acct.get('name') or acct.get('number') or aid[:8]}"
        entry = {"id": aid, "institution": acct.get("institution_name"), "name": acct.get("name"),
                 "type": (acct.get("meta") or {}).get("type") or acct.get("raw_type"),
                 "status": (acct.get("meta") or {}).get("status")}
        try:
            res = await st.request("POST", f"/api/v1/accounts/{aid}/trading/options/impact", body)
            entry["impact"] = res
            entry["supported"] = True
            if not as_json:
                print(f"{GREEN} {label:<42} options OK — cash {res.get('cash_change_direction')} "
                      f"{res.get('estimated_cash_change')}  fees {res.get('estimated_fee_total')}")
        except SnapTradeError as exc:
            entry["impact_error"] = {"status": exc.status, "body": exc.body}
            detail = exc.body.get("detail") if isinstance(exc.body, dict) else exc.body
            scode = exc.body.get("code") if isinstance(exc.body, dict) else None
            entry["supported"] = False if str(scode) == "1156" else None
            if not as_json:
                mark = RED if entry["supported"] is False else WARN
                print(f"{mark} {label:<42} {exc.status} [{scode}] {detail}")
            code = code or 2
        except SnapTradeUnknownOutcome as exc:
            entry["impact_error"] = {"unknown": str(exc)}
            entry["supported"] = None
            if not as_json:
                print(f"{WARN} {label:<42} unknown outcome: {exc}")
        out["accounts"].append(entry)

    if as_json:
        print(json.dumps(out, indent=2, default=str))
    else:
        print("\nLegend: ✓ supported (this is the venue for options) · ✗ SnapTrade code 1156, "
              "not supported for this brokerage · ! inconclusive")
    return code


def main() -> None:
    parser = argparse.ArgumentParser(description="Zargar ↔ SnapTrade options capability probe (read-only)")
    parser.add_argument("--underlying", default="F", help="US underlying to pick the probe contract from (default F)")
    parser.add_argument("--json", action="store_true", help="print raw payloads as JSON")
    args = parser.parse_args()
    # Windows consoles default to cp1252; the ✓/✗ markers would otherwise crash the run.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    try:
        code = asyncio.run(run(args.underlying, args.json))
    except KeyboardInterrupt:
        code = 130
    sys.exit(code)


if __name__ == "__main__":
    main()
