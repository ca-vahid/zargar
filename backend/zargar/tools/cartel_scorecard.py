"""The ONE computation of the Options Cartel Practice trial's stop-rule score. Read-only; places no orders.

    python -m zargar.tools.cartel_scorecard [--portfolio ID] [--start 2026-10-13] [--sessions 20] [--json]

Definition (written 2026-10-12, before the restarted sample; `reviews/2026-09-24-sharp-pencil/PLAN.md` section 10):

* A TRADE is one managed Cartel position (campaign) whose entry filled on or after ``--start`` on the book.
* It is CLOSED when no contracts remain (status closed). A partial exit does not close a trade.
* NET of a closed trade = sell proceeds - buy cost (x100 for options, x1 for shares) - every commission on its fills.
* The SCORE is the count of closed trades and the sum of their nets. Open positions are listed with the money
  already banked and the cost still at risk, and are NEVER part of the score (no mark is used anywhere).
* CONCENTRATION: the score is also shown without its single best closed trade.
* SESSIONS: trading days from ``--start`` to today; a session RAN when Cartel had at least one arm for it.
  The verdict is only final after ``--sessions`` sessions have RUN.

Verdict (preregistered): fewer than 8 closed trades -> stop; 8+ and net <= 0 -> stop; 8+ and net > 0 -> keep
(longer sample; never live money on this evidence alone). A positive net that turns <= 0 without its best trade
is reported as "depends on one trade".
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os

from ..marketstructure.market_calendar import is_trading_day
from ..marketstructure.sessions import ET

BOOK = "297d8b39d1c4418199f24c2331b14c11"
MIN_TRADES = 8


def multiplier(symbol: str) -> int:
    return 100 if len(symbol) > 10 and any(c.isdigit() for c in symbol) else 1


def score(positions: list[dict], fills: list[dict], *, start_ms: int) -> dict:
    """Pure. ``positions``: id, symbol, status, runId, openedMs. ``fills``: side, qty, price, commission, symbol,
    tags (of the order), ts (ms). A fill belongs to a position through ``cartel_run:<runId>`` (entry) or
    ``managed_exit:<positionId>:`` (exit) order tags."""
    trades = []
    for p in positions:
        if (p.get("openedMs") or 0) < start_ms:
            continue
        own = [f for f in fills if any(t == f"cartel_run:{p['runId']}" or t.startswith(f"managed_exit:{p['id']}:")
                                       for t in f.get("tags") or [])]
        bought = sum(f["qty"]*f["price"]*multiplier(f["symbol"]) for f in own if f["side"] == "BUY")
        sold = sum(f["qty"]*f["price"]*multiplier(f["symbol"]) for f in own if f["side"] == "SELL")
        fees = sum(f.get("commission") or 0 for f in own)
        qty_in = sum(f["qty"] for f in own if f["side"] == "BUY")
        qty_out = sum(f["qty"] for f in own if f["side"] == "SELL")
        closed = p["status"] == "closed" and qty_in > 0 and abs(qty_in-qty_out) < 1e-9
        trades.append({"positionId": p["id"], "symbol": p["symbol"], "openedMs": p["openedMs"], "closed": closed,
                       "contractsIn": qty_in, "contractsOut": qty_out, "bought": round(bought, 2), "sold": round(sold, 2),
                       "fees": round(fees, 2), "net": round(sold-bought-fees, 2) if closed else None,
                       "bankedSoFar": round(sold-fees, 2) if not closed else None,
                       "costStillOpen": round(bought*(qty_in-qty_out)/qty_in, 2) if not closed and qty_in else None})
    done = [t for t in trades if t["closed"]]
    net = round(sum(t["net"] for t in done), 2)
    best = max((t["net"] for t in done), default=0.0)
    return {"trades": trades, "closedTrades": len(done), "openTrades": len(trades)-len(done), "net": net,
            "winners": sum(t["net"] > 0 for t in done), "fees": round(sum(t["fees"] for t in done), 2),
            "netWithoutBest": round(net-best, 2) if done else 0.0}


def verdict(card: dict, *, sessions_run: int, sessions: int) -> str:
    final = sessions_run >= sessions
    if card["closedTrades"] < MIN_TRADES:
        return "STOP: fewer than 8 closed trades" if final else f"not final: {card['closedTrades']} of 8 closed trades so far"
    if card["net"] <= 0:
        return "STOP: net at or below zero after fees" if final else "not final: net at or below zero so far"
    one = " (depends on one trade)" if card["netWithoutBest"] <= 0 else ""
    return ("KEEP: longer sample, never live money on this evidence alone" if final else "not final: positive so far") + one


def trading_days(start: dt.date, end: dt.date) -> list[dt.date]:
    out, d = [], start
    while d <= end:
        if is_trading_day(d):
            out.append(d)
        d += dt.timedelta(days=1)
    return out


async def load(database_url: str, portfolio: str, start: dt.date):
    import asyncpg
    conn = await asyncpg.connect(database_url.replace("postgresql+asyncpg://", "postgresql://"),
                                 server_settings={"default_transaction_read_only": "on"})
    try:
        rows = await conn.fetch("select id, symbol, status, config->>'runId' run, state->>'openedMs' opened from managed_positions "
                                "where portfolio_id=$1 and technique='options_cartel'", portfolio)
        positions = [{"id": r["id"], "symbol": r["symbol"], "status": r["status"], "runId": r["run"],
                      "openedMs": int(float(r["opened"] or 0))} for r in rows]
        frows = await conn.fetch("select e.side, e.qty, e.price, e.commission, e.symbol, e.ts, o.tags from executions e "
                                 "join orders o on o.id=e.order_id where e.portfolio_id=$1 order by e.ts", portfolio)
        fills = [{"side": r["side"], "qty": r["qty"], "price": r["price"], "commission": r["commission"], "symbol": r["symbol"],
                  "ts": int(r["ts"].timestamp()*1000), "tags": json.loads(r["tags"]) if isinstance(r["tags"], str) else (r["tags"] or [])}
                 for r in frows]
        armed = await conn.fetch("select distinct (config->>'session') s from technique_runs where technique='options_cartel' and mode='preparation' "
                                 "and config->>'portfolioId'=$1 and config->>'session'>=$2 and coalesce((result->>'armed')::int,0) > 0",
                                 portfolio, start.isoformat())
        return positions, fills, {r["s"] for r in armed}
    finally:
        await conn.close()


async def main():
    from ..config import AppConfig
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--portfolio", default=BOOK)
    ap.add_argument("--start", default="2026-10-13")
    ap.add_argument("--sessions", type=int, default=20)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    start = dt.date.fromisoformat(args.start)
    url = os.environ.get("CARTEL_AUDIT_DATABASE_URL") or AppConfig().database_url
    positions, fills, armed_sessions = await load(url, args.portfolio, start)
    today = dt.datetime.now(ET).date()
    days = trading_days(start, today)
    ran = [d for d in days if d.isoformat() in armed_sessions]
    start_ms = int(dt.datetime.combine(start, dt.time(), ET).timestamp()*1000)
    card = score(positions, fills, start_ms=start_ms)
    card.update(start=args.start, sessions=args.sessions, tradingDaysElapsed=len(days), sessionsRun=len(ran),
                sessionsNotRun=[d.isoformat() for d in days if d not in ran and d < today],
                verdict=verdict(card, sessions_run=len(ran), sessions=args.sessions), placesOrders=False)
    if args.json:
        print(json.dumps(card, indent=1))
        return
    print(f"Options Cartel trial from {args.start}: {len(ran)} of {args.sessions} sessions run ({len(days)} trading days elapsed)")
    print(f"closed trades {card['closedTrades']} (need {MIN_TRADES}) | net after fees {card['net']:+.2f} | without best {card['netWithoutBest']:+.2f} "
          f"| winners {card['winners']} | fees {card['fees']:.2f} | open {card['openTrades']}")
    for t in card["trades"]:
        day = dt.datetime.fromtimestamp(t["openedMs"]/1000, ET).strftime("%m-%d")
        tail = f"net {t['net']:+.2f}" if t["closed"] else f"OPEN {t['contractsIn']-t['contractsOut']:g} left, banked {t['bankedSoFar']:+.2f}, cost at risk {t['costStillOpen']:.2f}"
        print(f"  {day} {t['symbol']:6} in {t['contractsIn']:g} out {t['contractsOut']:g} fees {t['fees']:.2f}  {tail}")
    if card["sessionsNotRun"]:
        print("sessions with no Cartel arms:", ", ".join(card["sessionsNotRun"]))
    print("verdict:", card["verdict"])


if __name__ == "__main__":
    asyncio.run(main())
