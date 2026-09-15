"""Historical evidence for the late-delivered tips of one session (KFIN-10, 2026-09-14).

The reviewer's coverage assessment (`reviews/2026-09-14-late-message-evidence-coverage.md`)
found ZERO contemporaneous NBBO for the option entry candidates in local stores. This tool
attempts retrieval through the already-authorized provider (Alpaca market data, the same
keys `research/optiontrades.py` uses), PERSISTS what came back with provider/time/quality
metadata (`historical_evidence`), and writes an honest per-case disposition:

  * option TRADES (prints with exchange + condition codes) around the post time,
  * option 1-minute BARS for the RTH window,
  * the NBBO endpoint is probed and its refusal recorded verbatim — Alpaca's
    `/v1beta1/options/quotes` answers 404 under this entitlement, so bid/ask/sizes
    at the alert are recorded as UNAVAILABLE, never estimated from prints or bars.

Nothing here prices a missed trade: a print is not an executable quote and a bar is not
a fill. Shares branches get a descriptive underlying path from the local `bars` table.

Usage (from backend/, runtime DB via ZARGAR_DATABASE_URL_SYNC or the default):
    python -m zargar.tools.tip_late_evidence --start 2026-09-14T13:30:00Z --end 2026-09-14T20:00:00Z \
        --cutoff 2026-09-15T01:56:55.589979Z --out ../docs/techniques/tip/reviews/2026-09-14-late-evidence
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import re
from pathlib import Path
from zoneinfo import ZoneInfo

import asyncpg
import httpx

ET = ZoneInfo("America/New_York")
DEFAULT_DB = os.environ.get("ZARGAR_DATABASE_URL_SYNC",
                            os.environ.get("ZARGAR_DATABASE_URL", "postgresql://zargar:zargar@127.0.0.1:5433/zargar")
                            .replace("postgresql+asyncpg://", "postgresql://"))
DATA = "https://data.alpaca.markets/v1beta1/options"
COHORT_SQL = """
WITH late AS (
  SELECT r.id AS content_id, m.id AS message_id, r.source_name, m.posted_at, r.received_at
  FROM raw_content r JOIN discord_messages m ON m.id = r.meta->>'messageId'
  WHERE m.posted_at >= $1 AND m.posted_at < $2 AND r.received_at >= $2 AND r.received_at < $3)
SELECT late.message_id, late.source_name, late.posted_at, late.received_at, s.id AS signal_id, s.ticker, s.action,
       s.instrument, s.strike, s.expiry, s.premium, s.entry_price
FROM late JOIN signals s ON s.raw_content_id = late.content_id
WHERE s.is_actionable AND s.action IN ('open', 'add') AND (s.extraction->>'experiment') IS NULL
ORDER BY late.posted_at, s.id"""

DDL = """
CREATE TABLE IF NOT EXISTS historical_evidence (
  id BIGSERIAL PRIMARY KEY,
  requested_at TIMESTAMPTZ NOT NULL,
  provider TEXT NOT NULL,
  kind TEXT NOT NULL,
  symbol TEXT NOT NULL,
  signal_id TEXT,
  message_id TEXT,
  window_start TIMESTAMPTZ NOT NULL,
  window_end TIMESTAMPTZ NOT NULL,
  status TEXT NOT NULL,
  reason TEXT,
  record_count INTEGER NOT NULL DEFAULT 0,
  first_ts TIMESTAMPTZ,
  last_ts TIMESTAMPTZ,
  http_status INTEGER,
  request TEXT,
  payload JSONB NOT NULL DEFAULT '[]'::jsonb
)"""


def _keys() -> tuple[str, str]:
    key = os.environ.get("ZARGAR_ALPACA_KEY_ID", "")
    sec = os.environ.get("ZARGAR_ALPACA_SECRET", "")
    if not (key and sec) and Path(".env").exists():
        env = dict(re.findall(r"^(ZARGAR_ALPACA_[A-Z_]+)=(.*)$", Path(".env").read_text(encoding="utf-8"), re.M))
        key, sec = env.get("ZARGAR_ALPACA_KEY_ID", "").strip(), env.get("ZARGAR_ALPACA_SECRET", "").strip()
    return key, sec


def _occ(ticker: str, expiry, right: str, strike: float) -> str:
    from ..options import occ as occ_mod
    return occ_mod.make(ticker, expiry, right, float(strike)).symbol if hasattr(occ_mod.make(ticker, expiry, right, float(strike)), "symbol") \
        else str(occ_mod.make(ticker, expiry, right, float(strike)))


async def _fetch(http: httpx.AsyncClient, kind: str, symbol: str, start: dt.datetime, end: dt.datetime, headers: dict) -> dict:
    params = {"symbols": symbol, "start": start.isoformat().replace("+00:00", "Z"), "end": end.isoformat().replace("+00:00", "Z"),
              "limit": 10000}
    if kind == "bars":
        params["timeframe"] = "1Min"
    url = f"{DATA}/{kind}"
    records: list = []
    status = None
    reason = ""
    token = None
    for _page in range(20):
        p = dict(params)
        if token:
            p["page_token"] = token
        try:
            r = await http.get(url, params=p, headers=headers, timeout=60)
        except Exception as exc:
            return {"status": "error", "reason": f"{type(exc).__name__}: {exc}"[:200], "http": None, "records": [], "request": url}
        status = r.status_code
        if r.status_code != 200:
            reason = f"HTTP {r.status_code}: {r.text[:160]}"
            return {"status": "unavailable", "reason": reason, "http": status, "records": [], "request": url}
        j = r.json()
        chunk = (j.get(kind) or {}).get(symbol) or []
        records.extend(chunk)
        token = j.get("next_page_token")
        if not token:
            break
    return {"status": "ok" if records else "empty", "reason": "" if records else "provider returned no records for the window",
            "http": status, "records": records, "request": url}


def _ts(rec: dict) -> dt.datetime | None:
    t = rec.get("t")
    if not t:
        return None
    return dt.datetime.fromisoformat(str(t).replace("Z", "+00:00"))


async def run(*, db: str, start: dt.datetime, end: dt.datetime, cutoff: dt.datetime, out: Path | None) -> dict:
    key, sec = _keys()
    headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": sec}
    conn = await asyncpg.connect(db)
    report: dict = {"provider": "alpaca", "entitlement": "market-data keys in backend/.env (research/optiontrades.py)",
                    "requestedAt": dt.datetime.now(dt.timezone.utc).isoformat(), "window": [start.isoformat(), end.isoformat()],
                    "cutoff": cutoff.isoformat(), "keysPresent": bool(key and sec), "cases": []}
    try:
        await conn.execute(DDL)
        rows = await conn.fetch(COHORT_SQL, start, end, cutoff)
        async with httpx.AsyncClient() as http:
            # one NBBO probe per run: the entitlement answer is a fact of the run
            probe = await _fetch(http, "quotes", "SPY261219C00700000", start, start + dt.timedelta(minutes=5), headers) if key else \
                {"status": "unavailable", "reason": "no Alpaca keys", "http": None}
            report["nbboProbe"] = {k: probe.get(k) for k in ("status", "reason", "http")}
            for r in rows:
                posted = r["posted_at"]
                case = {"messageId": str(r["message_id"]), "signalId": str(r["signal_id"]), "source": r["source_name"],
                        "postedAt": posted.isoformat(), "postedET": posted.astimezone(ET).strftime("%H:%M:%S"),
                        "receivedAt": r["received_at"].isoformat(), "ticker": r["ticker"], "action": r["action"],
                        "instrument": r["instrument"], "strike": r["strike"], "expiry": (str(r["expiry"]) if r["expiry"] else None),
                        "statedPremium": r["premium"], "statedEntry": r["entry_price"]}
                if r["instrument"] in ("call", "put") and r["strike"] and r["expiry"]:
                    sym = _occ(r["ticker"], r["expiry"], r["instrument"], r["strike"])
                    case["symbol"] = sym
                    for kind, w0, w1 in (("trades", posted - dt.timedelta(minutes=5), posted + dt.timedelta(minutes=60)),
                                         ("bars", start, end)):
                        res = await _fetch(http, kind, sym, w0, w1, headers) if key else {"status": "unavailable", "reason": "no Alpaca keys", "http": None, "records": [], "request": ""}
                        recs = res.get("records") or []
                        ts = [t for t in (_ts(x) for x in recs) if t]
                        await conn.execute(
                            "INSERT INTO historical_evidence (requested_at, provider, kind, symbol, signal_id, message_id, window_start, window_end, "
                            "status, reason, record_count, first_ts, last_ts, http_status, request, payload) VALUES (now(),'alpaca',$1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14::jsonb)",
                            kind, sym, str(r["signal_id"]), str(r["message_id"]), w0, w1, res["status"], res.get("reason") or "",
                            len(recs), (min(ts) if ts else None), (max(ts) if ts else None), res.get("http"), res.get("request") or "",
                            json.dumps(recs[:5000]))
                        summ = {"status": res["status"], "reason": res.get("reason") or "", "count": len(recs),
                                "first": (min(ts).isoformat() if ts else None), "last": (max(ts).isoformat() if ts else None)}
                        if kind == "trades" and recs:
                            after = [x for x in recs if (_ts(x) or posted) >= posted]
                            win5 = [x for x in after if (_ts(x) or posted) <= posted + dt.timedelta(minutes=5)]
                            summ["firstPrintAfterPost"] = ({"t": after[0].get("t"), "p": after[0].get("p"), "s": after[0].get("s"),
                                                            "x": after[0].get("x"), "c": after[0].get("c")} if after else None)
                            if win5:
                                vol = sum(float(x.get("s") or 0) for x in win5) or 0
                                summ["prints5min"] = {"n": len(win5), "low": min(float(x["p"]) for x in win5), "high": max(float(x["p"]) for x in win5),
                                                      "vwap": (round(sum(float(x["p"]) * float(x.get("s") or 0) for x in win5) / vol, 4) if vol else None)}
                        if kind == "bars" and recs:
                            minute = posted.replace(second=0, microsecond=0)
                            at = next((x for x in recs if _ts(x) == minute), None)
                            summ["barAtPostMinute"] = ({k: at.get(k) for k in ("t", "o", "h", "l", "c", "v", "n")} if at else None)
                        case[kind] = summ
                    # NBBO: the probe is the run-level fact; record it per case for the disposition
                    await conn.execute(
                        "INSERT INTO historical_evidence (requested_at, provider, kind, symbol, signal_id, message_id, window_start, window_end, "
                        "status, reason, record_count, http_status, request, payload) VALUES (now(),'alpaca','quotes',$1,$2,$3,$4,$5,$6,$7,0,$8,$9,'[]'::jsonb)",
                        sym, str(r["signal_id"]), str(r["message_id"]), posted - dt.timedelta(minutes=5), posted + dt.timedelta(minutes=60),
                        probe["status"], f"NBBO not retrievable: {probe.get('reason')}", probe.get("http"), f"{DATA}/quotes")
                    case["nbbo"] = {"status": probe["status"], "reason": probe.get("reason")}
                    case["disposition"] = ("trade prints and minute bars retrieved with provenance; contemporaneous bid/ask/sizes UNAVAILABLE "
                                           "under the entitlement — no executable fill, spread or slippage can be established; "
                                           "no missed-profit figure is derived") if case.get("trades", {}).get("count") else \
                        ("no contemporaneous option evidence retrievable (prints/bars empty or unavailable) and no NBBO — "
                         "case closed as insufficient historical evidence")
                else:
                    # shares: descriptive underlying path from the local exchange bars
                    bars = await conn.fetch("SELECT ts, open, high, low, close, volume FROM bars WHERE symbol=$1 AND tf='1m' AND source='exchange' "
                                            "AND ts >= $2 AND ts < $3 ORDER BY ts", r["ticker"], int(start.timestamp() * 1000), int(end.timestamp() * 1000))
                    pm = int(posted.replace(second=0, microsecond=0).timestamp() * 1000)
                    def _close_at(ms):
                        b = next((x for x in bars if x["ts"] == ms), None)
                        return float(b["close"]) if b else None
                    case["underlying"] = {"bars": len(bars), "closeAtPostMinute": _close_at(pm),
                                          "closePlus15": _close_at(pm + 15 * 60_000), "closePlus60": _close_at(pm + 60 * 60_000),
                                          "sessionClose": (float(bars[-1]["close"]) if bars else None)}
                    case["disposition"] = ("descriptive underlying path only (local exchange bars); the stated risk level names no "
                                           "indicator/trigger/fill policy, so no strategy P&L is derived")
                report["cases"].append(case)
    finally:
        await conn.close()
    if out is not None:
        out.mkdir(parents=True, exist_ok=True)
        (out / "evidence.json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
        (out / "disposition.md").write_text(to_markdown(report), encoding="utf-8")
    return report


def to_markdown(rep: dict) -> str:
    L = [f"# Late-message historical evidence — retrieval record {rep['requestedAt'][:19]}Z", "",
         f"Provider: **{rep['provider']}** ({rep['entitlement']}); keys present: {rep['keysPresent']}. Window {rep['window'][0]} → {rep['window'][1]}, "
         f"delivery cutoff {rep['cutoff']}.", "",
         f"**NBBO probe:** {rep.get('nbboProbe', {}).get('status')} — {rep.get('nbboProbe', {}).get('reason')}. Contemporaneous bid/ask/sizes are "
         "therefore recorded as UNAVAILABLE for every option case; prints and bars are not executable quotes and no fill, spread or "
         "missed-profit figure is derived.", "",
         "| Case | Source | Posted ET | Instrument | Stated | Prints (+5 min) | First print after post | Bar at post minute | NBBO | Disposition |",
         "|---|---|---|---|---:|---|---|---|---|---|"]
    for c in rep["cases"]:
        if c.get("symbol"):
            tr = c.get("trades") or {}; p5 = tr.get("prints5min") or {}; fp = tr.get("firstPrintAfterPost") or {}
            bar = (c.get("bars") or {}).get("barAtPostMinute") or {}
            L.append(f"| `{c['signalId'][:8]}` | {c['source']} | {c['postedET']} | `{c['symbol']}` ({c['action']}) | {c.get('statedPremium') or '—'} | "
                     f"{('%d prints %.2f–%.2f vwap %s' % (p5['n'], p5['low'], p5['high'], p5.get('vwap'))) if p5 else ('none' if tr.get('status') == 'ok' else tr.get('status', '—'))} | "
                     f"{('%s @ %s ×%s' % (str(fp.get('t'))[11:19], fp.get('p'), fp.get('s'))) if fp else '—'} | "
                     f"{('o %s h %s l %s c %s v %s' % (bar.get('o'), bar.get('h'), bar.get('l'), bar.get('c'), bar.get('v'))) if bar else ((c.get('bars') or {}).get('status', '—'))} | "
                     f"{(c.get('nbbo') or {}).get('status')} | {c['disposition']} |")
        else:
            u = c.get("underlying") or {}
            L.append(f"| `{c['signalId'][:8]}` | {c['source']} | {c['postedET']} | {c['ticker']} shares ({c['action']}) | entry {c.get('statedEntry') or '—'} | — | — | "
                     f"close@post {u.get('closeAtPostMinute')}, +15m {u.get('closePlus15')}, +60m {u.get('closePlus60')}, EOD {u.get('sessionClose')} ({u.get('bars')} bars) | n/a | {c['disposition']} |")
    L += ["", "Every retrieval (status, HTTP code, window, record count, first/last timestamp, request URL without credentials, raw records) is "
          "persisted in the runtime table `historical_evidence` keyed by signal and message id.", ""]
    return "\n".join(L)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--start", default="2026-09-14T13:30:00Z")
    ap.add_argument("--end", default="2026-09-14T20:00:00Z")
    ap.add_argument("--cutoff", default="2026-09-15T01:56:55.589979Z")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    iso = lambda s: dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    rep = asyncio.run(run(db=a.db, start=iso(a.start), end=iso(a.end), cutoff=iso(a.cutoff), out=(Path(a.out) if a.out else None)))
    print(f"cases {len(rep['cases'])}; NBBO probe {rep.get('nbboProbe')}")
    for c in rep["cases"]:
        print(" ", c["signalId"][:8], c.get("symbol") or f"{c['ticker']} shares", "trades", (c.get("trades") or {}).get("count"),
              "bars", (c.get("bars") or {}).get("count"), "|", c["disposition"][:70])


if __name__ == "__main__":
    main()
