"""Walk-forward validation of session plans (spec §6 of the walk-forward plan).

    for each session N: plan = build_session_plan(as_of = close of N)
                        replay(plan, bars of N+1)        # bar by bar, no look-ahead

`TriggerTracker` evaluates one trigger incrementally — the same object scores a
plan against historical bars here and watches live bars in `arming.py`, so
validation and live behaviour cannot drift apart. Fills and exits go through
`outcome.simulate_plan` (the backtester's and the outcome loop's scorer).

Two metric families are kept apart on purpose:
  * level quality  — did price *respect* each planned level? (no trades needed)
  * trigger quality — trigger rate, fill rate, win rate, R, per kind / window / tf
Each rule that is ours (R6 gating, gap rules) is also evaluated *without* itself
(counterfactuals) so its value is measured, not assumed.
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass, field

from ..domain import Bar
from .analysis import AnalysisRequest, compute_facts
from .candles import is_decisive
from .history import fetch_window
from .levels import session_key
from .outcome import simulate_plan
from .plans import SessionPlan, build_session_plan
from .rulebook import (
    DEFAULT_THRESHOLDS,
    PRIME_WINDOWS,
    Thresholds,
    session_bounds,
    session_date,
    session_window,
)
from .volume import VolumeProfile, build_profile, relative_volume

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

    status: str = "waiting"        # waiting | gapped_past | gapped_through | gap_void | observed | fired | not_triggered | expired
    fired_index: int | None = None
    fired_ts: int | None = None
    fired_window: str | None = None
    fill_price: float | None = None
    observed_midday: list[int] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    _bars: list[Bar] = field(default_factory=list)
    _break_index: int | None = None
    _gap_checked: bool = False

    # -- helpers
    @property
    def entry(self) -> float:
        return float(self.trigger["entry"]["price"])

    @property
    def stop(self) -> float:
        return float(self.trigger["stop"]["price"])

    @property
    def risk(self) -> float:
        return max(self.entry - self.stop, 1e-9)

    @property
    def kind(self) -> str:
        return self.trigger["kind"]

    def _note(self, bar: Bar, what: str, **detail) -> None:
        self.events.append({"ts": bar.ts, "event": what, **detail})

    def _rel_volume(self, bar: Bar) -> float | None:
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
        return (not self.enforce_windows) or session_window(ts) in PRIME_WINDOWS

    # -- main
    def on_bar(self, bar: Bar, index: int) -> str:
        t = self.thresholds
        self._bars.append(bar)
        if self.status in ("fired", "gapped_past", "gapped_through", "gap_void", "expired"):
            return self.status
        # opening gap checks, once
        if not self._gap_checked:
            self._gap_checked = True
            if self.gap_rules:
                # specific first (through the stop / past the level), then the magnitude rule
                if self.kind == "bounce":
                    if bar.open < self.stop:
                        self.status = "gapped_through"
                        self._note(bar, "gapped_through", open=bar.open, stop=self.stop)
                        return self.status
                    if bar.open <= self.entry:
                        self.status = "gapped_past"
                        self._note(bar, "gapped_past", open=bar.open, entry=self.entry)
                        return self.status
                else:
                    if bar.open > self.entry:
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
        if self.kind == "bounce":
            tol = max(self.entry * t.level_tolerance_pct, 1e-9)
            touched = bar.low <= self.entry + tol
            if not touched:
                return self.status
            if not self._window_ok(bar.ts):
                self.observed_midday.append(bar.ts)
                self.status = "observed"
                self._note(bar, "touch_outside_window", window=w)
                return self.status
            rel = self._rel_volume(bar)
            if rel is not None and rel < t.volume_floor_mult:
                self.skipped.append({"ts": bar.ts, "reason": f"R3.1 volume {rel:.2f}x below floor"})
                self._note(bar, "touch_skipped_volume", rel=round(rel, 3))
                return self.status
            self.status = "fired"
            self.fired_index, self.fired_ts, self.fired_window = index, bar.ts, w
            self.fill_price = self.entry
            self._note(bar, "fired", window=w, rel=rel, fill=self.entry)
            return self.status
        # breakout / wedge_break: close through, then confirmation
        if self._break_index is None:
            prev = self._bars[-2] if len(self._bars) >= 2 else None
            crossed = bar.close > self.entry and (prev is None or prev.close <= self.entry)
            if not crossed:
                return self.status
            if not self._window_ok(bar.ts):
                self.observed_midday.append(bar.ts)
                self.status = "observed"
                self._note(bar, "break_outside_window", window=w)
                return self.status
            rel = self._rel_volume(bar)
            decisive, _ = is_decisive(bar, self._bars[:-1], direction="long", thresholds=t)
            if rel is not None and rel < t.volume_spike_mult:
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
        held = all(b.close > self.entry for b in seq)
        cont = sum(1 for b in seq if b.close > self._bars[self._break_index].close)
        if held and cont >= t.followthrough_required:
            self.status = "fired"
            self.fired_index, self.fired_ts = index, bar.ts
            self.fired_window = session_window(bar.ts)
            self.fill_price = bar.close
            self._note(bar, "fired", window=self.fired_window, fill=bar.close, confirmedAfter=t.followthrough_bars)
        else:
            self.skipped.append({"ts": bar.ts, "reason": "T3.3c/f no follow-through / failed to hold"})
            self._note(bar, "break_failed_followthrough", held=held, continued=cont)
            self._break_index = None
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
    plan = {"setupType": tracker.trigger.get("setupType"),
            "entry": {"price": float(tracker.fill_price), "basis": "on_break"},   # fill at the fire bar
            "stop": {"price": tracker.stop},
            "targets": tracker.trigger["targets"]}
    # simulate from the fire bar (on_break fills at bars[start]); horizon = rest of session
    sim = simulate_plan(bars, i, plan, entry_window=1, horizon=len(bars))
    sim["rMultiple"] = sim["rMultiple"]
    res["sim"] = {k: sim.get(k) for k in ("filled", "outcome", "rMultiple", "mfeR", "maeR", "barsHeld", "hits", "resolved")}
    res["closedByEod"] = True
    return res


def replay_plan(plan: dict, bars: list[Bar], *, thresholds: Thresholds | None = None,
                profile: VolumeProfile | None = None, include_invalid: bool = False) -> dict:
    """Replay one session against a plan. Returns per-trigger results (with
    counterfactuals) plus level respect and a summary."""
    t = thresholds or DEFAULT_THRESHOLDS
    prev_close = float(plan.get("lastClose") or 0) or None
    out_triggers: list[dict] = []
    if not bars:
        return {"session": plan.get("planFor"), "bars": 0, "triggers": [], "levels": [],
                "summary": {"note": "no bars for the planned session (holiday / no data)"}}
    open_px = bars[0].open
    gap_pct = round((open_px - prev_close) / prev_close * 100, 3) if prev_close else None
    for tg in plan.get("triggers") or []:
        if not tg.get("valid") and not include_invalid:
            out_triggers.append({"id": tg["id"], "kind": tg["kind"], "valid": False,
                                 "status": "not_tradeable", "reasons": tg.get("noTradeReasons")})
            continue
        variants = {
            "base": TriggerTracker(tg, t, profile, True, True, prev_close),
            "noWindowGate": TriggerTracker(tg, t, profile, False, True, prev_close),
            "noGapRules": TriggerTracker(tg, t, profile, True, False, prev_close),
        }
        for i, b in enumerate(bars):
            for v in variants.values():
                v.on_bar(b, i)
        scored = {k: score_trigger(v, bars, thresholds=t) for k, v in variants.items()}
        base = scored["base"]
        out_triggers.append({
            "id": tg["id"], "kind": tg["kind"], "valid": True, "levelPrice": tg["levelPrice"],
            "entry": tg["entry"]["price"], "stop": tg["stop"]["price"], "riskReward": tg["riskReward"],
            "confluences": tg.get("confluences"), "confidence": tg.get("confidence"),
            **base,
            "counterfactual": {"noWindowGate": scored["noWindowGate"], "noGapRules": scored["noGapRules"]},
        })
    levels = level_respect(plan.get("levels") or [], bars, thresholds=t)
    fired = [x for x in out_triggers if x.get("status") == "fired"]
    sims = [x["sim"] for x in fired if x.get("sim")]
    summary = {
        "gapPct": gap_pct, "open": open_px, "close": bars[-1].close,
        "triggers": len([x for x in out_triggers if x.get("valid")]),
        "fired": len(fired),
        "wins": sum(1 for s in sims if (s.get("rMultiple") or 0) > 0),
        "sumR": round(sum(s.get("rMultiple") or 0 for s in sims), 4),
        "levelsRespected": sum(1 for l in levels if l["status"] == "respected"),
        "levelsBroken": sum(1 for l in levels if l["status"] in ("broken", "flipped")),
        "levelsFlipped": sum(1 for l in levels if l["status"] == "flipped"),
        "levelsUntested": sum(1 for l in levels if l["status"] == "untested"),
        "statuses": {x.get("status"): 1 for x in out_triggers},
    }
    return {"session": plan.get("planFor"), "bars": len(bars), "triggers": out_triggers, "levels": levels,
            "summary": summary}


# --- sweep ----------------------------------------------------------------------------


def _by_session(bars: list[Bar]) -> dict[str, list[Bar]]:
    out: dict[str, list[Bar]] = defaultdict(list)
    for b in bars:
        out[session_date(b.ts)].append(b)
    return dict(out)


async def run_symbol(symbol: str, start: str, end: str, *, structure_tfs: list[str], trigger_tf: str,
                     thresholds: Thresholds, warmup_sessions: int = 6, include_invalid: bool = False,
                     bars_override: dict[str, list[Bar]] | None = None,
                     progress=None) -> list[dict]:
    """Walk [start, end] for one symbol: one row per (plan session N, scored on N+1).
    `bars_override` (tf -> bars) lets tests / replays skip Yahoo."""
    o_ms, _ = session_bounds(start)
    _, e_ms = session_bounds(end)
    warm_ms = warmup_sessions * 2 * 86_400_000
    bars_by_tf: dict[str, list[Bar]] = {}
    for tf in list(structure_tfs) + [trigger_tf]:
        if bars_override and tf in bars_override:
            bars_by_tf[tf] = list(bars_override[tf])
        else:
            bars_by_tf[tf] = await fetch_window(symbol, tf, o_ms - warm_ms, e_ms)
    trig = bars_by_tf.get(trigger_tf) or []
    if not trig:
        return [{"symbol": symbol, "session": None, "error": f"no {trigger_tf} bars"}]
    sessions = _by_session(trig)
    keys = sorted(sessions)
    rows: list[dict] = []
    for i, day in enumerate(keys):
        if day < start or day > end or i + 1 >= len(keys):
            continue
        nxt = keys[i + 1]
        close_ms = sessions[day][-1].ts
        as_of = session_bounds(day)[1]          # 16:00 ET of N: outside the session, plan mode
        window = {tf: [b for b in bars if b.ts <= close_ms] for tf, bars in bars_by_tf.items()}
        if not window.get(trigger_tf):
            continue
        req = AnalysisRequest(symbol=symbol, as_of_ms=as_of, primary_tf=trigger_tf,
                              context_tfs=tuple(structure_tfs), thresholds=thresholds)
        facts = compute_facts(req, window, [])
        plan = build_session_plan(facts, thresholds=thresholds, structure_tfs=structure_tfs,
                                  trigger_tf=trigger_tf).to_dict()
        next_bars = sessions[nxt]
        prof = build_profile([b for b in trig if session_date(b.ts) < nxt and session_date(b.ts) >= keys[max(0, i - warmup_sessions)]])
        rep = replay_plan(plan, next_bars, thresholds=thresholds, profile=prof, include_invalid=include_invalid)
        rows.append({"symbol": symbol, "session": day, "planFor": nxt, "plan": _slim_plan(plan), "result": rep})
        if progress:
            await progress(symbol, day, len(rows))
    return rows


def _slim_plan(plan: dict) -> dict:
    return {k: plan.get(k) for k in ("symbol", "planFor", "builtFromSession", "structureTfs", "triggerTf",
                                     "lastClose", "levels", "triggers", "validTriggers", "invalidations")}


def aggregate(rows: list[dict]) -> dict:
    """Roll sweep rows up into the two metric families + claim checks (§6.4)."""
    lv_by_source: dict[str, dict] = defaultdict(lambda: {"n": 0, "respected": 0, "broken": 0, "flipped": 0, "untested": 0})
    lv_by_touch: dict[str, dict] = defaultdict(lambda: {"n": 0, "respected": 0, "broken": 0, "flipped": 0, "untested": 0})
    lv_by_tf: dict[str, dict] = defaultdict(lambda: {"n": 0, "respected": 0, "broken": 0, "flipped": 0, "untested": 0})
    lv_pd: dict[str, dict] = {"priorDay": {"n": 0, "respected": 0, "broken": 0, "flipped": 0, "untested": 0},
                              "other": {"n": 0, "respected": 0, "broken": 0, "flipped": 0, "untested": 0}}
    trig_by_kind: dict[str, dict] = defaultdict(lambda: {"planned": 0, "fired": 0, "wins": 0, "sumR": 0.0,
                                                         "gappedPast": 0, "gappedThrough": 0, "gapVoid": 0,
                                                         "observedMidday": 0, "notTriggered": 0, "mfeR": 0.0, "maeR": 0.0})
    trig_by_window: dict[str, dict] = defaultdict(lambda: {"fired": 0, "wins": 0, "sumR": 0.0})
    cf = {"base": {"fired": 0, "wins": 0, "sumR": 0.0}, "noWindowGate": {"fired": 0, "wins": 0, "sumR": 0.0},
          "noGapRules": {"fired": 0, "wins": 0, "sumR": 0.0}}
    midday_fires = {"fired": 0, "wins": 0, "sumR": 0.0}
    by_rr_gate: dict[str, dict] = defaultdict(lambda: {"fired": 0, "wins": 0, "sumR": 0.0})
    sessions = 0
    symbols = set()
    for r in rows:
        res = r.get("result") or {}
        if not res.get("bars"):
            continue
        sessions += 1
        symbols.add(r.get("symbol"))
        for l in res.get("levels") or []:
            for src in (l.get("sources") or ["?"]):
                d = lv_by_source[src]; d["n"] += 1; d[l["status"]] += 1
            tb = "1" if (l.get("touchesPlanned") or 0) <= 1 else "2" if l["touchesPlanned"] == 2 else "3+"
            d = lv_by_touch[tb]; d["n"] += 1; d[l["status"]] += 1
            for tf in (l.get("timeframes") or ["?"]):
                d = lv_by_tf[tf]; d["n"] += 1; d[l["status"]] += 1
            d = lv_pd["priorDay" if l.get("priorDayExtreme") else "other"]; d["n"] += 1; d[l["status"]] += 1
        for tg in res.get("triggers") or []:
            if not tg.get("valid"):
                continue
            k = trig_by_kind[tg["kind"]]
            k["planned"] += 1
            st = tg.get("status")
            if st == "fired":
                s = tg.get("sim") or {}
                rr = s.get("rMultiple") or 0.0
                k["fired"] += 1; k["sumR"] += rr; k["wins"] += 1 if rr > 0 else 0
                k["mfeR"] += s.get("mfeR") or 0.0; k["maeR"] += s.get("maeR") or 0.0
                w = trig_by_window[tg.get("firedWindow") or "?"]
                w["fired"] += 1; w["sumR"] += rr; w["wins"] += 1 if rr > 0 else 0
                cf["base"]["fired"] += 1; cf["base"]["sumR"] += rr; cf["base"]["wins"] += 1 if rr > 0 else 0
                gate = "rr>=4" if (tg.get("riskReward") or 0) >= 4 else "rr3-4"
                g = by_rr_gate[gate]; g["fired"] += 1; g["sumR"] += rr; g["wins"] += 1 if rr > 0 else 0
            elif st == "gapped_past":
                k["gappedPast"] += 1
            elif st == "gapped_through":
                k["gappedThrough"] += 1
            elif st == "gap_void":
                k["gapVoid"] += 1
            elif st == "observed":
                k["observedMidday"] += 1
            else:
                k["notTriggered"] += 1
            for name in ("noWindowGate", "noGapRules"):
                c = (tg.get("counterfactual") or {}).get(name) or {}
                if c.get("status") == "fired":
                    rr = (c.get("sim") or {}).get("rMultiple") or 0.0
                    cf[name]["fired"] += 1; cf[name]["sumR"] += rr; cf[name]["wins"] += 1 if rr > 0 else 0
                    if name == "noWindowGate" and c.get("firedWindow") == "midday":
                        midday_fires["fired"] += 1; midday_fires["sumR"] += rr; midday_fires["wins"] += 1 if rr > 0 else 0

    def rate(d, num, den):
        return round(d[num] / d[den], 3) if d.get(den) else None

    def finish_lv(m):
        return {k: {**v, "respectRate": rate(v, "respected", "n"),
                    "testedRespectRate": (round(v["respected"] / (v["n"] - v["untested"]), 3)
                                          if (v["n"] - v["untested"]) else None)} for k, v in m.items()}

    def finish_tr(m):
        out = {}
        for k, v in m.items():
            out[k] = {**{kk: (round(vv, 4) if isinstance(vv, float) else vv) for kk, vv in v.items()},
                      "winRate": rate(v, "wins", "fired"),
                      "avgR": round(v["sumR"] / v["fired"], 3) if v.get("fired") else None,
                      "triggerRate": rate(v, "fired", "planned") if "planned" in v else None}
        return out

    trig_kind = finish_tr(trig_by_kind)
    windows = finish_tr(trig_by_window)
    cfo = finish_tr(cf)
    pd_ = finish_lv(lv_pd)
    touch = finish_lv(lv_by_touch)

    # claim grid (§6.4) — only what the data can say
    claims = []
    def claim(name, rule, metric, ok, detail):
        claims.append({"claim": name, "rule": rule, "metric": metric,
                       "verdict": ("pass" if ok else "fail") if ok is not None else "insufficient", "detail": detail})
    a, b = pd_["priorDay"].get("testedRespectRate"), pd_["other"].get("testedRespectRate")
    claim("Prior-day HOD/LOD are the strongest levels", "T1.3a", "tested respect rate prior-day vs other",
          (a > b) if (a is not None and b is not None) else None, {"priorDay": a, "other": b})
    t2, t3 = touch.get("2", {}).get("testedRespectRate"), touch.get("3+", {}).get("testedRespectRate")
    claim("More touches = stronger level", "T1.2", "tested respect rate 3+ vs 2",
          (t3 >= t2) if (t2 is not None and t3 is not None) else None, {"2": t2, "3+": t3})
    po, pc, md = windows.get("prime_open", {}), windows.get("prime_close", {}), midday_fires
    prime_r = ((po.get("sumR") or 0) + (pc.get("sumR") or 0)) / max(1, (po.get("fired") or 0) + (pc.get("fired") or 0)) \
        if ((po.get("fired") or 0) + (pc.get("fired") or 0)) else None
    mid_r = (md["sumR"] / md["fired"]) if md["fired"] else None
    claim("Prime windows beat mid-day", "R6.1-R6.3", "avg R prime vs mid-day (counterfactual fires)",
          (prime_r > mid_r) if (prime_r is not None and mid_r is not None) else None,
          {"primeAvgR": round(prime_r, 3) if prime_r is not None else None, "middayAvgR": round(mid_r, 3) if mid_r is not None else None,
           "primeFired": (po.get("fired") or 0) + (pc.get("fired") or 0), "middayFired": md["fired"]})
    base_r = cfo["base"].get("avgR"); ng = cfo["noGapRules"].get("avgR")
    claim("Gap rules help (ours)", "Q11-Q13", "avg R with vs without gap rules",
          (base_r >= ng) if (base_r is not None and ng is not None) else None, {"with": base_r, "without": ng})
    g3, g4 = by_rr_gate.get("rr3-4", {}), by_rr_gate.get("rr>=4", {})
    claim("R:R >= 3 gate is not dominated by a stricter one", "R2", "avg R for 3-4 vs >=4",
          None if not (g3.get("fired") and g4.get("fired")) else (g3["sumR"] / g3["fired"] >= 0.5 * (g4["sumR"] / g4["fired"])),
          {"rr3-4": finish_tr({"x": g3})["x"] if g3 else None, "rr>=4": finish_tr({"x": g4})["x"] if g4 else None})
    bk = trig_kind.get("breakout", {}); bo = trig_kind.get("bounce", {})
    claim("Confirmed breakouts are worth taking", "T3.3a-c", "breakout win rate / avg R",
          (bk.get("avgR") or 0) > 0 if bk.get("fired") else None, {"breakout": bk})
    claim("Bounce at the level works", "T4.1/T4.2", "bounce win rate / avg R",
          (bo.get("avgR") or 0) > 0 if bo.get("fired") else None, {"bounce": bo})

    total_fired = cfo["base"]["fired"]
    return {
        "sessions": sessions, "symbols": sorted(s for s in symbols if s),
        "levels": {"bySource": finish_lv(lv_by_source), "byTouches": touch, "byTimeframe": finish_lv(lv_by_tf),
                   "priorDayVsOther": pd_},
        "triggers": {"byKind": trig_kind, "byWindow": windows, "counterfactual": cfo,
                     "middayFiresWithoutGate": finish_tr({"midday": midday_fires})["midday"],
                     "byRrGate": finish_tr(by_rr_gate)},
        "claims": claims,
        "sample": {"fired": total_fired, "target": 100,
                   "note": "the book asks for >= 100 trades before trusting a result (p. 72)"},
    }
