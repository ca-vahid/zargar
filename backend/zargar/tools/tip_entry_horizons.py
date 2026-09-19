"""Entry-study fixed horizons (entry-horizons-v2, 2026-09-19): TAKES and SKIPS on ONE evidence standard.

Every `TipEntryStudy` row with phase=created carries the quote the decision saw, for a take and a skip alike, so
both groups can be scored from the same kind of starting price on the same fixed horizons.

v2 (review ECON-02) - what counts as evidence:
* STARTING QUOTE: eligible only when the existing executable-evidence rule accepts it (`cohort.qualify_quote`:
  venue identity opra/ibkr, not delayed, a genuine source time, a valid uncrossed two-sided quote, inside the option
  venue session) AND it is at most START_MAX_AGE_S old at the sample. An ineligible start is counted and excluded.
* FORWARD ONLY: a horizon print is strictly AFTER the decision sample. A 15:40 print never scores a 15:55 decision.
* EXCHANGE-CALENDAR WINDOWS (`marketstructure.market_calendar`: holidays, early closes):
    +30 min        first print in [t0+30m, t0+45m], inside the decision session
    session close  last print in the final 30 minutes of the DECISION session (and after t0)
    next close     last print in the final 30 minutes of the NEXT TRADING session - a lone 09:31 print is not a close
* Missing stays missing, and the time of every print used is recorded.

Outcome = (print - ask) / ask and $ = (print - ask) x 100 - round-trip fees. Prints are Yahoo 1m TRADE prints, NOT
NBBO quotes: a print can lie on either side of the contemporaneous market and is NOT an executable bid fill. These
are DIAGNOSTICS - they book nothing, prove no realizable profit and change no rule. The same contract observed
several times is reported explicitly (observations vs distinct contracts).

  .venv/Scripts/python -m zargar.tools.tip_entry_horizons --since 2026-09-11 [--until 2026-09-18] [--json out.json]
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import datetime as dt
import json
import re
import statistics
import time

import asyncpg
import httpx

from ..marketstructure import market_calendar as cal
from ..techniques.tip.cohort import qualify_quote

VERSION = "entry-horizons-v2"
ET = dt.timezone(dt.timedelta(hours=-4))
OCC = re.compile(r"^([A-Z.]{1,6})(\d{6})([CP])(\d{8})$")
FEES_ROUND_TRIP = 2.08
START_MAX_AGE_S = 15.0          # the same freshness bound the Practice fill rule applies to a quote's source time
CLOSE_WINDOW_MIN = 30
OPEN_MIN = 9 * 60 + 30


def J(v):
    return (json.loads(v) if isinstance(v, str) else v) or {}


def next_session(d: dt.date) -> dt.date:
    return cal.next_trading_day(d)


def session_close(d: dt.date) -> dt.datetime:
    m = cal.session_close_minutes(d)
    return dt.datetime(d.year, d.month, d.day, m // 60, m % 60, tzinfo=ET)


def in_session(t: dt.datetime) -> bool:
    t = t.astimezone(ET)
    if not cal.is_trading_day(t.date()):
        return False
    mins = t.hour * 60 + t.minute
    return OPEN_MIN <= mins < cal.session_close_minutes(t.date())


def start_eligibility(payload: dict, sampled: dt.datetime) -> tuple[bool, list[str]]:
    """Is the decision-time quote executable comparison evidence? Reuses `cohort.qualify_quote`."""
    q = dict(payload.get("atDecision") or {})
    now_ms = int(sampled.timestamp() * 1000)
    src_ts = int(q.get("sourceTs") or 0)
    if src_ts > 0:
        q["ageSeconds"] = max(0.0, (now_ms - src_ts) / 1000.0)
    status, reasons = qualify_quote(q, is_option=True, max_age_s=START_MAX_AGE_S, now_ms=now_ms)
    return status == "fresh", ([] if status == "fresh" else (reasons or [status]))


def score(t0: dt.datetime, ask: float, prints: list[tuple[dt.datetime, float]] | None) -> dict:
    """Pure: the three horizon prints for one decision - forward-only, calendar windows, missing stays None."""
    out = {"p30": None, "p30At": None, "pclose": None, "pcloseAt": None, "pnext": None, "pnextAt": None,
           "missing": prints is None, "inSession": None}
    t0 = t0.astimezone(ET)
    out["inSession"] = in_session(t0)
    if not prints or not out["inSession"]:
        return out
    fwd = sorted((p for p in prints if p[0] > t0), key=lambda p: p[0])          # FORWARD ONLY
    day_close = session_close(t0.date())
    w30 = [p for p in fwd if t0 + dt.timedelta(minutes=30) <= p[0] <= min(t0 + dt.timedelta(minutes=45), day_close)]
    if w30:
        out["p30"], out["p30At"] = w30[0][1], w30[0][0].isoformat()
    wclose = [p for p in fwd if day_close - dt.timedelta(minutes=CLOSE_WINDOW_MIN) <= p[0] <= day_close]
    if wclose:
        out["pclose"], out["pcloseAt"] = wclose[-1][1], wclose[-1][0].isoformat()
    nclose = session_close(next_session(t0.date()))
    wnext = [p for p in fwd if nclose - dt.timedelta(minutes=CLOSE_WINDOW_MIN) <= p[0] <= nclose]
    if wnext:
        out["pnext"], out["pnextAt"] = wnext[-1][1], wnext[-1][0].isoformat()
    return out


def dte_bucket(symbol: str, day: dt.date) -> str:
    m = OCC.match(symbol or "")
    if not m:
        return "shares"
    d = (dt.datetime.strptime(m.group(2), "%y%m%d").date() - day).days
    return "0-4" if d <= 4 else "5-14" if d <= 14 else "15-45" if d <= 45 else "46+"


def _fetch(symbol: str, a: dt.datetime, b: dt.datetime):
    for _ in range(3):
        try:
            r = httpx.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
                          params={"period1": int(a.timestamp()), "period2": int(b.timestamp()), "interval": "1m"},
                          headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
            res = (r.json().get("chart") or {}).get("result")
            if not res:
                return []
            j = res[0]; ts = j.get("timestamp") or []; q = j["indicators"]["quote"][0]
            return [(dt.datetime.fromtimestamp(t, ET), q["close"][i]) for i, t in enumerate(ts)
                    if q["close"][i] is not None and (q["volume"][i] or 0) > 0]
        except Exception:                                   # noqa: BLE001
            time.sleep(1.5)
    return None


def summarize(rows: list[dict], key: str) -> dict:
    vals = [(r[key] - r["ask"]) / r["ask"] for r in rows if r.get(key) is not None]
    usd = [(r[key] - r["ask"]) * 100 - FEES_ROUND_TRIP for r in rows if r.get(key) is not None]
    if not vals:
        return {"n": 0, "of": len(rows)}
    return {"n": len(vals), "of": len(rows), "median": statistics.median(vals), "mean": statistics.mean(vals),
            "up": sum(v > 0 for v in vals), "usdMean": statistics.mean(usd), "usdMedian": statistics.median(usd)}


def render(out: list[dict], excluded: collections.Counter, since: str) -> str:
    L = [f"# Entry-study fixed horizons ({VERSION}) - decisions since {since}\n",
         "Start = the decision's own ask, used only when `qualify_quote` accepts it (venue identity, not delayed, genuine "
         f"source time <= {START_MAX_AGE_S:g}s old, uncrossed, in the venue session). Horizon prints are strictly AFTER the "
         "decision, inside exchange-calendar windows (final 30 minutes for a close). Prints are TRADE prints, not NBBO: "
         "DIAGNOSTICS, not executable fills and not proof of realizable profit. Missing stays missing. "
         f"$ = per contract after ${FEES_ROUND_TRIP:.2f} round-trip fees.\n"]
    contracts = {x["symbol"] for x in out}
    L.append(f"Denominator: {len(out)} eligible observation(s) on {len(contracts)} distinct contract(s); "
             f"{len(out) - len(contracts)} repeat observation(s) of an already-observed contract. "
             f"Excluded before scoring: {sum(excluded.values())} - " + (", ".join(f"{k}: {v}" for k, v in excluded.most_common()) or "none") + ".\n")
    for group, key in (("verdict", "verdict"), ("DTE bucket", "dte")):
        L.append(f"| {group} | observations | horizon | n | median | mean | up | $ mean | $ median |")
        L.append("|---|---:|---|---:|---:|---:|---:|---:|---:|")
        by = collections.defaultdict(list)
        for x in out:
            by[x[key]].append(x)
        for g, xs in sorted(by.items()):
            for h, label in (("p30", "+30 min"), ("pclose", "session close"), ("pnext", "next close")):
                s = summarize(xs, h)
                if not s["n"]:
                    L.append(f"| {g} | {len(xs)} | {label} | 0 | | | | | |")
                    continue
                L.append(f"| {g} | {len(xs)} | {label} | {s['n']} | {s['median']:+.0%} | {s['mean']:+.0%} | {s['up']} | "
                         f"{s['usdMean']:+,.0f} | {s['usdMedian']:+,.0f} |")
        L.append("")
    paired = [x for x in out if x.get("pnext") is not None and x.get("pclose") is not None]
    if paired:
        drift = [(x["pnext"] - x["pclose"]) / x["pclose"] for x in paired]
        L.append(f"Paired drift, decision-session close window -> next-session close window (same observation, both prints "
                 f"present): n={len(drift)} on {len({x['symbol'] for x in paired})} contract(s), median "
                 f"{statistics.median(drift):+.0%}, mean {statistics.mean(drift):+.0%}, up {sum(v > 0 for v in drift)}.")
        by = collections.defaultdict(list)
        for x in paired:
            by[x["dte"]].append((x["pnext"] - x["pclose"]) / x["pclose"])
        for k, v in sorted(by.items()):
            L.append(f"- DTE {k}: n={len(v)} median {statistics.median(v):+.0%} mean {statistics.mean(v):+.0%} up {sum(i > 0 for i in v)}")
    else:
        L.append("Paired drift: no observation has both a close-window and a next-close-window print.")
    L.append("\nLimits: takes and skips differ in setup and DTE, so the groups are not matched; samples are small; one market "
             "regime; a trade print is not a quote. Nothing here supports a rule change on its own.")
    return "\n".join(L) + "\n"


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="postgresql://zargar:zargar@127.0.0.1:5433/zargar")
    ap.add_argument("--since", default="2026-09-11")
    ap.add_argument("--until", default="")
    ap.add_argument("--json", default="")
    a = ap.parse_args()
    c = await asyncpg.connect(a.db, server_settings={"default_transaction_read_only": "on"})
    try:
        since = dt.datetime.fromisoformat(a.since).replace(tzinfo=ET)
        until = (dt.datetime.fromisoformat(a.until).replace(tzinfo=ET) + dt.timedelta(days=1)) if a.until else None
        rows = await c.fetch("""select ts, payload from events where type='TipEntryStudy' and payload->>'phase'='created'
                                and ts >= $1 order by ts""", since)
    finally:
        await c.close()
    out, excluded = [], collections.Counter()
    for r in rows:
        if until and r["ts"] >= until:
            continue
        p = J(r["payload"]); sym = p.get("symbol") or ""
        if not OCC.match(sym):
            excluded["not an option"] += 1
            continue
        try:
            sampled = dt.datetime.fromisoformat(p.get("sampledAt")) if p.get("sampledAt") else r["ts"]
        except ValueError:
            sampled = r["ts"]
        ok, why = start_eligibility(p, sampled)
        if not ok:
            excluded["ineligible start: " + (why[0] if why else "unknown")] += 1
            continue
        t0 = sampled.astimezone(ET)
        ask = float((p.get("atDecision") or {}).get("ask"))
        end = session_close(next_session(t0.date()))
        s = score(t0, ask, _fetch(sym, t0, end))
        q = p.get("atDecision") or {}
        out.append({"symbol": sym, "verdict": p.get("verdict") or "-", "ask": ask, "t0": t0.isoformat(),
                    "startSource": q.get("source"), "startSourceTs": q.get("sourceTs"), "dte": dte_bucket(sym, t0.date()), **s})
        time.sleep(0.3)
    print(render(out, excluded, a.since))
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump({"version": VERSION, "rows": out, "excluded": dict(excluded)}, f, indent=1, default=str)


if __name__ == "__main__":
    asyncio.run(main())
