"""Tips v0.9 V7.3 (2026-10-05): the Tips block of the daily desk report (`zargar/desk.py::morning_report`).

Per bound Tips book: capital utilisation (open cost basis / equity), open risk to the stops vs the
`max_open_risk_pct` cap, the horizon mix of open positions (read defensively: `config.horizon`,
`config.extras.horizon`, a `horizon:<class>` tag - positions without one count as `unlabelled`), and on recently
closed positions the share of the MFE kept and the noise stop-outs (stopped out, then the underlying traded at or
beyond +1R from the entry in a later session - judged on daily bars, unknown when no bars). Read-only; never raises.
"""
from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import logging
import time

log = logging.getLogger(__name__)

METRICS_VERSION = "tips-desk-v1"


def horizon_of(row_config: dict | None, tags: list | None) -> str | None:
    cfg = row_config or {}
    for v in (cfg.get("horizon"), (cfg.get("extras") or {}).get("horizon"), (cfg.get("policy") or {}).get("horizon")):
        if isinstance(v, dict):
            v = v.get("class") or v.get("horizon")
        if v:
            return str(v)
    for t in tags or []:
        if str(t).startswith("horizon:"):
            return str(t).split(":", 1)[1] or None
    return None


def mfe_kept(*, realized_r: float | None, peak_r: float | None) -> float | None:
    """Realized R / peak favourable R (None when the trade never went in favour)."""
    if realized_r is None or peak_r is None or peak_r <= 0:
        return None
    return round(realized_r / peak_r, 4)


def is_stop_exit(state: dict | None) -> bool:
    st = state or {}
    reason = str(st.get("closeReason") or "").lower()
    if "stop" in reason:
        return True
    ex = st.get("exits") or []
    return bool(ex) and "stop" in str((ex[-1] or {}).get("kind") or "").lower()


def noise_stop(*, direction: str, entry: float, risk: float, highs_after: list[float], lows_after: list[float]) -> bool | None:
    """True when the underlying reached +1R from the entry AFTER the stop-out (None = no bars to judge)."""
    if not risk or risk <= 0:
        return None
    if direction == "short":
        return (min(lows_after) <= entry - risk) if lows_after else None
    return (max(highs_after) >= entry + risk) if highs_after else None


async def tips_daily(eng, *, lookback_hours: float = 24.0, noise_days: int = 14) -> dict:
    from sqlalchemy import select

    from ...models import Execution, ManagedPositionRow
    from . import books as _books
    from . import sizing as _sz
    s = eng.settings
    out: dict = {"version": METRICS_VERSION, "books": []}
    sims = [p for p in eng.positions.portfolios() if p.get("kind") == "sim" and not p.get("book")
            and not p.get("archived")]
    bindings = [b for b in _books.resolve_books(s, eng.positions.portfolio,
                                                fallback_pid=(sims[0]["id"] if sims else None)) if b.enabled]
    now_ms = int(time.time() * 1000)
    for b in bindings:
        pid = b.portfolioId
        pf = eng.positions.portfolio(pid) or {}
        async with eng.sf() as session:
            rows = (await session.execute(select(ManagedPositionRow).where(
                ManagedPositionRow.technique == "tip", ManagedPositionRow.portfolio_id == pid))).scalars().all()
        open_rows = [r for r in rows if r.status in ("open", "attention", "opening", "closing")]
        equity = None
        with contextlib.suppress(Exception):
            equity = float(await eng.positions.equity(pid) or 0) or None
        cost = sum(abs(float(leg.get("avgFill") or 0) * float(leg.get("qty") or 0) * float(leg.get("multiplier") or 1))
                   for r in open_rows for leg in (r.legs or []))
        open_risk = round(sum(_sz.position_open_risk(r.legs, r.config, r.state) for r in open_rows), 2)
        cap_pct = float(_books.knob(b, "maxOpenRiskPct", s, 5.0) or 0)
        mix: dict[str, int] = {}
        for r in open_rows:
            h = horizon_of(r.config, r.tags) or "unlabelled"
            mix[h] = mix.get(h, 0) + 1
        # ---- recently closed: MFE kept + noise stop-outs
        recent = [r for r in rows if r.status == "closed"
                  and int((r.state or {}).get("closedMs") or 0) >= now_ms - int(max(lookback_hours, noise_days * 24) * 3600 * 1000)]
        oids = {str(leg.get("entryOrderId")) for r in recent for leg in (r.legs or []) if leg.get("entryOrderId")}
        oids |= {str(x.get("orderId")) for r in recent for x in ((r.state or {}).get("exits") or []) if x.get("orderId")}
        by_order: dict[str, list] = {}
        if oids:
            async with eng.sf() as session:
                for e in (await session.execute(select(Execution).where(Execution.order_id.in_(list(oids))))).scalars().all():
                    by_order.setdefault(e.order_id, []).append(e)
        kept, closed_rows, noise, stops, noise_unknown = [], [], 0, 0, 0
        daily_cache: dict[str, list] = {}
        for r in recent:
            st, cfg = r.state or {}, r.config or {}
            entry_ids = [str(leg.get("entryOrderId")) for leg in (r.legs or []) if leg.get("entryOrderId")]
            exit_ids = [str(x.get("orderId")) for x in (st.get("exits") or []) if x.get("orderId")]
            eq = sum(float(e.qty or 0) for o in entry_ids for e in by_order.get(o, []))
            fees = sum(float(e.commission or 0) for o in {*entry_ids, *exit_ids} for e in by_order.get(o, []))
            risk_total = _sz._initial_risk(r, eq)
            net = float(st.get("realizedPnl") or 0) - fees
            rr = (net / risk_total) if risk_total else None
            per_unit_risk = float(cfg.get("risk") or 0)
            peak = float((st.get("policyState") or {}).get("peakFavorable") or 0)
            peak_r = (peak / per_unit_risk) if per_unit_risk > 0 else None
            in_window = int(st.get("closedMs") or 0) >= now_ms - int(lookback_hours * 3600 * 1000)
            if in_window:
                k = mfe_kept(realized_r=rr, peak_r=peak_r)
                closed_rows.append({"positionId": r.id, "symbol": r.symbol, "r": (round(rr, 3) if rr is not None else None),
                                    "peakR": (round(peak_r, 3) if peak_r is not None else None), "mfeKept": k,
                                    "horizon": horizon_of(cfg, r.tags), "reason": st.get("closeReason")})
                if k is not None:
                    kept.append(k)
            if is_stop_exit(st) and per_unit_risk > 0 and cfg.get("entry"):
                stops += 1
                und = str(r.symbol or "").upper()
                with contextlib.suppress(Exception):
                    from ...options import occ as _occ
                    o = _occ.parse(und)
                    und = o.underlying if o else und
                bars = daily_cache.get(und)
                if bars is None:
                    bars = []
                    with contextlib.suppress(Exception):
                        from . import entry_context as _ec
                        fx = _ec._fetchers(eng)
                        if fx is not None:
                            bars = await asyncio.wait_for(fx["daily"](und, noise_days + 6), 5.0)
                    daily_cache[und] = bars
                # the sessions AFTER the stop-out's session (a daily bar is stamped at its open; the exit day's own
                # high may predate the stop, so it is not counted)
                after = [x for x in bars if int(x.ts) > int(st.get("closedMs") or 0)]
                from ...options import occ as _occ2
                _o = _occ2.parse(str(((r.legs or [{}])[0]).get("symbol") or ""))
                direction = "short" if (_o is not None and _o.option_type == "put") else "long"
                verdict = noise_stop(direction=direction, entry=float(cfg["entry"]), risk=per_unit_risk,
                                     highs_after=[float(x.high) for x in after], lows_after=[float(x.low) for x in after])
                if verdict is None:
                    noise_unknown += 1
                elif verdict:
                    noise += 1
        out["books"].append({
            "portfolioId": pid, "name": pf.get("name"), "role": b.role, "kind": pf.get("kind"),
            "equity": (round(equity, 2) if equity else None), "openPositions": len(open_rows),
            "openCost": round(cost, 2), "utilisationPct": (round(cost / equity * 100.0, 1) if equity else None),
            "openRisk": open_risk, "openRiskPct": (round(open_risk / equity * 100.0, 2) if equity else None),
            "openRiskCapPct": cap_pct, "horizonMix": mix,
            "closed": closed_rows, "mfeKeptMean": (round(sum(kept) / len(kept), 3) if kept else None),
            "stopOuts": stops, "noiseStopOuts": noise, "noiseUnknown": noise_unknown,
            "noiseWindowDays": noise_days,
        })
    out["asOf"] = dt.datetime.now(dt.timezone.utc).isoformat()
    return out


def summary_line(m: dict | None) -> str:
    """One line for the morning push ('' when nothing to say)."""
    if not m or not m.get("books"):
        return ""
    bits = []
    for b in m["books"]:
        u = b.get("utilisationPct")
        r = b.get("openRiskPct")
        bits.append(f"{b.get('name') or b['portfolioId'][:6]}: {b['openPositions']} open"
                    + (f", {u:g}% deployed" if u is not None else "")
                    + (f", risk {r:g}%/{b['openRiskCapPct']:g}%" if r is not None else "")
                    + (f", MFE kept {round(b['mfeKeptMean'] * 100)}%" if b.get("mfeKeptMean") is not None else "")
                    + (f", {b['noiseStopOuts']}/{b['stopOuts']} noise stops" if b.get("stopOuts") else ""))
    return "Tips: " + "; ".join(bits)
