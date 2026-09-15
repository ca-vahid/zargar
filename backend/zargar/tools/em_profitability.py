"""EM profitability cohorts - ORDER-FREE per-session report (reviewers' P-01..P-03, frozen 2026-09-15).

Nothing here arms, sizes, trades or changes a setting. It reads the journal, the plans, the executions and the
stored bars for ONE session and writes a baseline-versus-candidate report. Unknowns stay unknown.

Frozen definitions (`profitability-cohorts-v1`; change = new version, never a silent edit):

P-01 setup cohort `long_bounce_next_resistance`: an EM trigger of kind `bounce`, direction `long`, whose SAVED first
    target has basis `next_resistance`. It is reported BESIDE the full baseline (every EM fill of the session); it
    never switches another family off. Strata: entry confirmation (`observed_reclaim` = the firing bar CLOSED on the
    trade's side of the level, else `anticipated`), room at the ACTUAL entry (TP1 distance / actual risk: <1R, 1-3R,
    >=3R), quantity, source alignment (the symbol+direction is in the day's source ledger).
P-02 small-position exit `small-position-exit-v1` (SPX-1): eligible = option position, ORIGINAL filled quantity <= 2,
    first PRODUCTION sale >= 2.0R away (planned underlying geometry; for <3 contracts the first sale is the
    single-contract-exit rung). Alternative on IDENTICAL entry, contract and quantity: 2 contracts -> sell ONE at the
    first fresh, covered, executable bid observed at or after the underlying touches the plan's TP1 and keep the other
    on the production policy; 1 contract -> the whole position at that observation. Evidence = `TechniqueExitShadow`
    records with rung `tp1-candidate` (the disabled observer, when activated). No observation = UNKNOWN - never a
    candle high, never a print. Profit forgone on a big winner is counted: forgone = production's realized on the
    contracts the alternative would have sold minus the alternative's realized on them, when positive.
    Faster execution at UNCHANGED targets is the separate shadow-exit-v1 experiment (production rungs) - not mixed in.
P-03 contract economics: per entry intent (filled OR refused) the friction = (fill or ask - bid at the intent) x qty x
    multiplier + round-trip fees, as a fraction of the paid premium; the first-sale distance; the affordable quantity
    under the unchanged risk budget. `hurdle >= 8%` is a RANKING MARKER declared here, not a gate. An attainable
    payoff in premium terms needs a contract delta; the stored snapshot's `delta` is 0.0 (unknown) -> reported unknown.

    python -m zargar.tools.em_profitability report --date 2026-09-15 [--cutoff 16:00]
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
from collections import defaultdict
from zoneinfo import ZoneInfo

VERSION = "profitability-cohorts-v1"
COHORT_P01 = "long_bounce_next_resistance"
P02_POLICY = "small-position-exit-v1"
P02_MAX_QTY = 2
P02_MIN_FIRST_SALE_R = 2.0
P03_HURDLE_MARK = 0.08                      # ranking marker (share of paid premium), never a gate
ROOM_BINS = (("<1R", 0.0, 1.0), ("1-3R", 1.0, 3.0), (">=3R", 3.0, float("inf")))
NY = ZoneInfo("America/New_York")
EM_BOOK = "045d8c35b3f149628ea001ae90a58edb"
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
OUT_DIR = os.path.join(ROOT, "docs", "techniques", "enhanced-market", "research", "profitability")
LEDGER = os.path.join(ROOT, "docs", "techniques", "enhanced-market", "research", "source-candidates.json")


# ----------------------------------------------------------------------------------------------- pure definitions
def cohort_of(kind: str | None, direction: str | None, first_target_basis: str | None) -> str | None:
    """P-01 membership: long bounce with a saved next_resistance first target."""
    if kind == "bounce" and direction == "long" and first_target_basis == "next_resistance":
        return COHORT_P01
    return None


def room_r(actual_entry: float | None, stop: float | None, tp1: float | None, direction: str) -> float | None:
    """Room left at the ACTUAL entry: signed TP1 distance over the actual entry-to-stop distance."""
    if actual_entry is None or stop is None or tp1 is None:
        return None
    risk = abs(float(actual_entry) - float(stop))
    if risk <= 0:
        return None
    move = (float(tp1) - float(actual_entry)) if direction == "long" else (float(actual_entry) - float(tp1))
    return round(move / risk, 3)


def room_bin(r: float | None) -> str:
    if r is None:
        return "unknown"
    if r <= 0:
        return "behind"
    for label, lo, hi in ROOM_BINS:
        if lo <= r < hi:
            return label
    return "unknown"


def confirmation_class(bar_close: float | None, level: float | None, direction: str) -> str:
    """`observed_reclaim` when the firing bar CLOSED on the trade's side of the level; else `anticipated`."""
    if bar_close is None or level is None:
        return "unknown"
    ok = float(bar_close) > float(level) if direction == "long" else float(bar_close) < float(level)
    return "observed_reclaim" if ok else "anticipated"


def friction(fill_or_ask: float | None, bid: float | None, qty: float | None, multiplier: float, fee_side: float) -> dict:
    """P-03 friction: price concession to the contemporaneous bid plus round-trip fees, as a share of paid premium."""
    if fill_or_ask is None or qty is None or float(qty) <= 0:
        return {"concession": None, "fees": None, "total": None, "pctOfPremium": None, "known": False}
    q = float(qty); m = float(multiplier)
    concession = (round(max(0.0, float(fill_or_ask) - float(bid)) * q * m, 2)) if bid is not None else None
    fees = 2 * fee_side * q if m > 1 else 0.0                # share fees are 0 on this book's schedule
    premium = float(fill_or_ask) * q * m
    total = (round(concession + fees, 2)) if concession is not None else None
    return {"concession": concession, "fees": fees, "total": total,
            "pctOfPremium": (round(total / premium, 4) if total is not None and premium > 0 else None),
            "known": concession is not None}


def payoff_to_tp1(delta: float | None, entry: float | None, tp1: float | None, qty: float | None, multiplier: float = 100.0) -> float | None:
    """P-03 attainable payoff proxy to the plan's TP1 in premium dollars: delta x underlying move x qty x multiplier.
    None when the contract snapshot carries no positive delta (the stored 0.0 means unknown, never zero payoff)."""
    if not delta or float(delta) <= 0 or entry is None or tp1 is None or not qty:
        return None
    return round(abs(float(delta)) * abs(float(tp1) - float(entry)) * float(qty) * float(multiplier), 2)


def affordable_qty(risk_budget: float, premium: float, premium_stop_pct: float, multiplier: float = 100.0) -> int:
    """Contracts the UNCHANGED risk budget affords at the premium stop (FIX-03: the budget is a bound)."""
    per = float(premium) * float(multiplier) * float(premium_stop_pct) / 100.0
    return int(float(risk_budget) // per) if per > 0 else 0


def p02_eligible(instrument: str | None, filled_qty: float | None, first_sale_r: float | None) -> bool:
    return (instrument == "options" and filled_qty is not None and 0 < float(filled_qty) <= P02_MAX_QTY
            and first_sale_r is not None and float(first_sale_r) >= P02_MIN_FIRST_SALE_R)


def p02_compare(trade: dict, observations: list[dict], fee_side: float) -> dict:
    """SPX-1 on identical entry/contract/quantity. `trade`: filledQty, avgFill, multiplier, productionRealized
    (closed net $ of the whole position or None while open), productionPerContract (list of per-contract realized $
    in exit order, or None). `observations`: TechniqueExitShadow payloads for this trade (rung == 'tp1-candidate',
    disposition == 'covered' with a `bid`). Unknown without a covered observation."""
    q = int(float(trade.get("filledQty") or 0)); fill = trade.get("avgFill"); m = float(trade.get("multiplier") or 100)
    obs = [o for o in observations if o.get("rung") == "tp1-candidate" and o.get("disposition") == "covered" and o.get("bid")]
    out = {"policy": P02_POLICY, "quantity": q, "soldByAlternative": (1 if q == 2 else q), "outcome": "unknown", "why": None,
           "alternativeRealized": None, "productionRealized": trade.get("productionRealized"), "delta": None, "forgoneOnWinner": None}
    if not obs:
        out["why"] = "no covered executable-bid observation at the TP1 touch (observer records absent)"
        return out
    if fill is None or q <= 0:
        out["why"] = "entry fill unknown"; return out
    o = sorted(obs, key=lambda x: x.get("observedTs") or 0)[0]
    k = out["soldByAlternative"]
    alt_sold = k * (float(o["bid"]) - float(fill)) * m - 2 * fee_side * k      # entry-side + exit-side fees for k
    if trade.get("productionRealized") is None:
        out["outcome"] = "partial"; out["why"] = "production position still open - the retained runner is unresolved"
        out["alternativeRealized"] = round(alt_sold, 2); return out
    per = trade.get("productionPerContract") or []
    if len(per) != q:
        out["why"] = "production per-contract realized not reconstructible"; return out
    prod_on_sold = sum(per[:k])                                           # production's realized on the k first-out contracts
    alt_total = alt_sold + sum(per[k:])
    out.update({"outcome": "compared", "alternativeRealized": round(alt_total, 2), "delta": round(alt_total - float(trade["productionRealized"]), 2),
                "forgoneOnWinner": round(max(0.0, prod_on_sold - alt_sold), 2), "observedAt": o.get("observedTs"), "bid": o.get("bid")})
    return out


# ----------------------------------------------------------------------------------------------- session assembly
def _ms(d: dt.date, hh: int, mm: int) -> int:
    return int(dt.datetime(d.year, d.month, d.day, hh, mm, tzinfo=NY).timestamp() * 1000)


def underlying_proxy(bars: list[dict], fired_ts: int, entry: float, stop: float, tp1: float, direction: str, cutoff_ms: int) -> str:
    """Underlying-only diagnostic for a fired trigger that produced no position: which came first after the firing bar,
    a TP1 touch or a close through the stop, by the cutoff. Not dollars, not an option outcome."""
    long = direction == "long"
    path = [b for b in bars if fired_ts < int(b["ts"]) and int(b["ts"]) + 60000 <= cutoff_ms]
    prev_ts = None
    for b in sorted(path, key=lambda x: x["ts"]):
        if prev_ts is not None and int(b["ts"]) - prev_ts != 60000:
            return "unknown (bar gap)"
        prev_ts = int(b["ts"])
        stopped = b["close"] < stop if long else b["close"] > stop
        hit = b["high"] >= tp1 if long else b["low"] <= tp1
        if hit and stopped:
            return "unknown (same-bar target and stop)"
        if hit:
            return "tp1_first"
        if stopped:
            return "stop_first"
    return "unresolved"


async def build(date: str, cutoff: str = "16:00") -> dict:
    import asyncpg
    from ..config import AppConfig
    session = dt.date.fromisoformat(date)
    hh, mm = (int(x) for x in cutoff.split(":"))
    cutoff_ms = _ms(session, hh, mm); day0 = _ms(session, 9, 30)
    url = AppConfig().database_url.replace("postgresql+asyncpg://", "postgresql://")
    c = await asyncpg.connect(url)
    await c.execute("set transaction read only")
    try:
        armed = await c.fetch("""select a.run_id, a.symbol, a.config, a.state, r.result->'plan' as plan
            from technique_armed a join technique_runs r on r.id = a.run_id
            where a.technique='enhanced_market' and a.plan_for=$1""", date)
        ledger = []
        if os.path.exists(LEDGER):
            d = json.load(open(LEDGER, encoding="utf-8"))
            ledger = [r for r in (d if isinstance(d, list) else d.get("rows", [])) if r.get("date") == date]
        aligned = {(r["symbol"], r.get("direction", "long")) for r in ledger}
        fee_rows = await c.fetch("""select commission, symbol, qty from executions where portfolio_id=$1 and ts >= to_timestamp($2/1000.0) and ts < to_timestamp($3/1000.0)""",
                                 EM_BOOK, day0 - 3600_000, cutoff_ms)
        opt_fees = sorted(float(r["commission"] or 0) / float(r["qty"] or 1) for r in fee_rows if len(r["symbol"]) > 6 and r["qty"])
        fee_side = opt_fees[len(opt_fees) // 2] if opt_fees else 1.04
        trades, refused = [], []
        for a in armed:
            plan = a["plan"] if isinstance(a["plan"], dict) else json.loads(a["plan"] or "{}")
            state = a["state"] if isinstance(a["state"], dict) else json.loads(a["state"] or "{}")
            cfg = a["config"] if isinstance(a["config"], dict) else json.loads(a["config"] or "{}")
            trig = {t["id"]: t for t in (plan or {}).get("triggers", [])}
            ev = await c.fetch("""select ts, type, payload from events where aggregate_id=$1 and ts < to_timestamp($2/1000.0) order by ts""", a["run_id"], cutoff_ms)
            evs = [(e["ts"], e["type"], (e["payload"] if isinstance(e["payload"], dict) else json.loads(e["payload"] or "{}"))) for e in ev]
            bars = [dict(b) for b in await c.fetch("""select ts, open, high, low, close from bars where symbol=$1 and tf='1m' and ts >= $2 and ts < $3 order by ts""",
                                                    a["symbol"], day0, cutoff_ms)]
            for tr in (state.get("trades") or []):
                tid = tr.get("triggerId"); t = trig.get(tid, {})
                fired_ts = tr.get("firedTs")
                if not fired_ts or fired_ts >= cutoff_ms:
                    continue
                first_basis = ((t.get("targets") or [{}])[0]).get("basis") if t.get("targets") else None
                direction = tr.get("direction") or t.get("direction") or "long"
                level = ((t.get("level") or {}).get("price")) if isinstance(t.get("level"), dict) else t.get("levelPrice")
                fire_bar = next((b for b in bars if int(b["ts"]) == int(fired_ts)), None) or next((b for b in bars if int(b["ts"]) == int(fired_ts) - 60000), None)
                tp1 = (tr.get("targets") or [None])[0]
                intent = next((p for _, ty, p in evs if ty == "TechniquePlanOrderIntent" and p.get("trigger") == tid), None)
                td = next((p for _, ty, p in evs if ty == "TechniqueTargetDistance" and p.get("trigger") == tid and p.get("stage") == "fill"), None)
                shadow = [p for _, ty, p in evs if ty == "TechniqueExitShadow" and p.get("trigger") == tid]
                contract = (intent or {}).get("contract") or tr.get("contract") or {}
                row = {"runId": a["run_id"], "symbol": a["symbol"], "trigger": tid, "kind": tr.get("kind") or t.get("kind"), "direction": direction,
                       "cohort": cohort_of(tr.get("kind") or t.get("kind"), direction, first_basis), "firstTargetBasis": first_basis,
                       "firedAt": dt.datetime.fromtimestamp(fired_ts / 1000, NY).strftime("%H:%M:%S"),
                       "confirmation": confirmation_class(fire_bar["close"] if fire_bar else None, level, direction),
                       "sourceAligned": (a["symbol"], direction) in aligned, "status": tr.get("status"), "instrument": tr.get("instrument"),
                       "intendedEntry": tr.get("entry"), "stop": tr.get("stop"), "targets": tr.get("targets"),
                       "contract": {k: contract.get(k) for k in ("symbol", "bid", "ask", "mid", "spreadPct", "delta", "dte")} if contract else None}
                if tr.get("status") in ("open", "closed") and tr.get("filledQty"):
                    q = float(tr["filledQty"]); m = float(tr.get("multiplier") or (100 if tr.get("instrument") == "options" else 1))
                    oids = [tr.get("entryOrderId")] + [x.get("orderId") for x in (tr.get("exits") or []) if x.get("orderId")]
                    ex = await c.fetch("""select order_id, side, qty, price, commission, ts from executions where order_id = any($1::text[]) and ts < to_timestamp($2/1000.0) order by ts""",
                                       [o for o in oids if o], cutoff_ms)
                    buys = [e for e in ex if e["side"] == "BUY"]; sells = [e for e in ex if e["side"] == "SELL"]
                    sold_q = sum(float(e["qty"]) for e in sells); fees = sum(float(e["commission"] or 0) for e in ex)
                    avg_fill = tr.get("avgFill") or (sum(float(e["qty"]) * float(e["price"]) for e in buys) / max(1e-9, sum(float(e["qty"]) for e in buys)) if buys else None)
                    closed = sold_q >= q - 1e-9
                    gross = sum(float(e["qty"]) * (float(e["price"]) - float(avg_fill)) * m for e in sells) if avg_fill is not None else None
                    net = (gross - fees) if (closed and gross is not None) else None
                    per_contract = []
                    if closed and m > 1 and avg_fill is not None:
                        for e in sells:                                       # per-contract realized in exit order (fees split per side)
                            for _ in range(int(round(float(e["qty"])))):
                                per_contract.append((float(e["price"]) - float(avg_fill)) * m - 2 * fee_side)
                    first_sale_r = (td or {}).get("nextRungDistanceR")
                    row.update({"filledQty": q, "avgFill": avg_fill, "multiplier": m, "closed": closed, "netRealized": (round(net, 2) if net is not None else None),
                                "paidPremium": (round(float(avg_fill) * q * m, 2) if avg_fill is not None else None),
                                "entryFees": sum(float(e["commission"] or 0) for e in buys), "fees": fees,
                                "exitKinds": [x.get("kind") for x in (tr.get("exits") or [])],
                                "roomAtActualEntryR": room_r(tr.get("entry"), tr.get("stop"), tp1, direction), "firstSaleDistanceR": first_sale_r,
                                "fullExitRung": (td or {}).get("fullExitRung"),
                                "friction": friction(avg_fill, contract.get("bid"), q, m, fee_side),
                                "p02Eligible": p02_eligible(tr.get("instrument"), q, first_sale_r)})
                    row["roomBin"] = room_bin(row["roomAtActualEntryR"])
                    if row["p02Eligible"]:
                        row["p02"] = p02_compare({"filledQty": q, "avgFill": avg_fill, "multiplier": m, "productionRealized": row["netRealized"],
                                                  "productionPerContract": per_contract or None}, shadow, fee_side)
                    trades.append(row)
                else:
                    result = next((p for _, ty, p in evs if ty == "TechniquePlanOrderResult" and p.get("trigger") == tid), None)
                    skip = next((p for _, ty, p in evs if ty == "TechniquePlanTriggerSkipped" and p.get("trigger") == tid and p.get("event") in ("contract_quality", "size_zero")), None)
                    reason = (result or {}).get("reason") or (skip or {}).get("reason") or tr.get("reason") or "no order result"
                    ask = contract.get("ask"); qty = (intent or {}).get("qty")
                    row.update({"refusal": reason, "intendedQty": qty,
                                "friction": friction(ask, contract.get("bid"), qty, 100.0 if (intent or {}).get("secType") == "OPT" else 1.0, fee_side) if contract else None,
                                "roomAtActualEntryR": room_r(tr.get("entry"), tr.get("stop"), tp1, direction),
                                "underlyingProxy": underlying_proxy(bars, int(fired_ts), float(tr.get("entry") or 0), float(tr.get("stop") or 0), float(tp1), direction, cutoff_ms) if tp1 and tr.get("stop") else "unknown"})
                    row["roomBin"] = room_bin(row["roomAtActualEntryR"])
                    refused.append(row)
        return {"version": VERSION, "date": date, "cutoff": cutoff, "feePerContractSide": fee_side, "trades": trades, "refused": refused,
                "sourceLedgerRows": len(ledger)}
    finally:
        await c.close()


# ----------------------------------------------------------------------------------------------- report rendering
def summarize(data: dict) -> dict:
    trades, refused = data["trades"], data["refused"]

    def block(rows):
        closed = [r for r in rows if r.get("closed")]
        opened = [r for r in rows if not r.get("closed")]
        return {"fills": len(rows), "closed": len(closed), "netRealized": round(sum(r["netRealized"] for r in closed if r["netRealized"] is not None), 2),
                "winners": sum(1 for r in closed if (r["netRealized"] or 0) > 0), "losers": sum(1 for r in closed if (r["netRealized"] or 0) < 0),
                "open": len(opened), "openExposure": round(sum((r.get("paidPremium") or 0) + (r.get("entryFees") or 0) for r in opened), 2),
                "largestWinner": max([r["netRealized"] for r in closed if r["netRealized"] is not None] or [0.0]),
                "feesPaid": round(sum(r.get("fees") or 0 for r in rows), 2)}

    base = block(trades)
    coh = [r for r in trades if r["cohort"] == COHORT_P01]
    removed = [r for r in trades if r["cohort"] != COHORT_P01]
    missed = [r for r in refused if r["cohort"] == COHORT_P01]
    strata = defaultdict(lambda: {"n": 0, "net": 0.0, "open": 0})
    for r in coh:
        for key in (f"confirmation={r['confirmation']}", f"room={r['roomBin']}", f"qty={int(r['filledQty'])}", f"sourceAligned={r['sourceAligned']}"):
            s = strata[key]; s["n"] += 1
            if r.get("closed"): s["net"] += r["netRealized"] or 0
            else: s["open"] += 1
    p02 = [r for r in trades if r.get("p02Eligible")]
    p03 = sorted([r for r in trades + refused if r.get("friction") and r["friction"].get("pctOfPremium") is not None], key=lambda r: -r["friction"]["pctOfPremium"])
    return {"baseline": base, "cohort": block(coh), "removed": [{"symbol": r["symbol"], "trigger": r["trigger"], "kind": r["kind"], "direction": r["direction"],
                                                                  "basis": r["firstTargetBasis"], "net": r.get("netRealized"), "closed": r.get("closed")} for r in removed],
            "missedWinnersCandidates": [{"symbol": r["symbol"], "trigger": r["trigger"], "refusal": r["refusal"][:90], "underlyingProxy": r["underlyingProxy"], "room": r["roomBin"]} for r in missed],
            "strata": {k: {"n": v["n"], "net": round(v["net"], 2), "open": v["open"]} for k, v in sorted(strata.items())},
            "p02": [{"symbol": r["symbol"], "trigger": r["trigger"], "qty": r["filledQty"], "firstSaleDistanceR": r["firstSaleDistanceR"], **r["p02"]} for r in p02],
            "p03": [{"symbol": r["symbol"], "trigger": r["trigger"], "filled": "filledQty" in r, "qty": r.get("filledQty") or r.get("intendedQty"),
                     "hurdlePct": r["friction"]["pctOfPremium"], "hurdle": round(r["friction"]["total"], 2), "firstSaleDistanceR": r.get("firstSaleDistanceR"),
                     "flag": r["friction"]["pctOfPremium"] >= P03_HURDLE_MARK, "delta": (r.get("contract") or {}).get("delta"),
                     "payoffTp1": payoff_to_tp1((r.get("contract") or {}).get("delta"), r.get("intendedEntry"), (r.get("targets") or [None])[0],
                                                r.get("filledQty") or r.get("intendedQty"), r.get("multiplier") or 100.0)} for r in p03],
            "unknown": {"p02WithoutObservation": sum(1 for r in p02 if r["p02"]["outcome"] == "unknown"),
                        "refusedUnresolvedOrGap": sum(1 for r in refused if r["underlyingProxy"].startswith(("unresolved", "unknown"))),
                        "payoffInPremiumTermsUnknown": sum(1 for r in p03 if payoff_to_tp1((r.get("contract") or {}).get("delta"), r.get("intendedEntry"),
                                                                                              (r.get("targets") or [None])[0], r.get("filledQty") or r.get("intendedQty"),
                                                                                              r.get("multiplier") or 100.0) is None)}}


def render(data: dict, s: dict) -> str:
    L = [f"# EM profitability report {data['date']} (cutoff {data['cutoff']} ET, {VERSION})", "",
         "Order-free research. Baseline = every EM fill of the session; candidate P-01 = long bounce with a saved next_resistance first target. Dollars are net of fees from the book's executions; unknowns stay unknown.", "",
         "| Block | Fills | Closed | Net realized | Winners | Losers | Open | Open exposure (premium+entry fees) | Largest winner | Fees |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for name, b in (("Baseline (all EM fills)", s["baseline"]), (f"P-01 `{COHORT_P01}`", s["cohort"])):
        L.append(f"| {name} | {b['fills']} | {b['closed']} | {b['netRealized']:+.2f} | {b['winners']} | {b['losers']} | {b['open']} | {b['openExposure']:.2f} | {b['largestWinner']:+.2f} | {b['feesPaid']:.2f} |")
    L += ["", "**Removed by the candidate (baseline fills outside the cohort):** " + (", ".join(f"{r['symbol']} {r['trigger']} {r['kind']}/{r['direction']}/{r['basis']} net {('%+.2f' % r['net']) if r['net'] is not None else 'open'}" for r in s["removed"]) or "none"), ""]
    L += ["**Cohort-eligible fires that produced no position (missed-winner candidates; underlying-only proxy, not dollars):**"]
    L += [f"- {r['symbol']} {r['trigger']}: {r['refusal']} -> underlying {r['underlyingProxy']}, room {r['room']}" for r in s["missedWinnersCandidates"]] or ["- none"]
    L += ["", "**P-01 strata (cohort fills):**", "| Stratum | n | Net (closed) | Open |", "|---|---:|---:|---:|"]
    L += [f"| {k} | {v['n']} | {v['net']:+.2f} | {v['open']} |" for k, v in s["strata"].items()] or ["| (no cohort fills) | 0 | 0 | 0 |"]
    L += ["", f"**P-02 `{P02_POLICY}` (identical entry/contract/quantity; unknown without a covered TP1 bid observation):**",
          "| Position | Qty | First sale (R) | Outcome | Production net | Alternative net | Delta | Forgone on winner | Why |", "|---|---:|---:|---|---:|---:|---:|---:|---|"]
    L += [f"| {r['symbol']} {r['trigger']} | {int(r['qty'])} | {r['firstSaleDistanceR']} | {r['outcome']} | {r['productionRealized'] if r['productionRealized'] is not None else 'open'} | {r['alternativeRealized'] if r['alternativeRealized'] is not None else '-'} | {r['delta'] if r['delta'] is not None else '-'} | {r['forgoneOnWinner'] if r['forgoneOnWinner'] is not None else '-'} | {r['why'] or ''} |" for r in s["p02"]] or ["| (no eligible small position) | | | | | | | | |"]
    L += ["", f"**P-03 contract friction (concession to the intent bid + round-trip fees, share of paid premium; `flag` = >= {int(P03_HURDLE_MARK*100)}% ranking marker, not a gate):**",
          "| Intent | Filled | Qty | Hurdle $ | Hurdle % | First sale (R) | Flag | Payoff to TP1 (delta proxy) | Hurdle / payoff |", "|---|---|---:|---:|---:|---:|---|---:|---:|"]
    L += [f"| {r['symbol']} {r['trigger']} | {'yes' if r['filled'] else 'no'} | {r['qty']} | {r['hurdle']:.2f} | {r['hurdlePct']*100:.2f}% | {r['firstSaleDistanceR'] if r['firstSaleDistanceR'] is not None else '-'} | {'thin' if r['flag'] else ''} | {r['payoffTp1'] if r['payoffTp1'] is not None else 'unknown (no delta)'} | {(('%.0f%%' % (100*r['hurdle']/r['payoffTp1'])) if r['payoffTp1'] else '-')} |" for r in s["p03"]] or ["| (none) | | | | | | | | |"]
    L += ["", "**Unknowns:** " + json.dumps(s["unknown"]), "",
          f"Fees per contract per side observed: {data['feePerContractSide']:.2f}. Source ledger rows for the day: {data['sourceLedgerRows']}. Refused/skipped EM fires: {len(data['refused'])}.", ""]
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("report"); r.add_argument("--date", required=True); r.add_argument("--cutoff", default="16:00"); r.add_argument("--stdout", action="store_true")
    a = ap.parse_args(argv)
    data = asyncio.run(build(a.date, a.cutoff)); s = summarize(data); md = render(data, s)
    os.makedirs(OUT_DIR, exist_ok=True)
    json.dump({**data, "summary": s, "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat()}, open(os.path.join(OUT_DIR, f"{a.date}.json"), "w", encoding="utf-8"), indent=1, default=str)
    open(os.path.join(OUT_DIR, f"{a.date}.md"), "w", encoding="utf-8", newline="\n").write(md)
    print(md if a.stdout else f"wrote {OUT_DIR}/{a.date}.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
