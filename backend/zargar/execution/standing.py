"""Standing orders (2026-11-14) - the user's own order plan, executed by the app after THEY arm it.

The user says what they want ("sell my SPCX Monday", "buy ANT as soon as it lists with up to $8,000, take profit
+10%, stop -10%"). Claude drafts it as a `draft` row; the user arms it (POST /arm with the confirm phrase) - or,
while the user's time-boxed DELEGATION is active (2026-11-16), Claude arms it inside that delegation's accounts and
money caps, which the app enforces. A live/paper book additionally needs `execution.standing_orders.allow_live`,
which Claude never flips.

Once armed the service, every `poll_seconds`:
- waits for the trigger: `now` (regular session + a fresh two-sided quote), `at` (not before HH:MM ET) or
  `listing` (a new issue's first regular-session prints: fresh two-sided quote with volume);
- prices a LIMIT off the live quote (buy: ask x (1 + slippage), never above `max_price`; sell: bid x (1 -
  slippage), never below `min_price`) and sizes it (`qty`, or whole shares of `budget`);
- routes it through OrderManager.place (RiskGate inside, kill switch honoured for buys), write-ahead: the row is
  `placing` before the call and the order carries the tag `standing:<id>`, so a crash mid-call is reconciled
  from the orders table, never re-sent blindly;
- an unfilled limit is cancelled after `fill_wait_seconds` and re-priced on the next tick, up to `max_attempts`;
  a refusal is recorded with the venue's reason and pushed to the user's phone;
- a filled BUY with take-profit / stop-loss is adopted by the position manager (ladder target + fixed stop, the
  stop resting at the venue as a GTC order where the venue accepts one).
Unfilled after `expires_on` (ET date) = expired (a working order is cancelled first)."""
from __future__ import annotations

import contextlib
import datetime as dt
import logging
import math
import time
from zoneinfo import ZoneInfo

from sqlalchemy import select

from .. import events as ev
from ..domain import new_id
from ..models import Order, StandingDelegation, StandingOrder, utcnow
from ..risk import is_us_market_hours

log = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

TECHNIQUE_ID = "standing"
OPEN = ("armed", "placing", "working")
CLOSED = ("done", "failed", "cancelled", "expired")
_TERMINAL = ("FILLED", "CANCELLED", "REJECTED", "REJECTED_RISK", "ERROR", "EXPIRED", "DRY_RUN")
_REFUSED = ("REJECTED", "REJECTED_RISK", "ERROR")


def confirm_phrase(order_id: str) -> str:
    """Sent by the UI's confirm dialog after the user clicks Arm: deliberately not a default a script would send."""
    return f"ARM {order_id[:8]}"


DELEGATE_PHRASE = "I DELEGATE ARMING"
MAX_REPAIRS = 2          # corrected versions of one user-armed order Claude may arm on the user's original arm


def delegated_phrase(delegation_id: str) -> str:
    """The confirm an arm sends under the user's delegation; the app checks the window/accounts/caps behind it."""
    return f"DELEGATED {delegation_id[:8]}"


def today_et(now: dt.datetime | None = None) -> str:
    return (now or dt.datetime.now(ET)).astimezone(ET).date().isoformat()


def limit_for(side: str, quote, slippage_pct: float, cap: float | None) -> tuple[float | None, str]:
    """The limit to send now, or (None, why we wait). Pure: the tests pin it."""
    s = max(0.0, float(slippage_pct or 0.0)) / 100.0
    if side == "BUY":
        ask = float(getattr(quote, "ask", 0) or 0)
        if ask <= 0:
            return None, "no ask yet"
        if cap and ask > cap:
            return None, f"ask {ask:.2f} above your max {cap:.2f}"
        px = ask * (1 + s)
        return round(min(px, cap) if cap else px, 2), ""
    bid = float(getattr(quote, "bid", 0) or 0)
    if bid <= 0:
        return None, "no bid yet"
    if cap and bid < cap:
        return None, f"bid {bid:.2f} below your floor {cap:.2f}"
    px = bid * (1 - s)
    return round(max(px, cap) if cap else px, 2), ""


def size_for(row, limit: float) -> float:
    """Whole shares still to trade: the fixed quantity, or what is left of the budget at this limit."""
    filled = float(row.filled_qty or 0.0)
    if row.qty:
        return max(0.0, float(int(round(float(row.qty) - filled))))
    if row.budget and limit > 0:
        spent = filled * float(row.avg_fill_price or 0.0)
        return float(max(0, math.floor((float(row.budget) - spent) / limit)))
    return 0.0


def exit_policy(avg: float, take_profit_pct: float | None, stop_loss_pct: float | None) -> dict:
    """The position manager's exits for a filled buy: a fixed stop and a single full-size target, on 5m bars."""
    pol: dict = {"timeframe": "5m"}
    if stop_loss_pct:
        pol["stop"] = {"kind": "fixed", "price": round(avg * (1 - float(stop_loss_pct) / 100.0), 2)}
    if take_profit_pct:
        pol["ladder"] = {"targets": [round(avg * (1 + float(take_profit_pct) / 100.0), 2)], "fractions": [1.0]}
    return pol


class StandingOrderService:
    def __init__(self, engine) -> None:
        self.engine = engine
        self._task = None
        self._alerted: set[str] = set()
        self._refreshed_at: dict[str, float] = {}
        self._watched: set[str] = set()

    # ------------------------------------------------------------------ settings
    def s(self, key: str, default):
        return self.engine.settings.get(f"execution.standing_orders.{key}", default)

    def _kind(self, pid: str) -> str | None:
        pf = self.engine.positions.portfolio(pid) or {}
        return pf.get("kind")

    # ------------------------------------------------------------------ user-facing operations
    async def create(self, spec: dict) -> dict:
        """A DRAFT. Never armed here: arming is the user's own act (arm())."""
        pid = str(spec.get("portfolioId") or "")
        if not pid or self.engine.positions.portfolio(pid) is None:
            raise ValueError("unknown portfolioId")
        side = str(spec.get("side") or "").upper()
        if side not in ("BUY", "SELL"):
            raise ValueError("side must be BUY or SELL")
        qty = spec.get("qty")
        budget = spec.get("budget")
        spend_all = bool(spec.get("spendAll"))
        if spend_all and side != "BUY":
            raise ValueError("spendAll is for buys")
        if spend_all and qty:
            raise ValueError("spendAll sizes from cash - give no qty (a budget, if any, is a ceiling)")
        if not spend_all and bool(qty) == bool(budget):
            raise ValueError("give exactly one of qty or budget")
        if budget and side != "BUY":
            raise ValueError("budget is for buys; a sell takes qty")
        trigger = str(spec.get("trigger") or "now")
        if trigger not in ("now", "at", "listing"):
            raise ValueError("trigger must be now, at or listing")
        not_before = spec.get("notBefore")
        if trigger == "at":
            hh, mm = str(not_before or "").split(":")
            assert 0 <= int(hh) < 24 and 0 <= int(mm) < 60
        expires = str(spec.get("expiresOn") or today_et())
        dt.date.fromisoformat(expires)
        starts = spec.get("startsOn") or None
        if starts:
            dt.date.fromisoformat(str(starts))
            if str(starts) > expires:
                raise ValueError("startsOn is after expiresOn")
        tp, sl = spec.get("takeProfitPct"), spec.get("stopLossPct")
        if side == "SELL" and (tp or sl):
            raise ValueError("take-profit / stop-loss apply to buys")
        for v in (tp, sl):
            if v is not None and not (0 < float(v) < 100):
                raise ValueError("take-profit / stop-loss are percentages between 0 and 100")
        row = StandingOrder(
            id=new_id(), plan_id=(spec.get("planId") or None), plan_name=(spec.get("planName") or None),
            portfolio_id=pid, symbol=str(spec.get("symbol") or "").strip().upper(), side=side,
            qty=float(qty) if qty else None, budget=float(budget) if budget else None, spend_all=spend_all,
            trigger=trigger,
            not_before=not_before if trigger == "at" else None, expires_on=expires,
            starts_on=str(starts) if starts else None,
            max_price=float(spec["maxPrice"]) if spec.get("maxPrice") else None,
            min_price=float(spec["minPrice"]) if spec.get("minPrice") else None,
            slippage_pct=float(spec.get("slippagePct", self.s("slippage_pct", 0.5))),
            take_profit_pct=float(tp) if tp else None, stop_loss_pct=float(sl) if sl else None,
            status="draft", note=(spec.get("note") or None), attempts=[], order_ids=[])
        if not row.symbol:
            raise ValueError("symbol required")
        async with self.engine.sf() as session:
            session.add(row)
            await session.commit()
        await self._journal(row, "drafted", {})
        return self.to_dict(row)

    async def list(self, *, include_closed: bool = True) -> list[dict]:
        async with self.engine.sf() as session:
            q = select(StandingOrder).order_by(StandingOrder.created_at.desc())
            if not include_closed:
                q = q.where(StandingOrder.status.notin_(CLOSED))
            rows = (await session.execute(q.limit(200))).scalars().all()
        return [self.to_dict(r) for r in rows]

    async def get(self, oid: str) -> dict | None:
        async with self.engine.sf() as session:
            row = await session.get(StandingOrder, oid)
        return self.to_dict(row) if row else None

    # ------------------------------------------------------------------ delegation (2026-11-16)
    async def create_delegation(self, spec: dict, confirm: str) -> dict:
        """The user's go-ahead from the Standing orders page. `confirm` is the phrase the page asks them to type."""
        if confirm.strip() != DELEGATE_PHRASE:
            raise ValueError(f"type '{DELEGATE_PHRASE}' to delegate arming")
        pids = [str(p) for p in (spec.get("portfolioIds") or []) if p]
        if not pids:
            raise ValueError("pick at least one account")
        for p in pids:
            if self.engine.positions.portfolio(p) is None:
                raise ValueError(f"unknown portfolio {p}")
        ends = dt.datetime.fromisoformat(str(spec.get("endsAt") or ""))
        if ends.tzinfo is None:
            ends = ends.replace(tzinfo=ET)
        now = dt.datetime.now(dt.timezone.utc)
        if ends <= now:
            raise ValueError("the end must be in the future")
        if ends - now > dt.timedelta(days=31):
            raise ValueError("a delegation lasts at most 31 days")
        per, total = float(spec.get("maxOrderNotional") or 0), float(spec.get("maxTotalNotional") or 0)
        if per <= 0 or total <= 0 or per > total:
            raise ValueError("set a per-order cap and a total cap (per-order <= total)")
        row = StandingDelegation(id=new_id(), portfolio_ids=pids, starts_at=now, ends_at=ends,
                                 max_order_notional=per, max_total_notional=total, note=(spec.get("note") or None))
        async with self.engine.sf() as session:
            session.add(row)
            await session.commit()
        await self._journal_delegation(row, "delegated")
        return await self._delegation_dict(row)

    async def revoke_delegation(self, did: str) -> dict:
        async with self.engine.sf() as session:
            row = await session.get(StandingDelegation, did)
            if row is None:
                raise ValueError("no such delegation")
            if row.revoked_at is None:
                row.revoked_at = utcnow()
                await session.commit()
        await self._journal_delegation(row, "revoked")
        return await self._delegation_dict(row)

    async def delegations(self, *, active_only: bool = False) -> list[dict]:
        async with self.engine.sf() as session:
            rows = (await session.execute(select(StandingDelegation)
                                          .order_by(StandingDelegation.created_at.desc()).limit(20))).scalars().all()
        out = [await self._delegation_dict(r) for r in rows]
        return [d for d in out if d["active"]] if active_only else out

    @staticmethod
    def _active(d: StandingDelegation, now: dt.datetime | None = None) -> bool:
        now = now or dt.datetime.now(dt.timezone.utc)
        return d.revoked_at is None and d.starts_at <= now < d.ends_at

    @staticmethod
    def buy_notional(row: StandingOrder) -> float | None:
        """The most a buy can spend: its budget, or qty x its max price. None = unbounded (no delegated arm)."""
        if row.side != "BUY":
            return 0.0
        if row.budget:
            return float(row.budget)
        if row.qty and row.max_price:
            return float(row.qty) * float(row.max_price)
        return None

    async def _committed(self, did: str) -> float:
        """Buy money this delegation has armed: filled notional, plus the bound of what is still open."""
        tag = f"claude:delegation:{did}"
        async with self.engine.sf() as session:
            rows = (await session.execute(select(StandingOrder).where(StandingOrder.armed_by == tag,
                                                                      StandingOrder.side == "BUY"))).scalars().all()
        total = 0.0
        for r in rows:
            filled = float(r.filled_qty or 0) * float(r.avg_fill_price or 0)
            if r.status in OPEN:
                total += max(filled, self.buy_notional(r) or 0.0)
            else:
                total += filled
        return round(total, 2)

    async def _delegation_dict(self, d: StandingDelegation) -> dict:
        return {"id": d.id, "portfolioIds": list(d.portfolio_ids or []), "startsAt": d.starts_at.isoformat(),
                "endsAt": d.ends_at.isoformat(), "maxOrderNotional": d.max_order_notional,
                "maxTotalNotional": d.max_total_notional, "note": d.note, "active": self._active(d),
                "revokedAt": d.revoked_at.isoformat() if d.revoked_at else None,
                "committed": await self._committed(d.id), "confirm": delegated_phrase(d.id)}

    async def _check_delegated(self, row: StandingOrder, confirm: str) -> str:
        """The app's own gate on an arm made under delegation; returns the `armed_by` stamp or raises."""
        did_prefix = confirm.strip()[len("DELEGATED "):].strip()
        async with self.engine.sf() as session:
            ds = (await session.execute(select(StandingDelegation))).scalars().all()
        d = next((x for x in ds if x.id.startswith(did_prefix) and len(did_prefix) >= 8), None)
        if d is None:
            raise ValueError("no such delegation")
        if not self._active(d):
            raise ValueError("this delegation is not active (expired, revoked or not started)")
        if row.portfolio_id not in (d.portfolio_ids or []):
            raise ValueError("this account is not covered by the delegation")
        if row.expires_on > d.ends_at.astimezone(ET).date().isoformat():
            raise ValueError("the order outlives the delegation - shorten its expiry")
        if row.side == "BUY":
            cost = self.buy_notional(row)
            if cost is None:
                raise ValueError("a delegated buy needs a budget or a max price")
            if cost > d.max_order_notional + 1e-6:
                raise ValueError(f"this buy can spend {cost:,.2f}, over the per-order cap {d.max_order_notional:,.2f}")
            used = await self._committed(d.id)
            if used + cost > d.max_total_notional + 1e-6:
                raise ValueError(f"over the delegation's total cap: {used:,.2f} used + {cost:,.2f} > "
                                 f"{d.max_total_notional:,.2f}")
        return f"claude:delegation:{d.id}"

    async def _delegation_for(self, confirm: str) -> StandingDelegation | None:
        prefix = confirm.strip()[len("DELEGATED "):].strip()
        async with self.engine.sf() as session:
            ds = (await session.execute(select(StandingDelegation))).scalars().all()
        return next((x for x in ds if len(prefix) >= 8 and x.id.startswith(prefix)), None)

    async def _journal_delegation(self, d: StandingDelegation, stage: str) -> None:
        with contextlib.suppress(Exception):
            await self.engine.journal.append(ev.STANDING_ORDER, {
                "delegationId": d.id, "stage": stage, "portfolioIds": list(d.portfolio_ids or []),
                "endsAt": d.ends_at.isoformat(), "maxOrderNotional": d.max_order_notional,
                "maxTotalNotional": d.max_total_notional}, aggregate_type="standing_delegation", aggregate_id=d.id)

    # ------------------------------------------------------------------ repairs (2026-11-16, user decision)
    async def repair_plan(self, name: str, orders: list[dict]) -> dict:
        """Corrected orders for user-armed orders that failed (wrong account, a listing the venue refuses, a cap
        refusal). The USER's arm of the original carries over - the repair is armed at once, no second click
        ("once you have a directive, the corrected plan should be auto armed"). The app bounds it: same side, same
        broker connection, never more shares or a larger buy than the original, never past the original's expiry,
        at most MAX_REPAIRS per original; a sell may change symbol only to one this same repair buys (a test round
        trip). allow_live and every RiskGate check still apply. Each order names `repairOf` = the failed order."""
        if not orders:
            raise ValueError("a repair needs at least one order")
        today = today_et()
        checked: list[tuple[dict, StandingOrder, str]] = []
        buys = {(str(o.get("portfolioId")), str(o.get("symbol") or "").upper()) for o in orders
                if str(o.get("side") or "").upper() == "BUY"}
        for spec in orders:
            orig = await self._load(str(spec.get("repairOf") or ""))
            if orig is None:
                raise ValueError("each repair names repairOf = the failed standing order")
            root = await self._root(orig)
            if root.armed_at is None or not (root.armed_by == "user"
                                             or (root.armed_by or "").startswith("claude:delegation:")):
                raise ValueError("only an order the user armed (or a delegation armed) can be repaired")
            if orig.status not in ("failed", "armed"):
                raise ValueError(f"{orig.symbol} {orig.side} is {orig.status} - only a failed or waiting order is repaired")
            if orig.expires_on < today:
                raise ValueError(f"{orig.symbol} {orig.side} expired on {orig.expires_on} - a new plan needs the user")
            if await self._repair_count(root.id) >= MAX_REPAIRS:
                raise ValueError(f"{root.symbol} {root.side} was already repaired {MAX_REPAIRS} times - ask the user")
            side = str(spec.get("side") or "").upper()
            if side != orig.side:
                raise ValueError("a repair keeps the original's side")
            pid = str(spec.get("portfolioId") or "")
            if pid != orig.portfolio_id and not await self._same_connection(pid, orig.portfolio_id):
                raise ValueError("a repair stays at the same broker connection")
            sym = str(spec.get("symbol") or "").strip().upper()
            if spec.get("budget") and not orig.budget and not orig.max_price:
                raise ValueError("the original had no money bound - a budget repair needs the user")
            if side == "SELL" and sym != orig.symbol and (pid, sym) not in buys:
                raise ValueError("a sell may change symbol only to one this repair also buys")
            expires = str(spec.get("expiresOn") or orig.expires_on)
            if expires > orig.expires_on:
                raise ValueError("a repair never outlives the original")
            if spec.get("qty") and orig.qty and float(spec["qty"]) > float(orig.qty):
                raise ValueError("a repair never trades more shares than the original")
            checked.append(({**spec, "symbol": sym, "expiresOn": expires}, orig, root.id))
        # create, then bound the buys against the originals at their caps
        made = await self.create_plan(name, [{k: v for k, v in s.items() if k != "repairOf"} for s, _, _ in checked])
        try:
            for row_d, (spec, orig, root_id) in zip(made["orders"], checked):
                new = await self._load(row_d["id"])
                if new.side == "BUY":
                    cost, cap = self.buy_notional(new), self.buy_notional(orig)
                    if cost is None:
                        raise ValueError(f"the repair buy of {new.symbol} needs a max price or a budget")
                    if cap is not None and cost > cap + 1e-6:
                        raise ValueError(f"the repair buy of {new.symbol} can spend {cost:,.2f}, more than the "
                                         f"original's {cap:,.2f}")
                    if cap is None and new.symbol != orig.symbol:
                        raise ValueError("the original buy had no price cap - a symbol change needs the user")
                await self._update(new.id, repair_of=orig.id)
        except Exception:
            for o in made["orders"]:
                with contextlib.suppress(Exception):
                    await self.cancel(o["id"])
            raise
        armed = []
        for row_d, (spec, orig, root_id) in zip(made["orders"], checked):
            if orig.status == "armed":                          # the original stops waiting: the repair replaces it
                with contextlib.suppress(Exception):
                    await self._finish(orig, "cancelled", f"replaced by repair {row_d['id'][:8]}")
            armed.append(await self.arm(row_d["id"], confirm_phrase(row_d["id"]), armed_by=f"claude:repair:{root_id}"))
        return {"planId": made["planId"], "planName": name, "armed": armed}

    async def _load(self, oid: str) -> StandingOrder | None:
        if not oid:
            return None
        async with self.engine.sf() as session:
            return await session.get(StandingOrder, oid)

    async def _root(self, row: StandingOrder) -> StandingOrder:
        seen = 0
        while row.repair_of and seen < 10:
            parent = await self._load(row.repair_of)
            if parent is None:
                break
            row, seen = parent, seen + 1
        return row

    async def _repair_count(self, root_id: str) -> int:
        async with self.engine.sf() as session:
            rows = (await session.execute(select(StandingOrder).where(
                StandingOrder.armed_by == f"claude:repair:{root_id}"))).scalars().all()
        return len(rows)

    async def _same_connection(self, a: str, b: str) -> bool:
        from ..models import BrokerageAccount
        async with self.engine.sf() as session:
            rows = (await session.execute(select(BrokerageAccount).where(
                BrokerageAccount.portfolio_id.in_([a, b])))).scalars().all()
        conns = {r.portfolio_id: r.connection_id for r in rows}
        return a in conns and b in conns and conns[a] == conns[b]

    # ------------------------------------------------------------------ arming
    async def arm(self, oid: str, confirm: str, *, armed_by: str | None = None) -> dict:
        """`armed_by` is internal only (repairs): the routes never pass it."""
        armed_by = armed_by or "user"
        async with self.engine.sf() as session:
            row = await session.get(StandingOrder, oid)
            if row is None:
                raise ValueError("no such standing order")
            if row.status != "draft":
                raise ValueError(f"only a draft can be armed (this one is {row.status})")
            if confirm.strip().startswith("DELEGATED "):
                armed_by = await self._check_delegated(row, confirm)
            elif confirm.strip() != confirm_phrase(row.id):
                raise ValueError(f"type '{confirm_phrase(row.id)}' to arm this order")
            if self._kind(row.portfolio_id) in ("live", "paper") and not bool(self.s("allow_live", False)):
                raise ValueError("real-money standing orders are off: turn on Settings -> "
                                 "execution.standing_orders.allow_live first")
            if row.expires_on < today_et():
                raise ValueError("this draft expired - change its date first")
            row.status, row.armed_at, row.last_error, row.armed_by = "armed", utcnow(), None, armed_by
            await session.commit()
        with contextlib.suppress(Exception):
            await self.engine.ensure_symbol(row.symbol)
        await self._journal(row, "armed", {"armedBy": armed_by})
        if armed_by != "user":
            cap = row.budget or (f"<= {row.max_price}" if row.max_price else "")
            await self._push(f"Claude armed: {row.side} {row.symbol}",
                             f"{row.side} {row.qty or ''} {row.symbol} {cap} on {self._name(row.portfolio_id)} "
                             f"({'repair of your armed order' if armed_by.startswith('claude:repair:') else 'delegation'})"
                             f" - {row.plan_name or row.note or ''}".strip(),
                             key=f"delegated-arm:{row.id}")
        self.start()
        return self.to_dict(row)

    def _name(self, pid: str) -> str:
        return (self.engine.positions.portfolio(pid) or {}).get("name") or pid[:8]

    async def create_plan(self, name: str, orders: list[dict]) -> dict:
        """Several drafts that the user arms with ONE click (arm_plan). Validated all-or-nothing."""
        if not orders:
            raise ValueError("a plan needs at least one order")
        plan_id = new_id()
        made = []
        try:
            for spec in orders:
                made.append(await self.create({**spec, "planId": plan_id, "planName": name}))
        except Exception:
            for m in made:
                with contextlib.suppress(Exception):
                    await self.cancel(m["id"])
            raise
        # 2026-11-18: a plan that waits for the user's arm says so on their phone (the 11-16 corrected plans sat
        # unarmed and expired because nobody saw them)
        await self._push("A plan is waiting for your arm", f"{name} ({len(made)} order{'s' if len(made) != 1 else ''})",
                         key=f"drafted:{plan_id}", level="warning")
        return {"planId": plan_id, "planName": name, "armConfirm": confirm_phrase(plan_id), "orders": made}

    async def arm_plan(self, plan_id: str, confirm: str) -> dict:
        """The user's one click: arms every draft of the plan, or none (each passes the same gates as arm())."""
        delegated = confirm.strip().startswith("DELEGATED ")
        if not delegated and confirm.strip() != confirm_phrase(plan_id):
            raise ValueError("confirm phrase does not match this plan")
        async with self.engine.sf() as session:
            rows = (await session.execute(select(StandingOrder).where(StandingOrder.plan_id == plan_id))).scalars().all()
        drafts = [r for r in rows if r.status == "draft"]
        if not drafts:
            raise ValueError("no drafts left in this plan")
        for r in drafts:
            if self._kind(r.portfolio_id) in ("live", "paper") and not bool(self.s("allow_live", False)):
                raise ValueError("real-money standing orders are off: turn on Settings -> "
                                 "execution.standing_orders.allow_live first")
            if r.expires_on < today_et():
                raise ValueError(f"{r.symbol} {r.side} expired - change its date first")
        if delegated:
            # all or nothing: every buy of the plan must fit the caps TOGETHER before any order is armed
            for r in drafts:
                await self._check_delegated(r, confirm)
            plan_cost = sum(self.buy_notional(r) or 0.0 for r in drafts)
            d = await self._delegation_for(confirm)
            if d is not None and (await self._committed(d.id)) + plan_cost > d.max_total_notional + 1e-6:
                raise ValueError("this plan's buys together exceed the delegation's total cap")
        armed = [await self.arm(r.id, confirm.strip() if delegated else confirm_phrase(r.id)) for r in drafts]
        return {"planId": plan_id, "armed": armed}

    async def disarm(self, oid: str) -> dict:
        async with self.engine.sf() as session:
            row = await session.get(StandingOrder, oid)
            if row is None:
                raise ValueError("no such standing order")
            if row.status != "armed":
                raise ValueError(f"only an armed order waiting for its trigger can be disarmed (this one is {row.status})")
            row.status = "draft"
            await session.commit()
        await self._journal(row, "disarmed", {})
        return self.to_dict(row)

    async def cancel(self, oid: str) -> dict:
        async with self.engine.sf() as session:
            row = await session.get(StandingOrder, oid)
        if row is None:
            raise ValueError("no such standing order")
        if row.status in CLOSED:
            return self.to_dict(row)
        if row.order_id:
            with contextlib.suppress(Exception):
                await self.engine.orders.cancel(row.order_id)
        row = await self._update(oid, status="cancelled", order_id=None)
        await self._journal(row, "cancelled", {})
        return self.to_dict(row)

    async def preflight(self, oid: str) -> dict:
        """A DRY RUN through RiskGate at today's quote (no venue contact): what would happen if it fired now."""
        async with self.engine.sf() as session:
            row = await session.get(StandingOrder, oid)
        if row is None:
            raise ValueError("no such standing order")
        with contextlib.suppress(Exception):
            await self.engine.ensure_symbol(row.symbol)
        q = self.engine.quotes.get(row.symbol)
        if q is None:
            return {"ok": False, "why": f"no quote for {row.symbol} yet (not listed or not streaming)"}
        cap = row.max_price if row.side == "BUY" else row.min_price
        limit, why = limit_for(row.side, q, row.slippage_pct, cap)
        if limit is None:
            return {"ok": False, "why": why}
        if row.spend_all:
            qty, why = self._cash_qty(row, limit)
            if qty is None:
                return {"ok": False, "why": why}
        else:
            qty = size_for(row, limit)
        if qty < 1:
            return {"ok": False, "why": "nothing left to trade at this price"}
        if row.side == "SELL":
            held = self._held(row)
            if held < 1:
                return {"ok": False, "why": f"the book holds no {row.symbol} to sell"}
            qty = min(qty, held)
        res = await self.engine.orders.place(self._intent(row, qty, limit, dry_run=True))
        risk = res.get("risk") or {}
        failed = [c for c in risk.get("checks", []) if not c.get("passed")]
        return {"ok": not failed and res.get("status") == "DRY_RUN", "limit": limit, "qty": qty,
                "notional": round(qty * limit, 2), "failedChecks": failed, "status": res.get("status"),
                "reason": res.get("rejectReason")}

    # ------------------------------------------------------------------ loop
    def start(self) -> None:
        import asyncio
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop(), name="standing-orders")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(BaseException):
                await self._task
            self._task = None

    async def _loop(self) -> None:
        import asyncio
        while True:
            try:
                await self.tick()
            except Exception:                                   # noqa: BLE001 - never let one bad row stop the loop
                log.exception("standing-order tick failed")
            await asyncio.sleep(float(self.s("poll_seconds", 5.0)))

    async def tick(self, now: dt.datetime | None = None) -> None:
        async with self.engine.sf() as session:
            rows = (await session.execute(select(StandingOrder).where(StandingOrder.status.in_(OPEN)))).scalars().all()
        for row in rows:
            # 2026-11-19: a restart drops the feed's subscriptions and only arm() subscribed - ANT's buys read "no quote
            # for ANT yet" after the 10:50 ET restart until a manual preflight re-subscribed. Once per process per symbol.
            if row.symbol not in self._watched:
                self._watched.add(row.symbol)
                with contextlib.suppress(Exception):
                    await self.engine.ensure_symbol(row.symbol)
            try:
                await self._process(row, now)
            except Exception as exc:                            # noqa: BLE001
                log.exception("standing order %s", row.id)
                await self._fail(row, f"internal error: {exc}")

    async def _process(self, row: StandingOrder, now: dt.datetime | None) -> None:
        now = (now or dt.datetime.now(ET)).astimezone(ET)
        if row.status == "placing":
            return await self._reconcile_placing(row)
        if row.status == "working":
            return await self._check_working(row, now)
        # armed: expired?
        if row.expires_on < now.date().isoformat():
            return await self._finish(row, "expired", "not triggered before it expired")
        fired, why = self._triggered(row, now)
        if why == "quote is stale" and await self._refresh_quote(row.symbol):
            fired, why = self._triggered(row, now)
        if not fired:
            await self._note_wait(row, why)
            return
        if row.side == "BUY":
            halted = self.engine.trading_halted(row.portfolio_id)
            if halted:
                await self._note_wait(row, f"trading halted: {halted}")
                return
        if self._kind(row.portfolio_id) in ("live", "paper") and not bool(self.s("allow_live", False)):
            await self._note_wait(row, "execution.standing_orders.allow_live is off")
            return
        if row.spend_all and await self._plan_sells_pending(row):
            await self._note_wait(row, "waiting for this plan's sells in the account to finish")
            return
        q = self.engine.quotes.get(row.symbol)
        cap = row.max_price if row.side == "BUY" else row.min_price
        limit, why = limit_for(row.side, q, row.slippage_pct, cap)
        if limit is None:
            await self._note_wait(row, why)
            return
        if row.spend_all:
            qty, why = self._cash_qty(row, limit)
            if qty is None:
                await self._note_wait(row, why)
                return
        else:
            qty = size_for(row, limit)
        if qty < 1:
            return await self._finish(row, "done" if row.filled_qty else "failed",
                                      ("not enough cash for one share" if row.spend_all else
                                       "budget too small for one share") if not row.filled_qty else "complete")
        if row.side == "SELL":
            # 2026-11-16: a reduce-only SELL is checked by nobody against the shares held (RiskGate runs the
            # safety-only list); an XIU.TO sell with no position reached IBKR three times. On a US name the venue
            # would have opened a SHORT. A sell never exceeds what the book holds.
            held = self._held(row)
            if held < 1:
                return await self._finish(row, "done" if row.filled_qty else "failed",
                                          "complete" if row.filled_qty else f"the book holds no {row.symbol} to sell")
            qty = min(qty, held)
        await self._place(row, qty, limit, q)

    def _cash_qty(self, row: StandingOrder, limit: float) -> tuple[float | None, str]:
        """2026-11-17 ("sell all of them, spend everything"): whole shares the book's cash buys NOW, in the stock's
        currency at the live FX rate (never 1:1 - CAD read as USD would overspend by a third), less a reserve for the
        broker's FX fee and price drift, capped by `budget` when one is set. (None, why) = wait."""
        from ..fx import currency_for_symbol
        pf = self.engine.positions.portfolio(row.portfolio_id) or {}
        cash = float(pf.get("cash") or 0.0)
        book_ccy = str(pf.get("baseCurrency") or "USD").upper()
        sym_ccy = currency_for_symbol(row.symbol)
        rate = 1.0 if book_ccy == sym_ccy else self.engine.positions.fx.rate(book_ccy, sym_ccy)
        if rate is None:
            return None, f"no live {book_ccy}->{sym_ccy} rate to size from cash"
        reserve = max(0.0, float(self.s("spend_all_reserve_pct", 3.0))) / 100.0
        money = cash * rate * (1.0 - reserve)
        if row.budget:
            spent = float(row.filled_qty or 0.0) * float(row.avg_fill_price or 0.0)
            money = min(money, float(row.budget) - spent)
        return float(max(0, math.floor(money / limit))) if limit > 0 else 0.0, ""

    async def _plan_sells_pending(self, row: StandingOrder) -> bool:
        """A spend-all buy waits for the SAME plan's sells in the same account: their proceeds are the money."""
        if not row.plan_id:
            return False
        async with self.engine.sf() as session:
            sells = (await session.execute(select(StandingOrder).where(
                StandingOrder.plan_id == row.plan_id, StandingOrder.portfolio_id == row.portfolio_id,
                StandingOrder.side == "SELL"))).scalars().all()
        return any(s.status in ("draft", *OPEN) for s in sells)

    def _held(self, row: StandingOrder) -> float:
        """Whole shares of the symbol this book holds now (fractional remainders cannot be sold by a whole-share order)."""
        try:
            return float(math.floor(max(0.0, float(self.engine.positions.position_qty(row.portfolio_id, row.symbol,
                                                                                       "STK") or 0.0)) + 1e-9))
        except Exception:                                       # noqa: BLE001
            return 0.0

    def _triggered(self, row: StandingOrder, now: dt.datetime) -> tuple[bool, str]:
        if row.starts_on and now.date().isoformat() < row.starts_on:
            return False, f"waiting for {row.starts_on}"
        if not is_us_market_hours(now):
            return False, "market closed"
        # the clock first: a quote refresh is only worth asking for once the order is due
        if row.trigger == "at" and row.not_before:
            hh, mm = (int(x) for x in row.not_before.split(":"))
            if (now.hour, now.minute) < (hh, mm):
                return False, f"waiting for {row.not_before} ET"
        q = self.engine.quotes.get(row.symbol)
        stale = float(self.engine.settings.get("risk.stale_quote_seconds", 10))
        if q is None:
            return False, f"no quote for {row.symbol} yet"
        if self.engine.quotes.age_seconds(row.symbol) > stale:
            return False, "quote is stale"
        if not (q.bid and q.ask and q.ask >= q.bid):
            return False, "no two-sided quote yet"
        if row.trigger == "listing" and not (q.volume and q.volume > 0 and q.last):
            return False, "waiting for the first regular-session prints"
        return True, ""

    async def _refresh_quote(self, symbol: str) -> bool:
        """2026-11-16: a due order on a symbol whose only source is the Yahoo poll (XIU.TO) saw a 20-40 s old quote
        on most ticks and the 10 s freshness rule held it. Ask the feed for one fresh quote (at most every 5 s)."""
        refresh = getattr(self.engine.feed, "refresh", None)
        if refresh is None:
            return False
        last = self._refreshed_at.get(symbol, 0.0)
        if time.monotonic() - last < 5.0:
            return False
        self._refreshed_at[symbol] = time.monotonic()
        try:
            return bool(await refresh(symbol))
        except Exception:                                       # noqa: BLE001
            log.warning("quote refresh failed for %s", symbol, exc_info=True)
            return False

    # ------------------------------------------------------------------ placement (write-ahead)
    def _intent(self, row: StandingOrder, qty: float, limit: float, *, dry_run: bool = False):
        from ..orders import OrderIntent
        return OrderIntent(portfolio_id=row.portfolio_id, symbol=row.symbol, sec_type="STK", side=row.side,
                           qty=qty, order_type="LMT", limit_price=limit, tif="DAY", source="standing",
                           technique_id=TECHNIQUE_ID, tags=[f"standing:{row.id}"], dry_run=dry_run,
                           reduce_only=(row.side == "SELL"))

    async def _place(self, row: StandingOrder, qty: float, limit: float, q) -> None:
        attempt = {"n": len(row.attempts or []) + 1, "at": utcnow().isoformat(), "qty": qty, "limit": limit,
                   "bid": getattr(q, "bid", None), "ask": getattr(q, "ask", None)}
        row = await self._update(row.id, status="placing", attempts=[*(row.attempts or []), attempt])
        try:
            res = await self.engine.orders.place(self._intent(row, qty, limit))
        except Exception as exc:                                # noqa: BLE001 - a validation error, not a venue outcome
            await self._update(row.id, status="armed")
            return await self._refused(row, str(exc))
        oid = res.get("id")
        status = res.get("status")
        attempt.update({"orderId": oid, "status": status})
        row = await self._update(row.id, order_id=oid, order_ids=[*(row.order_ids or []), oid],
                                 attempts=[*(row.attempts or [])[:-1], attempt],
                                 status="working", working_since=utcnow())
        await self._journal(row, "placed", {"orderId": oid, "qty": qty, "limit": limit, "status": status})
        if status in _REFUSED:
            await self._update(row.id, status="armed", order_id=None)
            await self._refused(row, str(res.get("rejectReason") or status))

    async def _reconcile_placing(self, row: StandingOrder) -> None:
        """A crash between 'placing' and the order id being stored: find the order by its tag, never re-send."""
        tag = f"standing:{row.id}"
        async with self.engine.sf() as session:
            orders = (await session.execute(
                select(Order).where(Order.portfolio_id == row.portfolio_id, Order.symbol == row.symbol)
                .order_by(Order.created_at.desc()).limit(20))).scalars().all()
        mine = [o for o in orders if tag in (o.tags or []) and o.id not in (row.order_ids or [])]
        if mine:
            o = mine[0]
            await self._update(row.id, status="working", order_id=o.id, order_ids=[*(row.order_ids or []), o.id],
                               working_since=utcnow())
            await self._journal(row, "reconciled", {"orderId": o.id, "status": o.status})
        else:
            await self._update(row.id, status="armed")
            await self._journal(row, "reconciled", {"orderId": None, "note": "no order was created - back to armed"})

    async def _check_working(self, row: StandingOrder, now: dt.datetime) -> None:
        async with self.engine.sf() as session:
            o = await session.get(Order, row.order_id) if row.order_id else None
        if o is None:
            await self._update(row.id, status="armed", order_id=None)
            return
        if o.status in _TERMINAL:
            row = await self._account_fill(row, o)
            if o.status in _REFUSED:
                await self._update(row.id, status="armed", order_id=None)
                return await self._refused(row, str(o.reject_reason or o.status))
            remaining_qty = (float(row.qty) - float(row.filled_qty)) if row.qty else None
            if o.status == "FILLED" and (remaining_qty is None or remaining_qty < 1):
                return await self._complete(row)
            # cancelled / partially filled: back to armed - the next tick re-prices what is left
            await self._update(row.id, status="armed", order_id=None)
            return
        waited = (utcnow() - (row.working_since or utcnow())).total_seconds()
        if waited >= float(self.s("fill_wait_seconds", 60.0)):
            if len(row.attempts or []) >= int(self.s("max_attempts", 5)):
                with contextlib.suppress(Exception):
                    await self.engine.orders.cancel(o.id)
                await self._journal(row, "gave_up", {"orderId": o.id})
                return await self._finish(row, "done" if row.filled_qty else "failed",
                                          f"limit not filled after {len(row.attempts)} attempts - cancelled")
            with contextlib.suppress(Exception):
                await self.engine.orders.cancel(o.id)
            await self._journal(row, "repricing", {"orderId": o.id, "waited": round(waited)})

    async def _account_fill(self, row: StandingOrder, o: Order) -> StandingOrder:
        fq = float(o.filled_qty or 0.0)
        if fq <= 0:
            return row
        prev_q, prev_px = float(row.filled_qty or 0.0), float(row.avg_fill_price or 0.0)
        tot = prev_q + fq
        avg = (prev_q * prev_px + fq * float(o.avg_fill_price or 0.0)) / tot
        row = await self._update(row.id, filled_qty=tot, avg_fill_price=round(avg, 4))
        await self._journal(row, "filled", {"orderId": o.id, "qty": fq, "price": o.avg_fill_price,
                                            "totalQty": tot, "avg": round(avg, 4)})
        await self._push(f"{row.side} {fq:g} {row.symbol} filled @ {float(o.avg_fill_price or 0):.2f}",
                         f"standing order {row.id[:8]}: {tot:g} done so far, avg {avg:.2f}", key=f"fill:{o.id}")
        return row

    async def _complete(self, row: StandingOrder) -> None:
        if row.side == "BUY" and (row.take_profit_pct or row.stop_loss_pct) and row.filled_qty:
            avg = float(row.avg_fill_price)
            pol = exit_policy(avg, row.take_profit_pct, row.stop_loss_pct)
            stop = (pol.get("stop") or {}).get("price")
            try:
                pos = await self.engine.position_manager.adopt({
                    "portfolioId": row.portfolio_id, "symbol": row.symbol, "direction": "long",
                    "techniqueId": TECHNIQUE_ID, "tags": ["standing", f"standing:{row.id}"], "runId": row.id,
                    "entry": avg, "risk": max(avg - (stop or avg * 0.9), 0.01),
                    "legs": [{"symbol": row.symbol, "secType": "STK", "qty": float(row.filled_qty), "avgFill": avg,
                              "entryOrderId": row.order_id, "origin": "adoption"}],
                    "overnight": "venue_stop", "policy": pol, "extras": {"standingOrderId": row.id}})
                await self._update(row.id, position_id=pos.get("id"))
            except Exception as exc:                            # noqa: BLE001 - the fill stands; exits need attention
                await self._push(f"{row.symbol}: exits NOT set", f"the buy filled but adopting its exits failed: {exc}",
                                 key=f"adopt:{row.id}", level="warning")
                await self._journal(row, "exits_failed", {"error": str(exc)})
        await self._finish(row, "done", "filled")

    # ------------------------------------------------------------------ outcomes
    async def _refused(self, row: StandingOrder, reason: str) -> None:
        await self._update(row.id, last_error=reason)
        await self._journal(row, "refused", {"reason": reason})
        if "quote age" in reason.lower():
            return                                              # a timing miss: the next tick re-tries
        tries = len(row.attempts or [])
        if tries >= int(self.s("max_attempts", 5)):
            await self._finish(row, "failed", f"refused: {reason}")
        await self._push(f"{row.symbol} order refused", f"{row.side} {row.symbol} ({row.id[:8]}): {reason}",
                         key=f"refused:{row.id}:{reason[:40]}", level="warning")

    async def _fail(self, row: StandingOrder, reason: str) -> None:
        with contextlib.suppress(Exception):
            await self._finish(row, "failed", reason)

    async def _finish(self, row: StandingOrder, status: str, reason: str) -> None:
        if row.order_id and status in ("expired", "failed"):
            with contextlib.suppress(Exception):
                await self.engine.orders.cancel(row.order_id)
        row = await self._update(row.id, status=status, order_id=None,
                                 last_error=None if status == "done" else reason)
        await self._journal(row, status, {"reason": reason})
        await self._push(f"{row.symbol} standing order {status}",
                         f"{row.side} {row.symbol} ({row.id[:8]}): {reason}"
                         + (f" - {row.filled_qty:g} @ {row.avg_fill_price:.2f}" if row.filled_qty else ""),
                         key=f"finish:{row.id}", level="info" if status == "done" else "warning")

    async def _note_wait(self, row: StandingOrder, why: str) -> None:
        if row.last_error != why:
            await self._update(row.id, last_error=why)

    # ------------------------------------------------------------------ plumbing
    async def _update(self, oid: str, **fields) -> StandingOrder:
        async with self.engine.sf() as session:
            row = await session.get(StandingOrder, oid)
            for k, v in fields.items():
                setattr(row, k, v)
            await session.commit()
            await session.refresh(row)
            return row

    async def _journal(self, row: StandingOrder, stage: str, payload: dict) -> None:
        with contextlib.suppress(Exception):
            await self.engine.journal.append(ev.STANDING_ORDER, {
                "id": row.id, "stage": stage, "symbol": row.symbol, "side": row.side, "portfolioId": row.portfolio_id,
                "status": row.status, **payload}, aggregate_type="standing_order", aggregate_id=row.id,
                portfolio_id=row.portfolio_id)

    async def _push(self, title: str, body: str, *, key: str, level: str = "info") -> None:
        if key in self._alerted:
            return
        self._alerted.add(key)
        push = getattr(self.engine, "push", None)
        if push is not None:
            with contextlib.suppress(Exception):
                await push.send(title, body, url="/standing", tag="standing", level=level)

    @staticmethod
    def to_dict(r: StandingOrder) -> dict:
        return {"id": r.id, "planId": r.plan_id, "planName": r.plan_name,
                "planArmConfirm": confirm_phrase(r.plan_id) if r.plan_id else None, "portfolioId": r.portfolio_id, "symbol": r.symbol, "side": r.side, "qty": r.qty,
                "budget": r.budget, "trigger": r.trigger, "notBefore": r.not_before, "expiresOn": r.expires_on,
                "maxPrice": r.max_price, "minPrice": r.min_price, "slippagePct": r.slippage_pct,
                "takeProfitPct": r.take_profit_pct, "stopLossPct": r.stop_loss_pct, "status": r.status,
                "note": r.note, "lastError": r.last_error, "orderId": r.order_id, "orderIds": list(r.order_ids or []),
                "attempts": list(r.attempts or []), "filledQty": r.filled_qty, "avgFillPrice": r.avg_fill_price,
                "positionId": r.position_id, "armConfirm": confirm_phrase(r.id), "armedBy": r.armed_by or "user",
                "repairOf": r.repair_of, "spendAll": bool(r.spend_all), "startsOn": r.starts_on,
                "armedAt": r.armed_at.isoformat() if r.armed_at else None,
                "createdAt": r.created_at.isoformat() if r.created_at else None}


async def attach(engine) -> StandingOrderService:
    svc = StandingOrderService(engine)
    engine.standing_orders = svc
    svc.start()
    return svc
