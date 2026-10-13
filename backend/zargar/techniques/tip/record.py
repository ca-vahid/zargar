"""The desk's MEASURED RECORD, handed to the Tips analyst on every run (2026-10-12).

Why: the analyst's verdict carried no information - priced on the contracts' own trades, its takes did no better
than its skips, and the 600 free-text source notes it reads are stories, not rates. This module replaces opinion
with arithmetic: once a night (`tip_measured_record`) the two order-free replays (`tools/tip_option_replay`,
`tools/tip_source_replay`) re-score the whole archive in a SEPARATE process, the compact result is journaled
(`TipMeasuredRecord`, append-only) and `header_block` renders a few lines of it into the analyst's header: the
all-source base rate, this source's own line, the analyst's take-vs-skip record, and the cost arithmetic.

Nothing here gates an order. `techniques.tip.measured_record` = off | supply. The lines are counts and means over
fixed rules - no threshold in them was tuned on the sample, so there is nothing to overfit; whether supplying them
makes the takes better is read off `sinceSupply` (the same take-vs-skip split, tips from the supply date on).
"""
from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import json
import logging
import subprocess
import sys
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)

EVENT = "TipMeasuredRecord"
RULES = ("scalp", "bracket", "hold")
RULE_LABEL = {"scalp": "scalp (stop -30% / target +30%, flat at the day's close)",
              "bracket": "bracket (stop -50% / target +100%)", "hold": "hold to the tip's horizon, no stop"}
_CACHE_ATTR = "_tip_measured_record"


def mode(settings) -> str:
    return str(settings.get("techniques.tip.measured_record", "supply") or "supply").lower()


def _slim(g: dict | None, keys) -> dict | None:
    if not g:
        return None
    return {**{k: g.get(k) for k in ("tips", "scored", "armedUnfilled") if k in g},
            **{k: g[k] for k in keys if g.get(k) is not None}}


def verdict_split(rows: list[dict], since_day: str | None) -> dict:
    """take / skip counts and plain means per exit rule over the priced tips from `since_day` on (no interval:
    this is the running check of the supplied record, read as a trend until it holds 20 tips a side)."""
    out: dict = {}
    for r in rows:
        if not r.get("ok") or (since_day and str(r.get("day")) < since_day):
            continue
        g = out.setdefault(str(r.get("verdict") or "none"), {v: [] for v in RULES})
        for v in RULES:
            if (r.get(v) or {}).get("resolved"):
                g[v].append(float(r[v]["netPct"]))
    return {k: {v: {"n": len(xs), "meanPct": (round(sum(xs) / len(xs), 2) if xs else None),
                    "hitRate": (round(sum(1 for x in xs if x > 0) / len(xs), 3) if xs else None)}
                for v, xs in g.items()} for k, g in out.items()}


def compact(option_rep: dict, source_rep: dict | None, *, as_of: str, supply_since: str | None) -> dict:
    """The journaled snapshot: the replays' tables without their per-tip rows."""
    return {"asOf": as_of, "since": option_rep.get("since"), "optCost": option_rep.get("optCost"),
            "minN": option_rep.get("minN"), "optionVersion": option_rep.get("version"),
            "sourceVersion": (source_rep or {}).get("version"),
            "tips": option_rep.get("tips"), "scored": option_rep.get("scored"),
            "options": {"byVerdict": {k: _slim(g, RULES) for k, g in (option_rep.get("byAnalystVerdict") or {}).items()},
                        "bySource": {k: _slim(g, RULES) for k, g in (option_rep.get("bySource") or {}).items()}},
            "underlying": {"costPct": (source_rep or {}).get("costPct"),
                           "bySource": {k: _slim(g, ("immediate", "armed"))
                                        for k, g in ((source_rep or {}).get("bySource") or {}).items()}},
            "supplySince": supply_since,
            "sinceSupply": verdict_split(option_rep.get("rows") or [], supply_since) if supply_since else {}}


def _rule_bits(g: dict | None) -> str:
    bits = []
    for v in RULES:
        s = (g or {}).get(v) or {}
        if s.get("n"):
            bits.append(f"{v} {s['hitRate'] * 100:.0f}% winners, mean {s['meanPct']:+.1f}% (n={s['n']})")
    return "; ".join(bits)


def _worst_verdict(g: dict | None) -> str:
    vs = [((g or {}).get(v) or {}).get("verdict") for v in RULES]
    if vs and all(v == "negative" for v in vs):
        return "NEGATIVE under every rule"
    if "promising" in vs:
        return "promising under " + ", ".join(v for v in RULES if ((g or {}).get(v) or {}).get("verdict") == "promising")
    if all(v in (None, "not enough") for v in vs):
        return "too few priced tips for a verdict"
    if len(set(vs)) == 1:
        return str(vs[0])
    return "mixed (" + ", ".join(f"{v}: {((g or {}).get(v) or {}).get('verdict')}" for v in RULES) + ")"


def block(snap: dict | None, source: str | None) -> str:
    """The header lines. Empty when there is no snapshot - the header is then exactly what it was."""
    if not snap or not (snap.get("options") or {}).get("byVerdict", {}).get("ALL"):
        return ""
    opt = snap["options"]
    allg = opt["byVerdict"]["ALL"]
    cost = float(snap.get("optCost") or 0.0)
    ls = [f"MEASURED RECORD (the app's own arithmetic as of {str(snap.get('asOf'))[:10]}: {snap.get('scored')} archived "
          f"option tips since {snap.get('since')}, each bought on the contract's first traded minute AFTER the alert and "
          f"run through three fixed exit rules, in % of the premium paid after ${cost:.2f} a share of costs. Real prints; "
          "no model judged it. It outranks the notes below, the source's own claims and your priors):",
          f"- every source, option tips: {_rule_bits(allg)} -> {_worst_verdict(allg)}"]
    src = opt["bySource"].get(str(source)) if source else None
    if src and any(((src.get(v) or {}).get("n") or 0) >= int(snap.get("minN") or 20) for v in RULES):
        ls.append(f"- THIS source's option tips: {_rule_bits(src)} -> {_worst_verdict(src)}")
    else:
        ls.append(f"- THIS source's option tips: fewer than {int(snap.get('minN') or 20)} priced - it has no record of "
                  "its own; the every-source line is its base rate")
    und = ((snap.get("underlying") or {}).get("bySource") or {}).get(str(source)) if source else None
    im = (und or {}).get("immediate") or {}
    if im.get("n"):
        ci = im.get("ci90")
        ls.append(f"- THIS source as a direction call on the underlying (shares, bought at tip time): right "
                  f"{(im.get('hitRate') or 0) * 100:.0f}% of {im['n']}, mean {im.get('meanR'):+.2f}% versus the market "
                  f"after costs" + (f", 90% interval {ci[0]:+.2f}% to {ci[1]:+.2f}%" if ci else "")
                  + f" -> {im.get('verdict')}")
    take, skip = opt["byVerdict"].get("take"), opt["byVerdict"].get("skip")
    if take and skip:
        better = [v for v in RULES if ((take.get(v) or {}).get("meanPct") is not None
                                       and (skip.get(v) or {}).get("meanPct") is not None
                                       and take[v]["meanPct"] > skip[v]["meanPct"])]
        ls.append(f"- YOUR OWN verdicts on these tips: take -> {_rule_bits(take)}. skip -> {_rule_bits(skip)}. "
                  f"Your takes beat your skips under {len(better)} of {len(RULES)} rules"
                  + (" - so far your take carries no information." if len(better) <= 1 else "."))
    if cost > 0:
        ls.append(f"- cost: about ${cost:.2f} a share for the round trip - a premium under ${cost * 10:.2f} gives up 10% "
                  "or more to costs before the idea is tested.")
    if all(((allg.get(v) or {}).get("meanPct") or 0) < 0 for v in RULES):
        ls.append('What it means here: the base rate of a take is a LOSS. Answer "take" only when you can name a '
                  "specific, checkable fact about THIS tip that the losing record does not already contain (never "
                  '"the setup looks good", never the source\'s confidence) and open your rationale with it as '
                  '"EDGE: ...". Without one, "skip" or "watch" is the correct trade - and a record that favours the '
                  "underlying over the option is a reason to express a take in shares.")
    return "\n".join(ls) + "\n"


async def latest(eng) -> dict | None:
    """The snapshot in force: cached on the engine, hydrated once from the journal."""
    cached = getattr(eng, _CACHE_ATTR, None)
    if cached is not None:
        return cached or None
    from sqlalchemy import select

    from ...models import Event
    snap = None
    with contextlib.suppress(Exception):
        async with eng.sf() as session:
            snap = (await session.execute(select(Event.payload).where(Event.type == EVENT)
                                          .order_by(Event.id.desc()).limit(1))).scalars().first()
    setattr(eng, _CACHE_ATTR, snap or {})
    return snap or None


async def header_block(eng, source: str | None) -> str:
    """The analyst header's block for this source ('' when off or nothing is measured yet). Never raises."""
    try:
        if mode(eng.settings) != "supply":
            return ""
        return block(await latest(eng), source)
    except Exception:                                      # noqa: BLE001 - the header never fails on this
        log.debug("measured record block failed", exc_info=True)
        return ""


def _run_tool(module: str, out: Path, *, since: str, database_url: str, extra: list[str], timeout_s: int) -> dict:
    """One replay in its own process (its bootstrap is CPU work and its feeds are its own): never on the engine's loop."""
    import os
    backend = Path(__file__).resolve().parents[3]
    env = {**os.environ, "ZARGAR_DATABASE_URL": database_url}
    subprocess.run([sys.executable, "-m", module, "--since", since, "--json", str(out), *extra], cwd=str(backend),
                   env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout_s, check=True)
    with open(out, encoding="utf-8") as f:
        return json.load(f)


async def refresh(eng) -> dict | None:
    """The nightly job: re-score the archive, journal the compact snapshot, swap the cache. Returns the snapshot."""
    s = eng.settings
    if mode(s) == "off" or not getattr(eng.config, "alpaca_key_id", ""):      # no option prints, no record
        return None
    since = str(s.get("techniques.tip.measured_record_since", "2026-08-28") or "2026-08-28")
    cost = float(s.get("techniques.tip.measured_record_option_cost", 0.08) or 0.08)
    timeout_s = int(s.get("techniques.tip.measured_record_timeout_seconds", 1200) or 1200)
    url = str(eng.config.database_url)
    try:
        with tempfile.TemporaryDirectory(prefix="tip-record-") as tmp:
            opt = await asyncio.to_thread(_run_tool, "zargar.tools.tip_option_replay", Path(tmp) / "opt.json", since=since,
                                          database_url=url, extra=["--opt-cost", str(cost)], timeout_s=timeout_s)
            src = None
            with contextlib.suppress(Exception):           # the underlying line is optional; the option table is not
                src = await asyncio.to_thread(_run_tool, "zargar.tools.tip_source_replay", Path(tmp) / "src.json",
                                              since=since, database_url=url, extra=[], timeout_s=timeout_s)
    except Exception as exc:                               # noqa: BLE001 - yesterday's snapshot stays in force
        log.warning("measured record refresh failed: %s", exc)
        with contextlib.suppress(Exception):
            await eng.journal.append("TipMeasuredRecordFailed", {"error": str(exc)[:200]}, aggregate_type="tip",
                                     aggregate_id="measured-record")
        return None
    snap = compact(opt, src, as_of=dt.datetime.now(dt.timezone.utc).isoformat(),
                   supply_since=(str(s.get("techniques.tip.measured_record_supply_since", "") or "") or None))
    await eng.journal.append(EVENT, snap, aggregate_type="tip", aggregate_id="measured-record")
    setattr(eng, _CACHE_ATTR, snap)
    return snap
