"""Team2Runner — the Team2 technique on the shared PlanRunner money path.

The runner core (BUILDING-A-TECHNIQUE §2) owns everything that moves money: arm/restore/
persist, the fire chain, entry with retry, RiskGate, reduce-only exits, the loss halt, the
quote/premium stop watch, the failed-exit watchdog, alerts, audit, the phone summary and the
clock-driven close. Team2 supplies the READ:

- Every 2-minute close, `simulate_session` (the pure session walk in `session.py`) is re-run over
  the bars seen so far with `now_ms` = that close. Events it has not emitted before are ACTED
  on: `fire` mints a Trade and runs the shared fire chain (alert / proposal / auto);
  `trim`/`exit` on an open trade become reduce-only exits through `PlanRunner._exit`; reads
  (scenario, pm_break, skips) are logged + journaled so the audit shows what the method saw.
  Because live decisions come from the same function the scorer replays, live ≡ replay by
  construction (§6 parity).
- Plans are `TechniqueRun` rows (technique="team2", mode="plan") whose `result.plan` is the
  dict `plan.py` builds; `triggers` is empty — Team2 does not use `TriggerTracker`.
- The 09:25 pre-open hook completes the plan in place (PMH/PML, day type, sizing bucket).
- Contract: `pick_contract` reads the live chain and applies `options/pick.select_by_premium`
  (0DTE per the `dte_policy`, RiskGate's per-technique policy enforces the caps and times).

Settings resolve `techniques.team2.<key>` → `execution.<key>` via `self.rt`.
"""
from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import logging
import time
from types import SimpleNamespace

from sqlalchemy import select

from ... import events as ev
from ...domain import Bar
from ...execution.planrunner import ArmedPlan, FireJudgement, PlanRunner, Trade
from ...marketstructure.aggregate import bar_session, bucket_start_ms
from ...marketstructure.sessions import ET, session_bounds, session_date
from ...models import TechniqueRun
from .rules import Team2Rules, rules_from_settings
from .session import simulate_session

log = logging.getLogger("zargar.techniques.team2")

EXIT_KIND = {"trim1": "tp1", "trim2": "tp2"}


def _kind_for(reason: str, trims_done: int) -> str:
    r = reason.lower()
    if r.startswith("flatten"):
        return "flatten"
    if r.startswith("target"):
        return "tp3"
    if "premium stop" in r or "one-candle stop" in r and "runner" not in r:
        return "stop"
    if r.startswith("runner"):
        return "trail"
    if "first trim" in r:
        return "tp1"
    if "second trim" in r:
        return "tp2"
    return "exit"


class Team2Runner(PlanRunner):
    TECHNIQUE_ID = "team2"

    def __init__(self, engine) -> None:
        super().__init__(engine, name="team2-runner")
        self._bars: dict[str, list[Bar]] = {}          # run_id -> today's 1m bars (ext hours) seen so far
        self._warm: dict[str, list[Bar]] = {}          # run_id -> prior days' 1m bars (EMA warm-up)
        self._warm_loaded: set[str] = set()
        self._seen: dict[str, int] = {}                # run_id -> events already acted on
        self._last_sim: dict[str, dict] = {}           # run_id -> last SessionResult.to_dict()
        self._sigma_cache: dict[str, tuple[str, float]] = {}

    async def stop(self) -> None:
        for name in ("team2_plan_nightly", "team2_preopen"):
            with contextlib.suppress(Exception):
                self.engine.scheduler.unregister(name)
        await super().stop()

    # ------------------------------------------------------------- hooks
    def rules(self) -> Team2Rules:
        return rules_from_settings(self.engine.settings)

    async def load_plan(self, run_id: str) -> dict | None:
        async with self.engine.sf() as session:
            row = (await session.execute(select(TechniqueRun).where(TechniqueRun.id == run_id))).scalar_one_or_none()
        if row is None or row.technique != self.TECHNIQUE_ID:
            return None
        return {"id": row.id, "symbol": row.symbol, "mode": row.mode, "result": row.result or {},
                "config": row.config or {}, "technique": row.technique}

    async def load_baseline_bars(self, run_id: str, tf: str) -> list:
        return []

    def entry_windows_enforced(self) -> bool:
        return False                                   # the method has no schedule rule (P2); D6 gates inside the read

    async def plan_horizon(self, run: dict, plan: dict) -> tuple[int, str | None]:
        return 1, plan.get("planFor")

    async def analyze_fire(self, ap: ArmedPlan, tid: str, tr, trade: Trade) -> FireJudgement:
        fire = getattr(tr, "fire_event", {}) or {}
        return FireJudgement(verdict="setup", confidence=1.0,
                             trace=[{"stage": "read", "step": "fire", "reason": fire.get("why", ""),
                                     "regime": fire.get("regime"), "bucket": fire.get("bucket"),
                                     "touch": fire.get("touch"), "early": fire.get("early")}])

    def reviewer_available(self) -> bool:
        return False                                   # no LLM critic in v1 — the read is deterministic

    async def record_fire(self, ap, tid, tr, trade, judgement) -> None:
        return None

    async def emit_proposal(self, ap, trade, judgement, contract, *, contracts=None):
        # v1: proposal mode records the alert with the contract attached; a Signals proposal
        # comes with P5 (the earned ladder) — the runner marks it "proposal_failed" otherwise,
        # so say so plainly in the trade record instead
        trade.reason = "proposal mode is not wired for Team2 yet — recorded as an alert"
        return None

    async def after_fire(self, ap, tid, tr, trade, judgement, bar) -> None:
        return None

    def size_multiplier(self, contract: dict) -> tuple[float, list[str]]:
        m = float(contract.get("_sizeMult", 1.0) or 1.0)
        why = [f"Team2 bucket {contract.get('_bucket', '?')} ×{m:g}"] if m != 1.0 else []
        return m, why

    async def entry_limit_cap(self, ap: ArmedPlan, trade: Trade, contract: dict) -> float | None:
        ask = float(contract.get("ask") or 0.0)
        return round(ask + self.rules().tick, 2) if ask > 0 else None   # T6/C2: at the level, never chase

    async def pick_contract(self, ap: ArmedPlan, trade: Trade) -> dict | None:
        """The premium-targeted 0DTE contract (V1/F5) from the live chain."""
        trade.contract_attempted = True
        opts = getattr(self.engine, "options", None)
        if opts is None:
            trade.errors.append("options service not attached")
            return None
        rules = self.rules()
        try:
            from ...options.pick import select_by_premium
            provider = opts.provider()
            exps = await provider.expirations(ap.symbol)
            today = dt.datetime.now(ET).date()
            exps_d = sorted(e for e in exps if e)
            expiry = None
            if rules.dte_policy == "0dte":
                expiry = next((e for e in exps_d if e == today.isoformat()), None)
                if expiry is None:
                    trade.errors.append("no same-day expiry listed (dte_policy=0dte)")
                    return None
            else:
                expiry = next((e for e in exps_d if e > today.isoformat()), None)
                if expiry is None:
                    trade.errors.append("no expiry after today")
                    return None
            chain = await provider.chain(ap.symbol, expiry)
            spot = float(trade.entry)
            q = self.engine.quotes.get(ap.symbol)
            if q is not None and q.last and q.last > 0:
                spot = float(q.last)
            pick = select_by_premium(chain, spot, trade.direction, target_premium=rules.target_premium,
                                     premium_floor=rules.premium_floor, expiry=expiry, today=today,
                                     is_0dte=(expiry == today.isoformat()))
            if pick is None:
                trade.errors.append(f"no {'call' if trade.direction == 'long' else 'put'} between "
                                    f"${rules.premium_floor:.2f} and ${rules.target_premium:.2f} at {expiry}")
                return None
            c = pick.to_dict()
            c["_sizeMult"] = float(getattr(trade, "_size_mult", 1.0) or 1.0)
            c["_bucket"] = getattr(trade, "_bucket", "?")
            trade.contract = c
            trade.order_symbol = c.get("symbol")
            self._log(ap, "contract", f"{trade.trigger_id}: {c.get('display') or c.get('symbol')} ask {c.get('ask')} "
                      f"(target ${rules.target_premium:.2f}, {expiry})", trigger=trade.trigger_id)
            return c
        except Exception as exc:  # noqa: BLE001 - reported on the trade, never raised into the bar loop
            trade.errors.append(f"contract pick failed: {exc}")
            log.exception("team2 pick_contract failed")
            return None

    def preopen_due(self, now: dt.datetime) -> bool:
        m = now.hour * 60 + now.minute
        return 9 * 60 + 25 <= m < 9 * 60 + 30

    async def preopen_check(self, ap: ArmedPlan, premarket: float) -> dict | None:
        """09:25: complete the plan in place — PMH/PML, day type, sizing at the open (E11)."""
        from .plan import complete_plan
        bars = await self._today_bars(ap)
        done = complete_plan(ap.plan, bars)
        ap.plan.update(done)
        ap.plan["planFor"] = ap.plan_for
        ref = float(ap.plan.get("openPrice") or premarket or 0) or None
        prev_close = float(ap.plan.get("referencePrice") or 0) or None
        gap = ((ref - prev_close) / prev_close * 100.0) if ref and prev_close else 0.0
        self._log(ap, "preopen", f"{ap.plan.get('sheet')}", pmh=ap.plan.get("pmh"), pml=ap.plan.get("pml"),
                  dayType=ap.plan.get("dayType"), sizing=ap.plan.get("sizingAtOpen"))
        return {"rows": [], "reference": ref, "gapPct": round(gap, 3), "replan": False}

    # ------------------------------------------------------------- bars
    async def _load_warmup(self, ap: ArmedPlan) -> None:
        if ap.run_id in self._warm_loaded:
            return
        self._warm_loaded.add(ap.run_id)
        try:
            from ...marketdata import load_bars
            rows = await load_bars(self.engine.sf, ap.symbol, "1m", limit=6000)
        except Exception:  # noqa: BLE001
            rows = []
        warm = [b for b in rows if session_date(b.ts) < ap.plan_for]
        if len(warm) < 400:
            # day one: nothing banked yet — the 200 EMA on 2m needs ~400 minutes of history, so
            # fetch the last sessions' extended-hours tape once (Yahoo keeps ~20 days)
            try:
                from ...marketstructure.history import fetch_window
                from ...marketstructure.sessions import session_bounds
                end = session_bounds(ap.plan_for)[0]
                fetched = await fetch_window(ap.symbol, "1m", end - 5 * 86_400_000, end, session="ext")
                have = {b.ts for b in warm}
                warm.extend(b for b in fetched if session_date(b.ts) < ap.plan_for and b.ts not in have)
                warm.sort(key=lambda b: b.ts)
            except Exception:  # noqa: BLE001 - a failed warm-up only delays the first reads
                log.warning("team2 warm-up fetch failed for %s", ap.symbol)
        self._warm[ap.run_id] = warm
        # today's bars already banked (pre-market) join the live list
        todays = [b for b in rows if session_date(b.ts) == ap.plan_for]
        have = {b.ts for b in self._bars.get(ap.run_id, [])}
        merged = self._bars.setdefault(ap.run_id, [])
        merged.extend(b for b in todays if b.ts not in have)
        merged.sort(key=lambda b: b.ts)

    def merge_bars(self, ap: ArmedPlan, fresh: list[Bar]) -> None:
        """Add banked/fetched 1m bars of the plan's date (pre-market at 09:25) without disturbing
        the live sequence; the read re-runs over the merged list at the next 2m close."""
        cur = self._bars.setdefault(ap.run_id, [])
        have = {b.ts for b in cur}
        cur.extend(b for b in fresh if session_date(b.ts) == ap.plan_for and b.ts not in have)
        cur.sort(key=lambda b: b.ts)

    async def _today_bars(self, ap: ArmedPlan) -> list[Bar]:
        await self._load_warmup(ap)
        return list(self._bars.get(ap.run_id, []))

    async def _sigma(self, symbol: str) -> float:
        """IV proxy for the premium model (B2): ^VIX1D → ^VIX×1.3 → 0.20, cached per day."""
        day = dt.datetime.now(ET).strftime("%Y-%m-%d")
        hit = self._sigma_cache.get(symbol)
        if hit and hit[0] == day:
            return hit[1]
        sigma = 0.20
        src = str(self.rt("sigma_source", "vix1d"))
        try:
            from ...marketdata import load_bars
            if src in ("vix1d", "vix"):
                for sym, mult in (("^VIX1D", 1.0), ("^VIX", 1.3)):
                    if src == "vix" and sym == "^VIX1D":
                        continue
                    rows = await load_bars(self.engine.sf, sym, "1d", limit=3)
                    if rows and rows[-1].close > 0:
                        sigma = float(rows[-1].close) / 100.0 * mult
                        break
        except Exception:  # noqa: BLE001
            pass
        self._sigma_cache[symbol] = (day, sigma)
        return sigma

    # ------------------------------------------------------------- the bar loop (override)
    async def _on_bar(self, ap: ArmedPlan, bar: Bar, *, journal: bool) -> None:
        if session_date(bar.ts) != ap.plan_for:
            return
        if ap.last_bar_ts is not None and bar.ts <= ap.last_bar_ts:
            return
        ap.last_bar_ts = bar.ts
        ap.stale = False
        ap.bar_index += 1
        await self._load_warmup(ap)
        bars = self._bars.setdefault(ap.run_id, [])
        if not bars or bars[-1].ts < bar.ts:
            bars.append(bar)
        _, close_ms = session_bounds(ap.plan_for)
        rules = self.rules()
        step = rules.entry_tf_min * 60_000
        end_ts = bar.ts + 60_000
        # act only when a 2-minute bucket has just closed (decisions on closed bars)
        if bucket_start_ms(bar.ts, rules.entry_tf_min) + step == end_ts and bar_session(bar.ts) == "rth":
            try:
                await self._act(ap, bar, end_ts, rules, journal=journal)
            except Exception:
                log.exception("team2 read failed on %s %s", ap.symbol, bar.ts)
                self._log(ap, "read_error", f"the session read failed on the {bar.ts} bar — see logs")
        if journal and await self._maybe_loss_halt(ap):
            return
        if bar.ts >= close_ms - 60_000:
            await self._end_session(ap, journal=journal, reason="session closed")
        elif journal:
            await self._persist(ap)

    async def _act(self, ap: ArmedPlan, bar: Bar, now_ms: int, rules: Team2Rules, *, journal: bool) -> None:
        plan = dict(ap.plan)
        plan.setdefault("date", ap.plan_for)
        if not plan.get("zones"):
            return
        sigma = await self._sigma(ap.symbol)
        res = simulate_session(plan, self._bars.get(ap.run_id, []), rules, sigma=sigma, now_ms=now_ms,
                               warmup_1m=self._warm.get(ap.run_id, []))
        self._last_sim[ap.run_id] = res.to_dict()
        seen = self._seen.get(ap.run_id, 0)
        new = res.events[seen:]
        self._seen[ap.run_id] = len(res.events)
        halted = bool(getattr(self.engine.halt, "engaged", False))
        for e in new:
            what = e["event"]
            if what == "fire":
                await self._fire_from_event(ap, e, bar, res, halted=halted, journal=journal)
            elif what in ("trim", "exit"):
                await self._exit_from_event(ap, e, journal=journal)
            else:
                self._log(ap, what, e.get("why", what), **{k: v for k, v in e.items()
                                                          if k not in ("event", "why", "regime")})
                if journal and what in ("scenario", "pm_break", "late_touch", "skip_engulfing",
                                        "skip_range_confirmation", "skip_no_trade_zone", "skip_no_contract",
                                        "skip_reentries"):
                    await self.engine.journal.append(ev.TECHNIQUE_PLAN_TRIGGER_SKIPPED, {
                        "runId": ap.run_id, "symbol": ap.symbol, "trigger": str(e.get("setup") or e.get("scenario") or what),
                        "event": what, "ts": e.get("ts"), "reason": e.get("why", "")},
                        aggregate_type="technique_run", aggregate_id=ap.run_id)
                    self._publish(ap, what)

    async def _fire_from_event(self, ap: ArmedPlan, e: dict, bar: Bar, res, *, halted: bool, journal: bool) -> None:
        tid = f"{e.get('setup')}#{e.get('touch')}"
        if tid in ap.trades:
            return
        if ap.status == "paused":
            self._log(ap, "paused_skip", f"{tid}: conditions met but the plan is paused", trigger=tid)
            return
        if halted:
            self._log(ap, "halt_skip", f"{tid}: conditions met but the kill switch is engaged", trigger=tid)
            return
        open_or_working = sum(1 for t in ap.trades.values() if t.status in ("fired", "submitting", "working", "open"))
        if ap.config.mode == "auto" and open_or_working >= max(1, ap.config.max_open_trades):
            self._log(ap, "max_open_skip", f"{tid}: fired but already holding {open_or_working}", trigger=tid)
            return
        # A12: SPY/QQQ/IWM fire together on index moves — one Team2 position across ALL its plans
        # (money modes only; alert/proposal keep recording every read)
        if ap.config.mode == "auto":
            cap = max(1, int(self.rules().max_concurrent_positions))
            across = self.open_positions_across_plans()
            if across >= cap:
                self._log(ap, "max_concurrent_skip",
                          f"{tid}: fired but Team2 already holds {across} position(s) across its plans (cap {cap}, A12)",
                          trigger=tid)
                if journal:
                    await self.engine.journal.append(ev.TECHNIQUE_PLAN_TRIGGER_SKIPPED, {
                        "runId": ap.run_id, "symbol": ap.symbol, "trigger": tid, "event": "max_concurrent_positions",
                        "open": across, "max": cap, "ts": e.get("ts")},
                        aggregate_type="technique_run", aggregate_id=ap.run_id)
                return
        direction = "long" if e.get("regime", {}).get("stack") == "bull" else "short"
        setup = next((s for s in res.setups if s["id"] == e.get("setup")), {})
        direction = setup.get("direction") or direction
        spot = float(e.get("spot") or bar.close)
        atr = float((e.get("regime") or {}).get("atr") or 0.0) or max(spot * 0.001, 0.05)
        stop = spot - atr if direction == "long" else spot + atr
        target = setup.get("target")
        trade = Trade(trigger_id=tid, kind=str(setup.get("kind") or "team2"), direction=direction, fired_ts=e["ts"],
                      window="team2", entry=spot, stop=stop, targets=[float(target)] if target else [],
                      fire_bar_index=ap.bar_index - 1, last_price=bar.close, instrument=ap.config.instrument,
                      multiplier=100.0 if ap.config.instrument == "options" else 1.0)
        trade._size_mult = float(e.get("sizeMult") or 1.0)        # read by size_multiplier via the contract
        trade._bucket = str(e.get("bucket") or "?")
        trade.setup_id = str(e.get("setup"))
        ap.trades[tid] = trade
        self._log(ap, "fired", f"{tid}: {e.get('why', '')}", trigger=tid, spot=spot, premiumModel=e.get("premium"),
                  strikeModel=e.get("strike"), bucket=trade._bucket, early=e.get("early"))
        stub = SimpleNamespace(kind=trade.kind, direction=direction, fill_price=spot, entry=spot, stop=stop,
                               fire_event=e, trigger={"targets": [{"price": target}] if target else []},
                               status="fired")
        if journal:
            task = asyncio.create_task(self._fire_rest(ap, tid, stub, bar, ap.bar_index - 1, trade, journal=True),
                                       name=f"fire-{ap.symbol}-{tid}")
            ap.fire_tasks[tid] = task
            task.add_done_callback(lambda t, tid=tid, ap=ap: ap.fire_tasks.pop(tid, None))
        else:
            await self._fire_rest(ap, tid, stub, bar, ap.bar_index - 1, trade, journal=False)

    async def _exit_from_event(self, ap: ArmedPlan, e: dict, *, journal: bool) -> None:
        # the simulation names the setup via the position; find the open trade of that setup
        setup_id = None
        sim = self._last_sim.get(ap.run_id) or {}
        # the position that just (partly) closed is either the open one or the last trade
        pos = sim.get("openPosition") or (sim.get("trades") or [{}])[-1]
        setup_id = pos.get("setup")
        cands = [t for t in ap.trades.values() if t.setup_id == setup_id and t.status in ("open", "working", "alert", "proposal")]
        if not cands:
            return
        trade = sorted(cands, key=lambda t: t.fired_ts)[-1]
        kind = _kind_for(str(e.get("why", "")), trade.trims_done)
        frac = float(e.get("fraction") or 1.0)
        if trade.status in ("alert", "proposal") or not journal:
            self._log(ap, f"would_{e['event']}", f"{trade.trigger_id}: {e.get('why', '')} (model {e.get('pnlPct')}%)",
                      trigger=trade.trigger_id, fraction=frac, pnlPctModel=e.get("pnlPct"))
            if e["event"] == "exit":
                trade.closed_ts = e.get("ts")
            return
        if trade.status != "open" or trade.remaining <= 0:
            return
        qty = float(int(round(trade.filled_qty * frac))) if e["event"] == "trim" else trade.remaining
        qty = max(1.0, min(qty, trade.remaining)) if trade.remaining >= 1 else trade.remaining
        if kind in ("tp1", "tp2"):
            trade.trims_done += 1
        await self._exit(ap, trade, kind, qty, journal=True, reason=str(e.get("why", "")),
                         force_market=kind in ("stop", "flatten"))

    def open_positions_across_plans(self) -> int:
        """Open or in-flight Team2 trades across every armed plan (A12 concurrency cap)."""
        return sum(1 for ap in self._armed.values() for t in ap.trades.values()
                   if t.status in ("fired", "submitting", "working", "open"))

    # ------------------------------------------------------------- read-only views
    def last_read(self, run_id: str) -> dict | None:
        return self._last_sim.get(run_id)

    def _snapshot(self, ap: ArmedPlan) -> dict:
        """The Armed page speaks in triggers; Team2 has none (its read is the session walk), so
        the snapshot carries PSEUDO-triggers — the zones being watched before a scenario exists,
        the live setups after — and a summary in the method's own words. Same fields the
        Armed page already renders (id/label/kind/status/entry/targets/direction/distancePct),
        so no UI special-casing (user 2026-09-04: 'tell me how it works' inside the Armed section)."""
        d = super()._snapshot(ap)
        plan = ap.plan or {}
        read = self._last_sim.get(ap.run_id) or {}
        q = self.engine.quotes.get(ap.symbol)
        last = float(q.last) if q is not None and q.last and q.last > 0 else None
        zones = plan.get("zones") or {}
        pdh, pdl = zones.get("pdh") or {}, zones.get("pdl") or {}
        trig: list[dict] = []

        def pseudo(tid: str, label: str, kind: str, status: str, entry: float | None, direction: str,
                   targets: list[float] | None = None, stop: float | None = None) -> dict:
            row = {"id": tid, "label": label, "kind": kind, "status": status, "entry": entry, "stop": stop,
                   "targets": targets or [], "riskReward": None, "firedTs": None, "firedWindow": None,
                   "observedMidday": 0, "skipped": [], "gapUnchecked": False, "failedBreaks": 0, "grade": None,
                   "gradeScore": None, "conditions": None, "setupId": None, "direction": direction,
                   "levelTouches": None, "levelAge": None, "windowOpenNow": True}
            if last and entry:
                row["distancePct"] = round((entry - last) / last * 100, 3)
                row["distance"] = round(entry - last, 4)
            return row

        setups = read.get("setups") or []
        fired_setups = {t["setup"] for t in (read.get("trades") or [])}
        open_pos = read.get("openPosition")
        if not setups and pdh and pdl:
            tgt_up, tgt_dn = (plan.get("targets") or {}).get("above"), (plan.get("targets") or {}).get("below")
            trig.append(pseudo("pdh", f"15m close above the PDH zone {pdh.get('bottom', 0):.2f}–{pdh.get('top', 0):.2f} → calls",
                               "break PDH", "waiting" if ap.status == "armed" else ap.status, pdh.get("top"), "long",
                               [tgt_up] if tgt_up else []))
            trig.append(pseudo("pdl", f"15m close below the PDL zone {pdl.get('bottom', 0):.2f}–{pdl.get('top', 0):.2f} → puts",
                               "break PDL", "waiting" if ap.status == "armed" else ap.status, pdl.get("bottom"), "short",
                               [tgt_dn] if tgt_dn else []))
        for s in setups:
            label = (f"{s['kind'].replace('_', ' ')} at {s['anchor']:.2f} — buying the EMA13 pullbacks "
                     f"({'call' if s['direction'] == 'long' else 'put'}s), touches {s['touches']}")
            status = ("invalidated" if s.get("dead") else "fired" if (s["id"] in fired_setups or (open_pos and open_pos.get("setup") == s["id"]))
                      else "observed" if s.get("touches") else "waiting")
            trig.append(pseudo(s["id"], label, s["kind"], status, s.get("anchor"), s["direction"],
                               [s["target"]] if s.get("target") else []))
        if trig:
            d["triggers"] = trig
        # summary in the method's words
        regime = read.get("regimeLast") or {}
        bias = read.get("bias") or {}
        if ap.status in ("expired", "disarmed"):
            pass                                          # the base summary already says so
        elif ap.status == "paused":
            d["summary"] = "paused — reading, not firing"
        elif open_pos:
            d["summary"] = (f"in trade {open_pos.get('setup')}: {'call' if open_pos.get('call') else 'put'} {open_pos.get('strike'):g}, "
                            f"{open_pos.get('remaining', 1):.2f} left, peak +{open_pos.get('peakPct', 0):.0f}% — stop is a 2m close through the EMA13")
        elif bias.get("scenario"):
            live = [s for s in setups if not s.get("dead")]
            touches = max((s.get("touches", 0) for s in live), default=0)
            d["summary"] = (f"scenario {bias['scenario']} ({bias.get('label')}) → {'calls' if bias.get('direction') == 'long' else 'puts'} · "
                            f"waiting for the 1st/2nd 2m pullback into the EMA13 (touches {touches}) · EMA stack {regime.get('stack', '?')}, "
                            f"{regime.get('fan', '?')}")
        elif pdh and pdl:
            pm = (f" · PM {plan['pml']:.2f}–{plan['pmh']:.2f}" if plan.get("pmh") and plan.get("pml") else " · pre-market range at 09:25")
            day = f" · {str(plan.get('dayType')).replace('_', ' ')} day" if plan.get("dayType") else ""
            d["summary"] = (f"no scenario yet — needs a 15m close above {pdh.get('top', 0):.2f} (calls) or below "
                            f"{pdl.get('bottom', 0):.2f} (puts){pm}{day}"
                            + (f" · EMA stack {regime.get('stack')}, {regime.get('fan')}" if regime else ""))
        d["team2"] = {"sheet": plan.get("sheet"), "dayType": plan.get("dayType"), "sizingAtOpen": plan.get("sizingAtOpen"),
                      "bias": bias or None, "regime": regime or None, "read": {k: read.get(k) for k in ("summary",)} if read else None}
        return d


# ----------------------------------------------------------------- attach
async def attach_team2_runner(engine) -> None:
    """Called from the FastAPI lifespan after the engine starts (same shape as the tip runner)."""
    if getattr(engine, "team2_runner", None) is not None:
        return
    if not bool(engine.settings.get("techniques.team2.enabled", True)):
        log.info("team2 technique disabled (techniques.team2.enabled)")
        return
    runner = Team2Runner(engine)
    engine.team2_runner = runner
    if getattr(engine, "plan_runners", None) is None:
        engine.plan_runners = {}
    engine.plan_runners["team2"] = runner
    if getattr(engine, "techniques", None) is None:
        engine.techniques = {}
    engine.techniques.setdefault("team2", runner)
    try:
        restored = await runner.restore()
        if restored:
            log.info("team2 runner restored %d armed plan(s)", restored)
    except Exception:  # pragma: no cover
        log.exception("team2 runner restore failed")
    from .service import Team2Service
    engine.team2 = Team2Service(engine, runner)
    engine.scheduler.register("team2_plan_nightly", str(engine.settings.get("techniques.team2.plan_at", "17:00")),
                              lambda: engine.team2.nightly_plans())
    engine.scheduler.register("team2_preopen", str(engine.settings.get("techniques.team2.preopen_at", "09:25")),
                              lambda: engine.team2.preopen_complete())


__all__ = ["Team2Runner", "attach_team2_runner"]
