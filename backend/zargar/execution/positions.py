"""The durable position manager — phase 2b of the platform plan (§2.4).

A `ManagedPosition` lives until its POLICY closes it: days, weeks, across
restarts, weekends, holidays and feed outages. It is the second object next to
the session plan (`planrunner.py`, which expires at each close); the Tip /
Flow / Drift / Premium techniques hold through it.

Iron-clad rules implemented here (the chaos suite in
`tests/test_position_chaos.py` is the acceptance gate — this ships with it or
not at all):

- **Write-ahead**: the position row is persisted before any order; every order
  intent carries an idempotent client id; unknown outcomes are reconciled,
  never resubmitted blindly (the venue adapters already do that half).
- **Restored on boot regardless of date** (`restore()`), order index rebuilt.
- **Decisions on CLOSED bars of the policy's timeframe** (5m/15m/1h/1d), and
  only while the venue can fill (RTH for anything with an option leg). A stale
  quote allows exits and forbids nothing else — there are no entries here.
- **The quote watch is the crash brake** (underlying decisively through the
  stop; option mark bleeding past the premium stop) — reduce-only, N
  consecutive polls, exactly the session runner's semantics.
- **`dte_close` is enforced by the manager**: `execution.min_dte` is the floor a
  technique may only raise; an ITM contract never reaches auto-exercise.
- **Overnight protection**: a share position gets a resting venue GTC stop
  (cancel/replace as the policy tightens it). Option legs cannot rest a stop at
  our venues (verified 2026-08-27) — holding them overnight requires
  `overnight="app_managed"` PLUS the explicit acknowledgement, and the position
  is flagged loudly (`appManagedOnly`) until closed.
- **Exits are reduce-only** and can never be trapped by a halt or cap; the
  failed-exit watchdog retries at market and then alerts.
- **Multi-leg is one position**: legs are a child list (put spread = short put
  + long put), P&L is the net, the policy is evaluated on the net, closes
  reduce every leg together and partial closes stay proportional.
- **Reconciliation, not trust**: on boot and every pre-open, our legs are
  compared to the broker's book; options lifecycle transitions are *explained*
  (expired worthless → closed + scored; short-put assignment → the shares are
  adopted into the SAME position with the cash delta; short-call assignment
  mirror); anything unexplained flags the position and halts new entries on
  that symbol until a person looks.

Hooks stay out: techniques configure positions with *data* (the policy, sizing,
overnight mode); they do not subclass this. The runner journals everything
(`ManagedPosition*` kinds, registered in the event contracts).
"""
from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import logging
import time
from dataclasses import dataclass, field

from sqlalchemy import select

from .. import bus as topics
from ..domain import Bar, new_id
from ..marketstructure.sessions import ET, session_date, session_window
from ..models import ManagedPositionRow
from ..options import occ as occ_mod
from .exits import reduce_only_exit_intent
from .policies import (
    DEFAULT_TIMEFRAME,
    PolicyState,
    PositionView,
    apply_moves,
    evaluate,
    has_no_stop,
    stop_price,
    validate_policy,
)

log = logging.getLogger("zargar.execution.positions")

# journal kinds (contracts registered in zargar/research/events_contract.py)
POSITION_OPENED = "ManagedPositionOpened"
POSITION_ADOPTED = "ManagedPositionAdopted"
POSITION_EXIT = "ManagedPositionExit"
POSITION_CLOSED = "ManagedPositionClosed"
POSITION_POLICY = "ManagedPositionPolicyChanged"
POSITION_RECONCILED = "ManagedPositionReconciled"
POSITION_ATTENTION = "ManagedPositionAttention"
POSITION_SCALED = "ManagedPositionScaledIn"

TF_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "1d": 390}


@dataclass
class Leg:
    """One instrument inside the position. qty is SIGNED (+long / -short)."""
    symbol: str                    # what is traded (unpadded OCC for options, ticker for shares)
    sec_type: str                  # STK | OPT
    qty: float                     # signed
    avg_fill: float | None = None
    multiplier: float = 1.0
    entry_order_id: str | None = None
    origin: str = "entry"          # entry | assignment | adoption

    def to_dict(self) -> dict:
        return {"symbol": self.symbol, "secType": self.sec_type, "qty": self.qty, "avgFill": self.avg_fill,
                "multiplier": self.multiplier, "entryOrderId": self.entry_order_id, "origin": self.origin}

    @classmethod
    def from_dict(cls, d: dict) -> "Leg":
        return cls(symbol=str(d["symbol"]), sec_type=str(d.get("secType") or "STK"),
                   qty=float(d.get("qty") or 0), avg_fill=d.get("avgFill"),
                   multiplier=float(d.get("multiplier") or 1.0), entry_order_id=d.get("entryOrderId"),
                   origin=str(d.get("origin") or "entry"))

    def dte(self, today: dt.date | None = None) -> int | None:
        if self.sec_type != "OPT":
            return None
        o = occ_mod.parse(self.symbol)
        return o.dte(today) if o else None


@dataclass
class Managed:
    """In-memory shape of one durable position (the DB row is the projection)."""
    id: str
    portfolio_id: str
    symbol: str                    # the underlying
    direction: str                 # long | short (the idea's side, on the underlying)
    technique: str
    policy: dict
    legs: list[Leg]
    entry: float                   # underlying reference entry
    risk: float
    status: str = "open"           # open | closing | closed | attention
    overnight: str = "venue_stop"  # venue_stop | app_managed | day_only
    overnight_ack: bool = False
    tags: list[str] = field(default_factory=list)
    run_id: str | None = None
    state: PolicyState = field(default_factory=PolicyState)
    entry_mark: float | None = None      # net premium per unit (+debit / -credit) at open
    realized_pnl: float = 0.0
    exits: list[dict] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    sessions_seen: list[str] = field(default_factory=list)   # ET session dates with bars since open
    opened_ms: int = 0
    closed_ms: int | None = None
    last_tf_bar_ts: int | None = None
    venue_stop_order_id: str | None = None
    venue_stop_at: float | None = None
    attention: list[str] = field(default_factory=list)
    halt_entries: bool = False           # set by reconciliation on unexplained drift

    # ---------------------------------------------------------------- views
    @property
    def open_legs(self) -> list[Leg]:
        return [l for l in self.legs if abs(l.qty) > 1e-9]

    @property
    def has_options(self) -> bool:
        return any(l.sec_type == "OPT" for l in self.open_legs)

    def dte_min(self, today: dt.date | None = None) -> int | None:
        ds = [d for d in (l.dte(today) for l in self.open_legs) if d is not None]
        return min(ds) if ds else None

    def sessions_held(self) -> int:
        return max(0, len(self.sessions_seen) - 1)     # the opening session is day 0

    def net_mark(self, quote_of) -> float | None:
        """Net premium per unit across option legs, marked at bid (long) / ask
        (short) — what a close-now would roughly cost/realize. None when any
        open option leg has no usable quote."""
        opt = [l for l in self.open_legs if l.sec_type == "OPT"]
        if not opt:
            return None
        unit = min(abs(l.qty) for l in opt)
        total = 0.0
        for l in opt:
            q = quote_of(l.symbol)
            if q is None:
                return None
            px = (q.bid if l.qty > 0 else q.ask)
            px = float(px) if px and px > 0 else (float(q.last) if q.last and q.last > 0 else None)
            if px is None:
                return None
            total += (1 if l.qty > 0 else -1) * px * (abs(l.qty) / unit)
        return round(total, 4)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "portfolioId": self.portfolio_id, "symbol": self.symbol,
            "direction": self.direction, "technique": self.technique, "status": self.status,
            "policy": self.policy, "legs": [l.to_dict() for l in self.legs],
            "entry": self.entry, "risk": self.risk, "entryMark": self.entry_mark,
            "overnight": self.overnight, "overnightAck": self.overnight_ack,
            "appManagedOnly": self.overnight == "app_managed" and self.has_options,
            "tags": list(self.tags), "runId": self.run_id,
            "state": self.state.to_dict(), "realizedPnl": round(self.realized_pnl, 2),
            "exits": self.exits[-40:], "events": self.events[-100:],
            "sessionsSeen": self.sessions_seen, "sessionsHeld": self.sessions_held(),
            "openedMs": self.opened_ms, "closedMs": self.closed_ms,
            "lastTfBarTs": self.last_tf_bar_ts,
            "venueStopOrderId": self.venue_stop_order_id, "venueStopAt": self.venue_stop_at,
            "attention": self.attention, "haltEntries": self.halt_entries,
        }


class PositionManager:
    """Owns every durable position. One instance on the engine
    (`engine.position_manager`), started with it, restored on boot."""

    def __init__(self, engine) -> None:
        self.engine = engine
        self._pos: dict[str, Managed] = {}
        self._bar_task: asyncio.Task | None = None
        self._watch_task: asyncio.Task | None = None
        self._orders_task: asyncio.Task | None = None
        self._order_index: dict[str, str] = {}
        self._breaches: dict[tuple[str, str], int] = {}
        self._exit_retries: dict[tuple[str, str], tuple[float, int]] = {}
        self._last_decide: dict[str, int] = {}   # position id -> raw-bar ts last decided on
        self._entry_halted: set[str] = set()           # symbols where reconciliation found drift
        self._now = time.time                          # injectable clock (chaos tests)

    # ---------------------------------------------------------------- helpers
    def now_ms(self) -> int:
        return int(self._now() * 1000)

    def _setting(self, key: str, default):
        return self.engine.settings.get(key, default)

    def min_dte_floor(self) -> int:
        return max(0, int(self._setting("execution.min_dte", 1) or 0))

    def positions(self, *, status: str | None = None) -> list[dict]:
        out = [p.to_dict() for p in self._pos.values() if status is None or p.status == status]
        out.sort(key=lambda d: d["openedMs"], reverse=True)
        return out

    def get(self, pid: str) -> Managed | None:
        return self._pos.get(pid)

    def entries_halted(self, symbol: str) -> bool:
        return symbol.upper() in self._entry_halted

    # ---------------------------------------------------------------- lifecycle
    def start(self) -> None:
        if self._bar_task is None:
            self._bar_task = asyncio.create_task(self._bar_loop(), name="positions-bars")
        if self._watch_task is None:
            self._watch_task = asyncio.create_task(self._watch_loop(), name="positions-watch")
        if getattr(self, "_orders_task", None) is None:
            self._orders_task = asyncio.create_task(self._orders_loop(), name="positions-orders")

    async def stop(self) -> None:
        for attr in ("_bar_task", "_watch_task", "_orders_task"):
            t = getattr(self, attr)
            if t is not None:
                t.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await t
                setattr(self, attr, None)

    async def restore(self) -> int:
        """Reload every non-closed position, whatever its date (a position that
        slept through a weekend keeps being managed on Monday)."""
        async with self.engine.sf() as session:
            rows = (await session.execute(select(ManagedPositionRow).where(
                ManagedPositionRow.status.in_(("open", "closing", "attention", "opening"))))).scalars().all()
        n = 0
        for row in rows:
            try:
                p = self._from_row(row)
                if p.status == "opening":
                    # a crash mid-open: some legs may exist at the broker with no manager —
                    # a person must look before anything else happens on this symbol
                    p.status = "attention"
                    p.attention.append("restart interrupted the open — verify the legs at the broker")
                    p.halt_entries = True
                    self._entry_halted.add(p.symbol.upper())
                self._pos[p.id] = p
                for l in p.legs:
                    if l.entry_order_id:
                        pass                            # entry orders are terminal by now; exits re-register below
                for x in p.exits:
                    if x.get("orderId") and x.get("status") in (None, "SUBMITTED", "WORKING", "PARTIALLY_FILLED"):
                        self._register_exit_order(p, x["orderId"])
                # the feeds must follow the position across a restart: the stop
                # is judged on the UNDERLYING's bars/quotes and the premium stop
                # on each leg's — RKLB's underlying went unwatched after an
                # 11:1x restart on 2026-09-02 (last bar 10:59, stop blind)
                for sym in [p.symbol, *[l.symbol for l in p.legs]]:
                    with contextlib.suppress(Exception):
                        await self.engine.ensure_symbol(sym)
                n += 1
            except Exception:
                log.exception("restoring managed position %s failed", row.id)
        if n:
            log.info("restored %d managed position(s)", n)
        return n

    def _from_row(self, row: ManagedPositionRow) -> Managed:
        cfg = row.config or {}
        st = row.state or {}
        p = Managed(
            id=row.id, portfolio_id=row.portfolio_id, symbol=row.symbol,
            direction=str(cfg.get("direction") or "long"), technique=row.technique or "generic",
            policy=dict(cfg.get("policy") or {}), legs=[Leg.from_dict(d) for d in (row.legs or [])],
            entry=float(cfg.get("entry") or 0), risk=float(cfg.get("risk") or 0) or 1e-9,
            status=row.status, overnight=str(cfg.get("overnight") or "venue_stop"),
            overnight_ack=bool(cfg.get("overnightAck")), tags=list(row.tags or []),
            run_id=cfg.get("runId"), state=PolicyState.from_dict(st.get("policyState")),
            entry_mark=cfg.get("entryMark"), realized_pnl=float(st.get("realizedPnl") or 0),
            exits=list(st.get("exits") or []), events=list(st.get("events") or []),
            sessions_seen=list(st.get("sessionsSeen") or []),
            opened_ms=int(st.get("openedMs") or 0), closed_ms=st.get("closedMs"),
            last_tf_bar_ts=st.get("lastTfBarTs"),
            venue_stop_order_id=st.get("venueStopOrderId"), venue_stop_at=st.get("venueStopAt"),
            attention=list(st.get("attention") or []), halt_entries=bool(st.get("haltEntries")),
        )
        return p

    async def _persist(self, p: Managed) -> None:
        try:
            async with self.engine.sf() as session:
                row = await session.get(ManagedPositionRow, p.id)
                cfg = {"direction": p.direction, "policy": p.policy, "entry": p.entry, "risk": p.risk,
                       "overnight": p.overnight, "overnightAck": p.overnight_ack, "runId": p.run_id,
                       "entryMark": p.entry_mark}
                st = {"policyState": p.state.to_dict(), "realizedPnl": round(p.realized_pnl, 2),
                      "exits": p.exits[-100:], "events": p.events[-200:], "sessionsSeen": p.sessions_seen,
                      "openedMs": p.opened_ms, "closedMs": p.closed_ms, "lastTfBarTs": p.last_tf_bar_ts,
                      "venueStopOrderId": p.venue_stop_order_id, "venueStopAt": p.venue_stop_at,
                      "attention": p.attention, "haltEntries": p.halt_entries}
                if row is None:
                    row = ManagedPositionRow(id=p.id, technique=p.technique, symbol=p.symbol,
                                             portfolio_id=p.portfolio_id, status=p.status, tags=list(p.tags),
                                             config=cfg, legs=[l.to_dict() for l in p.legs], state=st)
                    session.add(row)
                else:
                    row.status = p.status
                    row.config = cfg
                    row.legs = [l.to_dict() for l in p.legs]
                    row.state = st
                    row.tags = list(p.tags)
                    row.updated_at = dt.datetime.now(dt.timezone.utc)
                await session.commit()
        except Exception:
            log.exception("persisting managed position failed")

    def _log(self, p: Managed, what: str, text: str, **detail) -> None:
        p.events.append({"ts": self.now_ms(), "event": what, "text": text, **detail})
        if len(p.events) > 300:
            del p.events[:-300]

    async def _journal(self, kind: str, p: Managed, extra: dict | None = None) -> None:
        payload = {"positionId": p.id, "technique": p.technique, "symbol": p.symbol,
                   "portfolioId": p.portfolio_id, "status": p.status, **(extra or {})}
        with contextlib.suppress(Exception):
            await self.engine.journal.append(kind, payload, aggregate_type="managed_position",
                                             aggregate_id=p.id, portfolio_id=p.portfolio_id)
        with contextlib.suppress(Exception):
            self.engine.bus.publish(topics.TECHNIQUE, {"kind": "position", "event": kind, "position": p.to_dict()})

    async def _alert(self, p: Managed, text: str, *, level: str = "critical", stage: str = "alert") -> None:
        self._log(p, "alert", text)
        await self._journal(POSITION_ATTENTION, p, {"error": text, "level": level, "stage": stage})
        with contextlib.suppress(Exception):
            self.engine.bus.publish(topics.TECHNIQUE, {"kind": "alert", "level": level,
                                                       "text": f"{p.symbol} position: {text}"})
        tg = getattr(self.engine, "telegram", None)
        if tg is not None:
            with contextlib.suppress(Exception):
                await tg.send(f"⚠ {p.symbol} managed position: {text}")

    # ---------------------------------------------------------------- open / adopt
    def _validate_spec(self, spec: dict) -> list[str]:
        problems = validate_policy(spec.get("policy") or {})
        legs = spec.get("legs") or []
        if not legs:
            problems.append("a position needs at least one leg")
        overnight = str(spec.get("overnight") or "venue_stop")
        if overnight not in ("venue_stop", "app_managed", "day_only"):
            problems.append(f"unknown overnight mode {overnight!r}")
        has_opt = any((l.get("secType") or "STK") == "OPT" for l in legs)
        if overnight == "venue_stop" and has_opt:
            problems.append("option legs cannot rest a stop at the venue (verified 2026-08-27) — "
                            "hold options overnight with overnight='app_managed' and overnightAck=true, "
                            "or overnight='day_only'")
        if overnight == "app_managed" and not bool(spec.get("overnightAck")):
            problems.append("overnight='app_managed' requires the explicit acknowledgement (overnightAck) — "
                            "the app being down would leave this position unprotected")
        if has_no_stop(spec.get("policy") or {}):
            # legal only with a declared guard AND a real loss-halt link on the account
            if not float(spec.get("dailyLossLink") or 0) and not spec.get("guardAccepted"):
                problems.append("a no-stop policy also needs guardAccepted=true (the declared portfolio-level "
                                "guard is a decision, not a default)")
        return problems

    async def open(self, spec: dict) -> dict:
        """Place the entry legs and manage the result. Write-ahead: the position
        row exists (status=opening) before any order. Legs the risk gate rejects
        fail the whole open (partial multi-leg entries are rolled back at market)."""
        problems = self._validate_spec(spec)
        sym = str(spec.get("symbol") or "").upper()
        if sym in self._entry_halted:
            problems.append(f"new entries on {sym} are halted (unexplained reconciliation drift) — "
                            "clear it from the positions API after checking the broker")
        if problems:
            raise ValueError("; ".join(problems))
        from ..orders import OrderIntent
        p = Managed(
            id=new_id(), portfolio_id=str(spec["portfolioId"]), symbol=sym,
            direction=str(spec.get("direction") or "long"), technique=str(spec.get("techniqueId") or "generic"),
            policy=dict(spec.get("policy") or {}), legs=[], entry=float(spec.get("entry") or 0),
            risk=max(float(spec.get("risk") or 0), 1e-9), status="opening",
            overnight=str(spec.get("overnight") or "venue_stop"), overnight_ack=bool(spec.get("overnightAck")),
            tags=[str(t) for t in (spec.get("tags") or [])], run_id=spec.get("runId"),
            opened_ms=self.now_ms(),
        )
        p.state = PolicyState(stop=stop_price(p.policy, PolicyState()))
        await self._persist(p)                          # write-ahead
        self._pos[p.id] = p
        filled: list[Leg] = []
        for legspec in spec["legs"]:
            sec = str(legspec.get("secType") or "STK")
            side = str(legspec.get("side") or "BUY").upper()
            qty = float(legspec.get("qty") or 0)
            intent = OrderIntent(
                portfolio_id=p.portfolio_id, symbol=str(legspec["symbol"]), sec_type=sec, side=side,
                qty=qty, order_type=str(legspec.get("orderType") or "LMT"),
                limit_price=legspec.get("limitPrice"), tif="DAY", source="technique",
                technique_id=p.technique, tags=list(p.tags))
            try:
                res = await self.engine.orders.place(intent)
            except Exception as exc:
                res = {"status": "ERROR", "rejectReason": f"{type(exc).__name__}: {exc}"}
            status = res.get("status")
            if status in ("REJECTED", "REJECTED_RISK", "ERROR"):
                self._log(p, "entry_rejected", f"{legspec['symbol']}: {res.get('rejectReason') or status}")
                # roll back what already filled — a half-open spread is unmanaged risk
                for done in filled:
                    with contextlib.suppress(Exception):
                        await self._close_leg(p, done, abs(done.qty), force_market=True,
                                              kind="rollback", reason="another leg was rejected")
                p.status = "closed"
                p.closed_ms = self.now_ms()
                await self._persist(p)
                self._pos.pop(p.id, None)
                raise ValueError(f"leg {legspec['symbol']} was rejected: {res.get('rejectReason') or status}")
            signed = qty if side == "BUY" else -qty
            leg = Leg(symbol=str(legspec["symbol"]).upper(), sec_type=sec, qty=signed,
                      avg_fill=res.get("avgFillPrice"), multiplier=100.0 if sec == "OPT" else 1.0,
                      entry_order_id=res.get("id"))
            p.legs.append(leg)
            filled.append(leg)
        p.entry_mark = self._entry_mark(p)
        p.status = "open"
        today = session_date(self.now_ms())
        p.sessions_seen = [today]
        await self._persist(p)
        await self._journal(POSITION_OPENED, p, {"legs": [l.to_dict() for l in p.legs],
                                                 "policy": p.policy, "tags": p.tags})
        self._log(p, "opened", f"{len(p.legs)} leg(s), policy tf {p.policy.get('timeframe', DEFAULT_TIMEFRAME)}")
        await self._ensure_venue_stop(p)
        self.start()
        return p.to_dict()

    async def adopt(self, spec: dict) -> dict:
        """Create a managed position from fills that already exist (an approved
        proposal, an assignment, a manual buy the user wants managed)."""
        problems = self._validate_spec(spec)
        if problems:
            raise ValueError("; ".join(problems))
        p = Managed(
            id=new_id(), portfolio_id=str(spec["portfolioId"]), symbol=str(spec.get("symbol") or "").upper(),
            direction=str(spec.get("direction") or "long"), technique=str(spec.get("techniqueId") or "generic"),
            policy=dict(spec.get("policy") or {}),
            legs=[Leg.from_dict({**l, "origin": l.get("origin") or "adoption"}) for l in spec["legs"]],
            entry=float(spec.get("entry") or 0), risk=max(float(spec.get("risk") or 0), 1e-9),
            overnight=str(spec.get("overnight") or "venue_stop"), overnight_ack=bool(spec.get("overnightAck")),
            tags=[str(t) for t in (spec.get("tags") or [])], run_id=spec.get("runId"),
            opened_ms=self.now_ms(),
        )
        p.state = PolicyState(stop=stop_price(p.policy, PolicyState()))
        p.entry_mark = spec.get("entryMark", self._entry_mark(p))
        p.sessions_seen = [session_date(self.now_ms())]
        self._pos[p.id] = p
        # the underlying's bars/quotes drive the stop; the legs' quotes drive
        # the premium stop — both must be flowing from the moment we manage
        for sym in [p.symbol, *[l.symbol for l in p.legs]]:
            with contextlib.suppress(Exception):
                await self.engine.ensure_symbol(sym)
        await self._persist(p)
        await self._journal(POSITION_ADOPTED, p, {"legs": [l.to_dict() for l in p.legs], "policy": p.policy})
        await self._ensure_venue_stop(p)
        self.start()
        return p.to_dict()

    async def append_leg(self, pid: str, leg: dict, *,
                         entry_ref: float | None = None) -> dict | None:
        """Scale-in accumulation (tips, ARM-PLAN P3): a later fill of the same
        idea joins the existing position — the leg list grows, the underlying
        reference entry re-averages (weighted by |qty|), the entry mark
        recomputes. The policy is untouched: ONE exit campaign over the
        combined size."""
        p = self._pos.get(pid)
        if p is None or p.status not in ("open", "attention"):
            return None
        new = Leg.from_dict({**leg, "origin": leg.get("origin") or "scale_in"})
        old_abs = sum(abs(l.qty) for l in p.legs) or 1.0
        p.legs.append(new)
        if entry_ref and entry_ref > 0:
            tot = old_abs + abs(new.qty)
            p.entry = (p.entry * old_abs + float(entry_ref) * abs(new.qty)) / tot
        p.entry_mark = self._entry_mark(p)
        await self._persist(p)
        await self._journal(POSITION_SCALED, p, {"leg": new.to_dict(),
                                                 "entry": round(p.entry, 4)})
        self._log(p, "scaled_in",
                  f"+{abs(new.qty):g} {new.symbol} — entry re-averaged to {p.entry:.4f}")
        await self._ensure_venue_stop(p)
        return p.to_dict()

    def _entry_mark(self, p: Managed) -> float | None:
        opt = [l for l in p.legs if l.sec_type == "OPT"]
        if not opt or any(l.avg_fill is None for l in opt):
            return None
        unit = min(abs(l.qty) for l in opt)
        return round(sum((1 if l.qty > 0 else -1) * float(l.avg_fill) * (abs(l.qty) / unit) for l in opt), 4)

    # ---------------------------------------------------------------- venue stop
    async def _ensure_venue_stop(self, p: Managed) -> None:
        """Share positions that may be held overnight get a resting GTC stop at
        the venue; the app being down must never leave them naked. Tightened
        stops cancel + replace."""
        if p.overnight != "venue_stop" or p.status not in ("open",):
            return
        stk = [l for l in p.open_legs if l.sec_type == "STK" and l.qty > 0]
        if not stk:
            return
        stop = stop_price(p.policy, p.state)
        if stop is None:
            return
        if p.venue_stop_order_id and p.venue_stop_at is not None and abs(p.venue_stop_at - stop) < 1e-9:
            return
        from ..orders import OrderIntent
        if p.venue_stop_order_id:
            with contextlib.suppress(Exception):
                await self.engine.orders.cancel(p.venue_stop_order_id)
        leg = stk[0]
        intent = OrderIntent(portfolio_id=p.portfolio_id, symbol=leg.symbol, sec_type="STK", side="SELL",
                             qty=abs(leg.qty), order_type="STP", stop_price=round(float(stop), 2), tif="GTC",
                             source="technique", technique_id=p.technique, tags=list(p.tags), reduce_only=True)
        try:
            res = await self.engine.orders.place(intent)
            p.venue_stop_order_id = res.get("id")
            p.venue_stop_at = float(stop)
            self._register_exit_order(p, p.venue_stop_order_id)
            self._log(p, "venue_stop", f"resting GTC stop {stop:.2f} at the venue (order {str(res.get('id'))[:8]})")
        except Exception as exc:
            await self._alert(p, f"could not place the venue GTC stop at {stop:.2f}: {exc} — "
                              f"the position is app-managed until this succeeds", level="warning",
                              stage="venue_stop")
        await self._persist(p)

    # ---------------------------------------------------------------- exits
    _EXIT_DEAD = ("REJECTED", "REJECTED_RISK", "CANCELLED", "EXPIRED", "ERROR")

    def _register_exit_order(self, p: Managed, order_id: str | None) -> None:
        if order_id:
            self._order_index[order_id] = p.id

    def _inflight_exit_qty(self, p: Managed, leg_symbol: str) -> float:
        """Qty this position is already trying to exit on `leg_symbol` — submitted
        but not yet filled or dead. New exits may only cover what's left beyond it.
        A record with zero fills past the TTL stops counting: a zombie order
        (crashed venue, lost ack) must never block getting flat."""
        ttl_ms = int(float(self._setting("execution.exit_inflight_ttl_seconds", 900) or 900) * 1000)
        now = self.now_ms()
        out = 0.0
        for rec in p.exits:
            if rec.get("leg") != leg_symbol or rec.get("status") in self._EXIT_DEAD:
                continue
            if (float(rec.get("filledQty") or 0) <= 0
                    and rec.get("ts") and now - rec["ts"] > ttl_ms):
                continue
            out += max(0.0, float(rec.get("qty") or 0) - float(rec.get("filledQty") or 0))
        return out

    async def _close_leg(self, p: Managed, leg: Leg, qty: float, *, force_market: bool,
                         kind: str, reason: str) -> dict | None:
        qty = float(int(min(qty, abs(leg.qty)))) if leg.sec_type == "OPT" else float(min(qty, abs(leg.qty)))
        # total outstanding exits must never exceed the leg: a policy decision,
        # the quote watch and a manual close can race a slow fill, and the
        # overshoot flips the position past flat. A further ladder rung while an
        # earlier one is still filling stays legal — only the overlap is cut.
        avail = abs(leg.qty) - self._inflight_exit_qty(p, leg.symbol)
        qty = min(qty, avail)
        if leg.sec_type == "OPT":
            qty = float(int(qty))
        if qty <= 0:
            self._log(p, "exit_skip",
                      f"{kind} {leg.symbol}: exits already in flight cover this qty")
            return None
        closing_short = leg.qty < 0
        if closing_short:
            # buying back a short leg is reduce-only in spirit but is a BUY order
            from ..orders import OrderIntent
            q = self.engine.quotes.get(leg.symbol)
            ask = float(q.ask) if q is not None and q.ask and q.ask > 0 else None
            intent = OrderIntent(portfolio_id=p.portfolio_id, symbol=leg.symbol, sec_type=leg.sec_type,
                                 side="BUY", qty=qty,
                                 order_type=("LMT" if (ask and not force_market) else "MKT"),
                                 limit_price=(round(ask, 2) if (ask and not force_market) else None),
                                 tif="DAY", source="technique", technique_id=p.technique,
                                 tags=list(p.tags), reduce_only=True)
        else:
            q = self.engine.quotes.get(leg.symbol)
            bid = float(q.bid) if q is not None and q.bid and q.bid > 0 else None
            intent = reduce_only_exit_intent(portfolio_id=p.portfolio_id, symbol=leg.symbol,
                                             sec_type=leg.sec_type, qty=qty, bid=bid,
                                             force_market=force_market, source="technique",
                                             technique_id=p.technique)
        rec = {"kind": kind, "leg": leg.symbol, "qty": qty, "orderId": None, "status": None,
               "filledQty": 0.0, "price": None, "ts": self.now_ms(), "reason": reason}
        p.exits.append(rec)
        await self._journal(POSITION_EXIT, p, {"kind": kind, "leg": leg.symbol, "qty": qty,
                                               "reduceOnly": True, "reason": reason})
        try:
            res = await self.engine.orders.place(intent)
        except Exception as exc:
            rec["status"] = "ERROR"
            rec["error"] = f"{type(exc).__name__}: {exc}"
            await self._alert(p, f"exit {kind} on {leg.symbol} errored: {exc} — watchdog will retry",
                              stage="exit_failed")
            return None
        rec["orderId"] = res.get("id")
        rec["status"] = res.get("status")
        self._register_exit_order(p, rec["orderId"])
        if rec["status"] in ("REJECTED", "REJECTED_RISK"):
            rec["error"] = res.get("rejectReason")
            await self._alert(p, f"exit {kind} on {leg.symbol} REJECTED — {rec['error']} "
                              f"(watchdog will retry)", stage="exit_failed")
        elif rec["status"] in ("FILLED", "PARTIALLY_FILLED"):
            await self.on_order_update(res)
        await self._persist(p)
        return rec

    async def close(self, pid: str, *, fraction: float = 1.0, reason: str = "manual close",
                    kind: str = "close", force_market: bool = False) -> dict | None:
        """Reduce every open leg together (partial closes stay proportional)."""
        p = self._pos.get(pid)
        if p is None:
            return None
        fraction = min(1.0, max(0.0, fraction))
        if fraction >= 1.0 - 1e-9:
            p.status = "closing"
        # cancel a resting venue stop first so it can't double-fill with the close
        if p.venue_stop_order_id and fraction >= 1.0 - 1e-9:
            with contextlib.suppress(Exception):
                await self.engine.orders.cancel(p.venue_stop_order_id)
            p.venue_stop_order_id = None
            p.venue_stop_at = None
        # a forced (stop) close supersedes any resting limit exit: cancel it so
        # the in-flight guard doesn't suppress the stop, and mark it dead
        # optimistically — a zombie order must never block getting flat
        if force_market:
            for rec in p.exits:
                if rec.get("orderId") and rec.get("status") not in self._EXIT_DEAD + ("FILLED",):
                    with contextlib.suppress(Exception):
                        await self.engine.orders.cancel(rec["orderId"])
                    rec["status"] = "CANCELLED"
        self._log(p, "close", f"closing {fraction:.0%} — {reason}")
        for leg in list(p.open_legs):
            want = abs(leg.qty) * fraction
            if leg.sec_type == "OPT":
                want = float(int(round(want))) or (1.0 if fraction > 0 else 0.0)
            await self._close_leg(p, leg, want, force_market=force_market, kind=kind, reason=reason)
        await self._persist(p)
        return p.to_dict()

    async def set_policy(self, pid: str, policy: dict) -> dict | None:
        p = self._pos.get(pid)
        if p is None:
            return None
        problems = validate_policy(policy)
        if problems:
            raise ValueError("; ".join(problems))
        old_tf = p.policy.get("timeframe", DEFAULT_TIMEFRAME)
        p.policy = dict(policy)
        new_stop = stop_price(p.policy, PolicyState())
        if new_stop is not None:
            short = p.direction == "short"
            if p.state.stop is None or (new_stop > p.state.stop if not short else new_stop < p.state.stop):
                p.state.stop = new_stop            # a policy change may only TIGHTEN the live stop
        self._log(p, "policy_changed", f"policy updated (tf {old_tf} -> {p.policy.get('timeframe', old_tf)})")
        await self._journal(POSITION_POLICY, p, {"policy": p.policy})
        await self._ensure_venue_stop(p)
        await self._persist(p)
        return p.to_dict()

    # ---------------------------------------------------------------- order updates
    async def on_order_update(self, o: dict) -> None:
        idx = getattr(self, "_order_index", {})
        pid = idx.get(o.get("id"))
        if not pid:
            return
        p = self._pos.get(pid)
        if p is None:
            return
        status = o.get("status")
        rec = next((x for x in p.exits if x.get("orderId") == o["id"]), None)
        if o["id"] == p.venue_stop_order_id and status in ("FILLED", "PARTIALLY_FILLED"):
            rec = rec or {"kind": "venue_stop", "leg": o.get("symbol"), "qty": float(o.get("filledQty") or 0),
                          "orderId": o["id"], "status": status, "filledQty": 0.0, "price": None,
                          "ts": self.now_ms(), "reason": "venue-side GTC stop"}
            if rec not in p.exits:
                p.exits.append(rec)
        if rec is None:
            return
        if status in ("FILLED", "PARTIALLY_FILLED"):
            fq = float(o.get("filledQty") or 0)
            prev = float(rec.get("filledQty") or 0)
            if fq > prev:
                rec["filledQty"] = fq
                rec["price"] = o.get("avgFillPrice")
                leg = next((l for l in p.legs if l.symbol == (o.get("symbol") or "").upper()
                            or l.symbol == rec.get("leg")), None)
                if leg is not None:
                    delta = fq - prev
                    signed_delta = -delta if leg.qty > 0 else delta
                    px = float(rec.get("price") or 0)
                    if leg.avg_fill is not None and px:
                        per_unit = (px - float(leg.avg_fill)) if leg.qty > 0 else (float(leg.avg_fill) - px)
                        p.realized_pnl += per_unit * delta * leg.multiplier
                    leg.qty += signed_delta
                rec["status"] = status
                self._exit_retries.pop((p.id, "exit"), None)      # a fill resets the watchdog
                self._log(p, "exit_fill", f"{rec['kind']} {rec.get('leg')}: {fq:g} @ {rec.get('price')}")
                if not p.open_legs and p.status != "closed":
                    await self._mark_closed(p, reason=rec.get("reason") or rec["kind"])
                await self._persist(p)
        elif status in ("REJECTED", "REJECTED_RISK", "CANCELLED", "EXPIRED"):
            rec["status"] = status
            rec["error"] = o.get("rejectReason")
            if status in ("REJECTED", "REJECTED_RISK"):
                await self._alert(p, f"exit {rec['kind']} {rec.get('leg')} {status} — {rec.get('error')}",
                                  stage="exit_failed")
            await self._persist(p)

    async def _mark_closed(self, p: Managed, *, reason: str) -> None:
        p.status = "closed"
        p.closed_ms = self.now_ms()
        if p.venue_stop_order_id:
            with contextlib.suppress(Exception):
                await self.engine.orders.cancel(p.venue_stop_order_id)
            p.venue_stop_order_id = None
        await self._journal(POSITION_CLOSED, p, {"realizedPnl": round(p.realized_pnl, 2), "reason": reason,
                                                 "sessionsHeld": p.sessions_held()})
        self._log(p, "closed", f"{reason} — realized {p.realized_pnl:+.2f}")
        self._pos.pop(p.id, None)
        await self._persist(p)

    # ---------------------------------------------------------------- bar loop
    async def _orders_loop(self) -> None:
        async with self.engine.bus.subscription(topics.ORDERS) as q:
            while True:
                msg = await q.get()
                try:
                    if msg.get("id") in getattr(self, "_order_index", {}):
                        await self.on_order_update(msg)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    log.exception("position order handling failed")

    async def _bar_loop(self) -> None:
        async with self.engine.bus.subscription(topics.BARS) as q:
            while True:
                msg = await q.get()
                try:
                    if msg.get("tf") != "1m":
                        continue
                    bar = msg.get("bar")
                    symbol = msg.get("symbol")
                    for p in [x for x in self._pos.values() if x.symbol == symbol and x.status in ("open", "closing", "attention")]:
                        await self.on_minute_bar(p, bar)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    log.exception("position bar handling failed")

    async def on_minute_bar(self, p: Managed, bar: Bar) -> None:
        """Advance the session ledger on every RTH 1m bar; DECIDE only when a bar
        of the policy's timeframe has closed."""
        w = session_window(bar.ts)
        if w == "extended":
            return                                       # R6.5 stays runner-core here too
        day = session_date(bar.ts)
        if day not in p.sessions_seen:
            p.sessions_seen.append(day)
        tf = str(p.policy.get("timeframe", DEFAULT_TIMEFRAME))
        step = TF_MINUTES.get(tf, 5)
        if tf == "1d":
            # the daily decision runs on the last RTH bar of the session
            closes_tf = (bar.ts // 60_000) % 390 == 0 or session_window(bar.ts + 60_000) == "extended"
        else:
            closes_tf = ((bar.ts // 60_000) + 1) % step == 0
        if not closes_tf:
            return
        tf_bars = self.engine.bars.bars(p.symbol, tf="5m" if tf == "1d" else tf, limit=40, include_forming=False) \
            if hasattr(self.engine, "bars") else []
        tfbar = tf_bars[-1] if tf_bars else bar
        if p.last_tf_bar_ts is not None and tfbar.ts <= p.last_tf_bar_ts:
            tfbar = bar                                  # fall back to the raw bar (tests feed those directly)
        p.last_tf_bar_ts = max(p.last_tf_bar_ts or 0, tfbar.ts)
        # a re-delivered closing minute (the ~5s exchange-corrected bar, or any
        # duplicate on the bus) must not re-run the policy: the first decision's
        # exit order can still be unfilled, and a second full-size exit turns a
        # long into a naked short (AAPL +4 → -4, 2026-08-31)
        if self._last_decide.get(p.id, -1) >= bar.ts:
            return
        self._last_decide[p.id] = bar.ts
        await self._decide(p, tfbar, tf_bars or [bar])

    async def _decide(self, p: Managed, bar: Bar, bars: list[Bar]) -> None:
        days_to_event = None
        fb = p.policy.get("flatten_before") or {}
        if fb and getattr(self.engine, "calendar", None) is not None:
            with contextlib.suppress(Exception):
                if fb.get("event") == "earnings":
                    days_to_event = await self.engine.calendar.days_to_earnings(p.symbol)
                elif fb.get("event") == "ex_dividend":
                    days_to_event = await self.engine.calendar.days_to_ex_dividend(p.symbol)
        view = PositionView(
            direction=p.direction, entry=p.entry, risk=p.risk, bar=bar, bars=bars,
            net_mark=p.net_mark(self.engine.quotes.get), entry_mark=p.entry_mark,
            dte_min=p.dte_min(dt.datetime.fromtimestamp(self.now_ms() / 1000, ET).date()),
            sessions_held=p.sessions_held(), days_to_event=days_to_event,
            min_dte_floor=self.min_dte_floor(),
        )
        decisions, moves = evaluate(p.policy, p.state, view)
        old_stop = p.state.stop
        p.state = apply_moves(p.state, view, decisions, moves)
        if p.state.stop != old_stop and p.state.stop is not None:
            self._log(p, "stop_moved", f"stop -> {p.state.stop:.4f}")
            await self._ensure_venue_stop(p)
        for d in decisions:
            self._log(p, d.kind, d.reason)
            await self.close(p.id, fraction=d.fraction, reason=d.reason, kind=d.kind,
                             force_market=d.kind in ("stop", "premium_stop"))
        if not decisions:
            await self._persist(p)

    # ---------------------------------------------------------------- quote watch + watchdog
    async def _watch_loop(self) -> None:
        await asyncio.sleep(1.0)
        while True:
            try:
                await self._watch_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("position quote watch failed")
            await asyncio.sleep(max(0.05, float(self._setting("execution.quote_exit_seconds", 2.0) or 2.0)))

    async def _watch_once(self) -> None:
        if not self._pos:
            return
        excess = float(self._setting("execution.quote_exit_excess_r", 0.25) or 0.25)
        need = max(1, int(self._setting("execution.quote_exit_polls", 2) or 2))
        stale_ms = int(self._setting("execution.stale_seconds", 180) or 180) * 1000
        now = self.now_ms()
        for p in list(self._pos.values()):
            if p.status not in ("open", "closing", "attention") or not p.open_legs:
                continue
            # failed-exit watchdog
            last = p.exits[-1] if p.exits else None
            if last and last.get("status") in ("ERROR", "REJECTED", "REJECTED_RISK"):
                key = (p.id, "exit")          # one counter per position: each retry mints a new order id
                ts0, attempts = self._exit_retries.get(key, (0.0, 0))
                if attempts < 5 and self._now() - ts0 >= 30.0:
                    self._exit_retries[key] = (self._now(), attempts + 1)
                    self._log(p, "exit_retry", f"watchdog retry {attempts + 1}/5 for {last.get('kind')}")
                    await self.close(p.id, fraction=1.0, reason=f"watchdog retry {attempts + 1}",
                                     kind="stop", force_market=True)
                    continue
                if attempts >= 5 and ts0 < 1e12:      # not yet alerted (the sentinel below)
                    await self._alert(p, "exit still failing after 5 retries — needs a person "
                                      "(close it at the broker)", stage="exit_watchdog")
                    self._exit_retries[key] = (1e18, attempts)   # alert exactly once
                    continue
            # expiry-day flatten by the CLOCK (a policy that holds into expiry
            # day — the tips lotto lane): the bar-driven decision is primary,
            # this is the net under it if the closing bars never arrive
            flat_et = p.policy.get("expiry_day_flatten_et")
            if flat_et:
                today = dt.datetime.fromtimestamp(now / 1000, ET).date()
                d = p.dte_min(today)
                if d is not None and d <= 0:
                    now_et = dt.datetime.fromtimestamp(now / 1000, ET)
                    hh, mm = (int(x) for x in str(flat_et).split(":"))
                    if now_et.hour * 60 + now_et.minute >= hh * 60 + mm \
                            and not any(x.get("status") not in self._EXIT_DEAD + ("FILLED",)
                                        for x in p.exits if x.get("orderId")):
                        self._log(p, "dte", f"expiry day — clock flatten at {flat_et} ET")
                        await self.close(p.id, fraction=1.0, kind="dte", force_market=True,
                                         reason=f"expiry day — flattened at {flat_et} ET (clock)")
                        continue
            # crash brake on the underlying
            stop = stop_price(p.policy, p.state)
            q = self.engine.quotes.get(p.symbol)
            fresh = q is not None and (now - q.ts) <= stale_ms
            if stop is not None and fresh and q.last and q.last > 0:
                short = p.direction == "short"
                beyond = (float(q.last) - stop) if short else (stop - float(q.last))
                if beyond >= excess * p.risk:
                    k = (p.id, "quote")
                    n = self._breaches.get(k, 0) + 1
                    self._breaches[k] = n
                    if n >= need:
                        self._breaches.pop(k, None)
                        self._log(p, "quote_stop", f"underlying {q.last} decisively through the stop {stop:.4f}")
                        await self.close(p.id, fraction=1.0, kind="stop", force_market=True,
                                         reason=f"intra-bar quote breach ({q.last} vs stop {stop:.4f})")
                    continue
                self._breaches.pop((p.id, "quote"), None)

    # ---------------------------------------------------------------- reconciliation
    async def reconcile(self) -> dict:
        """Boot + daily pre-open: our legs vs the broker's book. Options lifecycle
        transitions are EXPLAINED; anything else flags the position and halts new
        entries on that symbol."""
        report = {"positions": 0, "explained": [], "unexplained": []}
        today = dt.datetime.fromtimestamp(self.now_ms() / 1000, ET).date()
        for p in list(self._pos.values()):
            if p.status not in ("open", "closing", "attention"):
                continue
            report["positions"] += 1
            broker = {(x.get("symbol") or "").upper(): float(x.get("qty") or 0)
                      for x in self.engine.positions.positions_list(p.portfolio_id)}
            for leg in list(p.open_legs):
                have = broker.get(leg.symbol.upper())
                if have is not None and abs(have) >= abs(leg.qty) - 1e-9:
                    continue                              # broker holds at least what we think
                o = occ_mod.parse(leg.symbol) if leg.sec_type == "OPT" else None
                expired = o is not None and o.dte(today) < 0
                und_q = self.engine.quotes.get(p.symbol)
                und = float(und_q.last) if und_q is not None and und_q.last and und_q.last > 0 else None
                if expired and o is not None and und is not None:
                    itm = (und > o.strike) if o.right == "C" else (und < o.strike)
                    if not itm:
                        msg = f"{leg.symbol} expired worthless — leg closed at 0"
                        if leg.avg_fill and leg.qty > 0:
                            p.realized_pnl -= float(leg.avg_fill) * abs(leg.qty) * leg.multiplier
                        elif leg.avg_fill and leg.qty < 0:
                            p.realized_pnl += float(leg.avg_fill) * abs(leg.qty) * leg.multiplier
                        leg.qty = 0.0
                        report["explained"].append({"positionId": p.id, "what": msg})
                        self._log(p, "reconciled", msg)
                        continue
                    if o.right == "P" and leg.qty < 0:
                        shares = abs(leg.qty) * 100
                        got = broker.get(p.symbol.upper(), 0.0)
                        if got >= shares - 1e-9:
                            msg = (f"short put {leg.symbol} assigned — adopted {shares:g} shares at "
                                   f"{o.strike:.2f} into this position")
                            leg.qty = 0.0
                            p.legs.append(Leg(symbol=p.symbol, sec_type="STK", qty=shares,
                                              avg_fill=o.strike, multiplier=1.0, origin="assignment"))
                            report["explained"].append({"positionId": p.id, "what": msg})
                            self._log(p, "reconciled", msg)
                            await self._ensure_venue_stop(p)
                            continue
                    if o.right == "C" and leg.qty < 0:
                        contracts = abs(leg.qty)
                        msg = f"short call {leg.symbol} assigned — shares called away at {o.strike:.2f}"
                        leg.qty = 0.0
                        stk = next((l for l in p.legs if l.sec_type == "STK" and l.qty > 0), None)
                        if stk is not None:
                            called = min(stk.qty, contracts * 100)
                            if stk.avg_fill:
                                p.realized_pnl += (o.strike - float(stk.avg_fill)) * called
                            stk.qty -= called
                        report["explained"].append({"positionId": p.id, "what": msg})
                        self._log(p, "reconciled", msg)
                        continue
                # not explained
                msg = (f"{leg.symbol}: we hold {leg.qty:g}, the broker shows {have if have is not None else 'nothing'}"
                       f" — unexplained; new entries on {p.symbol} are halted until a person checks")
                p.status = "attention"
                p.attention.append(msg)
                p.halt_entries = True
                self._entry_halted.add(p.symbol.upper())
                report["unexplained"].append({"positionId": p.id, "what": msg})
                await self._alert(p, msg, stage="reconcile")
            if not p.open_legs and p.status != "closed":
                await self._mark_closed(p, reason="reconciliation: every leg resolved")
            else:
                await self._persist(p)
        with contextlib.suppress(Exception):
            await self.engine.journal.append(POSITION_RECONCILED, {
                "positions": report["positions"], "explained": report["explained"][:20],
                "unexplained": report["unexplained"][:20]})
        return report

    def clear_entry_halt(self, symbol: str) -> None:
        self._entry_halted.discard(symbol.upper())
