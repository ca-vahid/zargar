"""The Team2 session — ONE pure function that reads a day the way the method does.

`simulate_session(plan, bars1m, rules, sigma, now_ms=None)` walks the day's 2-minute CLOSED
bars (extended hours included for the EMAs), updates the 15-minute scenario read, arms setups,
fires pullback entries, and manages the 0DTE position in premium terms. It is used by
- the walk-forward / outcome scorer (whole day, `now_ms=None`), and
- the live runner, which re-runs it over the bars seen so far after every 2m close and acts
  on the *new* events — the same code path, so live ≡ replay by construction
  (BUILDING-A-TECHNIQUE §6 parity; PLATFORM-RULES: decisions on closed bars only).

Every decision appends a trace record (`events`) with a prose reason so the review loop can
replay "what it saw, why it did that" (F-1). Rule ids refer to METHOD.md.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from ...domain import Bar
from ...marketstructure.aggregate import aggregate, bar_session, minute_of_day
from ...marketstructure.dailylevels import Zone
from ...marketstructure.sessions import ET, session_date
from .premium import Fill, PremiumModel, pnl_pct
from .regime import RegimeRead, RegimeReader
from .rules import Team2Rules
from .scenario import (
    SCENARIO_LABEL, TREND_SCENARIOS, ScenarioTracker, body_closed_beyond, sizing_bucket,
)

TRACE_VERSION = 1


@dataclass
class Setup:
    """A confirmed directional idea to buy pullbacks into."""
    id: str
    kind: str                 # scenario_1..4 | pm_break_up | pm_break_down
    direction: str            # long | short
    anchor: float             # the level that broke / held (retest price, T2)
    target: float | None      # X3 outright exit
    confirmed_ts: int
    range_day: bool = False
    touches: int = 0          # EMA13 touches seen after confirmation (D9)
    entries: int = 0          # fires (incl. re-entries, A8)
    losses: int = 0
    dead: bool = False
    dead_reason: str | None = None
    _stalled: bool = False
    _skipped: str | None = None   # last "not a tradeable location" skip already said out loud (F23)

    def to_dict(self) -> dict:
        return {"id": self.id, "kind": self.kind, "direction": self.direction, "anchor": round(self.anchor, 4),
                "target": None if self.target is None else round(self.target, 4), "confirmedTs": self.confirmed_ts,
                "rangeDay": self.range_day, "touches": self.touches, "entries": self.entries, "losses": self.losses,
                "dead": self.dead, "deadReason": self.dead_reason}


@dataclass
class Position:
    setup: Setup
    direction: str
    entry_ts: int
    entry_spot: float
    strike: float
    call: bool
    entry_mark: float
    entry_fill: Fill
    remaining: float = 1.0          # fraction of the position still open
    trims: list[str] = field(default_factory=list)
    touch_index: int = 0
    early: bool = False
    bucket: str = "full"
    size_mult: float = 1.0
    entry_kind: str = "ema"
    peak_pct: float = 0.0
    extreme: float = 0.0            # highest high (long) / lowest low (short) since entry (X1 new-extreme cue)
    target: float | None = None     # what this position sells at: the planned level or the running HOD/LOD (X3b)
    target_kind: str = "plan"       # plan | hod
    avg_fill: Fill | None = None    # average premium after adds (X5); None = entry_fill
    adds: int = 0
    added: list[dict] = field(default_factory=list)      # X5 adds
    realised: list[dict] = field(default_factory=list)   # partial exits

    def to_dict(self) -> dict:
        return {"setup": self.setup.id, "direction": self.direction, "entryTs": self.entry_ts,
                "entrySpot": round(self.entry_spot, 4), "strike": self.strike, "call": self.call,
                "entryMark": round(self.entry_mark, 4), "entryPremium": self.entry_fill.premium,
                "remaining": round(self.remaining, 4), "trims": list(self.trims), "touchIndex": self.touch_index,
                "early": self.early, "bucket": self.bucket, "sizeMult": self.size_mult, "entryKind": self.entry_kind,
                "peakPct": round(self.peak_pct, 2),
                "target": None if self.target is None else round(self.target, 4), "targetKind": self.target_kind,
                "avgPremium": (self.avg_fill or self.entry_fill).premium, "adds": self.adds, "added": list(self.added)}


@dataclass
class Trade:
    """One completed round trip (all fractions closed)."""
    position: dict
    exits: list[dict]
    pnl_pct_weighted: float          # premium % in units of ONE full position (adds make fractions sum > 1), fee-adjusted
    exit_ts: int
    exit_reason: str                 # the reason the LAST fraction closed
    bars_held: int

    def to_dict(self) -> dict:
        return {**self.position, "exits": self.exits, "pnlPct": round(self.pnl_pct_weighted, 2),
                "exitTs": self.exit_ts, "exitReason": self.exit_reason, "barsHeld": self.bars_held,
                "win": self.pnl_pct_weighted > 0}


@dataclass
class SessionResult:
    symbol: str
    date: str
    events: list[dict]
    setups: list[dict]
    trades: list[dict]
    open_position: dict | None
    regime_last: dict | None
    bias: dict
    summary: dict
    premium_path: str = "bs_flat_iv"
    trace_version: int = TRACE_VERSION

    def to_dict(self) -> dict:
        return {"symbol": self.symbol, "date": self.date, "events": self.events, "setups": self.setups,
                "trades": self.trades, "openPosition": self.open_position, "regimeLast": self.regime_last,
                "bias": self.bias, "summary": self.summary, "premiumPathSimulated": self.premium_path,
                "traceVersion": self.trace_version}


def _hhmm(ts_ms: int) -> str:
    return dt.datetime.fromtimestamp(ts_ms / 1000, ET).strftime("%H:%M")


def _zone(d: dict, kind: str, date: str) -> Zone:
    return Zone(kind, top=float(d["top"]), bottom=float(d["bottom"]), date=date, anchor_ts=int(d.get("anchorTs") or 0))


def _avg_body(bars: list[Bar], n: int = 20) -> float:
    xs = [abs(b.close - b.open) for b in bars[-n:]]
    return sum(xs) / len(xs) if xs else 0.0


def simulate_session(plan: dict, bars1m: list[Bar], rules: Team2Rules, *, sigma: float,
                     now_ms: int | None = None, warmup_1m: list[Bar] | None = None) -> SessionResult:
    """See module docstring. `bars1m` = the session date's 04:00–20:00 1m bars (or as many as
    have closed); `warmup_1m` = prior days' extended-hours 1m bars so the 200 EMA is seeded."""
    symbol = str(plan["symbol"])
    date = str(plan["date"])
    zones = {"pdh": _zone(plan["zones"]["pdh"], "pdh", date), "pdl": _zone(plan["zones"]["pdl"], "pdl", date)}
    pmh = plan.get("pmh")
    pml = plan.get("pml")
    targets = plan.get("targets") or {}
    model = PremiumModel(sigma=float(sigma), fee_per_contract=rules.fee_per_contract,
                         slippage_ticks=rules.slippage_ticks, tick=rules.tick)
    events: list[dict] = []

    def note(ts: int, what: str, why: str, **detail) -> None:
        events.append({"ts": ts, "time": _hhmm(ts), "event": what, "why": why, **detail})

    def note_once(s: "Setup", ts: int, what: str, why: str, **detail) -> None:
        # F23: the "not a tradeable location" skips hold for as long as price sits there, and re-stating them
        # on every 2m close buries the read (and the journal) under identical rows. Say it once per setup and
        # again only when the reason changes; a real touch clears it (see `s._skipped = None` below).
        if s._skipped == what:
            return
        s._skipped = what
        note(ts, what, why, **detail)

    # ---- bars: 2m for everything EMA/entry, 15m (RTH) for confirmation
    all_1m = sorted([*(warmup_1m or []), *bars1m], key=lambda b: b.ts)
    if now_ms is not None:
        all_1m = [b for b in all_1m if b.ts + 60_000 <= now_ms]
    two = aggregate(all_1m, rules.entry_tf_min)
    if now_ms is not None:
        two = [b for b in two if b.ts + rules.entry_tf_min * 60_000 <= now_ms]
    today_15 = [b for b in aggregate([b for b in all_1m if session_date(b.ts) == date], rules.confirm_tf_min)
                if bar_session(b.ts) == "rth"]
    if now_ms is not None:
        today_15 = [b for b in today_15 if b.ts + rules.confirm_tf_min * 60_000 <= now_ms]
    pending_15 = sorted(today_15, key=lambda b: b.ts)     # consumed as their buckets close

    regime = RegimeReader(rules)
    scen = ScenarioTracker(zones, flip_on_close=rules.bias_flip_on_15m_close)
    setups: dict[str, Setup] = {}
    pos: Position | None = None
    trades: list[Trade] = []
    losses_today = 0
    day_pnl_pct = 0.0
    fifteen_seen: list[Bar] = []
    pm_up_done = pm_dn_done = False
    event_day_noted = False
    session_bars_2m: list[Bar] = []

    def setup_for(kind: str, direction: str, anchor: float, target: float | None, ts: int, range_day: bool) -> Setup:
        s = Setup(id=f"{kind}@{_hhmm(ts)}", kind=kind, direction=direction, anchor=anchor, target=target,
                  confirmed_ts=ts, range_day=range_day)
        setups[s.id] = s
        return s

    def close_fraction(p: Position, frac: float, spot: float, ts: int, reason: str) -> None:
        nonlocal pos, losses_today, day_pnl_pct
        frac = min(frac, p.remaining)
        if frac <= 0:
            return
        mark = model.mark(spot, p.strike, ts, call=p.call)
        f = model.sell(mark)
        pct = pnl_pct(p.avg_fill or p.entry_fill, f)
        p.realised.append({"ts": ts, "time": _hhmm(ts), "fraction": round(frac, 4), "spot": round(spot, 4),
                           "mark": round(mark, 4), "premium": f.premium, "pnlPct": round(pct, 2), "reason": reason})
        p.remaining = round(p.remaining - frac, 6)
        note(ts, "exit" if p.remaining <= 1e-9 else "trim", reason, fraction=round(frac, 4), pnlPct=round(pct, 2),
             premium=f.premium, spot=round(spot, 4))
        if p.remaining <= 1e-9:
            weighted = sum(x["fraction"] * x["pnlPct"] for x in p.realised)
            first_ts = p.entry_ts
            held = sum(1 for b in session_bars_2m if first_ts <= b.ts <= ts)
            trades.append(Trade(position=p.to_dict(), exits=list(p.realised), pnl_pct_weighted=weighted,
                                exit_ts=ts, exit_reason=reason, bars_held=held))
            day_pnl_pct += weighted
            if weighted < 0:
                losses_today += 1
                p.setup.losses += 1
            pos = None

    # ---- the walk
    for b2 in two:
        r: RegimeRead = regime.update(b2)
        if session_date(b2.ts) != date:
            continue                                   # warm-up bars only feed the EMAs
        sess = bar_session(b2.ts)
        if sess != "rth":
            continue
        session_bars_2m.append(b2)
        end_ts = b2.ts + rules.entry_tf_min * 60_000
        m = minute_of_day(b2.ts)
        # 15m closes that completed by this 2m close (a :45 close is seen on the 2m bar ending :46)
        while pending_15 and pending_15[0].ts + rules.confirm_tf_min * 60_000 <= end_ts:
            f15 = pending_15.pop(0)
            fifteen_seen.append(f15)
            before = scen.bias.scenario
            bias = scen.on_close(f15)
            if bias.scenario != before and bias.scenario is not None:
                n = bias.scenario
                tgt = targets.get("above") if n == 1 else targets.get("below") if n == 4 else (
                    zones["pdl"].top if n == 2 else zones["pdh"].bottom)
                for s in setups.values():
                    if not s.dead and s.kind.startswith("scenario_"):
                        s.dead, s.dead_reason = True, f"bias flipped to {SCENARIO_LABEL[n]} (D10)"
                setup_for(f"scenario_{n}", bias.direction, bias.level, tgt, f15.ts, n not in TREND_SCENARIOS)
                note(f15.ts, "scenario", f"15m body close {'above' if bias.direction == 'long' else 'below'} "
                     f"{bias.level:.2f}: scenario {n} ({SCENARIO_LABEL[n]}) → focus on "
                     f"{'calls' if bias.direction == 'long' else 'puts'} (B1/C1)",
                     scenario=n, close=round(f15.close, 4), level=round(bias.level, 4),
                     rangeDay=n not in TREND_SCENARIOS)
            # PM-range breaks (L2.4/L2.5, V7): direction inside yesterday's range
            if pmh is not None and not pm_up_done and body_closed_beyond(f15, pmh, "long") and f15.close <= zones["pdh"].top:
                pm_up_done = True
                tgt = zones["pdh"].bottom if pmh < zones["pdh"].bottom else targets.get("above")
                setup_for("pm_break_up", "long", float(pmh), tgt, f15.ts, range_day=False)
                note(f15.ts, "pm_break", f"15m close above the pre-market high {pmh:.2f} → calls up to the PDH zone (L2.5/V7)",
                     level=round(float(pmh), 4), close=round(f15.close, 4))
            if pml is not None and not pm_dn_done and body_closed_beyond(f15, pml, "short") and f15.close >= zones["pdl"].bottom:
                pm_dn_done = True
                tgt = zones["pdl"].top if pml > zones["pdl"].top else targets.get("below")
                setup_for("pm_break_down", "short", float(pml), tgt, f15.ts, range_day=False)
                note(f15.ts, "pm_break", f"15m close below the pre-market low {pml:.2f} → puts down to the PDL zone (L2.5/V7)",
                     level=round(float(pml), 4), close=round(f15.close, 4))

        # ---- manage an open position on this 2m close (S/X)
        if pos is not None:
            p = pos
            long = p.direction == "long"
            mark = model.mark(b2.close, p.strike, b2.ts, call=p.call)
            cur_pct = pnl_pct(p.avg_fill or p.entry_fill, model.sell(mark))
            p.peak_pct = max(p.peak_pct, cur_pct)
            # flatten (C3) first — nothing survives the flatten time
            if m + rules.entry_tf_min >= rules.flatten_min:
                close_fraction(p, p.remaining, b2.close, end_ts, "flatten: 0DTE flatten time reached (C3/D-1)")
                continue
            # target (X3/V11, X3b): the planned level — or the running high/low of day for a re-entry — was touched
            if rules.target_exit and p.target is not None:
                hit = b2.high >= p.target if long else b2.low <= p.target
                if hit:
                    what = (f"{'high' if long else 'low'} of day" if p.target_kind == "hod" else "planned level")
                    close_fraction(p, p.remaining, p.target, end_ts,
                                   f"target {p.target:.2f} ({what}) touched — sell at target (X3/V11{'/X3b' if p.target_kind == 'hod' else ''})")
                    continue
            # premium hard stop (P1/D13)
            if cur_pct <= -rules.premium_stop_pct:
                close_fraction(p, p.remaining, b2.close, end_ts, f"premium stop: {cur_pct:.0f}% ≤ −{rules.premium_stop_pct:.0f}% (P1/D13)")
                continue
            # candle stop (S1): a 2m close through the line the entry leaned on — EMA13, EMA48, the 200 EMA
            # (a range-day flush) or the level itself (retest / base)
            guard_name, guard = {"ema": ("EMA13", r.ema_fast), "ema48": ("EMA48", r.ema_mid),
                                 "ema200": ("200 EMA", r.ema_slow)}.get(p.entry_kind, ("level", p.setup.anchor))
            through = guard is not None and ((b2.close < guard) if long else (b2.close > guard))
            if through:
                why = f"2m close {b2.close:.2f} through the {guard_name} {guard:.2f} (S1 one-candle stop)"
                if p.trims:
                    why = "runner: " + why + " (X2)"
                close_fraction(p, p.remaining, b2.close, end_ts, why)
                continue
            # X1 "new high/low of day" cue: the first trim fires on the first new extreme after entry
            prev_extreme = p.extreme
            p.extreme = max(p.extreme, b2.high) if long else min(p.extreme, b2.low)
            if (rules.trim_cue == "new_extreme" and "trim1" not in p.trims and cur_pct > 0 and prev_extreme
                    and ((b2.high > prev_extreme) if long else (b2.low < prev_extreme))):
                p.trims.append("trim1")
                close_fraction(p, rules.trim_1_frac, b2.close, end_ts,
                               f"new {'high' if long else 'low'} of the move at +{cur_pct:.0f}% — first trim (X1 new-extreme cue)")
                continue
            # trims (V2/X1)
            if "trim2" not in p.trims and cur_pct >= rules.trim_2_pct and p.remaining > 0:
                if "trim1" not in p.trims:
                    p.trims.append("trim1")
                    close_fraction(p, rules.trim_1_frac, b2.close, end_ts, f"+{cur_pct:.0f}% ≥ +{rules.trim_1_pct:.0f}% — first trim (V2)")
                p.trims.append("trim2")
                close_fraction(p, rules.trim_2_frac, b2.close, end_ts, f"+{cur_pct:.0f}% ≥ +{rules.trim_2_pct:.0f}% — second trim (V2)")
                continue
            if "trim1" not in p.trims and cur_pct >= rules.trim_1_pct:
                p.trims.append("trim1")
                close_fraction(p, rules.trim_1_frac, b2.close, end_ts, f"+{cur_pct:.0f}% ≥ +{rules.trim_1_pct:.0f}% — first trim (V2)")
                continue
            # X5 trim-and-add: the trim freed room; a fresh EMA13 hold (the T1 read again) re-fills the position
            # at the current premium and the average moves ("get a bunch trimmed on that first push so I can free
            # up room for adds if I like the retest later… re-upped a full position")
            if (rules.add_on_retest and p.trims and p.adds < rules.max_adds and p.remaining < 1.0 - 1e-9
                    and r.ema_fast is not None and r.stack == ("bull" if long else "bear")):
                tol_a = rules.pm_tol_atr * (r.atr or 0.0)
                held = ((b2.low <= r.ema_fast + tol_a and b2.close > r.ema_fast) if long
                        else (b2.high >= r.ema_fast - tol_a and b2.close < r.ema_fast))
                if held:
                    add_f = round(1.0 - p.remaining, 6)
                    add_fill = model.buy(mark)
                    prev_avg = (p.avg_fill or p.entry_fill).premium
                    new_avg = (p.remaining * prev_avg + add_f * add_fill.premium) / (p.remaining + add_f)
                    p.avg_fill = Fill(premium=round(new_avg, 4), fee_per_contract=p.entry_fill.fee_per_contract)
                    p.remaining = round(p.remaining + add_f, 6)
                    p.adds += 1
                    p.added.append({"ts": end_ts, "time": _hhmm(end_ts), "fraction": add_f, "premium": add_fill.premium,
                                    "spot": round(b2.close, 4), "avgPremium": round(new_avg, 4)})
                    note(b2.ts, "add", f"{p.setup.id}: EMA13 {r.ema_fast:.2f} held again after the trim — re-up "
                         f"{add_f:.2f} of the position at ≈ ${add_fill.premium:.2f} (average now ${new_avg:.2f}; X5 trim-and-add)",
                         setup=p.setup.id, fraction=add_f, premium=add_fill.premium, avgPremium=round(new_avg, 4),
                         spot=round(b2.close, 4), adds=p.adds, prevAvgPremium=round(prev_avg, 4))
                    continue
            continue                                   # holding; no new entry while in a position (A12)

        # ---- entries (T): only inside the entry window, with the regime aligned
        if m < rules.first_entry_min or m >= rules.last_entry_min:
            continue
        if rules.avoid_event_days and plan.get("eventDay"):
            if not event_day_noted:
                event_day_noted = True
                note(b2.ts, "skip_event_day", f"macro event day ({plan.get('eventDayName') or 'scheduled release'}) — "
                     "no new entries (D-4; techniques.team2.avoid_event_days)")
            continue
        if losses_today >= rules.max_losses_per_day:
            continue
        live = [s for s in setups.values() if not s.dead and s.confirmed_ts <= b2.ts]
        if not live or not r.ready:
            continue
        # the newest confirmed setup in the current bias direction wins; PM breaks only while
        # no scenario of the same direction exists
        cur_bias = scen.bias.direction
        cands = [s for s in live if cur_bias is None or s.direction == cur_bias]
        if not cands:
            continue
        s = sorted(cands, key=lambda x: x.confirmed_ts)[-1]
        long = s.direction == "long"
        # T8 first: on a range day the trigger may be the 200 EMA flush itself — the 13/48 have crossed the
        # bias way but the full stack is not yet in order (his SPY 671p: bearish cross, then the close under
        # the 200). Every other entry needs the full stack (E3/B9) and a fanned trend (E4).
        flushed = (s.range_day and rules.allow_ema200_flush and r.ema_slow is not None and r.ema_fast is not None
                   and r.ema_mid is not None and len(session_bars_2m) >= 2
                   and ((r.ema_fast < r.ema_mid and b2.close < r.ema_slow <= session_bars_2m[-2].close) if not long
                        else (r.ema_fast > r.ema_mid and b2.close > r.ema_slow >= session_bars_2m[-2].close)))
        if not flushed and r.stack != ("bull" if long else "bear"):
            continue                                   # E3/B9: stack must agree (silent — happens every bar)
        if not flushed and r.fan == "chop":
            continue                                   # E4: braided EMAs = no trade
        ema = r.ema_fast
        if ema is None:
            continue
        atr = r.atr or 0.0
        tol = rules.pm_tol_atr * atr
        want_ema = rules.entry_at in ("ema", "both")
        want_lvl = rules.entry_at in ("level", "both")
        # T1: a touch — the bar reached INTO the EMA13 band and closed back on the trade's side
        touched_ema = want_ema and ((b2.low <= ema + tol and b2.close > ema) if long else (b2.high >= ema - tol and b2.close < ema))
        # E5: the 48 EMA is the second line of defense — a deeper dip that holds is an entry too
        ema48 = r.ema_mid
        touched_48 = (want_ema and rules.allow_ema48_entries and ema48 is not None and not touched_ema
                      and ((b2.low <= ema48 + tol and b2.close > ema48) if long else (b2.high >= ema48 - tol and b2.close < ema48)))
        # T2: the retest of the broken level itself
        touched_lvl = want_lvl and ((b2.low <= s.anchor + tol and b2.close > s.anchor) if long else (b2.high >= s.anchor - tol and b2.close < s.anchor))
        # T7: "break & base" — the last N 2m bars all held just beyond the level (within base_tol_atr) without
        # printing a touch: the base itself is the entry ("that break & base over pre market high is so nice")
        based = False
        if want_lvl and not touched_lvl and rules.base_bars > 0 and len(session_bars_2m) >= rules.base_bars and atr > 0:
            recent = session_bars_2m[-rules.base_bars:]
            band = rules.base_tol_atr * atr
            if long:
                based = all(x.close > s.anchor and x.low >= s.anchor - tol and x.high <= s.anchor + band for x in recent)
            else:
                based = all(x.close < s.anchor and x.high <= s.anchor + tol and x.low >= s.anchor - band for x in recent)
            based = based and all(x.ts > s.confirmed_ts for x in recent)
        # T8: `flushed` was judged above, before the stack gate
        if not (touched_ema or touched_48 or touched_lvl or based or flushed):
            # A6: a dip that has sat on the wrong side of the EMA13 for longer than pullback_max_bars is a
            # consolidation, not a pullback — say so once per setup
            recent_wrong = [x for x in session_bars_2m[-(rules.pullback_max_bars + 1):]
                            if ((x.close < ema) if long else (x.close > ema))]
            if rules.pullback_max_bars > 0 and len(recent_wrong) > rules.pullback_max_bars and not s._stalled:
                s._stalled = True
                note(b2.ts, "pullback_stalled", f"{s.id}: price has closed on the wrong side of the EMA13 for more than "
                     f"{rules.pullback_max_bars} bars — that is a consolidation, not a dip (A6)", setup=s.id)
            continue
        s._stalled = False
        if touched_ema:
            entry_kind, entry_spot = "ema", ema
        elif touched_48:
            entry_kind, entry_spot = "ema48", ema48
        elif touched_lvl:
            entry_kind, entry_spot = "level", s.anchor
        elif based:
            entry_kind, entry_spot = "base", b2.close
        else:
            entry_kind, entry_spot = "ema200", b2.close
        # the bar must not be an engulfing lunge into the EMA (A6/F4)
        body = abs(b2.close - b2.open)
        avg = _avg_body(session_bars_2m[:-1])
        idx = s.touches + 1
        # F18 (2026-09-04, IWM live): a dip that is not a tradeable location — the range day has not cleared its
        # PM level yet (B3/A4), or the dip sits inside the pre-market no-trade zone (V6/B5) — is not one of the
        # method's "first or second pullback": it does not consume the D9 allowance
        if s.range_day and rules.range_day_confirmation:
            pm_level = pml if long else pmh
            if pm_level is not None and ((b2.close < pm_level) if long else (b2.close > pm_level)):
                note_once(s, b2.ts, "skip_range_confirmation", f"range day: price has not cleared the PM level {pm_level:.2f} (B3/A4) — not counted as a pullback",
                          setup=s.id, touch=idx)
                continue
        bucket = sizing_bucket(entry_spot, zones, pmh, pml)
        mult = {"full": rules.size_full, "small": rules.size_small, "none": rules.size_none}[bucket]
        if mult <= 0:
            note_once(s, b2.ts, "skip_no_trade_zone", f"entry {entry_spot:.2f} sits inside the pre-market range — no-trade zone (V6/B5) — not counted as a pullback",
                      setup=s.id, touch=idx, bucket=bucket)
            continue
        s._skipped = None
        s.touches += 1
        if idx > rules.pullback_max_touches:
            note(b2.ts, "late_touch", f"touch #{idx} of {s.id} — beyond the first {rules.pullback_max_touches}, watch-only (D9/P6)",
                 setup=s.id, touch=idx, spot=round(entry_spot, 4))
            continue
        if avg > 0 and body > rules.pullback_body_mult * avg:
            note(b2.ts, "skip_engulfing", f"touch #{idx}: body {body:.2f} > {rules.pullback_body_mult:.1f}× avg {avg:.2f} — an engulfing lunge, not a drift (A6/F4)",
                 setup=s.id, touch=idx)
            continue
        if s.entries >= 1 + rules.max_reentries:
            note(b2.ts, "skip_reentries", f"{s.id} already entered {s.entries}× (max {1 + rules.max_reentries}, A8)", setup=s.id)
            continue
        if rules.shrink_after_win and day_pnl_pct > 0:
            mult = round(mult * 0.5, 4)                # P7/D14: protect the day after a win
        pick = model.pick_strike(entry_spot, end_ts, s.direction, target_premium=rules.target_premium,
                                 premium_floor=rules.premium_floor, step=rules.strike_step)
        if pick is None:
            note(b2.ts, "skip_no_contract", f"no strike prices between ${rules.premium_floor:.2f} and ${rules.target_premium:.2f} (V1)", setup=s.id)
            continue
        strike, mark = pick
        fill = model.buy(mark)
        # X3b: "high of day resistance is the main target for longs until it breaks" — a re-entry (this setup
        # already fired, or the day already has a trade) sells at the running HOD/LOD when it is nearer than
        # the planned level and leaves room; `hod_target=always` applies it to first entries too
        target, target_kind = s.target, "plan"
        if rules.hod_target != "off" and atr > 0 and (rules.hod_target == "always" or s.entries >= 1 or trades):
            prior = session_bars_2m[:-1]
            if prior:
                ext = max(x.high for x in prior) if long else min(x.low for x in prior)
                room = (ext - entry_spot) if long else (entry_spot - ext)
                nearer = target is None or ((ext < target) if long else (ext > target))
                if room >= rules.hod_target_min_atr * atr and nearer:
                    target, target_kind = ext, "hod"
        s.entries += 1
        pos = Position(setup=s, direction=s.direction, entry_ts=end_ts, entry_spot=entry_spot, strike=strike,
                       call=long, entry_mark=mark, entry_fill=fill, touch_index=idx,
                       early=m < rules.early_flag_before_min, bucket=bucket, size_mult=mult, entry_kind=entry_kind,
                       extreme=b2.high if long else b2.low, target=target, target_kind=target_kind, avg_fill=fill)
        kind_word = {"ema": "EMA13", "ema48": "EMA48", "level": "level", "base": "base beyond the level",
                     "ema200": "200 EMA flush"}[entry_kind]
        note(b2.ts, "fire", f"{s.id}: touch #{idx} — {kind_word} at {entry_spot:.2f} "
             f"held (close {b2.close:.2f}) in a {r.stack} stack — buy {'call' if long else 'put'} {strike:g} "
             f"≈ ${fill.premium:.2f} (T1/T2/V1); size {bucket} ×{mult:g}"
             + (f" — target the {'high' if long else 'low'} of day {target:.2f} (X3b)" if target_kind == "hod" else "")
             + (" — early (before 10:00, P2)" if m < rules.early_flag_before_min else ""),
             target=None if target is None else round(target, 4), targetKind=target_kind,
             setup=s.id, touch=idx, spot=round(entry_spot, 4), strike=strike, premium=fill.premium, bucket=bucket,
             sizeMult=mult, early=m < rules.early_flag_before_min, entryKind=entry_kind, regime=r.to_dict())

    summary = {
        "trades": len(trades), "wins": sum(1 for t in trades if t.pnl_pct_weighted > 0),
        "losses": sum(1 for t in trades if t.pnl_pct_weighted <= 0),
        "pnlPctSum": round(sum(t.pnl_pct_weighted for t in trades), 2),
        "setups": len(setups), "bars2m": len(session_bars_2m), "fifteenMinBars": len(fifteen_seen),
        "openAtEnd": pos is not None, "sigma": round(float(sigma), 4),
    }
    return SessionResult(symbol=symbol, date=date, events=events, setups=[s.to_dict() for s in setups.values()],
                         trades=[t.to_dict() for t in trades], open_position=pos.to_dict() if pos else None,
                         regime_last=regime.last.to_dict() if regime.last else None, bias=scen.bias.to_dict(),
                         summary=summary)


__all__ = ["simulate_session", "SessionResult", "Setup", "Position", "Trade", "TRACE_VERSION"]
