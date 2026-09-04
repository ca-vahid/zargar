"""Team2Runner — the Team2 technique on the shared PlanRunner money path.

The runner core (BUILDING-A-TECHNIQUE §2) owns everything that moves money: arm/restore/
persist, the fire chain, entry with retry, RiskGate, reduce-only exits, the loss halt, the
quote/premium stop watch, the failed-exit watchdog, alerts, audit, the phone summary and the
clock-driven close. Team2 supplies the READ:

- Every 2-minute close, `simulate_session` (the pure session walk in `session.py`) is re-run over
  the bars seen so far with `now_ms` = that close. Events it has not emitted before are ACTED
  on: `fire` mints a Trade and runs the shared fire chain (alert / proposal / auto);
  `trim`/`exit` on an open trade become reduce-only exits through `PlanRunner._exit` — but
  premium-% trims are judged on the contract's LIVE quote first (`_manage_live_trims`, every
  1m bar): the model's +50/+100% is a forecast, the bid is the fact; `add` (X5 trim-and-add)
  becomes a second Trade on the SAME contract through the ordinary fire chain (RiskGate inside); reads
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
        self._small_noted: set[tuple[str, str]] = set()
        self._loss_tally: dict[str, dict[str, tuple[int, str]]] = {}   # day -> run_id -> (losers, basis) (F37/F38)

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
        """T6/C2 never chase, anchored to the METHOD's premium band (F14, 2026-09-04): the fire chain
        re-prices the pick on the live NBBO before asking for the cap, so "ask + a tick" could never
        bind — a $0.55 pick from the delayed chain was buyable at $1.20 on OPRA. The cap is
        min(ask + tick, target_premium x chase_cap_mult); PlanRunner rests the entry at the cap and
        cancels it unfilled (`entry_capped`), which is the method's "if it ran, it ran" (V1/F5)."""
        rules = self.rules()
        band = round(float(rules.target_premium) * float(rules.chase_cap_mult), 2)
        ask = float(contract.get("ask") or 0.0)
        if ask <= 0:
            return band
        return round(min(ask + rules.tick, band), 2)

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
                                     is_0dte=(expiry == today.isoformat()), mode=rules.premium_pick)
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
        # the contract's own price first: premium-% trims on the live bid (every minute, money modes)
        if journal and bar_session(bar.ts) == "rth":
            try:
                await self._manage_live_trims(ap, rules, journal=True)
            except Exception:
                log.exception("team2 live trim check failed on %s", ap.symbol)
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
        halted = bool(self.engine.trading_halted(ap.config.portfolio_id))    # global switch OR this book's halt
        for e in new:
            what = e["event"]
            if what == "fire":
                await self._fire_from_event(ap, e, bar, res, halted=halted, journal=journal)
            elif what == "add":
                await self._add_from_event(ap, e, bar, halted=halted, journal=journal)
            elif what in ("trim", "exit"):
                await self._exit_from_event(ap, e, journal=journal)
            else:
                self._log(ap, what, e.get("why", what), **{k: v for k, v in e.items()
                                                          if k not in ("event", "why", "regime")})
                if journal and what in ("scenario", "pm_break", "late_touch", "pm_retest", "skip_engulfing",
                                        "skip_range_confirmation", "skip_no_trade_zone", "skip_no_contract",
                                        "skip_reentries", "skip_last_entry", "skip_loss_cap"):
                    # F28: the structural reads (a scenario, a PM break, a late touch) are not refusals —
                    # they get their own journal kind so skip counts mean skips
                    kind = ev.TECHNIQUE_PLAN_READ if what in ("scenario", "pm_break", "late_touch", "pm_retest") else ev.TECHNIQUE_PLAN_TRIGGER_SKIPPED
                    await self.engine.journal.append(kind, {
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
        # The kill switch blocks the MONEY modes. Alert mode places nothing (`_fire_rest` only
        # records `trade.status = "alert"`), so a halt on the shared portfolio — which another
        # technique's daily loss can engage — must not silence the desk's read of the tape: the
        # same rule the caps below and `_add_from_event`'s `would_add` already follow ("money
        # modes only; alert/proposal keep recording every read").
        if halted and ap.config.mode != "alert":
            self._log(ap, "halt_skip", f"{tid}: conditions met but the kill switch is engaged", trigger=tid)
            return
        open_or_working = sum(1 for t in ap.trades.values() if t.status in ("fired", "submitting", "working", "open"))
        if ap.config.mode == "auto" and open_or_working >= max(1, ap.config.max_open_trades):
            self._log(ap, "max_open_skip", f"{tid}: fired but already holding {open_or_working}", trigger=tid)
            return
        # F29: the author trades ONE book — max_losses_per_day counts the whole desk (model losses across
        # every plan, plus real closed losers in money modes), not one budget per symbol
        rules_now = self.rules()
        if (ap.config.mode != "alert" and getattr(rules_now, "losses_desk_wide", True)
                and self.losses_across_plans() >= int(rules_now.max_losses_per_day)):
            self._log(ap, "skip_loss_cap_desk",
                      f"{tid}: {self.losses_across_plans()} losing trades across the desk today (max {rules_now.max_losses_per_day}, "
                      f"counted from the {self.losses_basis()}) — done for the day (F29, desk-wide)", trigger=tid)
            if journal:
                await self.engine.journal.append(ev.TECHNIQUE_PLAN_TRIGGER_SKIPPED, {
                    "runId": ap.run_id, "symbol": ap.symbol, "trigger": tid, "event": "skip_loss_cap_desk",
                    "losses": self.losses_across_plans(), "max": int(rules_now.max_losses_per_day), "ts": e.get("ts")},
                    aggregate_type="technique_run", aggregate_id=ap.run_id)
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
        target = e.get("target") if e.get("target") is not None else setup.get("target")
        trade = Trade(trigger_id=tid, kind=str(setup.get("kind") or "team2"), direction=direction, fired_ts=e["ts"],
                      window="team2", entry=spot, stop=stop, targets=[float(target)] if target else [],
                      fire_bar_index=ap.bar_index - 1, last_price=bar.close, instrument=ap.config.instrument,
                      multiplier=100.0 if ap.config.instrument == "options" else 1.0)
        trade._size_mult = float(e.get("sizeMult") or 1.0)        # read by size_multiplier via the contract
        trade._bucket = str(e.get("bucket") or "?")
        trade.setup_id = str(e.get("setup"))
        trade.target_kind = str(e.get("targetKind") or "plan")
        ap.trades[tid] = trade
        self._log(ap, "fired", f"{tid}: {e.get('why', '')}", trigger=tid, spot=spot, premiumModel=e.get("premium"),
                  strikeModel=e.get("strike"), bucket=trade._bucket, early=e.get("early"), target=target,
                  targetKind=trade.target_kind, haltedAtFire=halted or None)
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
        # the simulation names the setup via the position; every trade of that setup (the entry and its
        # X5 adds) gets the same instruction — the position that just (partly) closed is either the
        # open one or the last trade
        sim = self._last_sim.get(ap.run_id) or {}
        pos = sim.get("openPosition") or (sim.get("trades") or [{}])[-1]
        setup_id = pos.get("setup")
        cands = [t for t in ap.trades.values() if t.setup_id == setup_id and t.status in ("open", "working", "alert", "proposal")]
        if not cands:
            return
        frac = float(e.get("fraction") or 1.0)
        for trade in sorted(cands, key=lambda t: t.fired_ts):
            kind = _kind_for(str(e.get("why", "")), trade.trims_done)
            if trade.status in ("alert", "proposal") or not journal:
                self._log(ap, f"would_{e['event']}", f"{trade.trigger_id}: {e.get('why', '')} (model {e.get('pnlPct')}%)",
                          trigger=trade.trigger_id, fraction=frac, pnlPctModel=e.get("pnlPct"))
                if e["event"] == "exit":
                    trade.closed_ts = e.get("ts")
                continue
            if trade.status != "open" or trade.remaining <= 0:
                continue
            if kind in ("tp1", "tp2"):
                level = 1 if kind == "tp1" else 2
                if trade.trims_done >= level:
                    self._log(ap, "trim_already_live", f"{trade.trigger_id}: the model's {'first' if level == 1 else 'second'} "
                              f"trim was already taken on the contract's live premium", trigger=trade.trigger_id)
                    continue
                live = self._live_pct(trade)
                need = self.rules().trim_1_pct if level == 1 else self.rules().trim_2_pct
                if live is not None and live < need:
                    # the model's flat-IV premium is a forecast; the bid is the fact (F8: the model runs
                    # 12-45% optimistic) — the live watch takes the trim when the contract gets there
                    self._log(ap, "trim_deferred_live", f"{trade.trigger_id}: model says +{float(e.get('pnlPct') or 0):.0f}% "
                              f"but the contract is at {live:+.0f}% live — waiting for +{need:.0f}% on the bid",
                              trigger=trade.trigger_id, livePct=round(live, 1), pnlPctModel=e.get("pnlPct"))
                    continue
                qty = self._trim_qty(ap, trade, level)
                if qty <= 0:
                    continue
                trade.trims_done = level
                await self._exit(ap, trade, kind, qty, journal=True, reason=str(e.get("why", "")))
                continue
            qty = float(int(round(trade.filled_qty * frac))) if e["event"] == "trim" else trade.remaining
            qty = max(1.0, min(qty, trade.remaining)) if trade.remaining >= 1 else trade.remaining
            await self._exit(ap, trade, kind, qty, journal=True, reason=str(e.get("why", "")),
                             force_market=kind in ("stop", "flatten"))

    # ------------------------------------------------------------- live premium (money modes)
    def _live_pct(self, tr: Trade) -> float | None:
        """Fee-adjusted premium % of an open option trade from the contract's own FRESH real-time bid;
        None when there is no usable quote (delayed chain rows never drive money)."""
        if tr.instrument != "options" or not tr.order_symbol or not tr.avg_fill:
            return None
        q = self.engine.quotes.get(tr.order_symbol)
        if q is None or not q.bid or q.bid <= 0 or getattr(q, "delayed", False):
            return None
        max_age = int(self.rt("stale_seconds", 180))
        if int(time.time() * 1000) - int(q.ts) > max_age * 1000:
            return None
        fee = float(self.rules().fee_per_contract)
        cost = float(tr.avg_fill) * 100.0 + fee
        proceeds = float(q.bid) * 100.0 - fee
        return (proceeds - cost) / cost * 100.0 if cost > 0 else None

    def _trim_qty(self, ap: ArmedPlan, tr: Trade, level: int) -> float:
        """Contracts for the first/second trim. Fewer than 3 contracts cannot be trimmed in thirds:
        the first trim is skipped and the second closes everything (EM's own small-position rule)."""
        rules = self.rules()
        if tr.filled_qty < 3:
            if level == 1:
                key = (ap.run_id, tr.trigger_id + "~small")
                if key not in self._small_noted:
                    self._small_noted.add(key)
                    self._log(ap, "too_small_to_trim", f"{tr.trigger_id}: {tr.filled_qty:g} contract(s) cannot be trimmed "
                              f"in thirds — holds whole until +{rules.trim_2_pct:.0f}%, the target or the EMA stop",
                              trigger=tr.trigger_id)
                return 0.0
            return float(tr.remaining)
        frac = rules.trim_1_frac if level == 1 else rules.trim_2_frac
        qty = float(int(round(tr.filled_qty * frac)))
        return max(1.0, min(qty, tr.remaining - tr.pending_exit_qty))

    async def _manage_live_trims(self, ap: ArmedPlan, rules: Team2Rules, *, journal: bool) -> None:
        """V2 trims on the contract's LIVE premium — the model's +50/+100% is only a forecast."""
        if not journal:
            return
        for tr in list(ap.trades.values()):
            if tr.status != "open" or tr.remaining <= 0 or tr.handoff_pending or tr.trims_done >= 2:
                continue
            pct = self._live_pct(tr)
            if pct is None:
                continue
            tr.live_pct = round(pct, 1)
            level = 1 if tr.trims_done == 0 else 2
            need = rules.trim_1_pct if level == 1 else rules.trim_2_pct
            if pct < need or tr.pending_exit_qty > 0:
                continue
            qty = self._trim_qty(ap, tr, level)
            if qty <= 0:
                if tr.filled_qty < 3 and level == 1:
                    tr.trims_done = 1                          # nothing to trim; the next live level closes it
                continue
            tr.trims_done = level
            reason = (f"live premium {pct:+.0f}% ≥ +{need:.0f}% on the bid — {'first' if level == 1 else 'second'} trim "
                      f"on the contract's own quote (V2)")
            self._log(ap, "live_trim", f"{tr.trigger_id}: {reason}", trigger=tr.trigger_id, livePct=round(pct, 1), qty=qty)
            await self._exit(ap, tr, "tp1" if level == 1 else "tp2", qty, journal=True, reason=reason)

    async def _add_from_event(self, ap: ArmedPlan, e: dict, bar: Bar, *, halted: bool, journal: bool) -> None:
        """X5 trim-and-add: buy the SAME contract again for the trimmed fraction. Auto mode only —
        a second Trade on the position, through the ordinary fire chain (RiskGate, never-chase cap);
        alert/proposal record `would_add`."""
        setup_id = str(e.get("setup"))
        bases = [t for t in ap.trades.values() if t.setup_id == setup_id and not getattr(t, "is_add", False)
                 and t.status in ("open", "alert", "proposal")]
        if not bases:
            return
        base = sorted(bases, key=lambda t: t.fired_ts)[-1]
        tid = f"{base.trigger_id}+add{int(e.get('adds') or 1)}"
        if tid in ap.trades:
            return
        frac = float(e.get("fraction") or 0.0)
        if ap.config.mode != "auto" or base.status != "open" or not journal:
            self._log(ap, "would_add", f"{base.trigger_id}: {e.get('why', '')}", trigger=base.trigger_id,
                      fraction=frac, premiumModel=e.get("premium"), avgPremiumModel=e.get("avgPremium"))
            return
        if ap.status == "paused" or halted:
            self._log(ap, "add_skip", f"{base.trigger_id}: add wanted but the plan is {'paused' if ap.status == 'paused' else 'halted'}",
                      trigger=base.trigger_id)
            return
        if base.remaining <= 0 or base.instrument != "options" or not base.contract or frac <= 0:
            return
        c = dict(base.contract)
        q = self.engine.quotes.get(base.order_symbol) if base.order_symbol else None
        if q is not None and q.ask and q.ask > 0:
            c["ask"], c["bid"] = float(q.ask), float(q.bid or 0.0)   # the add pays today's ask, capped by entry_limit_cap
        c["_sizeMult"] = float(c.get("_sizeMult", 1.0) or 1.0) * frac
        c["_bucket"] = f"{c.get('_bucket', '?')} add"
        spot = float(e.get("spot") or bar.close)
        trade = Trade(trigger_id=tid, kind=base.kind, direction=base.direction, fired_ts=e["ts"], window="team2",
                      entry=spot, stop=base.stop, targets=list(base.targets), fire_bar_index=ap.bar_index - 1,
                      last_price=bar.close, instrument="options", multiplier=100.0)
        trade.setup_id = setup_id
        trade.contract, trade.contract_attempted, trade.order_symbol = c, True, base.order_symbol
        trade.is_add = True
        trade.target_kind = getattr(base, "target_kind", "plan")
        trade._size_mult = c["_sizeMult"]
        trade._bucket = c["_bucket"]
        ap.trades[tid] = trade
        self._log(ap, "add", f"{tid}: {e.get('why', '')}", trigger=tid, spot=spot, fraction=frac,
                  premiumModel=e.get("premium"), ask=c.get("ask"))
        stub = SimpleNamespace(kind=trade.kind, direction=trade.direction, fill_price=spot, entry=spot, stop=base.stop,
                               fire_event=e, trigger={"targets": [{"price": t} for t in base.targets]}, status="fired")
        task = asyncio.create_task(self._fire_rest(ap, tid, stub, bar, ap.bar_index - 1, trade, journal=True),
                                   name=f"add-{ap.symbol}-{tid}")
        ap.fire_tasks[tid] = task
        task.add_done_callback(lambda t, tid=tid, ap=ap: ap.fire_tasks.pop(tid, None))

    @staticmethod
    def _plan_losses(mode: str, trades, sim: dict | None) -> tuple[int, str]:
        """F37: which record counts. A plan in a money mode that has ROUTED an order is judged by the
        book (its real closed losers); an alert plan — or a money-mode plan that never routed — by the
        model. Never the larger of the two: the model is recomputed by today's newest code and can
        "lose" trades the desk declined at the time (SPY/IWM 2026-09-04 15:10)."""
        routed = [t for t in trades if getattr(t, "entry_order_id", None) or float(getattr(t, "filled_qty", 0) or 0) > 0]
        if mode in ("auto", "proposal") and routed:
            return sum(1 for t in trades if t.status == "closed" and float(t.filled_qty or 0) > 0 and t.realized_pnl < 0), "book"
        return sum(1 for t in ((sim or {}).get("trades") or []) if not t.get("win")), "model"

    def losses_across_plans(self, day: str | None = None) -> int:
        """F29/F37/F38: losing trades today across the whole desk. Armed plans are counted live; a plan
        that disarmed (its own loss halt) keeps its losses in the day's tally — the cap must not loosen
        after the worst outcome a plan can have. The tally is seeded from the persisted rows at boot."""
        day = day or dt.datetime.now(ET).strftime("%Y-%m-%d")
        tally = self._loss_tally.setdefault(day, {})
        for ap in self._armed.values():
            n, basis = self._plan_losses(ap.config.mode, list(ap.trades.values()), self._last_sim.get(ap.run_id))
            tally[ap.run_id] = (n, basis)
        for d in [k for k in self._loss_tally if k != day]:
            self._loss_tally.pop(d, None)
        return sum(n for n, _ in tally.values())

    def losses_basis(self, day: str | None = None) -> str:
        day = day or dt.datetime.now(ET).strftime("%Y-%m-%d")
        bases = {b for _, b in self._loss_tally.get(day, {}).values()}
        return "/".join(sorted(bases)) or "model"

    async def seed_loss_tally(self, day: str | None = None) -> int:
        """F38: after a restart, today's DISARMED Team2 plans are not restored — read their real closed
        losers back from the persisted rows so the desk-wide cap still counts them."""
        day = day or dt.datetime.now(ET).strftime("%Y-%m-%d")
        tally = self._loss_tally.setdefault(day, {})
        try:
            from ...models import TechniqueArmed
            async with self.engine.sf() as session:
                rows = (await session.execute(select(TechniqueArmed).where(
                    TechniqueArmed.technique == self.TECHNIQUE_ID, TechniqueArmed.plan_for == day,
                    TechniqueArmed.status.in_(("disarmed", "expired"))))).scalars().all()
        except Exception:  # noqa: BLE001 - a missing tally only loosens a cap; say so in the log
            log.exception("team2 loss tally seed failed")
            return 0
        seeded = 0
        for row in rows:
            if row.run_id in self._armed:
                continue
            trades = (row.state or {}).get("trades") or []
            n = sum(1 for t in trades if t.get("status") == "closed" and float(t.get("filledQty") or 0) > 0
                    and float(t.get("realizedPnl") or 0) < 0)
            if n:
                tally[row.run_id] = (n, "book")
                seeded += n
        return seeded

    def open_positions_across_plans(self) -> int:
        """Open or in-flight Team2 trades across every armed plan (A12 concurrency cap)."""
        return sum(1 for ap in self._armed.values() for t in ap.trades.values()
                   if t.status in ("fired", "submitting", "working", "open") and not getattr(t, "is_add", False))

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
            guard = {"ema": "EMA13", "ema48": "EMA48", "ema200": "200 EMA"}.get(str(open_pos.get("entryKind")), "level")
            tgt = open_pos.get("target")
            tgt_s = (f", target {tgt:.2f} ({'high/low of day' if open_pos.get('targetKind') == 'hod' else 'planned level'})"
                     if tgt else "")
            adds_s = f", {open_pos.get('adds')} add" if open_pos.get("adds") else ""
            live_s = ""
            live_pcts = [t.live_pct for t in ap.trades.values() if t.status == "open" and getattr(t, "live_pct", None) is not None]
            if live_pcts:
                live_s = f" · contract {live_pcts[0]:+.0f}% live"
            else:
                # F31 (2026-09-04): the model holds until ITS stop (a 2m close through the level), but the
                # desk's real contract can already be gone — the live premium stop, the 15:45 flatten or a
                # failed-exit retry close it without the model knowing. QQQ today: premium stop out at 13:58
                # while the read still said "1.00 left". "In trade" then claims exposure the book does not
                # have, and on the phone that is the one line that must never lie. Only counted when
                # contracts were really filled, so alert mode (which mints trades but never fills) is silent.
                setup_id = str(open_pos.get("setup") or "")
                gone = [t for t in ap.trades.values()
                        if t.status == "closed" and float(getattr(t, "filled_qty", 0) or 0) > 0
                        and str(getattr(t, "trigger_id", "")).split("#")[0] == setup_id]
                if gone:
                    kind = ((gone[-1].exits or [{}])[-1] or {}).get("kind")
                    live_s = f" · book flat — the desk's contract is already closed ({kind or 'exit'})"
            strike = open_pos.get("strike")
            strike_s = f"{strike:g}" if isinstance(strike, (int, float)) else "?"
            d["summary"] = (f"in trade {open_pos.get('setup')}: {'call' if open_pos.get('call') else 'put'} {strike_s}, "
                            f"{open_pos.get('remaining', 1):.2f} left{adds_s}, model peak +{open_pos.get('peakPct', 0):.0f}%{tgt_s} — "
                            f"stop is a 2m close through the {guard}{live_s}")
        elif bias.get("scenario"):
            live = [s for s in setups if not s.get("dead")]
            # F24: report the allowance of the setup the session would actually enter — `session.py` takes the
            # NEWEST live setup in the bias direction, so a spent setup pointing the other way (SPY's
            # pm_break_down on 2026-09-04) must not be read as touches already used on this one.
            cands = [s for s in live if not bias.get("direction") or s.get("direction") == bias.get("direction")]
            picked = sorted(cands, key=lambda s: s.get("confirmedTs") or 0)[-1] if cands else None
            touches = picked.get("touches", 0) if picked else max((s.get("touches", 0) for s in live), default=0)
            d["summary"] = (f"scenario {bias['scenario']} ({bias.get('label')}) → {'calls' if bias.get('direction') == 'long' else 'puts'} · "
                            f"waiting for the 1st/2nd 2m pullback into the EMA13 (touches {touches}) · EMA stack {regime.get('stack', '?')}, "
                            f"{regime.get('fan', '?')}")
        elif pdh and pdl:
            pm = (f" · PM {plan['pml']:.2f}–{plan['pmh']:.2f}" if plan.get("pmh") and plan.get("pml") else " · pre-market range at 09:25")
            day = f" · {str(plan.get('dayType')).replace('_', ' ')} day" if plan.get("dayType") else ""
            d["summary"] = (f"no scenario yet — needs a 15m close above {pdh.get('top', 0):.2f} (calls) or below "
                            f"{pdl.get('bottom', 0):.2f} (puts){pm}{day}"
                            + (f" · EMA stack {regime.get('stack')}, {regime.get('fan')}" if regime else ""))
        live = [{"trigger": t.trigger_id, "livePct": t.live_pct, "trimsDone": t.trims_done, "isAdd": bool(getattr(t, "is_add", False))}
                for t in ap.trades.values() if t.status == "open" and getattr(t, "live_pct", None) is not None]
        d["team2"] = {"sheet": plan.get("sheet"), "dayType": plan.get("dayType"), "sizingAtOpen": plan.get("sizingAtOpen"),
                      "bias": bias or None, "regime": regime or None, "read": {k: read.get(k) for k in ("summary",)} if read else None,
                      "live": live or None}
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
        seeded = await runner.seed_loss_tally()
        if seeded:
            log.info("team2 desk loss tally seeded with %d loser(s) from today's disarmed plans (F38)", seeded)
    except Exception:  # pragma: no cover
        log.exception("team2 runner restore failed")
    # The desk's three symbols keep banking 1m bars whether or not a plan is armed on them:
    # a plan that disarms mid-session (loss halt) otherwise loses the rest of the day's tape
    # the moment the process restarts, and its replay/review is truncated at the disarm (F34).
    for sym in (engine.settings.get("techniques.team2.symbols") or []):
        try:
            await engine.ensure_symbol(str(sym).upper())
        except Exception:  # pragma: no cover — the feed must never block the attach
            log.debug("team2 ensure_symbol failed for %s", sym, exc_info=True)
    from .service import Team2Service
    engine.team2 = Team2Service(engine, runner)
    engine.scheduler.register("team2_plan_nightly", str(engine.settings.get("techniques.team2.plan_at", "17:00")),
                              lambda: engine.team2.nightly_plans())
    engine.scheduler.register("team2_preopen", str(engine.settings.get("techniques.team2.preopen_at", "09:25")),
                              lambda: engine.team2.preopen_complete())


__all__ = ["Team2Runner", "attach_team2_runner"]
