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

def share_substitution_ok(*, sec_type, risk_plan, settings, portfolio_kind, verdict, direction, lotto, alt) -> bool:
    """Pure (P-E): may an unfittable option TAKE become its equal-risk share alternative? Practice only (never a live
    book), analyst take, long, not a lotto, the option refused ONLY for size, an available alternative, knob on."""
    try:
        on = bool(settings.get("techniques.tip.shares_alternative_auto", False))
    except Exception:
        on = False
    return bool(on and sec_type == "OPT" and risk_plan is not None and getattr(risk_plan, "enforced", False)
                and "no quantity" in str(getattr(risk_plan, "reviewRequired", "") or "")
                and portfolio_kind not in ("live", "paper") and verdict == "take" and direction != "short"
                and not lotto and (alt or {}).get("available"))


def card_alert_text(p: dict, *, public_url=None) -> tuple[str, str]:
    """Pure: the one-line alert for a card that waits for a human, and the deep link."""
    ctx = p.get("context") or {}
    src = ctx.get("sourceName") or "?"
    why = ctx.get("reviewRequired") or "approval needed"
    alt = (ctx.get("riskPlan") or {}).get("sharesAlternative") or {}
    exp = str(p.get("expiresAt") or "")
    exp_hm = exp[11:16] + " UTC" if len(exp) >= 16 else "?"
    bits = [f"{p.get('side', 'BUY')} {p.get('qty'):g} {p.get('symbol')}" if isinstance(p.get("qty"), (int, float))
            else f"{p.get('symbol')}", f"from {src}", f"- {why}"]
    if alt.get("available"):
        bits.append(f"(share alternative: {alt.get('qty')} sh, stop {alt.get('stop')})")
    bits.append(f"expires {exp_hm}")
    return " ".join(bits), "/inbox"


def _event_context(eng) -> dict | None:
    """TMR-01: the verified macro-event label stamped on a card at creation (advisory)."""
    try:
        from ..techniques.tip import events as _evc
        c = _evc.context_for(eng)
        return {k: c.get(k) for k in ("version", "session", "status", "coverage", "label", "events", "nextEvent", "asOf")}
    except Exception:                                   # noqa: BLE001
        return None


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


def _contract_metadata(vehicle: dict | None, symbol: str | None) -> dict:
    """S21-01: strike / expiry / type / DTE for the payoff, from the vehicle when it carries them, else DECODED from
    the OCC symbol (never guessed). `source` says which. Missing stays missing."""
    v = dict(vehicle or {})
    out: dict = {"source": None, "strike": None, "expiry": None, "optionType": None, "dte": None}
    try:
        if v.get("strike") is not None and v.get("expiry"):
            out.update(source="vehicle", strike=float(v["strike"]), expiry=str(v["expiry"]),
                       optionType=(v.get("optionType") if v.get("optionType") in ("call", "put") else None))
        else:
            from ..options import occ as _occ
            o = _occ.parse(symbol)
            if o is not None:
                out.update(source="occ", strike=float(o.strike), expiry=o.expiry.isoformat(), optionType=o.option_type)
        if out["expiry"]:
            import datetime as _dt
            today = _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=-4))).date()
            out["dte"] = (_dt.date.fromisoformat(out["expiry"]) - today).days
        if out["optionType"] is None and v.get("optionType") in ("call", "put"):
            out["optionType"] = v["optionType"]
    except Exception:                                   # noqa: BLE001 - metadata is evidence, never a crash
        pass
    return out



class ProposalService:
    def __init__(self, engine) -> None:
        self.engine = engine
        self._task: asyncio.Task | None = None
        self._adopt_tasks: dict[str, asyncio.Task] = {}   # proposalId -> adopt-on-fill waiter
        self._entry_studies: set[asyncio.Task] = set()    # journal-only NBBO samplers (P3)

    def _cap_contracts(self, qty: int) -> int:
        """Safety net on option quantity: budget sizing on lotto premium is
        nonsense (277 × a $0.09 call, 2026-08-31) — a cheap contract is cheap
        because it is unlikely, not an invitation to buy hundreds. Caps stated
        analyst/tip counts too."""
        cap = int(self.engine.settings.get("techniques.tip.max_contracts_per_tip", 25) or 0)
        return min(qty, cap) if cap > 0 else qty

    async def _book_exposure(self, pid: str, underlying: str | None) -> tuple[float, float]:
        """ADV-06: cost basis ($) of every OPEN managed tip position in this book, and of those on `underlying`
        (an option leg counts under its OCC root)."""
        from ..options import occ as _occ
        total = name = 0.0
        u = str(underlying or "").upper()
        async with self.engine.sf() as session:
            rows = (await session.execute(select(ManagedPositionRow).where(
                ManagedPositionRow.technique == "tip", ManagedPositionRow.portfolio_id == pid,
                ManagedPositionRow.status.in_(("open", "attention"))))).scalars().all()
        for r in rows:
            for leg in (r.legs or []):
                c = abs(float(leg.get("avgFill") or 0) * float(leg.get("qty") or 0) * float(leg.get("multiplier") or 1.0))
                total += c
                sym = str(leg.get("symbol") or r.symbol or "").upper()
                o = _occ.parse(sym)
                if u and (o.underlying if o else sym) == u:
                    name += c
        return total, name

    @staticmethod
    def exposure_refusal(*, equity: float | None, total_cost: float, name_cost: float, book_pct: float, name_pct: float,
                         underlying: str | None) -> str | None:
        """ADV-06 (pure): refuse a NEW entry when the book's open tip cost basis, or this name's, is already at its cap
        (% of equity). 0 = no cap. Exits and management are never touched - only new entries are refused."""
        if not equity or equity <= 0:
            return None
        if book_pct > 0 and total_cost >= equity * book_pct / 100.0:
            return (f"book exposure cap: open tip positions cost ${total_cost:,.0f} = {total_cost / equity * 100:.0f}% of "
                    f"${equity:,.0f} equity (max {book_pct:g}%)")
        if name_pct > 0 and underlying and name_cost >= equity * name_pct / 100.0:
            return (f"name exposure cap: {underlying} already costs ${name_cost:,.0f} = {name_cost / equity * 100:.0f}% of "
                    f"equity (max {name_pct:g}%)")
        return None

    async def _tip_budget(self, policy, pid: str, underlying: str | None = None) -> tuple[float, str | None, str | None]:
        """Reserve-aware per-tip budget (user decision 2026-09-07: ambitious
        early, never lose a late tip to a full book). budget =
        min(policy.budget_per_tip, free_cash / reserve_slots) — the desk always
        keeps room for ~reserve_slots more ideas: full size while cash is
        plentiful, gliding down as the book fills, then a minimum expression
        (min_budget) while any cash lasts; only a truly empty book refuses.
        Also makes two per-source knobs REAL that were parsed and enforced
        nowhere: max_open_tips refuses a source's N+1th concurrent open tip,
        budget_open_max shrinks the budget to the source's remaining open
        allowance (cost basis of its open managed positions).
        Returns (budget, sizedNote, refuseReason) — budget 0 means no proposal."""
        eng = self.engine
        base = float(policy.budget_per_tip)
        pf = eng.positions.portfolio(pid) or {}
        if pf.get("kind") == "shadow":
            return base, None, None                    # research books: never gated
        note = None
        budget = base
        slots = int(eng.settings.get("techniques.tip.reserve_slots", 3) or 0)
        if slots > 0:
            cash = max(0.0, float(pf.get("cash") or 0.0))
            if cash < 50.0:
                return 0.0, None, f"book full: ${cash:,.0f} free cash in {pf.get('name', pid)}"
            glide = cash / slots
            if glide < budget:
                floor = float(eng.settings.get("techniques.tip.min_budget", 500.0))
                budget = max(glide, min(floor, cash))
                note = (f"Sized for the reserve: ${cash:,.0f} free cash across "
                        f"{slots} slots → ${budget:,.0f} budget (full is ${base:,.0f}).")
        # ADV-06 (2026-09-23): book-level concentration caps (0 = off; defaults off)
        _bp = float(eng.settings.get("techniques.tip.max_book_exposure_pct", 0) or 0)
        _np = float(eng.settings.get("techniques.tip.max_name_exposure_pct", 0) or 0)
        if _bp > 0 or _np > 0:
            with contextlib.suppress(Exception):
                _eq = float(await eng.positions.equity(pid) or 0)
                _tot, _nm = await self._book_exposure(pid, underlying)
                _why = self.exposure_refusal(equity=_eq, total_cost=_tot, name_cost=_nm, book_pct=_bp, name_pct=_np,
                                             underlying=underlying)
                if _why:
                    return 0.0, None, _why
        n_open, open_cost = await self._source_open(pid, policy.name)
        if int(policy.max_open_tips or 0) > 0 and n_open >= int(policy.max_open_tips):
            return 0.0, None, (f"source cap: {policy.name} already has {n_open} open tips "
                               f"(max_open_tips {policy.max_open_tips})")
        cap_open = float(policy.budget_open_max or 0)
        if cap_open > 0:
            room = cap_open - open_cost
            if room < 50.0:
                return 0.0, None, (f"source budget spent: ${open_cost:,.0f} of "
                                   f"${cap_open:,.0f} already open for {policy.name} "
                                   f"(budget_open_max)")
            if room < budget:
                budget = room
                note = ((note + " ") if note else "") + \
                    f"Capped to {policy.name}'s remaining open budget ${room:,.0f}."
        return budget, note, None

    async def _source_open(self, pid: str, source: str) -> tuple[int, float]:
        """(count, cost basis $) of the source's OPEN managed tip positions in
        this book — what budget_open_max / max_open_tips are judged against."""
        n, cost = 0, 0.0
        async with self.engine.sf() as session:
            rows = (await session.execute(select(ManagedPositionRow).where(
                ManagedPositionRow.technique == "tip",
                ManagedPositionRow.portfolio_id == pid,
                ManagedPositionRow.status.in_(("open", "attention"))))).scalars().all()
        for r in rows:
            if f"source:{source}" not in (r.tags or []):
                continue
            n += 1
            for leg in (r.legs or []):
                cost += abs(float(leg.get("avgFill") or 0) * float(leg.get("qty") or 0)
                            * float(leg.get("multiplier") or 1.0))
        return n, cost

    async def _refuse(self, *, signal_id: str | None, reason: str,
                      run_id: str | None = None) -> None:
        """A tip that minted no proposal because the book/source is full — on
        the record, never silent (the analyst's trail must show WHY)."""
        log.warning("no proposal: %s", reason)
        with contextlib.suppress(Exception):
            await self.engine.journal.append(
                ev.TIP_LANE_DECIDED,
                {"signalId": signal_id, "lane": "refused", "reason": reason,
                 **({"runId": run_id} if run_id else {})},
                aggregate_type="signal", aggregate_id=signal_id or run_id or "tip")

    def _cap_premium(self, qty: int, limit: float) -> int:
        """Per-tip premium concentration cap (BBAI 2026-09-04: 25 x $0.51 =
        $1,275 on one tip made a single loser the whole day). Caps the option
        premium a tip may spend — including analyst/tip stated counts — but a
        single contract always fits (the minimum expression of a take)."""
        cap = float(self.engine.settings.get("techniques.tip.max_premium_per_tip", 750.0) or 0)
        if cap > 0 and limit > 0:
            return min(qty, max(1, int(cap // (limit * 100))))
        return qty

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
        budget, glide_note, refuse = await self._tip_budget(policy, portfolio_id, underlying=signal_row.ticker)
        if refuse:
            await self._refuse(signal_id=signal_row.id, reason=refuse, run_id=run_id)
            return None
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
            qty = self._cap_premium(
                self._cap_contracts(int(contracts or 0) or max(1, math.floor(budget / (limit * 100)))),
                limit)
            symbol, sec_type = occ, "OPT"
            label = contract.get("display") or occ
            from ..options import occ as _occ_mod
            vehicle = {"kind": "option", "display": label, "underlying": signal_row.ticker,
                       "optionType": contract.get("optionType"), "pickedBy": "armed_fire",
                       "multiplier": _occ_mod.contract_multiplier(occ),   # None = adjusted/unknown -> review-gated
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
        # GEOMETRY rev 2: the armed-fire producer runs the same gate as the tip-time card
        arm_plan = exit_plan or {"targets": list(targets or []), "underlyingStop": stop}
        arm_plan, qty, arm_risk, gnote = await self._pre_entry_geometry(
            underlying=signal_row.ticker, direction=direction, pid=portfolio_id,
            exit_plan=arm_plan, vehicle=vehicle, sec_type=sec_type, symbol=symbol,
            limit=limit, qty=qty, entry_hint=entry, source=signal_row.source_name,
            signal_id=signal_row.id, analyst_run_id=analyst_run_id, entry_path="arm")
        if gnote:
            explain += " " + gnote
        if arm_risk is not None and arm_risk.enforced:
            exit_plan = arm_plan
            if sec_type == "STK":
                bracket = self._bracket_from_plan(arm_plan, fallback_target=(targets[0] if targets else None))
        ttl_min = int(eng.settings.get("signals.default_ttl_minutes", 30))
        row = Proposal(
            id=new_id(), signal_id=signal_row.id, portfolio_id=portfolio_id,
            symbol=symbol, sec_type=sec_type, side="BUY", qty=float(qty),
            order_type="LMT", limit_price=limit, bracket=bracket,
            rationale=signal_row.thesis_summary,
            context={"techniqueId": "tip", "sourceName": signal_row.source_name,
                     "armedRunId": run_id, "triggerId": trigger_id,
                     **({"riskPlan": arm_risk.to_dict()} if arm_risk else {}),
                     **({"reviewRequired": arm_risk.reviewRequired}
                        if (arm_risk and arm_risk.enforced and arm_risk.reviewRequired) else {}),
                     "vehicle": vehicle,
                     "explain": explain + ((" " + glide_note) if glide_note else ""),
                     **({"sizing": {"budget": round(budget, 2), "glide": glide_note}}
                        if glide_note else {}),
                     "signalPrices": {"entry": entry, "stop": stop,
                                      "target": (targets[0] if targets else None)},
                     **({"exitPlan": exit_plan} if exit_plan else {}),
                     **({"analystRunId": analyst_run_id} if analyst_run_id else {}),
                     "eventContext": _event_context(eng)},
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
        # tip proposals fill in the tips lane's own Practice book (2026-09-08), app default as fallback
        pid = str(eng.settings.get("techniques.tip.default_portfolio", "") or eng.settings.get("trading.default_portfolio", ""))
        if not pid or eng.positions.portfolio(pid) is None:
            portfolios = [p for p in eng.positions.portfolios() if p["kind"] == "sim"]
            if not portfolios:
                log.warning("no portfolio available for proposal")
                return None
            pid = portfolios[0]["id"]
        pf = eng.positions.portfolio(pid) or {}
        policy = resolve_policy(eng.settings, signal_row.source_name)
        budget, glide_note, refuse = await self._tip_budget(policy, pid, underlying=signal_row.ticker)
        if refuse:
            await self._refuse(signal_id=signal_row.id, reason=refuse)
            return None
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
                                        "maxLossPerSpread": round(max_loss * 100, 2),
                                        **({"glide": glide_note} if glide_note else {})},
                             "vehicle": {"kind": "spread", "display": disp,
                                         "underlying": sig.ticker.upper(),
                                         "direction": sig.direction,
                                         "legs": pick["legs"], "net": net,
                                         "width": width, "credit": bool(net < 0),
                                         "expiry": pick["expiry"]},
                             "explain": explain,
                             **self._spread_gate_context(pid),
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
            qty = self._cap_premium(
                self._cap_contracts(int(qty_hint or 0) or max(1, math.floor(budget / (limit * 100)))),
                limit)
            from ..options import occ as occ_mod
            parsed = occ_mod.parse(occ)
            opt_type = parsed.option_type if parsed else ("put" if sig.direction == "short" else "call")
            label = label or (occ_mod.display(occ) if parsed else occ)
            vehicle = {"kind": "option", "display": label, "underlying": sig.ticker.upper(),
                       "optionType": opt_type, "pickedBy": picked_by,
                       "multiplier": occ_mod.contract_multiplier(occ),   # None = adjusted/unknown -> review-gated
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
            # a proposal must FIT the caps it will be judged by (2026-09-03: the
            # $5,000/tip budget sized FSLR to 54.7% of a $9.1k practice book, the
            # card said "passes the risk gate", and the user's own click was
            # risk-rejected). Cap the shares to max_position_pct with 3% headroom
            # for equity drift between the card and the click.
            sized_note = ""
            try:
                equity = await eng.positions.equity(pid)
                cap_pct = float(eng.settings.get("risk.max_position_pct", 50.0))
                held = abs(eng.positions.position_qty(pid, sig.ticker.upper(), "STK")) * limit
                room = max(0.0, equity * cap_pct / 100.0 * 0.97 - held)
                if equity > 0 and limit * qty > room:
                    fit = int(room // limit)
                    if fit < 1:
                        log.warning("tip %s: no room under risk.max_position_pct "
                                    "(%.0f%% of $%.0f equity) — no proposal",
                                    signal_row.id, cap_pct, equity)
                        return None
                    sized_note = (f" Sized down {qty} → {fit} sh to fit the {cap_pct:g}% "
                                  f"position cap on ${equity:,.0f} equity.")
                    qty = fit
            except Exception:                            # sizing guard is advisory
                log.debug("share-fit sizing failed", exc_info=True)
            vehicle = {"kind": "shares"}
            if sig.target_price or sig.stop_price:
                bracket = {"take_profit": sig.target_price, "stop_loss": sig.stop_price,
                           "take_profit_pct": None, "stop_loss_pct": None}
            explain = (f"Approve = buy {qty} share{'s' if qty != 1 else ''} of {symbol} at a "
                       f"${limit:.2f} limit ≈ ${limit * qty:,.0f} in “{pf.get('name', pid)}” "
                       f"({pf.get('kind', '?')})"
                       + (", with the tip's target/stop attached as a bracket"
                          if bracket else "")
                       + "." + sized_note)

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

        # ---- GEOMETRY rev 2 (2026-09-14): finalize the geometry and size against the
        # risk budget BEFORE capital commits — shadow journals what would happen,
        # enforce applies it (a review-gated card never auto-approves)
        risk_plan = None
        exit_plan, qty, risk_plan, gnote = await self._pre_entry_geometry(
            underlying=sig.ticker.upper(), direction=sig.direction, pid=pid,
            exit_plan=exit_plan, vehicle=vehicle, sec_type=sec_type, symbol=symbol,
            limit=limit, qty=qty, entry_hint=sig.entry_price, source=signal_row.source_name,
            signal_id=signal_row.id, analyst_run_id=analyst.get("runId"))
        if gnote:
            explain += " " + gnote
        # ---- P-E (2026-09-23, user decision): on a PRACTICE book an analyst TAKE whose option cannot be sized
        # within the risk budget becomes the equal-risk SHARE proposal at the same stop, instead of a card that
        # expires waiting for a human (HOOD, GOOGL). Long ideas only; never a lotto; never a live book.
        alt = (getattr(risk_plan, "sharesAlternative", None) or {}) if risk_plan is not None else {}
        if share_substitution_ok(sec_type=sec_type, risk_plan=risk_plan, settings=eng.settings,
                                 portfolio_kind=pf.get("kind"), verdict=analyst.get("verdict"),
                                 direction=sig.direction, lotto=lotto, alt=alt):
            under = sig.ticker.upper()
            await eng.ensure_symbol(under)
            uq = eng.quotes.get(under)
            ref = (uq.ask if uq and uq.ask and uq.ask > 0 else None) or alt.get("entryRef")
            if ref:
                orig = symbol
                symbol, sec_type, side = under, "STK", "BUY"
                limit, qty = round(float(ref), 2), int(alt["qty"])
                vehicle = {"kind": "shares", "substitutedFor": orig,
                           "why": "the option could not be sized within the risk budget (P-E, Practice only)"}
                exit_plan = {**exit_plan, "underlyingStop": alt.get("stop"), "premiumStopPct": None}
                exit_plan, qty, risk_plan, gnote2 = await self._pre_entry_geometry(
                    underlying=under, direction=sig.direction, pid=pid, exit_plan=exit_plan, vehicle=vehicle,
                    sec_type=sec_type, symbol=symbol, limit=limit, qty=qty, entry_hint=sig.entry_price,
                    source=signal_row.source_name, signal_id=signal_row.id, analyst_run_id=analyst.get("runId"))
                explain = (f"Approve = buy {qty} share{'s' if qty != 1 else ''} of {symbol} at a ${limit:.2f} limit "
                           f"~ ${limit * qty:,.0f} in “{pf.get('name', pid)}” ({pf.get('kind', '?')}) - the "
                           f"equal-risk SHARE alternative to {orig}, whose option could not be sized within the risk "
                           f"budget. Stop {exit_plan.get('underlyingStop')}." + ((" " + gnote2) if gnote2 else ""))
                with contextlib.suppress(Exception):
                    await eng.journal.append("TipSharesSubstituted", {
                        "signalId": signal_row.id, "option": orig, "symbol": symbol, "qty": qty, "limit": limit,
                        "stop": exit_plan.get("underlyingStop"), "portfolioId": pid},
                        aggregate_type="signal", aggregate_id=signal_row.id, portfolio_id=pid)
        if risk_plan is not None and risk_plan.enforced and sec_type == "STK":
            # G91-02: every protection is built from the SAME final plan — the
            # bracket carries the finalized stop, never the signal's original
            bracket = self._bracket_from_plan(exit_plan, fallback_target=sig.target_price)

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
            cap_pct = float(eng.settings.get("risk.max_position_pct", 50.0))
            if equity > 0 and notional > equity * cap_pct / 100.0:
                warns.append(f"${notional:,.0f} is {notional / equity * 100:.0f}% of the book's "
                             f"${equity:,.0f} equity (cap {cap_pct:g}%) — approval would be risk-rejected")
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
        # a newer tip for the SAME contract replaces the one still waiting —
        # the re-arm rule, applied to proposals (2026-09-03: muggzone re-posted
        # his MU 995C re-entry and TWO cards sat pending; approving both would
        # have doubled the position). The superseded card expires now, journaled.
        superseded: list[str] = []
        async with eng.sf() as session:
            from sqlalchemy import select as _select
            old = (await session.execute(_select(Proposal).where(
                Proposal.status == "pending", Proposal.portfolio_id == pid,
                Proposal.symbol == symbol, Proposal.side == side))).scalars().all()
            for o in old:
                o.status = "expired"
                o.decided_at = dt.datetime.now(dt.timezone.utc)
                o.decided_via = "superseded"
                o.context = {**(o.context or {}), "supersededBy": "a newer tip for the same contract"}
                superseded.append(o.id)
            if old:
                await session.commit()
        for oid in superseded:
            await eng.journal.append(ev.PROPOSAL_EXPIRED,
                                     {"proposalId": oid, "reason": "superseded by a newer tip "
                                      "for the same contract"},
                                     aggregate_type="proposal", aggregate_id=oid, portfolio_id=pid)
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
                "sizing": {"budget": round(budget, 2), "refPrice": limit, "qty": qty,
                           **({"glide": glide_note} if glide_note else {})},
                "signalPrices": {"entry": sig.entry_price, "target": sig.target_price,
                                 "stop": sig.stop_price},
                "vehicle": vehicle,
                "explain": explain + ((" " + glide_note) if glide_note else ""),
                "exitPlan": exit_plan,
                **({"riskPlan": risk_plan.to_dict()} if risk_plan else {}),
                **({"reviewRequired": risk_plan.reviewRequired}
                   if (risk_plan and risk_plan.enforced and risk_plan.reviewRequired) else {}),
                "analystRunId": analyst.get("runId"),
                "analyst": ({k: analyst.get(k) for k in
                             ("verdict", "rationale", "invalidation", "confidence")}
                            if analyst else None),
                **({"riskWarning": "; ".join(warns)} if warns else {}),
                "eventContext": _event_context(eng),
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
        self._start_entry_study(pdict)
        self._start_card_alert(pdict)
        return pdict

    def _start_card_alert(self, pdict: dict, *, wait_s: float | None = None) -> None:
        """P-C (2026-09-23: HOOD, GOOGL and AMAT expired unseen - a card that needs a human sent nothing). A card still
        PENDING after `techniques.tip.card_alert_wait_s` (default 20 s, so a card the analyst auto-declines stays quiet)
        sends ONE push + Telegram line: symbol, source, why it waits, the equal-risk share alternative, the expiry.
        Journaled `TipCardAlert`. Never an order; a delivery failure is logged, not raised."""
        eng = self.engine
        if not bool(eng.settings.get("techniques.tip.card_alerts", True)):
            return
        wait = float(eng.settings.get("techniques.tip.card_alert_wait_s", 20) if wait_s is None else wait_s)

        async def alert() -> None:
            try:
                await asyncio.sleep(wait)
                async with eng.sf() as session:
                    row = await session.get(Proposal, pdict["id"])
                if row is None or row.status != "pending":
                    return
                pf = eng.positions.portfolio(row.portfolio_id) or {}
                if pf.get("kind") == "shadow" or pf.get("book"):
                    return                                     # research books never page a human
                text, url = card_alert_text(proposal_dict(row), public_url=None)
                sent = {"push": False, "telegram": False}
                push = getattr(eng, "push", None)
                if push is not None:
                    with contextlib.suppress(Exception):
                        await push.send("Tips card needs you", text, url=url, tag=f"card-{row.id}")
                        sent["push"] = True
                tg = getattr(eng, "telegram", None)
                if tg is not None:
                    with contextlib.suppress(Exception):
                        from ..push import public_url
                        from .telegram import open_keyboard
                        await tg.send("🔔 " + text, open_keyboard(public_url(eng.settings), url))
                        sent["telegram"] = True
                await eng.journal.append("TipCardAlert", {"proposalId": row.id, "symbol": row.symbol, "text": text,
                                                          "sent": sent}, aggregate_type="proposal",
                                         aggregate_id=row.id, portfolio_id=row.portfolio_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("card alert failed for %s", pdict.get("id"))
        with contextlib.suppress(RuntimeError):
            asyncio.get_running_loop().create_task(alert(), name=f"tip-card-alert-{pdict['id']}")

    def _start_entry_study(self, pdict: dict) -> None:
        """PROPOSAL-TIME diagnostics, never behavior (Codex consolidated
        recommendation P3 + v0.7.44 review corrections, 2026-09-10). Honest
        semantics: these are quotes at DECISION time (proposal creation, which
        follows extraction/appraisal), not recovered alert-time history; the
        delayed sample is measured from the decision sample. Fields keep the
        source's stated premium (the signal's), the proposal limit and — later,
        from fills — execution price SEPARATE; refPrice is the proposal limit,
        never the source quote. Coverage is proposal-path only: ideas that
        never become an option proposal are NOT in this cohort — this data is
        diagnostics, not yet the all-idea study the 1.05x/delay variants need.
        Two journal rows (phase created / delayed) so a restart between them
        loses only the delayed sample, visibly."""
        eng = self.engine
        if pdict.get("secType") != "OPT":
            return
        if not bool(eng.settings.get("techniques.tip.entry_study_enabled", True)):
            return
        delay = float(eng.settings.get("techniques.tip.entry_study_delay_seconds", 180) or 180)
        sym = pdict["symbol"]

        def snap() -> dict | None:
            q = eng.quotes.get(sym)
            if q is None:
                return None
            ts = getattr(q, "source_ts", None) or getattr(q, "ts", None)
            return {"bid": q.bid, "ask": q.ask, "last": q.last,
                    "source": getattr(q, "source", None), "sourceTs": ts,
                    "delayed": bool(getattr(q, "delayed", False))}

        async def study() -> None:
            try:
                signal_premium = None
                sig_id = pdict.get("signalId")
                if sig_id:
                    with contextlib.suppress(Exception):
                        async with eng.sf() as session:
                            sig = await session.get(Signal, sig_id)
                        signal_premium = getattr(sig, "premium", None) if sig else None
                base = {"proposalId": pdict["id"], "symbol": sym,
                        "verdict": ((pdict.get("context") or {}).get("analyst") or {}).get("verdict"),
                        "signalStatedPremium": signal_premium,
                        "proposalLimit": pdict.get("limitPrice"),
                        "proposalCreatedAt": pdict.get("createdAt"),
                        "delaySeconds": delay}
                with contextlib.suppress(Exception):
                    await eng.options.refresh_now(sym)
                at_decision = snap()
                await eng.journal.append(
                    "TipEntryStudy",
                    {**base, "phase": "created", "atDecision": at_decision,
                     "sampledAt": dt.datetime.now(dt.timezone.utc).isoformat()},
                    aggregate_type="proposal", aggregate_id=pdict["id"],
                    portfolio_id=pdict.get("portfolioId"))
                await asyncio.sleep(delay)
                with contextlib.suppress(Exception):
                    await eng.options.refresh_now(sym)
                later = snap()
                await eng.journal.append(
                    "TipEntryStudy",
                    {**base, "phase": "delayed", "atDecision": at_decision,
                     "afterDelay": later,
                     "sampledAt": dt.datetime.now(dt.timezone.utc).isoformat()},
                    aggregate_type="proposal", aggregate_id=pdict["id"],
                    portfolio_id=pdict.get("portfolioId"))
            except Exception:
                log.debug("entry study failed for %s", pdict.get("id"), exc_info=True)
        task = asyncio.create_task(study(), name=f"entry-study-{pdict['id'][:8]}")
        self._entry_studies.add(task)
        task.add_done_callback(self._entry_studies.discard)

    # ------------------------------------------------------------- geometry rev 2
    @staticmethod
    def _bracket_from_plan(plan: dict, *, fallback_target: float | None) -> dict | None:
        targets = [float(t) for t in (plan or {}).get("targets") or [] if t]
        stop = (plan or {}).get("underlyingStop")
        tp = targets[0] if targets else (float(fallback_target) if fallback_target else None)
        if tp is None and not stop:
            return None
        return {"take_profit": tp, "stop_loss": float(stop) if stop else None,
                "take_profit_pct": None, "stop_loss_pct": None}

    def _geometry_scope(self, pid: str) -> str | None:
        """G91-03: the gate is PRACTICE-scoped — 'enforce' | 'shadow' on a sim
        book, None everywhere else (live/paper/shadow/unknown books never see
        a computed plan; a Tips setting cannot change a live book's behaviour)."""
        from ..techniques.tip import geometry as _geo
        mode = _geo.gate_mode(self.engine.settings)
        if mode == "off":
            return None
        pf = self.engine.positions.portfolio(pid) or {}
        if pf.get("kind") != "sim":
            return None
        return mode

    def _spread_gate_context(self, pid: str) -> dict:
        """A 2-leg spread is not covered by the geometry estimator: under
        enforce on a Practice book the card is review-gated (a person decides),
        never auto-approved."""
        if self._geometry_scope(pid) == "enforce":
            return {"reviewRequired": "geometry gate does not cover spread vehicles — human decision only"}
        return {}

    async def _pre_entry_geometry(self, *, underlying: str, direction: str, pid: str,
                                  exit_plan: dict, vehicle: dict, sec_type: str, symbol: str,
                                  limit: float, qty: int, entry_hint: float | None,
                                  source: str | None, signal_id: str | None,
                                  analyst_run_id: str | None, phase: str = "pre-entry",
                                  proposal_id: str | None = None,
                                  entry_path: str = "proposal",
                                  count_failures: bool = True) -> tuple[dict, int, object | None, str]:
        """GEOMETRY-RISK-PLAN rev 2, steps 1-3 (reviewer-tightened G91-01/02/03):
        the same geometry rules the adoption gate runs — BEFORE entry — producing
        the FINAL stop; the size is derived from that stop against the approved
        risk budget B, invariant qty x unitLoss <= B on every proposal.

        - Practice scope only (`_geometry_scope`): elsewhere nothing is computed.
        - Shares are sized at the EXECUTABLE price (the BUY limit, the maximum
          admissible entry) — never at a lower last trade.
        - Options need a fresh, non-delayed underlying reference quote, a delta
          whose per-field age is inside `geometry_greeks_max_age_seconds` and
          EXPLICIT contract metadata (multiplier); anything missing or stale is
          a review-gated plan (no estimate is invented).
        - Under enforce, a failed computation is itself a review-gated plan:
          never an advisory skip that admits the trade.
        Returns (exit_plan, qty, RiskPlan | None, explain note); in shadow mode
        the plan is recorded and the caller's sizes are returned untouched."""
        from ..techniques.tip import geometry as _geo
        eng = self.engine
        mode = self._geometry_scope(pid)
        if mode is None or sec_type not in ("OPT", "STK"):
            return exit_plan, qty, None, ""
        enforce = mode == "enforce"

        def failed(reason: str):
            rp_ = _geo.RiskPlan(mode=mode, direction=direction,
                                vehicle=("option" if sec_type == "OPT" else "shares"),
                                entryRef=float(entry_hint or 0.0), qtyRequested=int(qty), qty=int(qty),
                                budgetSource="", reviewRequired=f"risk evidence unavailable: {reason}",
                                enforced=enforce, invariantOk=None)
            return exit_plan, qty, rp_, (f"Geometry gate: NO automatic entry — {rp_.reviewRequired}."
                                         if enforce else "")

        try:
            final_plan, rp = await self._compute_risk_plan(
                mode=mode, underlying=underlying, direction=direction, pid=pid, exit_plan=exit_plan,
                vehicle=vehicle, sec_type=sec_type, symbol=symbol, limit=limit, qty=qty,
                entry_hint=entry_hint)
        except Exception as exc:
            log.warning("pre-entry geometry failed for %s: %s", underlying, exc)
            out = failed(f"{type(exc).__name__}: {str(exc)[:120]}")
            if enforce:
                with contextlib.suppress(Exception):
                    await eng.journal.append(
                        ev.TIP_GEOMETRY_REPAIRED,
                        {"proposalId": proposal_id, "signalId": signal_id, "underlying": underlying,
                         "entryRef": None, "repairs": [], "phase": phase, "enforced": True, "mode": mode,
                         "entryPath": entry_path, "reviewRequired": out[2].reviewRequired,
                         "reviewClass": "evidence",
                         "analystRunId": analyst_run_id, "source": source},
                        aggregate_type="signal", aggregate_id=signal_id or underlying, portfolio_id=pid)
                if count_failures:
                    await self._note_pre_entry_failure(pid, entry_path, out[2].reviewRequired, signal_id,
                                                       review_class="evidence")
            return out
        with contextlib.suppress(Exception):
            await eng.journal.append(
                ev.TIP_GEOMETRY_REPAIRED,
                {"proposalId": proposal_id, "signalId": signal_id, "underlying": underlying,
                 "entryRef": rp.entryRef, "repairs": list(rp.repairs), "phase": phase,
                 "entryPath": entry_path,
                 "enforced": rp.enforced, "mode": mode, "plannedRisk": rp.plannedRisk,
                 "stressRisk": rp.stressRisk, "finalRisk": rp.plannedRisk,
                 "estimatorVersion": rp.estimatorVersion, "resizedFrom": rp.qtyRequested,
                 "resizedTo": rp.qty, "budget": rp.budget, "budgetSource": rp.budgetSource,
                 "reviewRequired": rp.reviewRequired, "reviewClass": rp.reviewClass,
                 "decisions": list(rp.decisions),
                 "quote": rp.quote, "greeks": {k: v for k, v in rp.greeks.items() if k != "text"},
                 "analystRunId": analyst_run_id, "source": source},
                aggregate_type="signal", aggregate_id=signal_id or underlying, portfolio_id=pid)
        note = ""
        if rp.enforced:
            if rp.reviewRequired:
                note = (f"Geometry gate: NO automatic entry — {rp.reviewRequired}. "
                        f"The card waits for you.")
                if phase == "pre-entry" and count_failures:
                    await self._note_pre_entry_failure(pid, entry_path, rp.reviewRequired, signal_id,
                                                       review_class=rp.reviewClass)
                return final_plan, qty, rp, note
            if rp.resized:
                note = f"Geometry gate: {rp.resizeReason}."
            elif rp.repairs:
                note = "Geometry gate finalized the stop before entry: " + "; ".join(rp.repairs) + "."
            return final_plan, int(rp.qty), rp, note
        if rp.resized or rp.repairs or rp.reviewRequired:
            note = ("Geometry gate (shadow): would " +
                    (f"resize {rp.qtyRequested} → {rp.qty}" if rp.resized else "repair the stop") +
                    (f"; review: {rp.reviewRequired}" if rp.reviewRequired else "") + ".")
        return exit_plan, qty, rp, note

    async def _note_pre_entry_failure(self, pid: str, entry_path: str, reason: str, ref: str | None,
                                      review_class: str | None = None) -> None:
        """KB-06 wiring: a review-gated pre-entry result is refused on its own;
        REPEATED SYSTEMIC ones (typed `reviewClass == "evidence"`) on one entry
        path in a session open an integrity incident for that path (recorded
        in every pause mode); budget / plan review gates never count."""
        with contextlib.suppress(Exception):
            from ..techniques.tip import integrity as _ig
            await _ig.record_pre_entry_failure(self.engine, portfolio_id=pid, entry_path=entry_path,
                                               reason=str(reason or "")[:160], ref=ref,
                                               review_class=review_class)

    async def _compute_risk_plan(self, *, mode: str, underlying: str, direction: str, pid: str,
                                 exit_plan: dict, vehicle: dict, sec_type: str, symbol: str,
                                 limit: float, qty: int, entry_hint: float | None):
        """The evidence-gathering half of the gate (raises on unexpected
        failure; evidence problems come back as a review-gated plan)."""
        from ..clock import now_ms as _now_ms
        from ..techniques.tip import geometry as _geo
        eng = self.engine
        s = eng.settings
        now = int(_now_ms())
        quote_meta: dict = {"limit": float(limit)}
        problems: list[tuple[str, str]] = []      # (readiness code, detail)
        q_max_age = float(s.get("techniques.tip.geometry_quote_max_age_seconds", 300.0) or 300.0)

        def _age_s(q) -> float | None:
            ts = getattr(q, "source_ts", None) or getattr(q, "ts", None)
            try:
                return max(0.0, (now - int(ts)) / 1000.0) if ts else None
            except (TypeError, ValueError):
                return None

        if sec_type == "STK":
            # G91-02: the maximum admissible entry is the BUY limit — size there
            if not limit or float(limit) <= 0:
                raise ValueError("no executable limit for a share entry")
            entry_ref = float(limit)
            quote_meta["entryRefBasis"] = "limit"
            # EOD-06: the share plan carries the SAME quote-freshness evidence the
            # incident classifier requires (source, age, delayed) — a valid fresh
            # share entry used to read as "missing evidence" after a fast loss
            sq = None
            with contextlib.suppress(Exception):
                sq = eng.quotes.get(underlying)
            if sq is not None:
                age = _age_s(sq)
                quote_meta.update({"source": getattr(sq, "source", None), "ageS": age,
                                   "delayed": bool(getattr(sq, "delayed", False)),
                                   "underlyingDelayed": bool(getattr(sq, "delayed", False))})
                if bool(getattr(sq, "delayed", False)):
                    problems.append(("quote_delayed", "share reference quote is delayed"))
                elif age is not None and age > q_max_age:
                    problems.append(("quote_stale", f"share reference quote is {age:.0f}s old (max {q_max_age:.0f}s)"))
        else:
            await eng.ensure_symbol(underlying)
            uq = eng.quotes.get(underlying)
            entry_ref = float(uq.last) if uq is not None and getattr(uq, "last", 0) and uq.last > 0 else None
            quote_meta["entryRefBasis"] = "underlying-last"
            if entry_ref is None:
                problems.append(("quote_missing", "no live underlying reference quote"))
                entry_ref = float(entry_hint) if entry_hint else 0.0
            else:
                age = _age_s(uq)
                quote_meta.update({"underlyingSource": getattr(uq, "source", None),
                                   "underlyingAgeS": age, "underlyingDelayed": bool(getattr(uq, "delayed", False))})
                if bool(getattr(uq, "delayed", False)):
                    problems.append(("quote_delayed", "underlying reference quote is delayed"))
                elif age is None:
                    problems.append(("quote_stale", "underlying reference quote age unknown"))
                elif age > q_max_age:
                    problems.append(("quote_stale", f"underlying reference quote is {age:.0f}s old (max {q_max_age:.0f}s)"))
        bars: list = []
        if type(getattr(eng, "feed", None)).__name__ != "SimQuoteFeed":
            try:
                from ..marketstructure.history import fetch_window
                bars = await fetch_window(underlying, "15m", now - 7 * 86_400_000, now)
            except Exception:
                log.debug("pre-entry geometry: no bars for %s", underlying)
        equity = None
        with contextlib.suppress(Exception):
            equity = float(await eng.positions.equity(pid) or 0) or None
        budget, budget_source = _geo.risk_budget(s, equity)
        delta = None
        greeks_meta: dict = {}
        multiplier = 1.0
        option_type = None
        currency = str((vehicle or {}).get("currency") or "USD")
        if sec_type == "OPT":
            raw_mult = (vehicle or {}).get("multiplier")
            if raw_mult is None:
                problems.append(("contract_metadata", "contract multiplier unknown (no contract metadata on the vehicle)"))
                multiplier = 0.0
            else:
                multiplier = float(raw_mult)
            option_type = (vehicle or {}).get("optionType")
            if option_type not in ("call", "put"):
                problems.append(("contract_metadata", "option type unknown"))
            snap = None
            with contextlib.suppress(Exception):
                snap = eng.options.snapshot_cached(symbol)
            g = (snap or {}).get("greeks") or {}
            g_max_age = float(s.get("techniques.tip.geometry_greeks_max_age_seconds", 900.0) or 900.0)
            if g.get("delta") is None:
                greeks_meta = {"reason": "missing delta — no estimate invented"}
            else:
                field_ts = ((snap or {}).get("greeksFieldAsOf") or {}).get("delta") or (snap or {}).get("asOf")
                try:
                    g_age = max(0.0, (now - int(field_ts)) / 1000.0) if field_ts else None
                except (TypeError, ValueError):
                    g_age = None
                greeks_meta = {"source": "live" if (snap or {}).get("greeksLive") else "chain",
                               "asOf": field_ts, "ageS": g_age}
                if g_age is None:
                    greeks_meta["reason"] = "delta age unknown — no estimate invented"
                elif g_age > g_max_age:
                    greeks_meta["reason"] = f"delta is {g_age:.0f}s old (max {g_max_age:.0f}s) — no estimate invented"
                else:
                    delta = float(g["delta"])
            oq = eng.quotes.get(symbol)
            if oq is not None:
                quote_meta.update({"source": getattr(oq, "source", None), "ageS": _age_s(oq),
                                   "delayed": bool(getattr(oq, "delayed", False))})
                if bool(getattr(oq, "delayed", False)):
                    problems.append(("quote_delayed", "contract quote is delayed"))
        final_plan, rp = _geo.plan_risk(
            mode=mode, direction=direction, vehicle=("option" if sec_type == "OPT" else "shares"),
            entry_ref=entry_ref, exit_plan=exit_plan, bars=bars, settings=s,
            limit=float(limit), qty_requested=int(qty), multiplier=multiplier,
            option_type=option_type, delta=delta, greeks_meta=greeks_meta,
            budget=budget, budget_source=budget_source, quote_meta=quote_meta, currency=currency)
        # PROF-02: the whole exit path in integer units, beside the risk numbers
        try:
            from ..techniques.tip import payoff as _po
            _targets = [float(t) for t in (final_plan.get("targets") or [])]
            _fr = [float(x) for x in (final_plan.get("fractions") or [])] or ([1.0] if _targets else [])
            _gains = _po.unit_gains(vehicle=("shares" if sec_type == "STK" else "option"), entry_ref=float(entry_ref or 0),
                                    targets=_targets, direction=direction, delta=delta, multiplier=(1.0 if sec_type == "STK" else multiplier))
            # S21-01 (2026-09-21 review): the CARD's payoff uses the same complete fee basis as execution and the
            # analyst (commission + regulatory per contract per side, `execcost.fees_from_settings`) and the verified
            # contract metadata - strike/expiry/type from the vehicle, else decoded from the OCC symbol itself - so the
            # expiration break-even and the horizon are printed instead of null. Estimator labels stay; no Greek is invented.
            from ..techniques.tip.execcost import fees_from_settings as _fees
            _fb = _fees(s)
            _fee_unit = 0.0 if sec_type == "STK" else float(_fb["feePerContract"]) + float(_fb["regPerContract"])
            _meta = _contract_metadata(vehicle, symbol) if sec_type == "OPT" else {}
            _hold = (exit_plan or {}).get("maxHoldSessions") or (final_plan or {}).get("maxHoldSessions")
            rp.payoff = _po.payoff_preview(qty=int(rp.qty or qty), fractions=_fr, gains=_gains, unit_loss=rp.unitLoss,
                                           fee_per_unit=_fee_unit, vehicle=("shares" if sec_type == "STK" else "option"),
                                           strike=_meta.get("strike"), premium=(None if sec_type == "STK" else float(limit)),
                                           option_type=_meta.get("optionType"), dte=_meta.get("dte"),
                                           hold_sessions=(int(_hold) if _hold is not None else None),
                                           expiry_date=_meta.get("expiry"))
            if sec_type == "OPT":
                rp.payoff["feeBasis"] = "options.fee_per_contract + sim.reg_fee_per_contract per contract per side (execcost basis)"
                rp.payoff["contractMetadata"] = {"source": _meta.get("source"), "strike": _meta.get("strike"),
                                                 "expiry": _meta.get("expiry"), "optionType": _meta.get("optionType")}
                # S21-03: the preview's target-price assumption is stated on the card, beside the numbers
                rp.payoff["targetExecution"] = ("scenarios assume an exit AT the target price; the live manager exits at the "
                                                "market after a closed-bar touch, so realised target exits can fall short")
        except Exception as exc:                            # noqa: BLE001 - S21-01: a payoff failure is visible, never silent
            log.warning("payoff preview failed for %s: %s", symbol, exc)
            rp.payoff = {"status": "unknown", "reason": f"payoff preview failed: {exc}"}
        # TMR-02 (2026-09-16): the instantaneous round-trip cost of the FINAL size on the
        # qualified quote - spread once, both sides' fees - a diagnostic beside the risk
        # numbers, never a gate (unknown on a stale / crossed / missing quote)
        try:
            from ..techniques.tip import execcost as _ec
            # TMR02-WIRE (2026-09-16): the EXACT symbol is the in-scope parameter; a failure of the
            # diagnostic is reported on the plan, never swallowed into an empty field
            rp.execCost = _ec.diagnose(eng, symbol=str(symbol), qty=float(rp.qty or qty),
                                       sec_type=str(sec_type), multiplier=(1.0 if sec_type == "STK" else multiplier))
        except Exception as exc:                        # noqa: BLE001 - diagnostic only, but visible
            log.warning("execution-cost diagnostic failed for %s: %s", symbol, exc)
            rp.execCost = {"status": "unknown", "symbol": str(symbol), "reasons": [f"diagnostic failed: {exc}"]}
        # ADV-07 / ADV-08 (2026-09-23): annotations on the card - never a gate, never a substitution
        with contextlib.suppress(Exception):
            if sec_type == "OPT" and str(s.get("techniques.tip.shares_alternative", "annotate") or "off") == "annotate" \
                    and (not rp.qty or (rp.reviewRequired and "no quantity" in str(rp.reviewRequired))):
                rp.sharesAlternative = _geo.shares_alternative(
                    direction=direction, entry_ref=entry_ref, final_stop=rp.finalStop, budget=rp.budget,
                    max_notional=float(s.get("techniques.tip.budget_per_tip", 0) or 0) or None)
            _fp = float(s.get("techniques.tip.friction_flag_pct", 0) or 0)
            _share = (rp.execCost or {}).get("costShareOfPurchase")
            if _fp > 0 and _share is not None and float(_share) * 100.0 >= _fp:
                rp.frictionFlag = {"roundTripSharePct": round(float(_share) * 100.0, 1), "flagPct": _fp,
                                   "note": "round-trip fees + spread at the quote exceed the configured share of the debit"}
        if problems:
            rp.evidence = [{"code": c, "detail": d} for c, d in problems]
            rp.reviewRequired = "; ".join(d for _c, d in problems) + (f"; {rp.reviewRequired}" if rp.reviewRequired else "")
            rp.reviewClass = rp.reviewClass or "evidence"
            rp.qty = int(qty)
            rp.invariantOk = None
            rp.plannedRisk = None
        return final_plan, rp

    async def _admit_geometry(self, pdict: dict, *, limit: float | None, qty: float,
                              via: str, phase: str = "submit",
                              count_failures: bool = True) -> tuple[float, dict, str | None]:
        """GEOMETRY rev 2, step 4 — final admission immediately before an entry
        order exists (reviewer-tightened G91-01/02): under enforce on a Practice
        book the WHOLE plan is recomputed at the limit that will actually be
        submitted (fresh underlying reference, Greek field age, geometry, budget)
        — not just the premium arithmetic. Returns (qty, pdict, refusal): a
        refusal means an AUTOMATED entry must not proceed (missing/stale/failed
        evidence included — never admission by absence); a human's click
        proceeds with the resized qty (the click is the review). The revalidated
        plan, final exit plan and bracket are persisted on the proposal."""
        eng = self.engine
        ctx = pdict.get("context") or {}
        if ctx.get("techniqueId") != "tip":
            return qty, pdict, None
        mode = self._geometry_scope(pdict.get("portfolioId") or "")
        if mode != "enforce":
            return qty, pdict, None
        # C95-05: the mandatory review refusal comes BEFORE any vehicle dispatch —
        # a review-only card (spread or otherwise unsupported vehicle included)
        # never reaches automatic execution through a code path the producer
        # did not anticipate
        if via == "auto" and ctx.get("reviewRequired"):
            return qty, pdict, f"geometry review required: {ctx.get('reviewRequired')}"
        if pdict.get("secType") not in ("OPT", "STK"):
            return (qty, pdict, ("geometry: vehicle not covered by the gate — automated entry refused"
                                 if via == "auto" else None))
        rp = ctx.get("riskPlan") or {}
        if via == "auto" and (not rp or not rp.get("enforced")):
            return qty, pdict, "geometry: no enforced risk plan on the proposal — automated entry refused"
        vehicle = ctx.get("vehicle") or {}
        sec_type = pdict.get("secType")
        underlying = str(vehicle.get("underlying") or pdict.get("symbol") or "").upper()
        direction = "short" if (sec_type == "OPT" and vehicle.get("optionType") == "put") else "long"
        new_limit = float(limit) if limit else float(pdict.get("limitPrice") or 0)
        final_plan, q2, rp2, _note = await self._pre_entry_geometry(
            underlying=underlying, direction=direction, pid=pdict["portfolioId"],
            exit_plan=dict(ctx.get("exitPlan") or {}), vehicle=vehicle, sec_type=sec_type,
            symbol=pdict["symbol"], limit=new_limit, qty=int(qty),
            entry_hint=(rp.get("entryRef") if rp else None), source=ctx.get("sourceName"),
            signal_id=pdict.get("signalId"), analyst_run_id=ctx.get("analystRunId"),
            phase=phase, proposal_id=pdict.get("id"), count_failures=count_failures)
        if rp2 is None:
            return (qty, pdict, "geometry: risk evidence unavailable at submission") if via == "auto" else (qty, pdict, None)
        refusal = None
        if rp2.reviewRequired:
            if via == "auto":
                refusal = f"geometry review required at submission: {rp2.reviewRequired}"
            q_final = qty                       # a person approved: their click is the review
        else:
            q_final = float(min(int(q2), int(qty)))
        new_bracket = self._bracket_from_plan(final_plan, fallback_target=None) if sec_type == "STK" and not rp2.reviewRequired else None
        with contextlib.suppress(Exception):
            async with eng.sf() as session:
                row = await session.get(Proposal, pdict["id"])
                if row is not None:
                    # a clean recomputation CLEARS a stale review flag (readiness-v1:
                    # a resolved evidence problem must not leave a permanent label)
                    kept = {k: v for k, v in (row.context or {}).items() if k != "reviewRequired"}
                    row.context = {**kept, "riskPlan": rp2.to_dict(),
                                   **({"exitPlan": final_plan} if not rp2.reviewRequired else {}),
                                   **({"reviewRequired": rp2.reviewRequired} if rp2.reviewRequired else {})}
                    if new_bracket is not None:
                        row.bracket = new_bracket
                    await session.commit()
                    pdict = proposal_dict(row)
        return q_final, pdict, refusal

    async def _refuse_automated(self, proposal_id: str, *, reason: str, revert: bool = False) -> dict:
        """An AUTOMATED entry the gate refuses — the card stays (or goes back
        to) pending with the reason on its record; journaled TipAutoPaused."""
        eng = self.engine
        async with eng.sf() as session:
            row = await session.get(Proposal, proposal_id)
            if row is None:
                return {"proposal": {"id": proposal_id}, "order": None, "refused": reason}
            if revert and row.status == "approved":
                row.status = "pending"
                row.decided_at = None
                row.decided_via = None
            ctx0 = row.context or {}
            row.context = {**ctx0, "autoGate": reason,
                           "readiness": self._readiness_from_refusal(proposal_dict(row), reason)}
            await session.commit()
            pdict = proposal_dict(row)
        await eng.journal.append(ev.TIP_AUTO_PAUSED, {"reason": reason, "proposalId": proposal_id,
                                                      **({"revertedApproval": True} if revert else {})},
                                 aggregate_type="proposal", aggregate_id=proposal_id,
                                 portfolio_id=pdict.get("portfolioId"))
        eng.bus.publish(topics.PROPOSALS, pdict)
        return {"proposal": pdict, "order": None, "refused": reason}

    # ------------------------------------------------------------- decide
    async def _maybe_retry_stale_quote(self, pdict: dict, intent: OrderIntent,
                                       order: dict, *, via: str = "") -> dict:
        """Bounded ONE-shot recovery for a pre-submission quote-staleness
        rejection (Codex consolidated recommendation 1A, 2026-09-10): the
        10:53 AAPL take died on 'quote age 10.5s (max 10s)' with no retry.

        Scope: Tips proposals on NON-LIVE books only. Fires only when the
        rejection is definitively pre-submission (REJECTED_RISK) and the ONLY
        failing gate was quote freshness. The retry refreshes the exact
        contract's quote once, keeps the never-raise limit rule (a fresh ask
        may only IMPROVE the limit — the source-price band never widens), and
        re-runs the COMPLETE risk gate on a new order. Once-only durably: the
        attempt is stamped on the proposal BEFORE the retry order exists, so
        duplicates and restarts can never chase twice. Any still-failing gate
        terminates visibly on the retry order's own record."""
        eng = self.engine
        if order.get("status") != "REJECTED_RISK":
            return order
        if via != "auto":
            return order                # AUTO entries only (Codex v0.7.44 1A-P2):
                                        # a human's click is the human's decision
        ctx = pdict.get("context") or {}
        if (ctx.get("techniqueId") or "") != "tip":
            return order
        pf = eng.positions.portfolio(pdict["portfolioId"]) or {}
        if pf.get("kind") != "sim":
            return order                # Practice books only — live/paper/unknown
                                        # kinds never retry
        reason = str(order.get("rejectReason") or "")
        if "quote age" not in reason or ";" in reason:
            return order                # not a pure freshness rejection
        if ctx.get("freshRetry"):
            return order                # once only
        stamp = {"at": dt.datetime.now(dt.timezone.utc).isoformat(),
                 "firstOrderId": order.get("id"), "reason": reason[:200]}
        async with eng.sf() as session:  # write-ahead: stamp BEFORE the retry,
            # row-locked so two concurrent approvals cannot both claim it
            row = await session.get(Proposal, pdict["id"], with_for_update=True)
            if row is None or (row.context or {}).get("freshRetry"):
                return order
            row.context = {**(row.context or {}), "freshRetry": stamp}
            await session.commit()
        # a REAL fresh observation for the exact contract (Codex v0.7.44 1A-P1:
        # reprice()'s already-served path re-reads the cache — the retry must
        # request new data and verify the source timestamp actually advanced)
        fresh_ask = None
        fresh_ts = None
        with contextlib.suppress(Exception):
            if intent.sec_type == "OPT":
                q = await eng.options.refresh_now(intent.symbol)
            else:
                q = eng.quotes.get(intent.symbol)
            if q is not None:
                fresh_ts = getattr(q, "source_ts", None) or getattr(q, "ts", None)
                fresh_ask = float(q.ask) if q.ask and q.ask > 0 else None
        stamp["freshSourceTs"] = fresh_ts
        limit = intent.limit_price
        if fresh_ask and limit and fresh_ask < float(limit):
            limit = round(fresh_ask, 2)
        # KB-06 then GEOMETRY rev 2: a queued retry is admitted like a fresh
        # automated entry — the integrity pause first (fails closed), then the
        # whole risk plan at the retry limit
        from ..techniques.tip import integrity as _ig
        refusal = await _ig.admission(eng, portfolio_id=pdict["portfolioId"], entry_path="retry",
                                      symbol=(ctx.get("vehicle") or {}).get("underlying") or pdict["symbol"])
        rqty = intent.qty
        if not refusal:
            rqty, pdict, refusal = await self._admit_geometry(pdict, limit=limit, qty=intent.qty, via="auto")
        if not refusal:
            # C95-08: the geometry refresh awaited real work — an incident may have
            # opened meanwhile; the pause is asked again immediately before the order
            refusal = await _ig.admission(eng, portfolio_id=pdict["portfolioId"], entry_path="retry",
                                          symbol=(ctx.get("vehicle") or {}).get("underlying") or pdict["symbol"])
        if refusal:
            stamp["retryRefused"] = refusal
            async with eng.sf() as session:
                row = await session.get(Proposal, pdict["id"])
                if row is not None:
                    row.context = {**(row.context or {}), "freshRetry": stamp}
                    await session.commit()
            await eng.journal.append(ev.PROPOSAL_RETRIED, {"proposalId": pdict["id"], **stamp},
                                     aggregate_type="proposal", aggregate_id=pdict["id"],
                                     portfolio_id=pdict["portfolioId"])
            return order
        # the retry carries the NEWLY admitted protection (the revalidated bracket), not a stale copy
        retry_bracket = intent.bracket
        if pdict.get("bracket"):
            retry_bracket = BracketSpec(**{k: v for k, v in {
                "take_profit": pdict["bracket"].get("take_profit"),
                "stop_loss": pdict["bracket"].get("stop_loss"),
                "take_profit_pct": pdict["bracket"].get("take_profit_pct"),
                "stop_loss_pct": pdict["bracket"].get("stop_loss_pct"),
            }.items() if v is not None})
        retry = await eng.orders.place(OrderIntent(
            portfolio_id=intent.portfolio_id, symbol=intent.symbol,
            sec_type=intent.sec_type, side=intent.side, qty=rqty,
            order_type=intent.order_type, limit_price=limit,
            bracket=retry_bracket, source="signal",
            signal_id=intent.signal_id, proposal_id=pdict["id"]))
        stamp = {**stamp, "retryOrderId": retry.get("id"),
                 "retryStatus": retry.get("status"),
                 "retryLimit": limit,
                 "retryReject": str(retry.get("rejectReason") or "")[:200] or None}
        async with eng.sf() as session:
            row = await session.get(Proposal, pdict["id"])
            if row is not None:
                row.context = {**(row.context or {}), "freshRetry": stamp}
                await session.commit()
        await eng.journal.append(
            ev.PROPOSAL_RETRIED, {"proposalId": pdict["id"], **stamp},
            aggregate_type="proposal", aggregate_id=pdict["id"],
            portfolio_id=pdict["portfolioId"])
        log.info("proposal %s: quote-freshness retry -> %s", pdict["id"],
                 retry.get("status"))
        return retry


    # ------------------------------------------------------------- readiness
    def _readiness_from_refusal(self, pdict: dict, reason: str) -> dict:
        """The typed state an AUTOMATED refusal implies (the same shape a
        refresh produces) so a refused card never shows only prose."""
        from . import readiness as _rd
        ctx = pdict.get("context") or {}
        rp = ctx.get("riskPlan") or None
        scope = self._geometry_scope(pdict.get("portfolioId") or "")
        blockers = _rd.plan_blockers(rp, enforced_scope=(scope == "enforce"))
        info: list[dict] = []
        code = _rd.classify_refusal(reason)
        if code and code not in {b["code"] for b in blockers}:
            b = _rd.blocker(code, reason)
            (info if b["scope"] == "auto" else blockers).append(b)
        valid = float(self.engine.settings.get("techniques.tip.geometry_quote_max_age_seconds", 300.0) or 300.0)
        return _rd.build(pdict=pdict, rp=rp, blockers=blockers, info=info,
                         limit=pdict.get("limitPrice"), qty=float(pdict.get("qty") or 0),
                         scope_mode=scope, phase="auto-refused", via="auto", valid_for_s=valid)

    async def _auto_qualification(self, source_name: str | None) -> str | None:
        """Why this source's cards are not approved AUTOMATICALLY (informational
        for a person: it never blocks a manual decision)."""
        eng = self.engine
        name = source_name or "unknown"
        policy = ((eng.settings.get("techniques.tip.sources") or {}).get(name, {}) or {})
        if policy.get("mode") == "auto":
            return None
        if policy.get("mode") and policy.get("mode") != "auto":
            return f"source policy: {policy.get('mode')} - approvals are manual"
        svc = getattr(eng, "signals_service", None)
        if svc is None or not hasattr(svc, "source_trust"):
            return None
        try:
            trust = await svc.source_trust(name)
        except Exception:                                   # noqa: BLE001 - informational
            return None
        need_n = int(eng.settings.get("techniques.tip.auto_min_graded", 5))
        need_hit = float(eng.settings.get("techniques.tip.auto_min_hit", 0.4))
        if int(trust.get("graded") or 0) < need_n:
            return f"auto not yet earned: {trust.get('graded') or 0}/{need_n} graded tips"
        hr = trust.get("hitRate")
        if hr is not None and float(hr) < need_hit:
            return f"auto not earned: hit rate {float(hr):.2f} below the {need_hit:.2f} bar ({trust.get('graded')} graded)"
        return None

    async def _incident_set(self, pid: str, underlying: str, prose: str | None) -> dict | None:
        """A86-01: the COMPLETE applicable incident state as one identity
        (every open incident on this book/path with id, revision and evidence
        hash); a prose refusal naming an incident the store does not hold
        (unavailable rows) contributes its id alone. None only when nothing applies."""
        from . import readiness as _rd
        from ..techniques.tip import integrity as _ig
        items: list[dict] = []
        try:
            items = await _ig.applicable_incidents(self.engine, portfolio_id=pid, entry_path="proposal", symbol=underlying)
        except Exception as exc:                            # noqa: BLE001
            # a structured read that fails is UNAVAILABLE state - never a partial
            # identity built from prose (review 2026-09-15, v0.7.87 verdict)
            return {"unavailable": f"execution-integrity state unavailable ({type(exc).__name__}: {str(exc)[:80]})"}
        pi = _rd.incident_identity(prose)
        if pi and not any(i["id"].startswith(pi["incidentId"]) for i in items):
            items.append({"id": pi["incidentId"]})
        return {"incidents": sorted(items, key=lambda x: x["id"])} if items else None

    async def assess(self, pdict: dict, *, via: str, half: bool = False, refresh: bool = True,
                     phase: str = "revalidate", limit_basis: float | None = None) -> tuple[dict, dict, float, float | None]:
        """Execution readiness of a Tips card RIGHT NOW (readiness-v1, 2026-09-15):
        refresh the quotes the plan needs, re-price the limit (the live ask may
        only IMPROVE it - never raise), recompute geometry + sizing under the
        gate's own rules, ask the execution-integrity store, note the source's
        automatic-trading qualification, and PERSIST the typed result on the
        card (`context.readiness`, the risk plan, a cleared or set review flag,
        the improved limit). Places nothing. Returns (readiness, pdict, qty, limit)."""
        from . import readiness as _rd
        from ..techniques.tip import integrity as _ig
        eng = self.engine
        ctx = pdict.get("context") or {}
        pid = pdict["portfolioId"]
        now = dt.datetime.now(dt.timezone.utc)
        blockers: list[dict] = []
        info: list[dict] = []
        exp = pdict.get("expiresAt")
        expired = False
        with contextlib.suppress(Exception):
            expired = bool(exp and dt.datetime.fromisoformat(exp) < now)
        if expired:
            blockers.append(_rd.blocker("expired", f"expired {exp}"))
        vehicle = ctx.get("vehicle") or {}
        sec_type = pdict.get("secType")
        underlying = str(vehicle.get("underlying") or pdict.get("symbol") or "").upper()
        limit0 = float(pdict.get("limitPrice") or 0) or None
        limit = float(limit_basis) if limit_basis else limit0    # AP85-02: the approved maximum the person saw
        limit_submit = limit
        if refresh and not expired:
            with contextlib.suppress(Exception):
                await eng.ensure_symbol(underlying)
            if sec_type == "OPT":
                with contextlib.suppress(Exception):
                    await eng.options.refresh_now(pdict["symbol"])
            if pdict.get("side") == "BUY" and pdict.get("orderType") == "LMT" and limit:
                ask = None
                with contextlib.suppress(Exception):
                    if sec_type == "OPT":
                        ask = await _live_ask(eng, pdict["symbol"])
                    else:
                        q = eng.quotes.get(pdict["symbol"])
                        ask = float(q.ask) if q is not None and q.ask and q.ask > 0 else None
                if ask and ask < limit:
                    limit_submit = round(ask, 2)             # never-chase: an explicitly permitted improvement
                    if not limit_basis:
                        limit = limit_submit                 # a refresh displays the improved limit as the new maximum
        req_qty = max(1.0, float(pdict.get("qty") or 1) / 2 if half else float(pdict.get("qty") or 1))
        scope = self._geometry_scope(pid)
        q_final = req_qty
        rp = ctx.get("riskPlan") or None
        if not expired and scope == "enforce":
            if sec_type in ("OPT", "STK"):
                q_final, pdict, _ = await self._admit_geometry(pdict, limit=limit, qty=req_qty, via="app",
                                                               phase=phase, count_failures=False)
                rp = (pdict.get("context") or {}).get("riskPlan") or None
                blockers += _rd.plan_blockers(rp, enforced_scope=True)
            else:
                blockers.append(_rd.blocker("unsupported_instrument",
                                            (pdict.get("context") or {}).get("reviewRequired")
                                            or "the geometry gate does not cover this vehicle"))
        if not expired and _ig.pauses(eng.settings):
            why = await _ig.admission(eng, portfolio_id=pid, entry_path="proposal", symbol=underlying)
            if why:
                code = _rd.integrity_code(why)
                ident = await self._incident_set(pid, underlying, why) if code == "integrity_incident" else None
                if ident and ident.get("unavailable"):
                    code, why, ident = "integrity_unavailable", ident["unavailable"], None
                detail = why if not ident else (why + " | applicable incidents: " + ", ".join(
                    f"{i['id'][:8]}@r{i.get('revision', '?')}" for i in ident["incidents"]))
                blockers.append(_rd.blocker(code, detail, identity=ident))
        gate = await self._auto_qualification((pdict.get("context") or {}).get("sourceName"))
        if gate:
            info.append(_rd.blocker("source_not_qualified", gate))
        valid = float(eng.settings.get("techniques.tip.geometry_quote_max_age_seconds", 300.0) or 300.0)
        readiness = _rd.build(pdict=pdict, rp=rp, blockers=blockers, info=info, limit=limit, qty=q_final,
                              scope_mode=scope, phase=phase, via=via, valid_for_s=valid, now=now)
        # persist: the typed state, the auto label (first reason, prose kept for older readers),
        # a stale review flag cleared, the improved limit
        async with eng.sf() as session:
            row = await session.get(Proposal, pdict["id"], with_for_update=True)
            if row is not None and row.status == "pending":      # a claimed (approved) plan is never rewritten
                c = {k: v for k, v in (row.context or {}).items() if k not in ("readiness", "autoGate")}
                c["readiness"] = readiness
                first = (readiness["blockers"] or readiness["info"] or [None])[0]
                if first:
                    c["autoGate"] = f"{first['label']}: {first['detail']}" if first.get("detail") else first["label"]
                if not any(b["code"] in ("risk_budget_exceeded", "plan_review", "unsupported_instrument",
                                         "risk_evidence_unavailable", "no_enforced_plan") or b["code"] in _rd.EVIDENCE_CODES
                           for b in readiness["blockers"]):
                    c.pop("reviewRequired", None)
                row.context = c
                if limit and limit0 and limit < limit0 and not limit_basis:
                    row.limit_price = limit
                await session.commit()
                pdict = proposal_dict(row)
        return readiness, pdict, q_final, (min(limit_submit, limit) if limit_submit and limit else limit)

    async def revalidate(self, proposal_id: str, *, via: str = "app") -> dict:
        """Refresh and revalidate a pending card: quotes, geometry, sizing,
        incidents, qualification - persisted, journaled, ZERO orders. An
        expired card is marked expired here rather than left with a stale label."""
        eng = self.engine
        async with eng.sf() as session:
            row = await session.get(Proposal, proposal_id)
            if row is None:
                raise ValueError("unknown proposal")
            if row.status != "pending":
                raise ValueError(f"proposal is {row.status}, not pending")
            pdict = proposal_dict(row)
        before = ((pdict.get("context") or {}).get("readiness") or {}).get("fingerprint")
        limit_before = pdict.get("limitPrice")
        readiness, pdict, _q, limit = await self.assess(pdict, via=via, refresh=True, phase="revalidate")
        if readiness["state"] == "expired":
            async with eng.sf() as session:
                row = await session.get(Proposal, proposal_id, with_for_update=True)
                if row is not None and row.status == "pending":
                    row.status = "expired"
                    row.decided_at = dt.datetime.now(dt.timezone.utc)
                    await session.commit()
                    pdict = proposal_dict(row)
            await eng.journal.append(ev.PROPOSAL_EXPIRED, {"proposalId": proposal_id, "reason": "expired at revalidation"},
                                     aggregate_type="proposal", aggregate_id=proposal_id, portfolio_id=pdict.get("portfolioId"))
        await eng.journal.append(
            ev.PROPOSAL_REVALIDATED,
            {"proposalId": proposal_id, "action": "refresh", "via": via, "state": readiness["state"],
             "blockers": [b["code"] for b in readiness["blockers"]], "info": [b["code"] for b in readiness["info"]],
             "fingerprint": readiness["fingerprint"], "changed": bool(before and before != readiness["fingerprint"]),
             "limitFrom": limit_before, "limitTo": limit, "orders": 0},
            aggregate_type="proposal", aggregate_id=proposal_id, portfolio_id=pdict.get("portfolioId"))
        eng.bus.publish(topics.PROPOSALS, pdict)
        return {"proposal": pdict, "readiness": readiness, "order": None}

    async def _refuse_human(self, proposal_id: str, readiness: dict, *, reason: str,
                            changed: bool = False, revert: bool = False) -> dict:
        """A manual approval that must not proceed: the card keeps (or goes
        back to) pending with the typed readiness on it; journaled; no order."""
        eng = self.engine
        async with eng.sf() as session:
            row = await session.get(Proposal, proposal_id, with_for_update=True)
            if row is None:
                return {"proposal": {"id": proposal_id}, "order": None, "refused": reason, "readiness": readiness}
            if revert and row.status == "approved":
                row.status = "pending"
                row.decided_at = None
                row.decided_via = None
            row.context = {**(row.context or {}), "readiness": readiness}
            await session.commit()
            pdict = proposal_dict(row)
        await eng.journal.append(
            ev.PROPOSAL_REVALIDATED,
            {"proposalId": proposal_id, "action": "approval_refused", "reason": reason[:300], "changed": changed,
             "state": readiness.get("state"), "blockers": [b["code"] for b in readiness.get("blockers") or []],
             "fingerprint": readiness.get("fingerprint"), "orders": 0, **({"revertedApproval": True} if revert else {})},
            aggregate_type="proposal", aggregate_id=proposal_id, portfolio_id=pdict.get("portfolioId"))
        eng.bus.publish(topics.PROPOSALS, pdict)
        return {"proposal": pdict, "order": None, "refused": reason, "readiness": readiness, "changed": changed}

    async def approve(self, proposal_id: str, *, via: str = "app",
                      half: bool = False, expected: str | None = None,
                      override: dict | None = None) -> dict:
        eng = self.engine
        # KB-06: an AUTOMATED approval of a tip card is admitted only while no
        # execution-integrity incident pauses this book (a human's click is a decision)
        if via == "auto":
            async with eng.sf() as session:
                pre = await session.get(Proposal, proposal_id)
                pre_pid = pre.portfolio_id if pre is not None else None
                pre_tip = bool(pre is not None and (pre.context or {}).get("techniqueId") == "tip")
            if pre_tip:
                from ..techniques.tip import integrity as _ig
                paused = await _ig.admission(eng, portfolio_id=pre_pid, entry_path="proposal")
                if paused:
                    return await self._refuse_automated(proposal_id, reason=paused)
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
            pre = proposal_dict(row)
        # readiness-v1 (2026-09-15): a PERSON's approval submits the displayed,
        # freshly validated plan - the card is revalidated right now (quotes,
        # geometry, sizing, incidents); a blocked card is refused unless every
        # failed check is overridable and named in a labeled override with a
        # reason; a plan that changed since it was displayed is refused so the
        # person reviews the refreshed card; a non-tip card keeps its old path
        assessed = False
        override_record: dict | None = None
        limit_pre: float | None = None
        snapshot: dict | None = None
        if via != "auto" and (pre.get("context") or {}).get("techniqueId") == "tip":
            from . import readiness as _rd
            shown = (pre.get("context") or {}).get("readiness") or {}
            if not expected:
                # AP85-02: every manual entry point must say which displayed plan it approves
                rd0 = shown or self._readiness_from_refusal(pre, "no displayed plan confirmed")
                return await self._refuse_human(
                    proposal_id, rd0,
                    reason="approval needs the confirmation of the displayed plan (fingerprint) - "
                           "refresh the card and approve exactly what it shows")
            basis = float(((shown.get("plan") or {}).get("limit") or 0) or 0) or None
            if shown.get("fingerprint") != expected:
                basis = None
            readiness, pre, q_final, limit_pre = await self.assess(pre, via=via, half=False, refresh=True,
                                                                   phase="submit", limit_basis=basis)
            if readiness["state"] == "expired":
                async with eng.sf() as session:
                    row = await session.get(Proposal, proposal_id, with_for_update=True)
                    if row is not None and row.status == "pending":
                        row.status = "expired"
                        row.decided_at = dt.datetime.now(dt.timezone.utc)
                        await session.commit()
                raise ValueError("proposal has expired")
            if expected and expected != readiness["fingerprint"]:
                return await self._refuse_human(
                    proposal_id, readiness, changed=True,
                    reason="the plan changed since it was displayed (quote, stop, size or checks) - "
                           "review the refreshed card and approve again")
            try:
                accepted, reason_text = _rd.validate_override(readiness, override)
            except ValueError as exc:
                return await self._refuse_human(proposal_id, readiness, reason=str(exc))
            # AP85-03: Half is an explicit transformation of the DISPLAYED plan
            qty = float(_rd.half_qty(readiness["plan"].get("qty") or q_final)) if half else float(q_final)
            if accepted:
                override_record = {"checks": [b["code"] for b in accepted], "labels": [b["label"] for b in accepted],
                                   "details": [b.get("detail") for b in accepted],
                                   "identities": [b.get("identity") for b in accepted], "reason": reason_text,
                                   "by": via, "exposure": {**readiness["plan"], "qty": int(qty),
                                                           "plannedRisk": (round(float(readiness["plan"]["unitLoss"]) * qty, 2)
                                                                           if readiness["plan"].get("unitLoss") is not None else None)},
                                   "fingerprint": readiness["fingerprint"],
                                   "at": dt.datetime.now(dt.timezone.utc).isoformat()}
            snapshot = dict(readiness)
            assessed = True
        # GEOMETRY rev 2: an AUTOMATED approval is admitted only if the enforced
        # risk plan still holds at the current limit — a refused card stays
        # pending for a person, with the reason on its record (no status flip)
        if via == "auto" and (pre.get("context") or {}).get("techniqueId") == "tip":
            _q, pre, refusal = await self._admit_geometry(pre, limit=pre.get("limitPrice"), qty=qty, via=via)
            if refusal:
                return await self._refuse_automated(proposal_id, reason=refusal)
        async with eng.sf() as session:
            # row-locked, re-checked: two clicks (or a click racing the TTL)
            # cannot both approve - the second one is told the card moved
            row = await session.get(Proposal, proposal_id, with_for_update=True)
            if row is None or row.status != "pending":
                raise ValueError(f"proposal is {row.status if row is not None else 'unknown'}, not pending")
            if row.expires_at and row.expires_at < dt.datetime.now(dt.timezone.utc):
                row.status = "expired"
                await session.commit()
                raise ValueError("proposal has expired")
            if snapshot is not None:
                # AP85-02 compare-and-claim: the row's persisted plan must still be
                # the one the person confirmed - a concurrent refresh or writer that
                # changed the readiness, the bracket or the limit means no claim
                stored = (row.context or {}).get("readiness") or {}
                sp = snapshot.get("plan") or {}
                claim_ok = stored.get("fingerprint") == expected
                if claim_ok:
                    # A86-02: never trust the cached hash - recompute the canonical plan
                    # from the row's CURRENT state (exit policy, bracket, vehicle, risk
                    # plan) and require the same fingerprint the person confirmed
                    from . import readiness as _rd
                    cur = _rd.plan_summary(proposal_dict(row), (row.context or {}).get("riskPlan"),
                                           limit=sp.get("limit"), qty=float(sp.get("qty") or 0))
                    claim_ok = _rd.fingerprint(cur, stored.get("blockers") or []) == expected
                if claim_ok and sp.get("finalStop") is not None and row.sec_type == "STK":
                    rs = (row.bracket or {}).get("stop_loss")
                    claim_ok = rs is not None and abs(float(rs) - float(sp["finalStop"])) < 1e-6
                if claim_ok and sp.get("limit") and row.limit_price and float(row.limit_price) > float(sp["limit"]) + 1e-9:
                    claim_ok = False
                if not claim_ok:
                    await session.rollback()
                    return await self._refuse_human(
                        proposal_id, snapshot, changed=True,
                        reason="the plan changed while it was being approved (concurrent refresh or edit) - "
                               "review the refreshed card and approve again")
            row.status = "approved"
            row.decided_at = dt.datetime.now(dt.timezone.utc)
            row.decided_via = via
            if override_record is not None:
                row.context = {**(row.context or {}), "override": override_record}
            if snapshot is not None:
                # A86-02: the claimed payload is immutable from here - dispatch and
                # adoption read it, never the live row fields a later writer may touch
                approved = {"fingerprint": expected, "qty": qty, "plan": snapshot.get("plan"),
                            **(snapshot.get("snapshot") or {}), "claimedAt": dt.datetime.now(dt.timezone.utc).isoformat()}
                row.context = {**(row.context or {}), "approvedPlan": approved}
                if approved.get("exitPlan") is not None:
                    row.context["exitPlan"] = approved["exitPlan"]
                if approved.get("vehicle") is not None:
                    row.context["vehicle"] = approved["vehicle"]
                if approved.get("bracket") is not None:
                    row.bracket = approved["bracket"]
            await session.commit()
            pdict = proposal_dict(row)

        await eng.journal.append(
            ev.PROPOSAL_APPROVED, {"via": via, "half": half, "qty": qty,
                                   **({"fingerprint": expected} if expected else {}),
                                   **({"override": override_record} if override_record else {})},
            aggregate_type="proposal", aggregate_id=proposal_id,
            portfolio_id=pdict["portfolioId"])
        if override_record is not None:
            await eng.journal.append(
                ev.PROPOSAL_OVERRIDDEN, {"proposalId": proposal_id, **override_record},
                aggregate_type="proposal", aggregate_id=proposal_id, portfolio_id=pdict["portfolioId"])

        if assessed:
            # AP85-01 final admission BEFORE any dispatch (single order or spread):
            # an unavailable integrity store always blocks; an incident is admitted
            # only when the override acknowledged exactly THAT incident identity
            from . import readiness as _rd
            from ..techniques.tip import integrity as _ig
            paused = await _ig.admission(eng, portfolio_id=pdict["portfolioId"], entry_path="proposal") \
                if _ig.pauses(eng.settings) else None
            if paused:
                code = _rd.integrity_code(paused)
                underlying_ = str(((pdict.get("context") or {}).get("vehicle") or {}).get("underlying") or pdict.get("symbol") or "").upper()
                ident = await self._incident_set(pdict["portfolioId"], underlying_, paused) if code == "integrity_incident" else None
                if ident and ident.get("unavailable"):
                    code, paused, ident = "integrity_unavailable", ident["unavailable"], None
                acknowledged = [i for i in ((override_record or {}).get("identities") or []) if i]
                # A86-01: exact equality of the complete set (ids, revisions, evidence)
                ok = (code == "integrity_incident" and ident is not None and ident in acknowledged)
                if not ok:
                    rd = dict(snapshot or {})
                    rd["blockers"] = [b for b in (rd.get("blockers") or []) if b["code"] not in ("integrity_incident", "integrity_unavailable")] + \
                        [_rd.blocker(code, paused)]
                    rd["state"] = "blocked"
                    rd["fingerprint"] = _rd.fingerprint(rd.get("plan") or {}, rd["blockers"])
                    return await self._refuse_human(proposal_id, rd, reason=paused, changed=True, revert=True)
            # the order is built from the CLAIMED snapshot, never re-read from the row
            sp = snapshot.get("plan") or {}
            if sp.get("bracket") and pdict.get("secType") == "STK":
                pdict = {**pdict, "bracket": {**sp["bracket"], "stop_loss": sp.get("finalStop", sp["bracket"].get("stop_loss"))}}
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

        # re-price an aged limit at approval time (2026-09-01: a 2h-old $23.80
        # limit vs a live $11.82 mid tripped the price collar and failed the
        # user's own click). The never-chase rule from creation applies again:
        # the live ask may only IMPROVE the limit, never raise it.
        limit = pdict["limitPrice"]
        if assessed:
            # the person approved the plan assess() just displayed and persisted:
            # that limit and size ARE the order (no second silent re-derivation)
            limit = limit_pre or limit
        else:
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
            # GEOMETRY rev 2: the WHOLE plan is re-derived at the limit actually
            # submitted; an automated entry the gate refuses here goes back to
            # pending (G91-01: the final refusal is honoured, not just the pre-check)
            qty, pdict, refusal = await self._admit_geometry(pdict, limit=limit, qty=qty, via=via)
            if refusal and via == "auto":
                return await self._refuse_automated(proposal_id, reason=refusal, revert=True)
        # the bracket is built AFTER admission from the proposal's (possibly
        # revalidated) protection plan — every protection from the same final plan
        bracket = None
        if pdict["bracket"]:
            bracket = BracketSpec(**{k: v for k, v in {
                "take_profit": pdict["bracket"].get("take_profit"),
                "stop_loss": pdict["bracket"].get("stop_loss"),
                "take_profit_pct": pdict["bracket"].get("take_profit_pct"),
                "stop_loss_pct": pdict["bracket"].get("stop_loss_pct"),
            }.items() if v is not None})
        intent = OrderIntent(
            portfolio_id=pdict["portfolioId"], symbol=pdict["symbol"],
            sec_type=pdict["secType"], side=pdict["side"], qty=qty,
            order_type=pdict["orderType"], limit_price=limit,
            bracket=bracket, source="signal",
            signal_id=pdict["signalId"], proposal_id=proposal_id)
        # KB-06 final admission: immediately before the entry order exists
        if via == "auto" and (pdict.get("context") or {}).get("techniqueId") == "tip":
            from ..techniques.tip import integrity as _ig
            paused = await _ig.admission(eng, portfolio_id=pdict["portfolioId"], entry_path="proposal")
            if paused:
                return await self._refuse_automated(proposal_id, reason=paused, revert=True)
        order = await eng.orders.place(intent)
        order = await self._maybe_retry_stale_quote(pdict, intent, order, via=via)

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

    async def reject(self, proposal_id: str, *, via: str = "app",
                     reason: str | None = None) -> dict:
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
            if reason:
                row.context = {**(row.context or {}), "declineReason": reason}
            await session.commit()
            pdict = proposal_dict(row)
        await eng.journal.append(ev.PROPOSAL_REJECTED, {"via": via, **({"reason": reason} if reason else {})},
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
