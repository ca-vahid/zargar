"""W2.1 (2026-10-02): fit-or-reshape before a budget skip - the analyst's `find_alternatives` tool.

The 2026-10-02 review (appendix B, finding 6): when the stated contract did not fit the ~1% risk budget the analyst
said so and stopped - no cheaper strike, no later expiry, no debit spread, the shares alternative in 10 of 44. User
direction: "AI looking for another way to take the trade when the first option is too expensive ... don't add
unnecessary restrictions or blockers."

This module builds the alternatives DETERMINISTICALLY (no model call inside it) from the chain provider and the SAME
feasibility authority the pre-entry gate uses (`risk_evidence.gather` + `geometry.fit_expression`), so every number
the analyst sees is the number the gate will apply:

  1. same expiry, cheaper strikes - the next 1-2 strikes further out of the money, liquid (two-sided, spread within
     the liquidity rule, open interest), limit at the ask inside the risk gate's price collar (the fill band);
  2. later expiry, same strike - the next 1-2 listed expiries;
  3. a debit vertical of the stated contract - long the stated strike, short a further-OTM strike of the same expiry
     (venue-dependent: native multi-leg where the venue supports it, else the leg-sequenced open);
  4. shares of the underlying, sized to the risk budget at the (finalized) structure stop - long ideas only.

A live/paper book with `techniques.tip.live_shares_only` (the IBKR adapter has no option path) is offered the shares
alternative only. Each alternative carries qty, planned risk at the final stop, max loss, break-even, spread %, the
fill band and `preview_payoff` numbers, plus the exact `vehicle` fields a normal take uses - the existing proposal
path trades it. Nothing here substitutes anything: the analyst chooses, or skips with a reason per alternative.
"""
from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import logging
import re as _re_mod

from ...options import occ as occ_mod
from ...technique.options import MAX_SPREAD_PCT, MIN_OPEN_INTEREST
from . import geometry as _geo
from . import payoff as _po
from . import risk_evidence as _re

log = logging.getLogger(__name__)

ALTERNATIVES_VERSION = "alternatives-v1"
FETCH_TIMEOUT_S = 8.0
KIND_ORDER = ("strike", "expiry", "vertical", "shares")


def fill_band(*, bid: float | None, ask: float | None, last: float | None, settings, is_option: bool) -> dict:
    """The BUY limit (the ask) against the risk gate's price collar (`risk.price_collar_pct`; options measured
    from the mid with a floor of a few ticks or the spread, shares from the last) - the 'fill band' an order at
    this limit is admitted inside."""
    collar = float(settings.get("risk.price_collar_pct", 5.0) or 5.0)
    b, a = float(bid or 0.0), float(ask or 0.0)
    if is_option:
        if a <= 0:
            return {"limit": None, "withinCollar": False, "note": "no ask - not priceable"}
        ref = (b + a) / 2 if b > 0 else a
        tol = max(ref * collar / 100.0, 0.05, (a - b) if a > b > 0 else 0.0)
    else:
        ref = float(last or 0.0) or a
        if ref <= 0 or a <= 0:
            return {"limit": None, "withinCollar": False, "note": "no executable share quote"}
        tol = ref * collar / 100.0
    return {"limit": round(a, 2), "reference": round(ref, 4), "tolerance": round(tol, 4),
            "low": round(ref - tol, 4), "high": round(ref + tol, 4), "withinCollar": abs(a - ref) <= tol + 1e-9,
            "basis": ("mid, tolerance max(collar %, $0.05, spread)" if is_option else "last, collar %")}


def liquidity_problem(cell: dict | None) -> str | None:
    """The desk's liquidity rule for a contract the app picks (the tip's own named contract is judged by the analyst):
    a two-sided market, spread <= MAX_SPREAD_PCT of the mid, open interest >= MIN_OPEN_INTEREST."""
    if not cell:
        return "not listed in the chain"
    bid, ask = float(cell.get("bid") or 0), float(cell.get("ask") or 0)
    if bid <= 0 or ask <= 0:
        return f"one-sided market (bid {bid:g} / ask {ask:g})"
    sp = cell.get("spreadPct")
    if sp is not None and float(sp) > MAX_SPREAD_PCT:
        return f"spread {float(sp):.1f}% of mid > {MAX_SPREAD_PCT:g}%"
    if int(cell.get("openInterest") or 0) < MIN_OPEN_INTEREST:
        return f"open interest {int(cell.get('openInterest') or 0)} < {MIN_OPEN_INTEREST}"
    return None


def cap_qty(qty_by_risk: int | None, *, unit_cost: float, allocation: float | None, settings, is_option: bool,
            position_room: float | None = None) -> tuple[int, list[str]]:
    """The size the proposal path will mint: the risk fit, then the purchase allocation (per-tip budget), the per-tip
    premium cap and the contract cap (options) / the position cap room (shares). Returns (qty, binding notes)."""
    notes: list[str] = []
    if qty_by_risk is None:
        return 0, ["no risk estimate"]
    q = int(qty_by_risk)
    if allocation is not None and unit_cost > 0:
        a = int(allocation // unit_cost)
        if a < q:
            q = a
            notes.append(f"purchase allocation ${float(allocation):,.0f} buys {a}")
    if is_option and unit_cost > 0:
        cap = float(settings.get("techniques.tip.max_premium_per_tip", 750.0) or 0)
        if cap > 0:
            c = max(1, int(cap // unit_cost))
            if c < q:
                q = c
                notes.append(f"premium cap ${cap:,.0f} allows {c}")
        cc = int(settings.get("techniques.tip.max_contracts_per_tip", 25) or 0)
        if cc > 0 and cc < q:
            q = cc
            notes.append(f"contract cap {cc}")
    if not is_option and position_room is not None and unit_cost > 0:
        r = int(position_room // unit_cost)
        if r < q:
            q = r
            notes.append(f"position cap room buys {r}")
    return max(0, q), notes


def _plan(args: dict) -> dict:
    targets = [float(t) for t in (args.get("exit_targets") or []) if t]
    fr = [float(x) for x in (args.get("exit_fractions") or [])] or ([1.0] if targets else [])
    out = {"targets": targets, "fractions": fr}
    if args.get("underlying_stop") is not None:
        out["underlyingStop"] = float(args["underlying_stop"])
    if args.get("premium_stop_pct") is not None:
        out["premiumStopPct"] = float(args["premium_stop_pct"])
    return out


def _payoff(*, vehicle: str, qty: int, plan: dict, entry_ref: float, direction: str, delta, multiplier: float,
            unit_loss, fee: float, strike=None, premium=None, option_type=None, expiry=None, hold=None) -> dict:
    tg = list(plan.get("targets") or [])
    gains = _po.unit_gains(vehicle=vehicle, entry_ref=float(entry_ref or 0), targets=tg, direction=direction,
                           delta=delta, multiplier=multiplier)
    dte = None
    if expiry:
        with contextlib.suppress(Exception):
            dte = (dt.date.fromisoformat(str(expiry)) - dt.datetime.now(dt.timezone(dt.timedelta(hours=-4))).date()).days
    pv = _po.payoff_preview(qty=max(1, int(qty or 1)), fractions=list(plan.get("fractions") or ([1.0] if tg else [])),
                            gains=gains, unit_loss=unit_loss, fee_per_unit=fee, vehicle=vehicle, strike=strike,
                            premium=premium, option_type=option_type, dte=dte,
                            hold_sessions=(int(hold) if hold is not None else None), expiry_date=expiry)
    return {k: pv.get(k) for k in ("qty", "ladder", "scenarios", "oneLot", "singleLot", "breakEven", "horizon",
                                   "plannedRisk", "reason")}


class _Builder:
    def __init__(self, eng, args: dict, ctx: dict):
        self.eng, self.args, self.ctx = eng, dict(args or {}), dict(ctx or {})
        self.s = eng.settings
        self.cache: dict = {}
        self.plan = _plan(self.args)
        self.alloc = self.ctx.get("budgetPerTip")
        from .execcost import fees_from_settings
        f = fees_from_settings(self.s)
        self.fee = float(f["feePerContract"]) + float(f["regPerContract"])
        self.entry_hint = (self.ctx.get("tip") or {}).get("entryPrice")
        self.hold = self.args.get("hold_sessions") or (self.ctx.get("tip") or {}).get("horizonSessions")

    async def chain(self, underlying: str, expiry: str) -> dict | None:
        key = ("chain", underlying, expiry)
        if key not in self.cache:
            try:
                self.cache[key] = await asyncio.wait_for(self.eng.options.chain(underlying, expiry), FETCH_TIMEOUT_S)
            except Exception as exc:                    # noqa: BLE001 - an unavailable chain is a labelled gap
                log.info("find_alternatives: chain %s %s unavailable: %s", underlying, expiry, exc)
                self.cache[key] = None
        return self.cache[key]

    @staticmethod
    def cell(chain: dict | None, strike: float, side: str) -> dict | None:
        for r in (chain or {}).get("rows") or []:
            if abs(float(r.get("strike") or 0) - float(strike)) < 1e-6:
                return r.get(side)
        return None

    async def option(self, *, kind: str, label: str, underlying: str, symbol: str, cell: dict | None,
                     direction: str, pid: str | None, limit: float | None = None, check_liquidity: bool = True) -> dict:
        o = occ_mod.parse(symbol)
        side = o.option_type if o else ("put" if direction == "short" else "call")
        out: dict = {"kind": kind, "label": label, "contract": symbol,
                     "display": (occ_mod.display(symbol) if o else symbol),
                     "expiry": (o.expiry.isoformat() if o else None), "strike": (float(o.strike) if o else None)}
        why = liquidity_problem(cell) if check_liquidity else None
        if why:
            return {**out, "available": False, "reason": why}
        ask = float(limit) if limit else float((cell or {}).get("ask") or 0)
        if ask <= 0:
            return {**out, "available": False, "reason": "no ask - not priceable"}
        vehicle = {"multiplier": occ_mod.contract_multiplier(symbol), "optionType": side, "currency": "USD"}
        ev = await _re.gather(self.eng, underlying=underlying, sec_type="OPT", symbol=symbol, vehicle=vehicle,
                              limit=ask, entry_hint=self.entry_hint, pid=pid, cache=self.cache)
        final, fit = _geo.fit_expression(direction=direction, vehicle="option", entry_ref=ev["entryRef"],
                                         exit_plan=self.plan, bars=ev["bars"], settings=self.s, premium=ask,
                                         multiplier=ev["multiplier"], option_type=side, delta=ev["delta"],
                                         budget=ev["budget"])
        mult = float(ev["multiplier"] or 0) or 100.0
        qty, binds = cap_qty(fit["qtyByRisk"], unit_cost=ask * mult, allocation=self.alloc, settings=self.s,
                             is_option=True)
        q = max(qty, 1)
        pay = _payoff(vehicle="option", qty=q, plan=final, entry_ref=ev["entryRef"], direction=direction,
                      delta=ev["delta"], multiplier=mult, unit_loss=fit["unitLoss"], fee=self.fee,
                      strike=out["strike"], premium=ask, option_type=side, expiry=out["expiry"], hold=self.hold)
        bid = float((cell or {}).get("bid") or 0)
        out.update({
            "available": True, "fits": qty >= 1, "qty": qty, "unitRisk": fit["unitLoss"],
            "unitRiskBasis": fit["unitLossBasis"], "plannedRisk": (round(qty * fit["unitLoss"], 2)
                                                                   if fit["unitLoss"] is not None and qty else None),
            "maxLoss": round(qty * ask * mult, 2) if qty else round(ask * mult, 2),
            "maxLossBasis": "the whole debit (premium x multiplier x qty)",
            "riskBudget": ev["budget"], "finalStop": fit["finalStop"], "stopRepairs": fit["repairs"],
            "breakEven": (pay.get("breakEven") or {}).get("expiration"),
            "bid": bid or None, "ask": ask, "delta": ev["delta"], "spreadPct": (cell or {}).get("spreadPct"),
            "openInterest": (cell or {}).get("openInterest"), "volume": (cell or {}).get("volume"),
            "fillBand": fill_band(bid=bid, ask=ask, last=None, settings=self.s, is_option=True),
            "binding": binds, "payoff": pay,
            "gateEvidence": [d for _c, d in ev["problems"]] + ([ev["greeksMeta"]["reason"]]
                                                               if ev["greeksMeta"].get("reason") else []),
            "vehicle": {"instrument": "option", "contract": symbol, "contract_label": out["display"],
                        "limit_price": round(ask, 2), "quantity": qty}})
        if qty < 1:
            out["reason"] = fit.get("reason") or "; ".join(binds) or "no quantity fits"
        return out

    async def vertical(self, *, underlying: str, long_sym: str, long_cell: dict | None, short_cell: dict | None,
                       short_strike: float, direction: str, pid: str | None, venue: dict) -> dict:
        o = occ_mod.parse(long_sym)
        side = o.option_type if o else "call"
        short_sym = (short_cell or {}).get("symbol") or ""
        label = f"debit vertical {float(o.strike):g}/{float(short_strike):g}{side[0].upper()} {o.expiry.isoformat()}" if o else "debit vertical"
        out: dict = {"kind": "vertical", "label": label, "contract": None, "expiry": o.expiry.isoformat() if o else None,
                     "longStrike": float(o.strike) if o else None, "shortStrike": float(short_strike),
                     "legs": [{"action": "buy", "type": side, "strike": float(o.strike) if o else None, "symbol": long_sym},
                              {"action": "sell", "type": side, "strike": float(short_strike), "symbol": short_sym}],
                     "venueDependent": True, **venue}
        la, sb = float((long_cell or {}).get("ask") or 0), float((short_cell or {}).get("bid") or 0)
        if la <= 0 or sb <= 0:
            return {**out, "available": False, "reason": f"legs not priceable (long ask {la:g}, short bid {sb:g})"}
        why = liquidity_problem(short_cell)
        if why:
            return {**out, "available": False, "reason": f"short leg: {why}"}
        net = round(la - sb, 4)
        width = abs(float(short_strike) - float(o.strike))
        if net <= 0 or net >= width:
            return {**out, "available": False, "reason": f"not a sensible debit (net {net:g}, width {width:g})"}
        vl = {"multiplier": occ_mod.contract_multiplier(long_sym), "optionType": side, "currency": "USD"}
        vs = {"multiplier": occ_mod.contract_multiplier(short_sym), "optionType": side, "currency": "USD"}
        evl = await _re.gather(self.eng, underlying=underlying, sec_type="OPT", symbol=long_sym, vehicle=vl,
                               limit=la, entry_hint=self.entry_hint, pid=pid, cache=self.cache)
        evs = await _re.gather(self.eng, underlying=underlying, sec_type="OPT", symbol=short_sym, vehicle=vs,
                               limit=sb, entry_hint=self.entry_hint, pid=pid, cache=self.cache)
        net_delta = (abs(float(evl["delta"])) - abs(float(evs["delta"]))
                     if evl["delta"] is not None and evs["delta"] is not None else None)
        if net_delta is not None and net_delta <= 0:
            net_delta = None
        final, fit = _geo.fit_expression(direction=direction, vehicle="option", entry_ref=evl["entryRef"],
                                         exit_plan=self.plan, bars=evl["bars"], settings=self.s, premium=net,
                                         multiplier=evl["multiplier"], option_type=side, delta=net_delta,
                                         budget=evl["budget"])
        mult = float(evl["multiplier"] or 0) or 100.0
        qty, binds = cap_qty(fit["qtyByRisk"], unit_cost=net * mult, allocation=self.alloc, settings=self.s,
                             is_option=True)
        pay = _payoff(vehicle="option", qty=max(qty, 1), plan=final, entry_ref=evl["entryRef"], direction=direction,
                      delta=net_delta, multiplier=mult, unit_loss=fit["unitLoss"], fee=2 * self.fee,
                      strike=float(o.strike), premium=net, option_type=side, expiry=out["expiry"], hold=self.hold)
        out.update({
            "available": True, "fits": qty >= 1, "qty": qty, "netDebit": net, "width": width,
            "unitRisk": fit["unitLoss"], "unitRiskBasis": fit["unitLossBasis"] + " (net delta of the two legs)",
            "plannedRisk": round(qty * fit["unitLoss"], 2) if fit["unitLoss"] is not None and qty else None,
            "maxLoss": round(max(qty, 1) * net * mult, 2), "maxLossBasis": "the net debit (defined risk)",
            "maxGain": round(max(qty, 1) * (width - net) * mult, 2), "riskBudget": evl["budget"],
            "finalStop": fit["finalStop"], "stopRepairs": fit["repairs"],
            "breakEven": round(float(o.strike) + net if side == "call" else float(o.strike) - net, 4),
            "spreadPct": {"long": (long_cell or {}).get("spreadPct"), "short": (short_cell or {}).get("spreadPct")},
            "fillBand": {"long": fill_band(bid=(long_cell or {}).get("bid"), ask=la, last=None, settings=self.s, is_option=True),
                         "short": {"limit": round(sb, 2), "note": "sold at the bid"}},
            "binding": binds, "payoff": pay,
            "capsTheRunner": f"gains stop at the short strike {float(short_strike):g} (max gain above)",
            "gateEvidence": [d for _c, d in evl["problems"] + evs["problems"]],
            "vehicle": {"instrument": "option", "contract": None, "legs": [
                {"action": "buy", "type": side, "strike": float(o.strike)},
                {"action": "sell", "type": side, "strike": float(short_strike)}],
                "legs_expiry": out["expiry"], "quantity": qty, "limit_price": round(net, 2)}})
        if qty < 1:
            out["reason"] = fit.get("reason") or "; ".join(binds) or "no quantity fits"
        return out

    async def shares(self, *, underlying: str, direction: str, pid: str | None) -> dict:
        out: dict = {"kind": "shares", "label": f"{underlying} shares at the structure stop", "contract": None}
        if direction == "short":
            return {**out, "available": False, "reason": "a bearish idea is never expressed by shorting shares"}
        if self.plan.get("underlyingStop") is None:
            return {**out, "available": False, "reason": "no underlying stop declared - share risk cannot be bounded"}
        await self.eng.ensure_symbol(underlying)
        q = self.eng.quotes.get(underlying)
        ask = float(q.ask) if q is not None and q.ask and q.ask > 0 else (float(q.last) if q is not None and q.last else 0.0)
        if ask <= 0:
            return {**out, "available": False, "reason": "no share quote"}
        ev = await _re.gather(self.eng, underlying=underlying, sec_type="STK", symbol=underlying, vehicle={},
                              limit=ask, entry_hint=self.entry_hint, pid=pid, cache=self.cache)
        final, fit = _geo.fit_expression(direction=direction, vehicle="shares", entry_ref=ev["entryRef"],
                                         exit_plan=self.plan, bars=ev["bars"], settings=self.s, premium=ask,
                                         budget=ev["budget"])
        room = None
        if ev.get("equity"):
            held = 0.0
            with contextlib.suppress(Exception):
                held = abs(self.eng.positions.position_qty(pid, underlying, "STK")) * ask
            room = max(0.0, float(ev["equity"]) * float(self.s.get("risk.max_position_pct", 50.0)) / 100.0 * 0.97 - held)
        qty, binds = cap_qty(fit["qtyByRisk"], unit_cost=ask, allocation=self.alloc, settings=self.s,
                             is_option=False, position_room=room)
        pay = _payoff(vehicle="shares", qty=max(qty, 1), plan=final, entry_ref=ev["entryRef"], direction=direction,
                      delta=None, multiplier=1.0, unit_loss=fit["unitLoss"], fee=0.0, hold=self.hold)
        out.update({
            "available": True, "fits": qty >= 1, "qty": qty, "unitRisk": fit["unitLoss"],
            "unitRiskBasis": fit["unitLossBasis"],
            "plannedRisk": round(qty * fit["unitLoss"], 2) if fit["unitLoss"] is not None and qty else None,
            "maxLoss": round(qty * ask, 2), "maxLossBasis": "to zero (theoretical); the stop bounds the planned risk",
            "notional": round(qty * ask, 2), "riskBudget": ev["budget"], "finalStop": fit["finalStop"],
            "stopRepairs": fit["repairs"], "breakEven": round(ask, 4), "ask": ask,
            "spreadPct": round(float(q.spread_pct), 3) if q is not None and getattr(q, "spread_pct", None) is not None else None,
            "fillBand": fill_band(bid=getattr(q, "bid", None), ask=ask, last=getattr(q, "last", None), settings=self.s,
                                  is_option=False),
            "binding": binds, "payoff": pay, "gateEvidence": [d for _c, d in ev["problems"]],
            "vehicle": {"instrument": "shares", "contract": None, "limit_price": round(ask, 2), "quantity": qty}})
        if qty < 1:
            out["reason"] = fit.get("reason") or "; ".join(binds) or "no quantity fits"
        return out


def _stated_contract(args: dict, ctx: dict) -> str | None:
    raw = str(args.get("contract") or "").strip()
    if raw and raw.lower() not in ("shares", "stock"):
        p = occ_mod.parse_loose(raw) if hasattr(occ_mod, "parse_loose") else occ_mod.parse(raw)
        if p is not None:
            return p.symbol
    tip = ctx.get("tip") or {}
    inst, strike, exp = tip.get("instrument"), tip.get("strike"), tip.get("expiry")
    if inst in ("call", "put") and strike and exp:
        with contextlib.suppress(Exception):
            return occ_mod.make(str(ctx.get("ticker") or "").upper(), str(exp), "C" if inst == "call" else "P",
                                float(strike)).symbol
    return None


async def find_alternatives(eng, args: dict, ctx: dict) -> dict:
    """The tool. Deterministic; reads the chain provider and the quote store; never calls a model, never orders."""
    from ...approvals.proposals import live_vehicle_refusal, policy_kind, shares_first_applies
    from .lifecycle import _mleg_supported
    s = eng.settings
    if not bool(s.get("techniques.tip.find_alternatives_enabled", True)):
        return {"error": "find_alternatives is disabled (techniques.tip.find_alternatives_enabled)"}
    b = _Builder(eng, args, ctx)
    pid = _re.tip_book_id(eng)
    pf = (eng.positions.portfolio(pid) or {}) if pid else {}
    stated = _stated_contract(args, ctx)
    parsed = occ_mod.parse(stated) if stated else None
    underlying = (parsed.underlying if parsed else str(ctx.get("ticker") or args.get("symbol") or "")).upper()
    tip_dir = str((ctx.get("tip") or {}).get("direction") or "long")
    direction = ("short" if parsed.option_type == "put" else "long") if parsed else tip_dir
    why_shares = live_vehicle_refusal(s, pf, "OPT")
    if why_shares is None:
        # the proposal path's shares-first rule (P1): on this book a long, non-lotto idea of a shares-first source
        # is proposed as SHARES whatever option is named - offering option alternatives would be a false promise
        with contextlib.suppress(Exception):
            from ...signals.sources import resolve_policy
            pol = resolve_policy(s, ctx.get("source"))
            if shares_first_applies(pol.expression, direction=direction, lotto=bool(ctx.get("lotto")),
                                    portfolio_kind=policy_kind(s, pf)):
                why_shares = (f"source {ctx.get('source')} is shares-first on this book (expression=shares): a long "
                              "idea is proposed in shares")
    shares_only = why_shares is not None
    book = {"portfolioId": pid, "name": pf.get("name"), "kind": pf.get("kind"), "policyKind": policy_kind(s, pf),
            "sharesOnly": shares_only, **({"sharesOnlyReason": why_shares} if shares_only else {})}
    result: dict = {"version": ALTERNATIVES_VERSION, "underlying": underlying, "direction": direction,
                    "book": book, "declaredPlan": b.plan, "original": None, "alternatives": [], "notFitting": [],
                    "unavailable": []}
    cands: list[dict] = []
    if parsed is not None:
        exp = parsed.expiry.isoformat()
        side = parsed.option_type
        chain = await b.chain(underlying, exp)
        stated_cell = b.cell(chain, float(parsed.strike), side)
        limit = float(args["limit"]) if args.get("limit") else None
        result["original"] = await b.option(kind="stated", label="the tip's stated contract", underlying=underlying,
                                            symbol=parsed.symbol, cell=stated_cell, direction=direction, pid=pid,
                                            limit=limit, check_liquidity=False)
        if chain is None:
            result["unavailable"].append({"kind": "strike", "reason": f"chain for {exp} unavailable"})
        if not shares_only and chain is not None:
            # (1) same expiry, cheaper strikes: further out of the money (calls up, puts down), nearest first
            strikes = sorted(float(r["strike"]) for r in (chain.get("rows") or []) if r.get(side))
            further = ([k for k in strikes if k > float(parsed.strike) + 1e-9] if side == "call"
                       else sorted([k for k in strikes if k < float(parsed.strike) - 1e-9], reverse=True))
            n_otm = max(0, int(s.get("techniques.tip.alternatives_strikes_otm", 2) or 0))
            for k in further[:n_otm]:
                c = b.cell(chain, k, side)
                cands.append(await b.option(kind="strike", label=f"same expiry, {k:g} strike (further OTM)",
                                            underlying=underlying, symbol=(c or {}).get("symbol") or occ_mod.make(
                                                underlying, exp, "C" if side == "call" else "P", k).symbol,
                                            cell=c, direction=direction, pid=pid))
            if not further:
                result["unavailable"].append({"kind": "strike", "reason": "no further-OTM strike listed at this expiry"})
            # (3) debit vertical: short leg at the first target (the move the plan expects), else 2 strikes out
            tg = list(b.plan.get("targets") or [])
            shorts: list[float] = []
            if tg:
                t0 = float(tg[0])
                beyond = [k for k in further if (k >= t0 - 1e-9 if side == "call" else k <= t0 + 1e-9)]
                if beyond:
                    shorts.append(beyond[0])
            for k in further[1:3]:
                if k not in shorts and len(shorts) < 2:
                    shorts.append(k)
            if not shorts and further:
                shorts.append(further[0])
            venue = ({"venue": "native multi-leg (one combined order)", "autoEligible": False}
                     if pid and _mleg_supported(eng, pid) else
                     {"venue": "leg-sequenced (long leg fills first, then the short)", "autoEligible": False})
            from . import geometry as _g
            if pid and _g.gate_mode(s) == "enforce" and policy_kind(s, pf) == "sim":
                venue["executionNote"] = ("the Practice geometry gate does not size spread vehicles: a spread card waits "
                                          "for a person (never auto-approved)")
            for k in shorts:
                cands.append(await b.vertical(underlying=underlying, long_sym=parsed.symbol, long_cell=stated_cell,
                                              short_cell=b.cell(chain, k, side), short_strike=k, direction=direction,
                                              pid=pid, venue=dict(venue)))
        if not shares_only:
            # (2) later expiries, same strike
            n_exp = max(0, int(s.get("techniques.tip.alternatives_later_expiries", 2) or 0))
            later: list[str] = []
            with contextlib.suppress(Exception):
                ex = await asyncio.wait_for(eng.options.expiries(underlying), FETCH_TIMEOUT_S)
                later = [e["date"] for e in (ex.get("expiries") or []) if str(e.get("date")) > exp][:n_exp]
            if not later:
                result["unavailable"].append({"kind": "expiry", "reason": "no later expiry listed (or expiries unavailable)"})
            chains = await asyncio.gather(*(b.chain(underlying, e) for e in later))
            for e, ch in zip(later, chains):
                c = b.cell(ch, float(parsed.strike), side)
                sym = (c or {}).get("symbol") or occ_mod.make(underlying, e, "C" if side == "call" else "P",
                                                              float(parsed.strike)).symbol
                alt = await b.option(kind="expiry", label=f"same strike, later expiry {e}", underlying=underlying,
                                     symbol=sym, cell=c, direction=direction, pid=pid)
                hs = b.hold
                if alt.get("available") and hs:
                    alt["horizonNote"] = f"declared hold {int(hs)} session(s); this contract has {(dt.date.fromisoformat(e) - dt.date.today()).days} calendar days"
                cands.append(alt)
    else:
        result["unavailable"].append({"kind": "option", "reason": "no stated option contract - only shares can be sized"})
    if shares_only:
        result["unavailable"].append({"kind": "option", "reason": book.get("sharesOnlyReason")})
    # (4) shares at the structure stop
    cands.append(await b.shares(underlying=underlying, direction=direction, pid=pid))
    n = 0
    for c in sorted(cands, key=lambda x: KIND_ORDER.index(x["kind"]) if x["kind"] in KIND_ORDER else 9):
        if not c.get("available"):
            result["unavailable"].append({k: c.get(k) for k in ("kind", "label", "contract", "reason")})
            continue
        n += 1
        c["id"] = f"alt{n}"
        (result["alternatives"] if c.get("fits") else result["notFitting"]).append(c)
    result["instructions"] = (
        "To take one: answer verdict 'take' with alternativeChosen = its id and copy its `vehicle` fields "
        "(instrument, contract or legs + legs_expiry, limit_price, quantity) and an exit plan at its finalStop. "
        "To skip for budget/size: list EVERY id here in alternativesConsidered with a concrete reason against it. "
        "Numbers come from the same risk arithmetic the gate applies; payoff figures are estimates, not forecasts.")
    if not result["alternatives"]:
        result["note"] = "no alternative fits the risk budget - a skip for size is on the record with these numbers"
    return result


def _slim_payoff(p: dict | None) -> dict | None:
    if not p:
        return None
    be = p.get("breakEven") or {}
    hz = p.get("horizon") or {}
    return {"scenarios": p.get("scenarios"), "oneLot": p.get("oneLot"),
            "units": (p.get("ladder") or {}).get("units"), "expirationBreakEven": be.get("expiration"),
            **({"holdCapEndsOn": hz.get("holdCapEndsOn"), "dte": hz.get("dte")} if hz else {}),
            **({"reason": p.get("reason")} if p.get("reason") else {})}


def for_model(result: dict) -> dict:
    """The model-facing rendition (tool results are capped at 6000 chars): every number that decides the choice,
    without the ladder/horizon prose. The full result stays on the run record."""
    keep = ("id", "kind", "label", "contract", "legs", "expiry", "qty", "fits", "unitRisk", "plannedRisk", "maxLoss",
            "maxGain", "netDebit", "breakEven", "ask", "delta", "spreadPct", "openInterest", "finalStop", "stopRepairs",
            "binding", "reason", "venue", "venueDependent", "autoEligible", "executionNote", "capsTheRunner",
            "horizonNote", "gateEvidence", "vehicle")

    def slim(a: dict) -> dict:
        out = {k: a.get(k) for k in keep if a.get(k) not in (None, [], {})}
        fb = a.get("fillBand") or {}
        if fb:
            out["fillBand"] = ({k: fb.get(k) for k in ("limit", "low", "high", "withinCollar")} if "limit" in fb
                               else {"long": {k: (fb.get("long") or {}).get(k) for k in ("limit", "low", "high", "withinCollar")}})
        out["payoff"] = _slim_payoff(a.get("payoff"))
        return out
    return {"version": result.get("version"), "underlying": result.get("underlying"), "book": result.get("book"),
            "original": slim(result["original"]) if result.get("original") else None,
            "alternatives": [slim(a) for a in result.get("alternatives") or []],
            "notFitting": [{k: a.get(k) for k in ("id", "kind", "label", "contract", "unitRisk", "reason")}
                           for a in result.get("notFitting") or []],
            "unavailable": result.get("unavailable"), "instructions": result.get("instructions"),
            **({"note": result["note"]} if result.get("note") else {})}


def compact(result: dict) -> list[dict]:
    """The list as it is journaled (TipAlternativesOffered) - ids, kinds, contracts, size and risk, no payoff body."""
    out = []
    for grp in ("alternatives", "notFitting"):
        for a in result.get(grp) or []:
            out.append({k: a.get(k) for k in ("id", "kind", "label", "contract", "legs", "qty", "fits", "plannedRisk",
                                              "maxLoss", "breakEven", "ask", "netDebit", "finalStop", "reason")})
    return out


BUDGET_SKIP_RE = _re_mod.compile(
    r"budget|too (expensive|large|big|rich)|risks? \$|one (unit|contract|lot|share)\b.{0,40}(risk|exceed|above)|"
    r"does ?n[o']?t fit|cannot fit|can'?t fit|won'?t fit|infeasib|not feasible|feasib|qty 0|zero (qty|quantity)|"
    r"\bsizing\b|\bsize\b|unaffordable|premium (is )?too", _re_mod.I)


def is_priced_bto(tip: dict | None, verification: dict | None) -> bool:
    """A verified, priced buy-to-open: verification passed, an open/add, a price the desk can act on (the premium
    or the entry). Parked / shadow-only / non-actionable content is not one."""
    t, v = dict(tip or {}), dict(verification or {})
    return bool(v.get("passed") and not v.get("park") and not v.get("shadow_only")
                and str(t.get("action") or "open") in ("open", "add") and (t.get("premium") or t.get("entryPrice")))


def reask_reason(opinion: dict, *, tip: dict | None, verification: dict | None, offered: dict | None) -> str | None:
    """W2.2 (pure): why a verdict must be re-asked once - a budget/size skip (or watch) of a verified priced BTO
    that did not weigh the alternatives. None = the verdict stands."""
    if str(opinion.get("verdict") or "") not in ("skip", "watch"):
        return None
    if not is_priced_bto(tip, verification):
        return None
    text = " ".join(str(opinion.get(k) or "") for k in ("rationale", "expression_note", "invalidation", "entry_note"))
    if not BUDGET_SKIP_RE.search(text):
        return None
    if offered is None:
        return "budget/size skip without find_alternatives"
    fits = [a.get("id") for a in offered.get("alternatives") or []]
    if not fits:
        return None                                   # nothing fits: the skip stands on the offered numbers
    seen = {str(c.get("id")): str(c.get("reason") or "").strip()
            for c in (opinion.get("alternativesConsidered") or []) if isinstance(c, dict)}
    missing = [i for i in fits if not seen.get(str(i))]
    if missing:
        return f"budget/size skip without a concrete reason against {', '.join(missing)}"
    return None


def reask_args(opinion: dict, tip: dict | None, ticker: str | None) -> dict:
    """find_alternatives arguments for a server-side run from the verdict + the tip (stated contract, stop, plan)."""
    t = dict(tip or {})
    args: dict = {"contract": opinion.get("contract") or None,
                  "underlying_stop": opinion.get("underlying_stop") if opinion.get("underlying_stop") is not None
                  else t.get("stopPrice"),
                  "premium_stop_pct": opinion.get("premium_stop_pct"),
                  "exit_targets": list(opinion.get("exit_targets") or ([t["targetPrice"]] if t.get("targetPrice") else [])),
                  "exit_fractions": list(opinion.get("exit_fractions") or []),
                  "hold_sessions": opinion.get("max_hold_sessions") or t.get("horizonSessions"),
                  "limit": t.get("premium")}
    return {k: v for k, v in args.items() if v not in (None, [], "")}


def apply_choice(opinion: dict, choice: dict, offered: dict) -> dict:
    """The chosen alternative becomes the take's vehicle EXACTLY as a normal take carries it (so the existing proposal
    path trades it), with `reshapedFrom` = the stated contract and the analyst's own limit/qty kept when tighter."""
    op = dict(opinion)
    veh = dict(choice.get("vehicle") or {})
    orig = (offered.get("original") or {}).get("contract")
    if choice["kind"] == "shares":
        op.update(instrument="shares", contract=None, contract_label=None, legs=[], legs_expiry=None)
    elif choice["kind"] == "vertical":
        op.update(instrument="option", contract=None, contract_label=choice.get("label"),
                  legs=list(veh.get("legs") or []), legs_expiry=veh.get("legs_expiry"))
    else:
        op.update(instrument="option", contract=veh.get("contract"), contract_label=veh.get("contract_label"),
                  legs=[], legs_expiry=None)
    lim = veh.get("limit_price")
    if lim and (not op.get("limit_price") or float(op["limit_price"]) > float(lim) or choice["kind"] == "shares"):
        op["limit_price"] = lim
    q = int(veh.get("quantity") or 0)
    if q >= 1 and (not op.get("quantity") or int(op["quantity"]) > q):
        op["quantity"] = q
    if choice.get("finalStop") is not None and op.get("underlying_stop") is None:
        op["underlying_stop"] = choice["finalStop"]
    op["alternativeChosen"] = choice.get("id")
    op["reshapedFrom"] = orig or "the tip's stated expression"
    op["reshape"] = {"kind": choice["kind"], "label": choice.get("label"), "qty": choice.get("qty"),
                     "plannedRisk": choice.get("plannedRisk"), "maxLoss": choice.get("maxLoss"),
                     "finalStop": choice.get("finalStop"), "version": offered.get("version"),
                     **({"venue": choice.get("venue"), "autoEligible": choice.get("autoEligible"),
                         "executionNote": choice.get("executionNote")} if choice["kind"] == "vertical" else {})}
    return op


def match_choice(result: dict | None, opinion: dict) -> dict | None:
    """Which offered alternative the analyst took: by `alternativeChosen` id, else by the vehicle it named."""
    if not result:
        return None
    fits = list(result.get("alternatives") or []) + list(result.get("notFitting") or [])
    want = str(opinion.get("alternativeChosen") or "").strip()
    if want:
        hit = next((a for a in fits if a.get("id") == want), None)
        if hit is not None:
            return hit
    inst = opinion.get("instrument")
    con = str(opinion.get("contract") or "").upper()
    legs = opinion.get("legs") or []
    for a in fits:
        if a["kind"] == "shares" and inst == "shares" and not con:
            return a
        if a.get("contract") and con and a["contract"].upper() == con:
            return a
        if a["kind"] == "vertical" and len(legs) == 2:
            ks = sorted(float(lg.get("strike") or 0) for lg in legs)
            if ks == sorted([float(a.get("longStrike") or 0), float(a.get("shortStrike") or 0)]):
                return a
    return None
