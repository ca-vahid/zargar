"""Pending-proposal queue: verified signal → sized order proposal → approve/reject/expire."""
from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import logging
import math

from sqlalchemy import select

from .. import bus as topics
from .. import events as ev
from ..domain import new_id
from ..models import ManagedPositionRow, Order, Proposal, Signal
from ..orders import BracketSpec, OrderIntent
from ..signals.schemas import TradeSignal

log = logging.getLogger("zargar.proposals")


def proposal_dict(p: Proposal) -> dict:
    return {
        "id": p.id,
        "signalId": p.signal_id,
        "portfolioId": p.portfolio_id,
        "symbol": p.symbol,
        "secType": p.sec_type,
        "side": p.side,
        "qty": p.qty,
        "orderType": p.order_type,
        "limitPrice": p.limit_price,
        "bracket": p.bracket,
        "rationale": p.rationale,
        "context": p.context,
        "status": p.status,
        "expiresAt": p.expires_at.isoformat() if p.expires_at else None,
        "decidedAt": p.decided_at.isoformat() if p.decided_at else None,
        "decidedVia": p.decided_via,
        "orderId": p.order_id,
        "createdAt": p.created_at.isoformat() if p.created_at else None,
    }


def build_exit_plan_spread(signal_row, sig, analyst: dict, policy) -> dict:
    """The spread's exit context: hold cap + analyst campaign when present
    (credit spreads run the engine's credit-target policy regardless)."""
    from ..techniques.tip.lifecycle import build_exit_plan
    return build_exit_plan(signal_row, sig, analyst or {}, policy)


async def _live_ask(eng, occ: str) -> float | None:
    """The contract's ask from the real-time source when one is configured
    (options.track -> OPRA); a delayed chain quote is NOT a price to size or
    limit against, so with a live source configured but not serving this
    contract the answer is None (the stated premium stands). Without any live
    source (sim/tests) the cached quote is used as before."""
    opts = getattr(eng, "options", None)
    if opts is not None and opts.quote_source(ignore_backoff=True) is not None:
        import contextlib
        with contextlib.suppress(Exception):
            await opts.track(occ)
            if not opts.served_live(occ):
                await opts._refresh_live()
        if not opts.served_live(occ):
            return None
    q = eng.quotes.get(occ)
    return float(q.ask) if q is not None and q.ask and q.ask > 0 else None


def _ttl_expiry(ttl_min: int, now: dt.datetime | None = None) -> dt.datetime:
    """Proposal expiry that respects the clock (ARM-PLAN P1/F9): during regular
    hours it is now+TTL; off-hours (evening, weekend, pre-open) the countdown
    starts at the NEXT session open, so an overnight take is still standing when
    the market can actually act on it."""
    from zoneinfo import ZoneInfo
    et = ZoneInfo("America/New_York")
    now_utc = now or dt.datetime.now(dt.timezone.utc)
    now_et = now_utc.astimezone(et)
    open_t = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
    close_t = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
    if now_et.weekday() < 5 and open_t <= now_et <= close_t:
        base = now_et
    else:
        day = now_et.date()
        if now_et.weekday() >= 5 or now_et > close_t:
            day += dt.timedelta(days=1)
        while day.weekday() >= 5:
            day += dt.timedelta(days=1)
        base = dt.datetime.combine(day, dt.time(9, 30), tzinfo=et)
    return (base + dt.timedelta(minutes=ttl_min)).astimezone(dt.timezone.utc)


class ProposalService:
    def __init__(self, engine) -> None:
        self.engine = engine
        self._task: asyncio.Task | None = None
        self._adopt_tasks: dict[str, asyncio.Task] = {}   # proposalId -> adopt-on-fill waiter

    def _cap_contracts(self, qty: int) -> int:
        """Safety net on option quantity: budget sizing on lotto premium is
        nonsense (277 × a $0.09 call, 2026-08-31) — a cheap contract is cheap
        because it is unlikely, not an invitation to buy hundreds. Caps stated
        analyst/tip counts too."""
        cap = int(self.engine.settings.get("techniques.tip.max_contracts_per_tip", 25) or 0)
        return min(qty, cap) if cap > 0 else qty

    # ------------------------------------------------------------- create
    async def create_from_armed_fire(self, signal_row: Signal, *, run_id: str, trigger_id: str,
                                     portfolio_id: str, direction: str, entry: float, stop: float,
                                     targets: list[float], contract: dict | None,
                                     contracts: int | None, exit_plan: dict | None,
                                     analyst_run_id: str | None) -> dict | None:
        """A proposal minted by an ARMED plan's fire (ARM-GAPS A5): the level the
        plan waited for finally touched, in proposal mode — the card asks the
        human to take the trade NOW, with the vehicle the fire actually picked.
        Same shape and notification path as `create_from_signal` (Telegram + push
        ride topics.PROPOSALS)."""
        eng = self.engine
        from ..signals.sources import resolve_policy
        policy = resolve_policy(eng.settings, signal_row.source_name)
        budget = float(policy.budget_per_tip)
        pf = eng.positions.portfolio(portfolio_id) or {}
        analyst = (signal_row.extraction or {}).get("analyst") or {}
        bracket = None
        if contract and contract.get("symbol"):
            occ = str(contract["symbol"]).upper()
            live_ask = float(contract.get("ask") or 0) or None
            # never chase above the analyst's/tip's stated premium — a live ask
            # may only IMPROVE the limit (same guard as the tip-time proposal)
            ref = analyst.get("limit_price") or signal_row.premium or live_ask
            if live_ask and ref and live_ask < float(ref):
                ref = live_ask
            if not ref or float(ref) <= 0:
                log.warning("armed fire %s: no premium reference for %s — no proposal", run_id, occ)
                return None
            limit = round(float(ref), 2)
            qty = self._cap_contracts(int(contracts or 0) or max(1, math.floor(budget / (limit * 100))))
            symbol, sec_type = occ, "OPT"
            label = contract.get("display") or occ
            vehicle = {"kind": "option", "display": label, "underlying": signal_row.ticker,
                       "optionType": contract.get("optionType"), "pickedBy": "armed_fire",
                       "multiplier": 100,
                       **({"substituted": contract["substituted"]}
                          if contract.get("substituted") else {})}
            explain = (f"The level this plan waited for touched: buy {qty} contract"
                       f"{'s' if qty != 1 else ''} of {label} at a ${limit:.2f} limit "
                       f"≈ ${limit * qty * 100:,.0f} in “{pf.get('name', portfolio_id)}” "
                       f"({pf.get('kind', '?')}). RiskGate still checks the order on approval.")
        else:
            if direction == "short":
                log.warning("armed fire %s: short with no contract — share shorting is never proposed", run_id)
                return None
            q = eng.quotes.get(signal_row.ticker)
            ref = (float(q.ask) if q is not None and q.ask and q.ask > 0 else None) or float(entry or 0)
            if not ref or ref <= 0:
                return None
            limit = round(ref, 2)
            qty = max(1, math.floor(budget / limit))
            symbol, sec_type = signal_row.ticker, "STK"
            vehicle = {"kind": "shares"}
            if targets or stop:
                bracket = {"take_profit": (targets[0] if targets else None), "stop_loss": stop or None,
                           "take_profit_pct": None, "stop_loss_pct": None}
            explain = (f"The level this plan waited for touched: buy {qty} share"
                       f"{'s' if qty != 1 else ''} of {symbol} at a ${limit:.2f} limit "
                       f"≈ ${limit * qty:,.0f} in “{pf.get('name', portfolio_id)}” "
                       f"({pf.get('kind', '?')}). RiskGate still checks the order on approval.")
        ttl_min = int(eng.settings.get("signals.default_ttl_minutes", 30))
        row = Proposal(
            id=new_id(), signal_id=signal_row.id, portfolio_id=portfolio_id,
            symbol=symbol, sec_type=sec_type, side="BUY", qty=float(qty),
            order_type="LMT", limit_price=limit, bracket=bracket,
            rationale=signal_row.thesis_summary,
            context={"techniqueId": "tip", "sourceName": signal_row.source_name,
                     "armedRunId": run_id, "triggerId": trigger_id,
                     "vehicle": vehicle, "explain": explain,
                     "signalPrices": {"entry": entry, "stop": stop,
                                      "target": (targets[0] if targets else None)},
                     **({"exitPlan": exit_plan} if exit_plan else {}),
                     **({"analystRunId": analyst_run_id} if analyst_run_id else {})},
            expires_at=_ttl_expiry(ttl_min))
        async with eng.sf() as session:
            session.add(row)
            sig_db = await session.get(Signal, signal_row.id)
            if sig_db is not None and sig_db.status in ("verified", "parked"):
                sig_db.status = "proposed"
            await session.commit()
        pdict = proposal_dict(row)
        await eng.journal.append(ev.PROPOSAL_CREATED, pdict, aggregate_type="proposal",
                                 aggregate_id=row.id, portfolio_id=portfolio_id)
        eng.bus.publish(topics.PROPOSALS, pdict)
        return pdict

    async def create_from_signal(self, signal_row: Signal, sig: TradeSignal,
                                 verification: dict) -> dict | None:
        """Verified tip → the order the human is asked to approve. The proposal
        trades the SAME vehicle the shadow books do: a tip that names an option
        proposes that contract (BUY to open — a bearish tip buys the put, share
        shorting is never proposed); the analyst's pick, when it said "take",
        wins over the raw expression (the P6 handshake). Sized by the source's
        per-tip budget, like the books, so the scorecard stays comparable."""
        from ..signals.sources import resolve_policy

        eng = self.engine
        pid = str(eng.settings.get("trading.default_portfolio", ""))
        if not pid or eng.positions.portfolio(pid) is None:
            portfolios = [p for p in eng.positions.portfolios() if p["kind"] == "sim"]
            if not portfolios:
                log.warning("no portfolio available for proposal")
                return None
            pid = portfolios[0]["id"]
        pf = eng.positions.portfolio(pid) or {}
        policy = resolve_policy(eng.settings, signal_row.source_name)
        budget = float(policy.budget_per_tip)
        # the lotto lane (0-3 DTE, user 2026-09-01): its own budget, tip-time
        # only, and no 0-DTE entries once the expiry-day flatten time has passed
        from ..techniques.tip.lotto import is_lotto, lotto_budget, past_flatten_time
        lotto = is_lotto(signal_row, eng.settings)
        if lotto:
            budget = lotto_budget(eng.settings, budget)
            from zoneinfo import ZoneInfo
            now_et = dt.datetime.now(ZoneInfo("America/New_York"))
            exp = str(signal_row.expiry or "")
            if exp == now_et.strftime("%Y-%m-%d") and past_flatten_time(eng.settings, now_et):
                log.info("lotto %s: 0DTE past the flatten time — no proposal", signal_row.id)
                return None

        extraction = signal_row.extraction or {}
        analyst = extraction.get("analyst") or {}
        expr = extraction.get("shadowExpression") or {}

        # ---- spread vehicle (ARM-PLAN P5): a stated/analyst 2-leg defined-risk
        # spread proposes as ONE unit; approve() opens it leg-sequenced
        a_legs = (analyst.get("legs") or []) if analyst.get("verdict") == "take" else []
        sig_legs = (extraction.get("signal") or {}).get("legs") or []
        spread_legs = a_legs if len(a_legs) == 2 else (sig_legs if len(sig_legs) == 2 else None)
        if spread_legs:
            from ..techniques.tip.express import pick_spread
            pick = await pick_spread(
                eng, symbol=sig.ticker.upper(), legs=spread_legs,
                expiry=analyst.get("legs_expiry") or signal_row.expiry,
                dte_min=policy.dte_min, dte_max=policy.dte_max)
            if pick.get("available"):
                net, width = float(pick["net"]), float(pick["width"])
                max_loss = net if net > 0 else max(width - abs(net), 0.01)
                qty = self._cap_contracts(max(1, math.floor(budget / (max_loss * 100))))
                disp = (f"{sig.ticker.upper()} "
                        f"{pick['legs'][0]['strike']:g}/{pick['legs'][1]['strike']:g} "
                        f"{pick['legs'][0]['optionType']} spread {pick['expiry']}")
                explain = (f"Approve = open {qty} x {disp} as a defined-risk spread "
                           f"({'debit' if net > 0 else 'credit'} {abs(net):.2f}, width {width:g}; "
                           f"max loss ≈ ${max_loss * 100 * qty:,.0f}) in "
                           f"“{pf.get('name', pid)}” ({pf.get('kind', '?')}). The long leg fills "
                           f"FIRST, then the short leg — risk is defined at every instant.")
                ttl_min = int(eng.settings.get("signals.default_ttl_minutes", 30))
                row = Proposal(
                    id=new_id(), signal_id=signal_row.id, portfolio_id=pid,
                    symbol=sig.ticker.upper(), sec_type="SPREAD",
                    side="BUY" if net > 0 else "SELL", qty=float(qty),
                    order_type="LMT", limit_price=round(net, 2), bracket=None,
                    rationale=sig.thesis_summary,
                    context={"techniqueId": "tip", "sourceName": signal_row.source_name,
                             "confidence": sig.confidence, "verification": verification,
                             "sizing": {"budget": round(budget, 2), "qty": qty,
                                        "maxLossPerSpread": round(max_loss * 100, 2)},
                             "vehicle": {"kind": "spread", "display": disp,
                                         "underlying": sig.ticker.upper(),
                                         "direction": sig.direction,
                                         "legs": pick["legs"], "net": net,
                                         "width": width, "credit": bool(net < 0),
                                         "expiry": pick["expiry"]},
                             "explain": explain,
                             "exitPlan": build_exit_plan_spread(signal_row, sig, analyst, policy),
                             "analystRunId": analyst.get("runId"),
                             "analyst": ({k: analyst.get(k) for k in
                                          ("verdict", "rationale", "invalidation",
                                           "confidence")} if analyst else None)},
                    expires_at=_ttl_expiry(ttl_min))
                async with eng.sf() as session:
                    session.add(row)
                    sig_db = await session.get(Signal, signal_row.id)
                    if sig_db is not None:
                        sig_db.status = "proposed"
                    await session.commit()
                pdict = proposal_dict(row)
                await eng.journal.append(ev.PROPOSAL_CREATED, pdict,
                                         aggregate_type="proposal", aggregate_id=row.id,
                                         portfolio_id=pid)
                eng.bus.publish(topics.PROPOSALS, pdict)
                return pdict
            log.info("stated spread not tradable (%s) — falling back to single-leg",
                     pick.get("error"))

        # ---- vehicle: the analyst's contract beats the book's, both beat shares
        occ = label = None
        limit_hint = qty_hint = None
        if analyst.get("verdict") == "take" and analyst.get("contract") \
                and analyst.get("instrument", "option") == "option":
            occ = str(analyst["contract"]).upper()
            label = analyst.get("contract_label") or occ
            limit_hint = analyst.get("limit_price")
            qty_hint = analyst.get("quantity")
            picked_by = "analyst"
        elif expr.get("vehicle") == "option" and expr.get("contract"):
            occ = str(expr["contract"]).upper()
            label = expr.get("display") or occ
            limit_hint = expr.get("ask")
            qty_hint = expr.get("contracts")
            picked_by = "tip"

        bracket = None
        vehicle: dict = {}
        if occ:
            symbol, sec_type, side = occ, "OPT", "BUY"      # long the contract, both directions
            # deliberately NOT ensure_symbol(occ): the sim feed would fabricate a
            # quote for the contract and poison the risk gate's reference price.
            # The real-time source (OPRA via options.track) is asked instead —
            # a delayed chain ask "improving" the limit produced approved orders
            # that could never fill (audit 2026-09-02)
            live_ask = await _live_ask(eng, occ)
            # the analyst's/tip's stated limit is the trader's price — never chase
            # above it; a live ask may only IMPROVE the limit (found 2026-08-28:
            # a bad option quote priced 2 contracts at $16k against a $4.60 tip)
            ref_price = limit_hint or sig.premium or live_ask
            if live_ask and ref_price and live_ask < float(ref_price):
                ref_price = live_ask
            if not ref_price or ref_price <= 0:
                log.warning("no premium reference for %s — no proposal", occ)
                return None
            limit = round(float(ref_price), 2)
            qty = self._cap_contracts(int(qty_hint or 0) or max(1, math.floor(budget / (limit * 100))))
            from ..options import occ as occ_mod
            parsed = occ_mod.parse(occ)
            opt_type = parsed.option_type if parsed else ("put" if sig.direction == "short" else "call")
            label = label or (occ_mod.display(occ) if parsed else occ)
            vehicle = {"kind": "option", "display": label, "underlying": sig.ticker.upper(),
                       "optionType": opt_type, "pickedBy": picked_by, "multiplier": 100,
                       **({"lotto": True} if lotto else {})}
            cost = limit * qty * 100
            explain = (f"Approve = buy {qty} contract{'s' if qty != 1 else ''} of "
                       f"{label} (a {opt_type} — {'bullish' if opt_type == 'call' else 'bearish'}) "
                       f"at a ${limit:.2f} limit ≈ ${cost:,.0f} in “{pf.get('name', pid)}” "
                       f"({pf.get('kind', '?')}). The order still passes the risk gate; "
                       f"on the fill the position is handed to the durable manager under "
                       f"the analyst's exit plan.")
        else:
            if sig.direction == "short":
                # bearish with no usable put: share shorting is never proposed
                log.warning("short tip %s has no usable put — no proposal (shorts are puts only)",
                            signal_row.id)
                return None
            symbol, sec_type, side = sig.ticker.upper(), "STK", "BUY"
            await eng.ensure_symbol(symbol)
            quote = eng.quotes.get(symbol)
            ref_price = (quote.ask if quote and quote.ask > 0 else None) or sig.entry_price
            if not ref_price or ref_price <= 0:
                return None
            limit = round(float(ref_price), 2)
            qty = max(1, math.floor(budget / limit))
            vehicle = {"kind": "shares"}
            if sig.target_price or sig.stop_price:
                bracket = {"take_profit": sig.target_price, "stop_loss": sig.stop_price,
                           "take_profit_pct": None, "stop_loss_pct": None}
            explain = (f"Approve = buy {qty} share{'s' if qty != 1 else ''} of {symbol} at a "
                       f"${limit:.2f} limit ≈ ${limit * qty:,.0f} in “{pf.get('name', pid)}” "
                       f"({pf.get('kind', '?')})"
                       + (", with the tip's target/stop attached as a bracket"
                          if bracket else "")
                       + ". The order still passes the risk gate.")

        # the exit campaign this position will run after the fill — the analyst's
        # plan when it wrote one, else the tip's own stop/targets (ANALYST.md §5)
        from ..techniques.tip.lifecycle import build_exit_plan
        exit_plan = build_exit_plan(signal_row, sig, analyst, policy)
        bits = []
        if exit_plan.get("targets"):
            fr = exit_plan.get("fractions") or []
            bits.append("trims " + ", ".join(
                (f"{int(round(fr[i] * 100))}% @ {t:g}" if i < len(fr) else f"@ {t:g}")
                for i, t in enumerate(exit_plan["targets"])))
        if exit_plan.get("underlyingStop"):
            bits.append(f"stop {exit_plan['underlyingStop']:g}")
        if exit_plan.get("premiumStopPct"):
            bits.append(f"premium stop {exit_plan['premiumStopPct']:g}%")
        if exit_plan.get("maxHoldSessions"):
            bits.append(f"time box {exit_plan['maxHoldSessions']} sessions")
        if bits:
            explain += f" Exit campaign ({exit_plan.get('author', 'tip')}): {'; '.join(bits)}."

        # ---- preflight coherence (ARM-PLAN P1/F7): compare this order against
        # the platform risk caps NOW, on the card — not as a silent risk
        # rejection at fill time
        warns: list[str] = []
        try:
            equity = await eng.positions.equity(pid)
            mult = 100 if sec_type == "OPT" else 1
            notional = limit * qty * mult
            cap_notional = float(eng.settings.get("risk.max_position_notional", 1000.0))
            if notional > cap_notional:
                warns.append(f"${notional:,.0f} exceeds risk.max_position_notional "
                             f"(${cap_notional:,.0f}) — the fill will be risk-rejected")
            if sec_type == "OPT":
                prem_pct = float(eng.settings.get("risk.max_option_premium_pct", 5.0))
                prem_abs = float(eng.settings.get("risk.max_option_premium_notional", 1000.0))
                cap_prem = min(equity * prem_pct / 100 if equity > 0 else prem_abs, prem_abs)
                if notional > cap_prem:
                    warns.append(f"premium ${notional:,.0f} exceeds the option caps "
                                 f"({prem_pct:g}% of equity / ${prem_abs:,.0f})")
        except Exception:                                # advisory only
            log.debug("proposal preflight cap check failed", exc_info=True)

        ttl_min = int(eng.settings.get("signals.default_ttl_minutes", 30))
        row = Proposal(
            id=new_id(),
            signal_id=signal_row.id,
            portfolio_id=pid,
            symbol=symbol,
            sec_type=sec_type,
            side=side,
            qty=float(qty),
            order_type="LMT",
            limit_price=limit,
            bracket=bracket,
            rationale=sig.thesis_summary,
            context={
                "techniqueId": "tip",
                "sourceName": signal_row.source_name,
                "confidence": sig.confidence,
                "verification": verification,
                "sizing": {"budget": round(budget, 2), "refPrice": limit, "qty": qty},
                "signalPrices": {"entry": sig.entry_price, "target": sig.target_price,
                                 "stop": sig.stop_price},
                "vehicle": vehicle,
                "explain": explain,
                "exitPlan": exit_plan,
                "analystRunId": analyst.get("runId"),
                "analyst": ({k: analyst.get(k) for k in
                             ("verdict", "rationale", "invalidation", "confidence")}
                            if analyst else None),
                **({"riskWarning": "; ".join(warns)} if warns else {}),
            },
            expires_at=_ttl_expiry(ttl_min),
        )
        async with eng.sf() as session:
            session.add(row)
            sig_db = await session.get(Signal, signal_row.id)
            if sig_db is not None:
                sig_db.status = "proposed"
            await session.commit()
        pdict = proposal_dict(row)
        await eng.journal.append(ev.PROPOSAL_CREATED, pdict,
                                 aggregate_type="proposal", aggregate_id=row.id,
                                 portfolio_id=pid)
        eng.bus.publish(topics.PROPOSALS, pdict)
        return pdict

    # ------------------------------------------------------------- decide
    async def approve(self, proposal_id: str, *, via: str = "app",
                      half: bool = False) -> dict:
        eng = self.engine
        async with eng.sf() as session:
            row = await session.get(Proposal, proposal_id)
            if row is None:
                raise ValueError("unknown proposal")
            if row.status != "pending":
                raise ValueError(f"proposal is {row.status}, not pending")
            if row.expires_at and row.expires_at < dt.datetime.now(dt.timezone.utc):
                row.status = "expired"
                await session.commit()
                raise ValueError("proposal has expired")
            qty = max(1.0, row.qty / 2 if half else row.qty)
            row.status = "approved"
            row.decided_at = dt.datetime.now(dt.timezone.utc)
            row.decided_via = via
            await session.commit()
            pdict = proposal_dict(row)

        await eng.journal.append(
            ev.PROPOSAL_APPROVED, {"via": via, "half": half, "qty": qty},
            aggregate_type="proposal", aggregate_id=proposal_id,
            portfolio_id=pdict["portfolioId"])

        # defined-risk spread approval (ARM-PLAN P5): leg-sequenced open, not a
        # single OrderIntent — risk stays defined at every instant
        if pdict["secType"] == "SPREAD":
            from ..techniques.tip.lifecycle import open_spread
            v = (pdict.get("context") or {}).get("vehicle") or {}
            try:
                pos = await open_spread(
                    eng, portfolio_id=pdict["portfolioId"],
                    underlying=str(v.get("underlying") or pdict["symbol"]),
                    direction=str(v.get("direction") or "long"),
                    legs=list(v.get("legs") or []), qty=int(qty),
                    exit_plan=(pdict.get("context") or {}).get("exitPlan"),
                    source=(pdict.get("context") or {}).get("sourceName") or "unknown",
                    analyst_run_id=(pdict.get("context") or {}).get("analystRunId"),
                    signal_id=pdict.get("signalId"))
                new_status, pos_id = "executed", pos.get("id")
            except Exception as exc:
                log.warning("spread open failed for proposal %s: %s", proposal_id, exc)
                new_status, pos_id = "failed", None
            async with eng.sf() as session:
                row = await session.get(Proposal, proposal_id)
                row.status = new_status
                row.order_id = pos_id
                await session.commit()
                pdict = proposal_dict(row)
            eng.bus.publish(topics.PROPOSALS, pdict)
            return {"proposal": pdict, "order": None}

        bracket = None
        if pdict["bracket"]:
            bracket = BracketSpec(**{k: v for k, v in {
                "take_profit": pdict["bracket"].get("take_profit"),
                "stop_loss": pdict["bracket"].get("stop_loss"),
                "take_profit_pct": pdict["bracket"].get("take_profit_pct"),
                "stop_loss_pct": pdict["bracket"].get("stop_loss_pct"),
            }.items() if v is not None})
        # re-price an aged limit at approval time (2026-09-01: a 2h-old $23.80
        # limit vs a live $11.82 mid tripped the price collar and failed the
        # user's own click). The never-chase rule from creation applies again:
        # the live ask may only IMPROVE the limit, never raise it.
        limit = pdict["limitPrice"]
        if (pdict["side"] == "BUY" and pdict["orderType"] == "LMT" and limit):
            if pdict["secType"] == "OPT":
                ask = await _live_ask(eng, pdict["symbol"])
            else:
                q = eng.quotes.get(pdict["symbol"])
                ask = float(q.ask) if q is not None and q.ask and q.ask > 0 else None
            if ask and ask < float(limit):
                log.info("proposal %s: limit improved %s -> %s (live ask)",
                         proposal_id, limit, round(ask, 2))
                limit = round(ask, 2)
        intent = OrderIntent(
            portfolio_id=pdict["portfolioId"], symbol=pdict["symbol"],
            sec_type=pdict["secType"], side=pdict["side"], qty=qty,
            order_type=pdict["orderType"], limit_price=limit,
            bracket=bracket, source="signal",
            signal_id=pdict["signalId"], proposal_id=proposal_id)
        order = await eng.orders.place(intent)

        status = "executed" if order.get("status") not in ("REJECTED_RISK", "REJECTED") else "failed"
        async with eng.sf() as session:
            row = await session.get(Proposal, proposal_id)
            row.status = status
            row.order_id = order.get("id")
            await session.commit()
            pdict = proposal_dict(row)
        eng.bus.publish(topics.PROPOSALS, pdict)
        # If this came from an armed technique plan, hand the position to the armer
        # so its exits (stop / ladder / flatten) are managed like an auto trade.
        tech = (pdict.get("context") or {}).get("technique") or {}
        run_id = tech.get("runId")
        if status == "executed" and run_id and getattr(eng, "technique", None) is not None:
            with contextlib.suppress(Exception):
                await eng.technique.armer.adopt_order(
                    run_id, key=f"proposal:{proposal_id[:8]}", underlying=tech.get("underlying") or {},
                    order=order, instrument=("options" if pdict.get("secType") == "OPT" else "shares"),
                    order_symbol=(pdict.get("symbol") if pdict.get("secType") == "OPT" else None),
                    multiplier=(100.0 if pdict.get("secType") == "OPT" else 1.0))
        # A tip proposal: once the order fills, the position is handed to the
        # durable manager under the analyst's exit plan (ANALYST.md §5).
        elif status == "executed" and (pdict.get("context") or {}).get("techniqueId") == "tip":
            from ..techniques.tip.lifecycle import adopt_when_filled
            task = asyncio.create_task(adopt_when_filled(eng, pdict, order),
                                       name=f"tip-adopt-{proposal_id[:8]}")
            self._adopt_tasks[proposal_id] = task
            task.add_done_callback(lambda _t, k=proposal_id: self._adopt_tasks.pop(k, None))
        return {"proposal": pdict, "order": order}

    async def reject(self, proposal_id: str, *, via: str = "app") -> dict:
        eng = self.engine
        async with eng.sf() as session:
            row = await session.get(Proposal, proposal_id)
            if row is None:
                raise ValueError("unknown proposal")
            if row.status != "pending":
                raise ValueError(f"proposal is {row.status}, not pending")
            row.status = "rejected"
            row.decided_at = dt.datetime.now(dt.timezone.utc)
            row.decided_via = via
            await session.commit()
            pdict = proposal_dict(row)
        await eng.journal.append(ev.PROPOSAL_REJECTED, {"via": via},
                                 aggregate_type="proposal", aggregate_id=proposal_id)
        eng.bus.publish(topics.PROPOSALS, pdict)
        return pdict

    # ------------------------------------------------------------- queries
    async def list_pending(self) -> list[dict]:
        async with self.engine.sf() as session:
            rows = (await session.execute(
                select(Proposal).where(Proposal.status == "pending")
                .order_by(Proposal.created_at.desc()))).scalars().all()
        return [proposal_dict(r) for r in rows]

    async def list_all(self, limit: int = 100) -> list[dict]:
        """Decided proposals are hydrated with WHERE THEY WENT (`outcome`): the
        order's fill state and, when the fill was adopted, the managed position —
        so the history answers "I approved it; what happened?" on the card."""
        async with self.engine.sf() as session:
            rows = (await session.execute(
                select(Proposal).order_by(Proposal.created_at.desc()).limit(limit)
            )).scalars().all()
            dicts = [proposal_dict(r) for r in rows]
            order_ids = {d["orderId"] for d in dicts if d.get("orderId")}
            if order_ids:
                orders = {o.id: o for o in (await session.execute(
                    select(Order).where(Order.id.in_(order_ids)))).scalars()}
                pos_rows = (await session.execute(
                    select(ManagedPositionRow)
                    .order_by(ManagedPositionRow.created_at.desc())
                    .limit(300))).scalars().all()
                pos_by_id = {p.id: p for p in pos_rows}
                by_entry_order: dict[str, ManagedPositionRow] = {}
                for p in pos_rows:
                    for leg in (p.legs or []):
                        oid = (leg or {}).get("entryOrderId")
                        if oid:
                            by_entry_order.setdefault(str(oid), p)
                for d in dicts:
                    oid = d.get("orderId")
                    if not oid:
                        continue
                    out: dict = {}
                    if d["secType"] == "SPREAD":
                        pos = pos_by_id.get(oid)      # spread approve stores the position id
                        if pos is not None:
                            out = {"positionId": pos.id, "positionStatus": pos.status}
                    else:
                        o = orders.get(oid)
                        if o is not None:
                            out = {"orderStatus": o.status, "filledQty": o.filled_qty,
                                   "avgFillPrice": o.avg_fill_price,
                                   **({"rejectReason": o.reject_reason}
                                      if o.reject_reason else {})}
                        pos = by_entry_order.get(oid)
                        if pos is not None:
                            out.update({"positionId": pos.id, "positionStatus": pos.status})
                    if out:
                        d["outcome"] = out
        return dicts

    # ------------------------------------------------------------- expiry
    def start(self) -> None:
        self._task = asyncio.create_task(self._expiry_loop(), name="proposal-expiry")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        for t in list(self._adopt_tasks.values()):
            t.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t
        self._adopt_tasks.clear()

    async def expire_due(self) -> int:
        eng = self.engine
        now = dt.datetime.now(dt.timezone.utc)
        expired: list[dict] = []
        async with eng.sf() as session:
            rows = (await session.execute(
                select(Proposal).where(Proposal.status == "pending",
                                       Proposal.expires_at < now))).scalars().all()
            for row in rows:
                row.status = "expired"
                row.decided_at = now
                expired.append(proposal_dict(row))
            await session.commit()
        for pdict in expired:
            await eng.journal.append(ev.PROPOSAL_EXPIRED, {"reason": "ttl"},
                                     aggregate_type="proposal", aggregate_id=pdict["id"])
            eng.bus.publish(topics.PROPOSALS, pdict)
        return len(expired)

    async def expire_for_followup(self, *, source: str, ticker: str, reason: str) -> int:
        """A verified source follow-up ("sold", "I'm out") kills the still-pending
        proposals it invalidates (ARM-GAPS D4) — with the reason on the card,
        before a human (or auto mode) can approve a reversed idea."""
        eng = self.engine
        now = dt.datetime.now(dt.timezone.utc)
        expired: list[dict] = []
        async with eng.sf() as session:
            rows = (await session.execute(
                select(Proposal).join(Signal, Proposal.signal_id == Signal.id)
                .where(Proposal.status == "pending",
                       Signal.source_name == source,
                       Signal.ticker == ticker.upper()))).scalars().all()
            for row in rows:
                row.status = "expired"
                row.decided_at = now
                row.context = {**(row.context or {}), "expiredReason": reason}
                expired.append(proposal_dict(row))
            await session.commit()
        for pdict in expired:
            await eng.journal.append(ev.PROPOSAL_EXPIRED,
                                     {"reason": reason, "source": source, "ticker": ticker},
                                     aggregate_type="proposal", aggregate_id=pdict["id"])
            eng.bus.publish(topics.PROPOSALS, pdict)
        if expired:
            log.info("expired %d pending proposal(s) on %s follow-up (%s)",
                     len(expired), ticker, reason)
        return len(expired)

    async def _expiry_loop(self) -> None:
        while True:
            await asyncio.sleep(20)
            try:
                await self.expire_due()
            except Exception:  # pragma: no cover
                log.exception("proposal expiry failed")
