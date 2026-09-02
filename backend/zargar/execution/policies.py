"""Exit policies as DATA, evaluated by shared code (platform plan §2.4; phase 2b).

A technique hands the position manager a plain-dict policy; the SAME evaluator
runs live (PositionManager, on closed bars of the policy's timeframe) and in
`simulate.simulate_position` (over history) — that identity is what makes a
policy backtestable by the code that will trade it, and it is asserted by the
chaos suite's parity test.

Policy document (all keys optional unless noted):

    {
      "timeframe": "5m" | "15m" | "1h" | "1d",          # bars decisions are judged on (default 5m)
      "stop": {"kind": "fixed", "price": 97.5}           # underlying stop, judged on bar close
            | {"kind": "none", "guard": "<declared portfolio-level guard>"},   # explicit, journaled
      "ladder": {"targets": [p1, p2, ...], "fractions": [f1, f2, ...]},        # trims at targets
      "profit_target_pct_of_credit": 60,                 # net-credit positions: close at N% of max profit
      "premium_stop_pct": 50,                            # option mark bled N% from entry -> close
      "premium_ladder": {"gains_pct": [100, 200],        # options: trims when the CONTRACT is up N%
                         "fractions": [0.5, 0.5]},       #   (a 0DTE triples on a 0.3% underlying move —
                                                         #    an underlying ladder never sees it)
      "premium_floor_after_trim": true,                  # after the first premium trim the rest can't go red
      "premium_watch": true,                             # judge premium stop/ladder on the ~2s quote loop too
      "breakeven_after_r": 1.0,                          # favorable excursion >= N R -> stop to entry
      "trailing": {"mode": "pct" | "atr" | "structure",  # trailing stop on the underlying
                   "value": 2.0,                         # pct: %, atr: multiple; structure ignores it
                   "after_r": 1.0},                      # activates only once up N R (trail_after)
      "time_stop_sessions": 10,                          # TRADING sessions held (weekends don't count)
      "dte_close": 7,                                    # close when min leg DTE <= N (clamped >= execution.min_dte)
      "flatten_before": {"event": "earnings", "days": 1} # close N days before the event
    }

Decisions come out as data too — the caller places the orders:
    Decision(kind, fraction, reason)          # kind: stop|trim|close|premium_stop|dte|time|event|credit_target
    StopMove(new_stop, reason)                # state change only, no order

The evaluator is pure: no I/O, no settings, no clock reads — everything arrives
in `PositionView`. Precedence: protective exits first (stop, premium stop), then
mandatory closes (DTE, time, event), then profit-taking (credit target, ladder),
then stop maintenance (breakeven, trailing).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..domain import Bar
from ..marketstructure.levels import atr as _atr, find_pivots

DEFAULT_TIMEFRAME = "5m"


@dataclass(frozen=True)
class Decision:
    kind: str                    # stop | trim | close | premium_stop | dte | time | event | credit_target
    fraction: float              # of the REMAINING size (1.0 = close it all)
    reason: str


@dataclass(frozen=True)
class StopMove:
    new_stop: float
    reason: str


@dataclass
class PolicyState:
    """The mutable part the evaluator threads between bars. Persisted verbatim in
    the position row; `simulate_position` builds its own and must end up identical
    given the same bars (parity)."""
    trims_done: int = 0
    stop: float | None = None
    trailing_active: bool = False
    peak_favorable: float | None = None      # best underlying close in the position's favor
    breakeven_done: bool = False
    premium_trims_done: int = 0              # premium-ladder rungs taken
    premium_floor: float | None = None       # net-mark floor once a premium trim is banked

    def to_dict(self) -> dict:
        return {"trimsDone": self.trims_done, "stop": self.stop, "trailingActive": self.trailing_active,
                "peakFavorable": self.peak_favorable, "breakevenDone": self.breakeven_done,
                "premiumTrimsDone": self.premium_trims_done, "premiumFloor": self.premium_floor}

    @classmethod
    def from_dict(cls, d: dict | None) -> "PolicyState":
        d = d or {}
        return cls(trims_done=int(d.get("trimsDone") or 0), stop=d.get("stop"),
                   trailing_active=bool(d.get("trailingActive")), peak_favorable=d.get("peakFavorable"),
                   breakeven_done=bool(d.get("breakevenDone")),
                   premium_trims_done=int(d.get("premiumTrimsDone") or 0),
                   premium_floor=d.get("premiumFloor"))


@dataclass
class PositionView:
    """Everything the evaluator may look at for one closed bar. Built by the live
    manager and by the simulator from the same definitions."""
    direction: str                       # long | short — the underlying idea's side
    entry: float                         # underlying reference entry
    risk: float                          # |entry - initial stop| (or a declared risk unit)
    bar: Bar                             # the closed bar of the policy timeframe (underlying)
    bars: list[Bar] = field(default_factory=list)   # trailing window of closed bars incl. `bar`
    net_mark: float | None = None        # options: current net premium per unit (+debit basis / -credit)
    entry_mark: float | None = None      # options: net premium paid (+) or credit received (-)
    dte_min: int | None = None           # min days-to-expiry across option legs
    sessions_held: int = 0               # closed TRADING sessions since open
    days_to_event: int | None = None     # e.g. days to earnings (None = unknown)
    min_dte_floor: int = 1               # execution.min_dte — the platform floor

    def favorable(self, price: float) -> float:
        return (price - self.entry) if self.direction == "long" else (self.entry - price)


def _ladder(policy: dict) -> tuple[list[float], list[float]]:
    lad = policy.get("ladder") or {}
    targets = [float(t) for t in (lad.get("targets") or [])]
    fractions = [float(f) for f in (lad.get("fractions") or [])]
    if targets and not fractions:
        fractions = [1.0 / len(targets)] * len(targets)
    return targets, fractions


def stop_price(policy: dict, state: PolicyState) -> float | None:
    """The effective stop right now: the state's (moved) stop wins over the policy's."""
    if state.stop is not None:
        return float(state.stop)
    st = policy.get("stop") or {}
    if st.get("kind") == "fixed" and st.get("price") is not None:
        return float(st["price"])
    return None


def has_no_stop(policy: dict) -> bool:
    return (policy.get("stop") or {}).get("kind") == "none"


def _premium_ladder(policy: dict) -> tuple[list[float], list[float]]:
    lad = policy.get("premium_ladder") or {}
    gains = [float(g) for g in (lad.get("gains_pct") or [])]
    fractions = [float(f) for f in (lad.get("fractions") or [])]
    if gains and not fractions:
        fractions = [1.0 / len(gains)] * len(gains)
    return gains, fractions


def evaluate_premium(policy: dict, state: PolicyState,
                     net_mark: float | None, entry_mark: float | None) -> Decision | None:
    """The premium-only judgements — the premium stop (with the post-trim floor)
    and the premium ladder — on the CONTRACT's mark alone, no bar needed. The
    bar path (`evaluate`) and the live quote loop (`premium_watch`) both call
    this, so a 0DTE lotto is judged every ~2 s, not every 15 minutes."""
    if net_mark is None or not entry_mark:
        return None
    prem_pct = policy.get("premium_stop_pct")
    if entry_mark > 0:                                    # net debit (long premium)
        floor = state.premium_floor
        if floor is not None and net_mark <= floor:
            return Decision("premium_stop", 1.0,
                            f"net premium {net_mark:.2f} back at the post-trim floor {floor:.2f}")
        if prem_pct and net_mark <= entry_mark * (1 - float(prem_pct) / 100.0):
            return Decision("premium_stop", 1.0,
                            f"net premium {net_mark:.2f} bled {prem_pct:g}% from {entry_mark:.2f}")
        gains, fractions = _premium_ladder(policy)
        i = state.premium_trims_done
        if i < len(gains) and net_mark >= entry_mark * (1 + gains[i] / 100.0):
            frac = fractions[i] if i < len(fractions) else 0.0
            remaining_frac = 1.0 - sum(fractions[:i])
            rel = min(1.0, frac / remaining_frac) if remaining_frac > 1e-9 else 1.0
            return Decision("premium_trim", rel,
                            f"contract +{(net_mark / entry_mark - 1) * 100:.0f}% "
                            f"(premium TP{i + 1} +{gains[i]:g}%)")
    elif prem_pct:                                        # net credit: buy-back cost rising against us
        credit = -entry_mark
        if credit > 0 and net_mark >= credit * (1 + float(prem_pct) / 100.0):
            return Decision("premium_stop", 1.0,
                            f"buy-back cost {net_mark:.2f} is {prem_pct:g}% past the {credit:.2f} credit")
    return None


def apply_premium_decision(policy: dict, state: PolicyState, d: Decision | None,
                           entry_mark: float | None) -> PolicyState:
    """State after a premium decision: a trim advances the rung and (by default)
    floors the rest at the entry premium — a doubled lotto never goes red."""
    if d is None or d.kind != "premium_trim":
        return state
    floor = state.premium_floor
    if policy.get("premium_floor_after_trim", True) and entry_mark and entry_mark > 0:
        floor = max(floor or 0.0, float(entry_mark))
    return PolicyState(trims_done=state.trims_done, stop=state.stop,
                       trailing_active=state.trailing_active, peak_favorable=state.peak_favorable,
                       breakeven_done=state.breakeven_done,
                       premium_trims_done=state.premium_trims_done + 1, premium_floor=floor)


def validate_policy(policy: dict) -> list[str]:
    """Problems that make a policy unsafe to run. Empty = fine."""
    out: list[str] = []
    st = policy.get("stop") or {}
    kinds = {"fixed", "none", None}
    if st and st.get("kind") not in kinds:
        out.append(f"unknown stop kind {st.get('kind')!r}")
    if st.get("kind") == "none" and not str(st.get("guard") or "").strip():
        out.append("a no-stop policy must DECLARE its portfolio-level guard "
                   "(stop.guard: sizing cap + daily-loss halt link) — an omitted stop is not a policy")
    if st.get("kind") == "fixed" and not st.get("price"):
        out.append("fixed stop needs a price")
    targets, fractions = _ladder(policy)
    if len(fractions) > len(targets):
        out.append("ladder has more fractions than targets")
    if sum(fractions) > 1.0 + 1e-9:
        out.append("ladder fractions sum past 1.0")
    tr = policy.get("trailing") or {}
    if tr and tr.get("mode") not in ("pct", "atr", "structure"):
        out.append(f"unknown trailing mode {tr.get('mode')!r}")
    tf = policy.get("timeframe", DEFAULT_TIMEFRAME)
    if tf not in ("1m", "5m", "15m", "1h", "1d"):
        out.append(f"unsupported timeframe {tf!r}")
    return out


def evaluate(policy: dict, state: PolicyState, view: PositionView) -> tuple[list[Decision], list[StopMove]]:
    """One closed bar -> decisions (orders for the caller) + stop moves (state).
    Deterministic and side-effect free; the caller applies StopMoves to `state`
    and executes Decisions reduce-only."""
    decisions: list[Decision] = []
    moves: list[StopMove] = []
    bar = view.bar
    short = view.direction == "short"
    risk = max(view.risk, 1e-9)

    # ---- 1. protective exits -------------------------------------------------
    stop = stop_price(policy, state)
    if stop is not None:
        breached = (bar.close >= stop) if short else (bar.close <= stop)
        if breached:
            return [Decision("stop", 1.0, f"bar closed through the stop {stop:.4f} (close {bar.close:.4f})")], moves
    prem = evaluate_premium(policy, state, view.net_mark, view.entry_mark)
    if prem is not None and prem.kind == "premium_stop":
        return [prem], moves

    # ---- 2. mandatory closes ---------------------------------------------------
    if view.dte_min is not None:
        flatten_et = policy.get("expiry_day_flatten_et")
        if flatten_et:
            # a policy that may hold INTO expiry day (the tips lotto lane): the
            # "never hold to expiry" invariant is kept as "never through the
            # close of expiry day" — flatten at the stated ET time
            if view.dte_min <= 0:
                from ..marketstructure.sessions import ET as _ET
                import datetime as _dt
                bar_et = _dt.datetime.fromtimestamp(view.bar.ts / 1000, _ET)
                hh, mm = (int(x) for x in str(flatten_et).split(":"))
                # the decision runs on the bar CLOSE: a bar ending at/after the
                # flatten time is the flatten bar
                if (bar_et.hour * 60 + bar_et.minute + 1) >= hh * 60 + mm:
                    return [Decision("dte", 1.0, f"expiry day — flattening at {flatten_et} ET "
                                                 "(never hold through the close)")], moves
            elif view.dte_min < 0:
                return [Decision("dte", 1.0, "contract expired — closing")], moves
        else:
            min_dte = max(int(policy.get("dte_close") or 0), int(view.min_dte_floor))
            if view.dte_min <= min_dte:
                return [Decision("dte", 1.0, f"min leg DTE {view.dte_min} <= dte_close floor {min_dte} — "
                                             "never hold to expiry")], moves
    ts = policy.get("time_stop_sessions")
    if ts and view.sessions_held >= int(ts):
        return [Decision("time", 1.0, f"held {view.sessions_held} trading sessions (time stop {ts})")], moves
    fb = policy.get("flatten_before") or {}
    if fb and view.days_to_event is not None and view.days_to_event <= int(fb.get("days", 1)):
        return [Decision("event", 1.0, f"{fb.get('event', 'event')} in {view.days_to_event} day(s) — flattening")], moves

    # ---- 3. profit taking -------------------------------------------------------
    pt = policy.get("profit_target_pct_of_credit")
    if pt and view.entry_mark is not None and view.entry_mark < 0 and view.net_mark is not None:
        credit = -view.entry_mark
        captured = (credit - max(0.0, view.net_mark)) / credit * 100.0 if credit > 0 else 0.0
        if captured >= float(pt):
            return [Decision("credit_target", 1.0,
                             f"captured {captured:.0f}% of the {credit:.2f} credit (target {pt:g}%)")], moves
    if prem is not None and prem.kind == "premium_trim":
        return [prem], moves                             # the contract got there first
    targets, fractions = _ladder(policy)
    while state.trims_done < len(targets):
        t = targets[state.trims_done]
        hit = (bar.low <= t) if short else (bar.high >= t)
        if not hit:
            break
        frac = fractions[state.trims_done] if state.trims_done < len(fractions) else 0.0
        remaining_frac = 1.0 - sum(fractions[:state.trims_done])
        rel = min(1.0, frac / remaining_frac) if remaining_frac > 1e-9 else 1.0
        decisions.append(Decision("trim", rel, f"TP{state.trims_done + 1} {t:.4f} reached"))
        break                                            # one exit decision per bar, like the session runner

    # ---- 4. stop maintenance (state only) ----------------------------------------
    fav = view.favorable(bar.close)
    peak = max(state.peak_favorable or 0.0, fav)
    be = policy.get("breakeven_after_r")
    if be and not state.breakeven_done and fav >= float(be) * risk:
        new_stop = view.entry
        if stop is None or (new_stop > stop if not short else new_stop < stop):
            moves.append(StopMove(new_stop, f"breakeven: up {fav / risk:.2f}R (>= {be}R)"))
    tr = policy.get("trailing") or {}
    if tr:
        after_r = float(tr.get("after_r") or 0)
        active = state.trailing_active or fav >= after_r * risk
        if active:
            mode = tr.get("mode")
            new_stop = None
            if mode == "pct":
                pct = float(tr.get("value") or 0) / 100.0
                ref = (view.entry + peak) if not short else (view.entry - peak)
                new_stop = ref * (1 - pct) if not short else ref * (1 + pct)
            elif mode == "atr":
                a = _atr(view.bars[-15:]) if view.bars else 0.0
                if a > 0:
                    ref = (view.entry + peak) if not short else (view.entry - peak)
                    new_stop = ref - float(tr.get("value") or 1.0) * a if not short \
                        else ref + float(tr.get("value") or 1.0) * a
            elif mode == "structure":
                piv = find_pivots(view.bars, window=3) if len(view.bars) >= 7 else []
                lows = [p.price for p in piv if p.kind == ("high" if short else "low")]
                if lows:
                    new_stop = lows[-1]
            if new_stop is not None:
                better = stop is None or (new_stop > stop if not short else new_stop < stop)
                if better:
                    moves.append(StopMove(float(new_stop), f"trailing ({mode}) -> {float(new_stop):.4f}"))
    return decisions, moves


def apply_moves(state: PolicyState, view: PositionView, decisions: list[Decision],
                moves: list[StopMove], policy: dict | None = None) -> PolicyState:
    """Advance the state after a bar: trims, peak, breakeven, and the tightest
    stop the moves proposed (a stop only ever tightens)."""
    short = view.direction == "short"
    trims = state.trims_done + sum(1 for d in decisions if d.kind == "trim")
    fav = view.favorable(view.bar.close)
    peak = max(state.peak_favorable or 0.0, fav)
    new_stop = state.stop
    be_done = state.breakeven_done
    trailing = state.trailing_active
    for m in moves:
        if m.new_stop is None:
            continue
        if "trailing" in m.reason:
            trailing = True
        if "breakeven" in m.reason:
            be_done = True
        cand = float(m.new_stop)
        if new_stop is None or (cand > new_stop if not short else cand < new_stop):
            new_stop = cand
    out = PolicyState(trims_done=trims, stop=new_stop, trailing_active=trailing,
                      peak_favorable=peak, breakeven_done=be_done,
                      premium_trims_done=state.premium_trims_done, premium_floor=state.premium_floor)
    for d in decisions:
        if d.kind == "premium_trim":
            out = apply_premium_decision(policy or {}, out, d, view.entry_mark)
    return out
