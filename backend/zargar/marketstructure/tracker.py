"""TriggerTracker — the shared touch / break / gap / volume / false-break /
invalidation state machine, plus level respect and post-session scoring.

ONE implementation for live arming, session-plan replay and walk-forward sweeps
(parity tests assert it). Parameterised by `MarketRules` (a technique's own
rules object, e.g. EM's `Thresholds`, is duck-compatible): tolerance, volume
floor, gap policy, follow-through, max false breaks, stop-on-close and the
windows an entry may fire in. It never reads settings or a technique's rulebook.
"""
from __future__ import annotations

import logging
import math  # noqa: F401
from dataclasses import dataclass, field

from ..domain import Bar
from .candles import is_decisive
from .levels import atr, session_key  # noqa: F401
from .outcome import simulate_plan
from .rules import DEFAULT_MARKET_RULES as DEFAULT_THRESHOLDS, MarketRules as Thresholds
from .sessions import PRIME_WINDOWS, session_bounds, session_date, session_window
from .volume import VolumeProfile, build_profile, relative_volume  # noqa: F401

log = logging.getLogger("zargar.marketstructure.tracker")

# --- level respect ----------------------------------------------------------------


def level_respect(levels: list[dict], bars: list[Bar], *, thresholds: Thresholds | None = None) -> list[dict]:
    """Per planned level: did the session respect it?

    respected — price entered the +/-tol band and reversed >= respect_mult*tol on
               the defending side before any close beyond the band
    broken    — a bar closed beyond the band (support: close < price - tol)
    flipped   — broken, and later the level held from the other side
    untested  — price never came within the band
    """
    t = thresholds or DEFAULT_THRESHOLDS
    out: list[dict] = []
    for lv in levels:
        price = float(lv["price"])
        kind = lv.get("effectiveKind") or lv.get("kind") or "support"
        tol = max(price * t.level_tolerance_pct * 2, 1e-9)
        need = tol * t.respect_mult
        status = "untested"
        touched_ts = None
        touches = 0
        in_band = False
        max_rev = 0.0
        broke_ts = None
        flipped = False
        for b in bars:
            inside = b.low <= price + tol and b.high >= price - tol
            if kind == "support":
                if broke_ts is None:
                    if inside and not in_band:
                        touches += 1
                        touched_ts = touched_ts or b.ts
                    if touched_ts and b.close < price - tol:
                        broke_ts = b.ts
                        status = "broken"
                    elif touched_ts and b.high - price >= need and status != "broken":
                        max_rev = max(max_rev, b.high - price)
                        status = "respected"
                    elif touched_ts:
                        max_rev = max(max_rev, b.high - price)
                else:
                    # after the break the level may act as resistance (T1.3b)
                    if inside and price - b.low >= 0 and b.close < price - tol:
                        pass
                    if inside:
                        flipped_touch = True
                    else:
                        flipped_touch = False
                    if flipped_touch and price - b.close >= need:
                        flipped = True
                    if b.close > price + tol:
                        flipped = False if not flipped else flipped
            else:  # resistance
                if broke_ts is None:
                    if inside and not in_band:
                        touches += 1
                        touched_ts = touched_ts or b.ts
                    if touched_ts and b.close > price + tol:
                        broke_ts = b.ts
                        status = "broken"
                    elif touched_ts and price - b.low >= need and status != "broken":
                        max_rev = max(max_rev, price - b.low)
                        status = "respected"
                    elif touched_ts:
                        max_rev = max(max_rev, price - b.low)
                else:
                    if inside and b.close - price >= need:
                        flipped = True
            in_band = inside
        if status == "broken" and flipped:
            status = "flipped"
        out.append({"price": round(price, 4), "kind": kind, "sources": list(lv.get("sources") or []),
                    "touchesPlanned": lv.get("touches"), "timeframes": list(lv.get("timeframes") or []),
                    "priorDayExtreme": bool(lv.get("priorDayExtreme")), "ageSessions": lv.get("ageSessions"),
                    "status": status, "touchesInSession": touches, "firstTouchTs": touched_ts,
                    "brokeTs": broke_ts, "maxReversal": round(max_rev, 4), "tol": round(tol, 4)})
    return out


# --- trigger tracking -------------------------------------------------------------


@dataclass
class TriggerTracker:
    """Incremental evaluation of one plan trigger against bars of the plan's session.

    Feed bars in order with `on_bar(bar, index)`; read `status` / `fired_at`.
    `enforce_windows=False` and `gap_rules=False` give the counterfactual readings.
    """
    trigger: dict
    thresholds: Thresholds = field(default_factory=lambda: DEFAULT_THRESHOLDS)
    profile: VolumeProfile | None = None
    enforce_windows: bool = True
    gap_rules: bool = True
    prev_close: float | None = None

    status: str = "waiting"        # waiting | gapped_past | gapped_through | gap_void | observed | fired | not_triggered | expired | exhausted
    fired_index: int | None = None
    fired_ts: int | None = None
    fired_window: str | None = None
    fill_price: float | None = None
    observed_midday: list[int] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    # The open-gap rules can only be judged on the session's OPENING bar. When the
    # first bar this tracker sees is a later one (a late start / restart — 08-26
    # the app came up at 09:50 and 22 triggers were "gap-voided" against the 09:50
    # bar) the gap cannot be known: the trigger runs WITHOUT the gap rules and
    # says so, instead of voiding on a number that is not a gap.
    gap_unchecked: bool = False
    # R3.2 — breaks of this level that failed to hold this session; after
    # `max_false_breaks` the level is done for the day (`exhausted`)
    failed_breaks: int = 0
    _bars: list[Bar] = field(default_factory=list)
    _break_index: int | None = None
    _gap_checked: bool = False

    TERMINAL = ("fired", "gapped_past", "gapped_through", "gap_void", "expired", "exhausted", "invalidated")

    # -- helpers
    @property
    def entry(self) -> float:
        return float(self.trigger["entry"]["price"])

    @property
    def stop(self) -> float:
        return float(self.trigger["stop"]["price"])

    @property
    def risk(self) -> float:
        return max(abs(self.entry - self.stop), 1e-9)

    @property
    def kind(self) -> str:
        return self.trigger["kind"]

    @property
    def direction(self) -> str:
        return "short" if self.trigger.get("direction") == "short" else "long"

    def _note(self, bar: Bar, what: str, **detail) -> None:
        self.events.append({"ts": bar.ts, "event": what, **detail})

    def _rel_volume(self, bar: Bar) -> float | None:
        """R3.1/T2.9 — the bar's volume against its time-of-day baseline (prior
        sessions); None when it cannot be measured. One computation for live
        arming and replay, and one policy for None: an ENTRY never fires on
        unknown volume (the book's only confirmation instrument) — the trigger
        stays alive and is re-judged on the next bar."""
        if bar.volume <= 0:
            return None
        if self.profile is not None and self.profile.overall > 0:
            r = relative_volume(bar, self.profile)
            return r if r > 0 else None
        # fallback: vs mean of the previous 20 bars in this session
        prev = [b.volume for b in self._bars[-21:-1] if b.volume > 0]
        if len(prev) >= 5:
            m = sum(prev) / len(prev)
            return bar.volume / m if m > 0 else None
        return None

    def _window_ok(self, ts: int) -> bool:
        return (not self.enforce_windows) or session_window(ts) in (getattr(self.thresholds, "windows", None) or PRIME_WINDOWS)

    def _volume_unknown(self, bar: Bar, what: str) -> str:
        self.skipped.append({"ts": bar.ts, "reason": "R3.1 volume unknown — no baseline or no volume on the bar; "
                                                     "not entering on unconfirmed volume"})
        self._note(bar, what)
        return self.status

    # -- main
    def on_bar(self, bar: Bar, index: int) -> str:
        t = self.thresholds
        self._bars.append(bar)
        if self.status in self.TERMINAL:
            return self.status
        # opening gap checks, once — and only on the session's opening bar
        if not self._gap_checked:
            self._gap_checked = True
            open_ms = session_bounds(session_date(bar.ts))[0]
            if self.gap_rules and bar.ts > open_ms + 60_000:
                # first bar seen is not the open (late start / restart): the gap
                # is unknowable from here — run without the gap rules, and say so
                self.gap_unchecked = True
                self._note(bar, "gap_unchecked", firstBar=bar.ts, sessionOpen=open_ms)
            elif self.gap_rules:
                # specific first (through the stop / past the level), then the magnitude rule
                short = self.direction == "short"
                if self.kind in ("bounce", "reject"):
                    through = (bar.open > self.stop) if short else (bar.open < self.stop)
                    past = (bar.open >= self.entry) if short else (bar.open <= self.entry)
                    if through:
                        self.status = "gapped_through"
                        self._note(bar, "gapped_through", open=bar.open, stop=self.stop)
                        return self.status
                    if past:
                        self.status = "gapped_past"
                        self._note(bar, "gapped_past", open=bar.open, entry=self.entry)
                        return self.status
                else:
                    past = (bar.open < self.entry) if short else (bar.open > self.entry)
                    if past:
                        self.status = "gapped_past"
                        self._note(bar, "gapped_past", open=bar.open, entry=self.entry)
                        return self.status
                if self.prev_close:
                    gap = abs(bar.open - self.prev_close)
                    if gap > t.gap_void_r * self.risk:
                        self.status = "gap_void"
                        self._note(bar, "gap_void", open=bar.open, prevClose=self.prev_close, gap=round(gap, 4),
                                   limit=round(t.gap_void_r * self.risk, 4))
                        return self.status
        w = session_window(bar.ts)
        short = self.direction == "short"
        # T4.3d — a close through the STOP before entry breaks the level: the idea
        # this trigger trades no longer exists, and any later "touch" would be a
        # re-test of a failed level from the wrong side. Terminal — without this,
        # a critic-vetoed trigger re-armed into a broken level refires forever
        # (LITE b1 / MSTR r2, 2026-08-27).
        if (bar.close > self.stop) if short else (bar.close < self.stop):
            self.status = "invalidated"
            self._note(bar, "invalidated", close=bar.close, stop=self.stop)
            return self.status
        if self.kind in ("bounce", "reject"):
            tol = max(self.entry * t.level_tolerance_pct, 1e-9)
            # A touch is a bar that reaches INTO the level band — a bar wholly
            # beyond the level is a break of it, not a test (LITE 2026-08-27:
            # price 2.5% BELOW a bounce level "touched" on every bar and the
            # trigger zombie-fired at a fantasy fill through ten critic vetoes)
            if short:
                touched = bar.high >= self.entry - tol and bar.low <= self.entry + tol
            else:
                touched = bar.low <= self.entry + tol and bar.high >= self.entry - tol
            if not touched:
                return self.status
            if not self._window_ok(bar.ts):
                self.observed_midday.append(bar.ts)
                self.status = "observed"
                self._note(bar, "touch_outside_window", window=w)
                return self.status
            # volume_floor_mult <= 0 = this technique does not require volume
            # confirmation (platform plan §2.1: a tip passes volume_floor=None
            # and reuses the machinery). EM's floor is 0.5, so EM is unaffected.
            rel = None
            if t.volume_floor_mult > 0:
                rel = self._rel_volume(bar)
                if rel is None:
                    return self._volume_unknown(bar, "touch_skipped_volume_unknown")
                if rel < t.volume_floor_mult:
                    self.skipped.append({"ts": bar.ts, "reason": f"R3.1 volume {rel:.2f}x below floor"})
                    self._note(bar, "touch_skipped_volume", rel=round(rel, 3))
                    return self.status
            self.status = "fired"
            self.fired_index, self.fired_ts, self.fired_window = index, bar.ts, w
            self.fill_price = self.entry
            self._note(bar, "fired", window=w, rel=rel, fill=self.entry)
            return self.status
        # breakout / wedge_break / breakdown: close through, then confirmation
        if self._break_index is None:
            prev = self._bars[-2] if len(self._bars) >= 2 else None
            if short:
                crossed = bar.close < self.entry and (prev is None or prev.close >= self.entry)
            else:
                crossed = bar.close > self.entry and (prev is None or prev.close <= self.entry)
            if not crossed:
                return self.status
            if not self._window_ok(bar.ts):
                self.observed_midday.append(bar.ts)
                self.status = "observed"
                self._note(bar, "break_outside_window", window=w)
                return self.status
            rel = self._rel_volume(bar)
            decisive, _ = is_decisive(bar, self._bars[:-1], direction=self.direction, thresholds=t)
            if rel is None:
                return self._volume_unknown(bar, "break_skipped_volume_unknown")
            if rel < t.volume_spike_mult:
                self.skipped.append({"ts": bar.ts, "reason": f"T3.3d no volume surge ({rel:.2f}x)"})
                self._note(bar, "break_skipped_volume", rel=round(rel, 3))
                return self.status
            if not decisive:
                self.skipped.append({"ts": bar.ts, "reason": "T3.3b/e candle not decisive"})
                self._note(bar, "break_skipped_candle")
                return self.status
            self._break_index = index
            self._note(bar, "break_candidate", rel=rel, window=w)
            return self.status
        # follow-through after the candidate break
        after = self._bars[self._break_index + 1:]
        if len(after) < t.followthrough_bars:
            return self.status
        seq = after[:t.followthrough_bars]
        bc = self._bars[self._break_index].close
        if short:
            held = all(b.close < self.entry for b in seq)
            cont = sum(1 for b in seq if b.close < bc)
        else:
            held = all(b.close > self.entry for b in seq)
            cont = sum(1 for b in seq if b.close > bc)
        if held and cont >= t.followthrough_required:
            self.status = "fired"
            self.fired_index, self.fired_ts = index, bar.ts
            self.fired_window = session_window(bar.ts)
            # a break is filled at or beyond the level, never inside it (T fired at
            # 25.84 against a 25.87 level, 2026-08-26) — the guard the dev asked for
            self.fill_price = (min(bar.close, self.entry) if short else max(bar.close, self.entry))
            self._note(bar, "fired", window=self.fired_window, fill=bar.close, confirmedAfter=t.followthrough_bars)
        else:
            self.failed_breaks += 1
            self.skipped.append({"ts": bar.ts, "reason": "T3.3c/f no follow-through / failed to hold"})
            self._note(bar, "break_failed_followthrough", held=held, continued=cont, failedBreaks=self.failed_breaks)
            self._break_index = None
            if t.max_false_breaks and self.failed_breaks >= t.max_false_breaks:
                # R3.2 — "more than two false breakouts" = poor price action; the
                # level has shown it cannot hold a break today (T 2026-08-26 broke
                # 25.86 six times inside a 3-cent box and the paid critic had to
                # refuse every one). Deterministic now.
                self.status = "exhausted"
                self.skipped.append({"ts": bar.ts, "reason": f"R3.2 {self.failed_breaks} false breakouts of this "
                                                             f"level — done for the session"})
                self._note(bar, "exhausted", failedBreaks=self.failed_breaks)
        return self.status

    def finish(self) -> str:
        if self.status in ("waiting", "observed"):
            self.status = "not_triggered" if self.status == "waiting" else "observed"
        return self.status


def score_trigger(tracker: TriggerTracker, bars: list[Bar], *, thresholds: Thresholds | None = None) -> dict:
    """After the session: simulate the fill and exits from the fire bar to the close."""
    t = thresholds or DEFAULT_THRESHOLDS
    tracker.finish()
    res = {"status": tracker.status, "firedTs": tracker.fired_ts, "firedWindow": tracker.fired_window,
           "fillPrice": tracker.fill_price, "observedMidday": len(tracker.observed_midday),
           "skipped": tracker.skipped, "events": tracker.events[-12:]}
    if tracker.status != "fired" or tracker.fired_index is None:
        return res
    i = tracker.fired_index
    plan = {"setupType": tracker.trigger.get("setupType"), "direction": tracker.direction,
            "entry": {"price": float(tracker.fill_price), "basis": "on_break"},   # fill at the fire bar
            "stop": {"price": tracker.stop},
            "targets": tracker.trigger["targets"]}
    # simulate from the fire bar (on_break fills at bars[start]); horizon = rest of session
    sim = simulate_plan(bars, i, plan, entry_window=1, horizon=len(bars),
                        stop_on="close" if t.stop_on_close else "low")
    res["sim"] = {k: sim.get(k) for k in ("filled", "outcome", "rMultiple", "mfeR", "maeR", "barsHeld", "hits", "resolved")}
    res["closedByEod"] = True
    return res


