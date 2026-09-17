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
from ...marketstructure.aggregate import bar_session, bucket_start_ms, minute_of_day
from ...marketstructure.sessions import ET, session_bounds, session_date
from ...models import TechniqueRun
from ...options.pick import MAX_OVER_TARGET
from .rules import apply_overrides, Team2Rules, rules_from_settings
from .scenario import destination_check, target_is_ahead
from .session import simulate_session
from . import diagnostics as diag

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
        self._listing_tried: dict[str, int] = {}       # F104: last listing fetch attempt per plan (ms)
        self._listing_warned: dict[str, bool] = {}
        self._trail_gaps: dict[str, list[dict]] = {}   # run_id -> journal writes that failed (evidence gaps)
        self._contract_verdicts: dict[str, list[dict]] = {}   # R5: run_id -> the day's contract verdicts (durable copy = journal)
        self._trail_gaps: dict[str, list[dict]] = {}   # run_id -> journal writes that failed (evidence gaps)
        self._seen: dict[str, int] = {}                # run_id -> events already acted on
        self._last_sim: dict[str, dict] = {}           # run_id -> last SessionResult.to_dict()
        self._sigma_cache: dict[str, tuple[str, float]] = {}
        # 2026-09-08 (Codex review): the read is recomputed every 2m close; acted-on events are recognised by
        # FINGERPRINT, not by their position in the list, so an input that moves under the read (IV, a late
        # bar) can never re-fire or skip one. `_seen` (the count) stays for the tests/UI that read it.
        self._seen_fp: dict[str, set[str]] = {}
        self._rewrite_noted: dict[str, int] = {}
        # R3 (2026-09-14): the last decision's clock per plan — an event whose close is at or before it was NOT
        # there when that minute was judged (a revision surfaced it) and is analytical state, never an order
        self._decision_wm: dict[str, int] = {}
        self._small_noted: set[tuple[str, str]] = set()
        self._flatten_noted: set[str] = set()          # F106: the flatten's once-per-run note
        self._loss_tally: dict[str, dict[str, tuple]] = {}   # day -> run_id -> (losers, basis, portfolio_id) (F37/F38)

    async def stop(self) -> None:
        for name in ("team2_plan_nightly", "team2_preopen"):
            with contextlib.suppress(Exception):
                self.engine.scheduler.unregister(name)
        await super().stop()

    # ------------------------------------------------------------- hooks
    @staticmethod
    def _book(ap) -> str | None:
        """The plan's book (portfolio id); None for a bare test rig without a config."""
        return getattr(getattr(ap, "config", None), "portfolio_id", None)

    def rules(self) -> Team2Rules:
        """The shared baseline (`techniques.team2.*`). Test rigs patch this; `rules_for(ap)` layers a book's overrides on it."""
        return rules_from_settings(self.engine.settings)

    def rules_for(self, ap) -> Team2Rules:
        """The rules THIS plan runs under: the baseline plus the experiment override FROZEN ON THE PLAN at mint time
        (`plan.experiment.overrides`, stamped by `mint_plan_run`; review of 41ec565). The live experiment map is never
        consulted here: disabling or editing it cannot turn an armed sizing book back into a full-size baseline mid-
        session, and a restart restores the same book/rule identity from the run. A plan without a stamp, or a bare
        test rig, runs the baseline exactly."""
        base = self.rules()
        plan = getattr(ap, "plan", None)
        exp = plan.get("experiment") if isinstance(plan, dict) else None
        if not isinstance(exp, dict) or not exp.get("overrides"):
            return base
        return apply_overrides(base, exp.get("overrides"))

    async def arm(self, run_id: str, config=None, *, restored: bool = False, paused: bool = False, prior_state: dict | None = None) -> dict:
        """The sim-only boundary at EVERY arm — manual, nightly and restore: a plan stamped as an experiment may only be
        armed on the Practice (sim) book it was minted for (review of 41ec565, section 3)."""
        run = await self.load_plan(run_id)
        exp = ((run or {}).get("result") or {}).get("plan", {}).get("experiment") if run else None
        if isinstance(exp, dict) and exp.get("label"):
            cfg = config.to_dict() if hasattr(config, "to_dict") else dict(config or {})
            pid = str(cfg.get("portfolioId") or cfg.get("portfolio_id") or "")
            if not pid:
                pid = str(exp.get("portfolioId") or "")
            pf = self.engine.positions.portfolio(pid) if pid else None
            if pf is None or str(pf.get("kind")) != "sim" or bool(pf.get("archived")):
                raise ValueError(f"experiment plan {run_id} ({exp.get('label')}) may only be armed on an unarchived Practice (sim) book — never real money")
            if str(exp.get("portfolioId") or "") and pid != str(exp.get("portfolioId")):
                raise ValueError(f"experiment plan {run_id} ({exp.get('label')}) was minted for book {exp.get('portfolioId')}, not {pid}")
            cfg["portfolioId"] = pid
            config = cfg
        return await super().arm(run_id, config, restored=restored, paused=paused, prior_state=prior_state)

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
        rules = self.rules_for(ap)
        band = round(float(rules.target_premium) * float(rules.chase_cap_mult), 2)
        ask = float(contract.get("ask") or 0.0)
        if ask <= 0:
            return band
        return round(min(ask + rules.tick, band), 2)

    _UNFILLED_TERMINAL = ("failed", "cancelled", "skipped", "rejected", "expired")

    def _record_unfilled(self, ap: ArmedPlan, tid: str) -> bool:
        """R1: tell the read that this fire never became a position (refused / deferred / cutoff / stale / rejected
        / unfilled / sizing). The list rides the ordinary persist (`state_extras`), comes back on restore
        (`restore_extras`) and is rebuilt from the durable verdicts (`load_contract_verdicts`), so a restart does not
        resurrect the proxy. Returns True when the trigger was newly recorded."""
        plan = ap.plan if isinstance(getattr(ap, "plan", None), dict) else None
        if plan is None:
            return False
        lst = plan.setdefault("executionRefused", [])
        if tid in lst:
            return False
        lst.append(tid)
        return True

    def _sync_unfilled(self, ap: ArmedPlan) -> int:
        """R1: every ZERO-FILL outcome exempts its fire from the read's proxy, wherever it happened — the picker,
        the stale gate, the entry gate, the order (rejected / cancelled unfilled / capped away), sizing or budget.
        An unknown-ACK order (submitting / working) and a partial fill are NOT exempt: the book may hold them."""
        n = 0
        plan = ap.plan if isinstance(getattr(ap, "plan", None), dict) else {}
        lst = plan.get("executionRefused") if isinstance(plan.get("executionRefused"), list) else None
        for t in list(ap.trades.values()):
            if getattr(t, "is_add", False):
                continue
            if getattr(t, "submit_uncertain", False) or t.status in ("submitting", "working", "open") or float(t.filled_qty or 0) > 0:
                # F: an unknown venue outcome, a live order or ANY fill keeps (or takes back) its occupancy — the
                # overlay is reconciled by evidence, never append-only
                if lst is not None and t.trigger_id in lst:
                    lst.remove(t.trigger_id)
                    self._log(ap, "execution_overlay_reconciled", f"{t.trigger_id}: fill/order evidence arrived — the read's proxy "
                              f"exemption is withdrawn (status {t.status}, filled {float(t.filled_qty or 0):g})", trigger=t.trigger_id)
                continue
            if float(t.filled_qty or 0) <= 0 and t.status in self._UNFILLED_TERMINAL and self._record_unfilled(ap, t.trigger_id):
                n += 1
        return n

    def _exempt_from_verdicts(self, ap: ArmedPlan) -> int:
        """R1: a durable refusal / deferral whose trade projection is absent (or terminal and unfilled) is an exemption
        after a restart too — the journal is the record, not the in-memory list. The LAST verdict of a trigger
        decides (a deferral followed by a pick is not a refusal)."""
        last: dict[str, str] = {}
        for v in self._contract_verdicts.get(ap.run_id) or []:
            last[str(v.get("trigger"))] = str(v.get("verdict") or "")
        n = 0
        for tid, verdict in last.items():
            if verdict not in ("refused", "deferred") or tid == "None":
                continue
            t = ap.trades.get(tid)
            if t is None or (float(t.filled_qty or 0) <= 0 and t.status in self._UNFILLED_TERMINAL
                             and not getattr(t, "submit_uncertain", False)):
                if self._record_unfilled(ap, tid):
                    n += 1
        return n

    def state_extras(self, ap: ArmedPlan) -> dict:
        self._sync_unfilled(ap)
        plan = ap.plan if isinstance(getattr(ap, "plan", None), dict) else {}
        return {"executionRefused": list(plan.get("executionRefused") or []),
                "decisionWatermark": self._decision_wm.get(ap.run_id),
                "decisionLedger": diag.ledger_state(self._ledger_of(ap.run_id)),          # 2026-09-16: the close report's record
                "diagnostics": self.__dict__.get("_diag", {}).get(ap.run_id)}

    def restore_extras(self, ap: ArmedPlan, state: dict) -> None:
        for tid in (state or {}).get("executionRefused") or []:
            self._record_unfilled(ap, str(tid))
        wm = (state or {}).get("decisionWatermark")
        if wm:
            self._decision_wm[ap.run_id] = max(int(wm), int(self._decision_wm.get(ap.run_id) or 0))
        led = (state or {}).get("decisionLedger")
        if led:
            self.__dict__.setdefault("_ledger", {})[ap.run_id] = diag.ledger_from_state(led)
        dg = (state or {}).get("diagnostics")
        if isinstance(dg, dict) and isinstance(dg.get("attempts"), dict):
            pend = [dict(p, status=("pending" if p.get("status") == "inflight" else p.get("status"))) for p in (dg.get("pending") or [])]
            self.__dict__.setdefault("_diag", {})[ap.run_id] = {"attempts": dict(dg["attempts"]), "pending": pend}

    def _entry_time_refusal(self, ap: ArmedPlan, stage: str) -> str | None:
        """R2/E: the wall clock at the order boundary — outside the plan's session or past the entry cutoff nothing new
        is sent, whether the order is an entry, an X5 add on a cached contract, a transport retry or a re-price retry.
        Pure and synchronous so it can run inside OrderManager after its last await. The signal-age rule stays at
        the origin (`_stale_signal`): the chain itself may legitimately take a minute."""
        if ap.config.mode == "alert":
            return None
        rules = self.rules_for(ap)
        now = int(time.time() * 1000)
        now_et = dt.datetime.fromtimestamp(now / 1000, ET)
        if now_et.strftime("%Y-%m-%d") != ap.plan_for:
            return f"order boundary ({stage}): {now_et.strftime('%Y-%m-%d')} is not the plan's session {ap.plan_for} (R2)"
        m = now_et.hour * 60 + now_et.minute
        if m >= int(rules.last_entry_min):
            return (f"order boundary ({stage}): the entry cutoff ({rules.last_entry_min // 60:02d}:{rules.last_entry_min % 60:02d}) "
                    f"had passed at {now_et.strftime('%H:%M:%S')} — no new order (R2)")
        return None

    async def entry_gate(self, ap: ArmedPlan, trade: Trade, stage: str) -> str | None:
        if stage == "order" and not getattr(trade, "is_add", False):
            self._diag_submission(ap, trade)                 # shadow: the underlying at the order boundary (2026-09-16)
        return self._entry_time_refusal(ap, stage)

    def entry_guard_predicate(self, ap: ArmedPlan, trade: Trade) -> str | None:
        return self._entry_time_refusal(ap, "submit")

    async def _trail(self, ap: ArmedPlan, kind: str, event: str, reason: str, **detail) -> None:
        """Cohort v2 (2026-09-10, user decision): the candidate -> quote -> order -> fill -> exit trail is journaled under
        the plan run, not only kept in the plan's in-memory events. Orders, fills and exits are journaled by the
        PlanRunner already; this writes the steps before the order."""
        journal = getattr(getattr(self, "engine", None), "journal", None)
        run_id = getattr(ap, "run_id", None)
        if journal is None or not run_id:
            return
        payload = {"runId": run_id, "symbol": ap.symbol, "event": event, "reason": reason, **detail}
        # F111 (2026-09-11): the TechniquePlanRead contract requires `trigger`; a plan-level read row
        # (warmup, listing, open_finalized, targets_rederived) has none, and every one of them logged a
        # contract warning. State the absence rather than omit the field.
        if kind == ev.TECHNIQUE_PLAN_READ:
            payload.setdefault("trigger", None)
        if kind == ev.TECHNIQUE_PLAN_CONTRACT:
            # R5: the contract verdicts of the day, kept for the close funnel (the journal is the durable copy;
            # `load_contract_verdicts` re-reads it after a restart)
            self.__dict__.setdefault("_contract_verdicts", {}).setdefault(run_id, []).append(dict(payload))
        try:
            await journal.append(kind, payload, aggregate_type="technique_run", aggregate_id=run_id)
        except Exception as exc:  # noqa: BLE001 - a hole in the record is itself evidence (Codex, 2026-09-10)
            gaps = self._trail_gaps.setdefault(run_id, [])
            gaps.append({"event": event, "kind": kind, "error": str(exc)[:200], "at": int(time.time() * 1000)})
            self._log(ap, "trail_gap", f"the audit record for '{event}' was NOT written ({exc}) — this session's trail is "
                      f"incomplete: {len(gaps)} gap(s) so far", event_=event, error=str(exc)[:200], gaps=len(gaps))
            log.error("team2 trail gap on %s: %s not journaled (%s)", run_id, event, exc)
            if len(gaps) == 1:
                with contextlib.suppress(Exception):
                    await self._alert(ap, f"Team2 {ap.symbol}: audit trail gap — '{event}' was not journaled ({exc}); "
                                          f"treat today's record as incomplete", level="warning", stage="trail")

    def trail_gaps(self, run_id: str) -> list[dict]:
        """The journal writes that FAILED for this plan run (empty = every trail step is on the record)."""
        return list(self._trail_gaps.get(run_id, []))

    # ------------------------------------------------------------- chain listings (2026-09-17 item 3): bounded cache, coalescing, retry
    # The QQQ 13:06 candidate was deferred by a CBOE HTTP 429 before any contract was examined. A LISTING (which contracts
    # exist for an expiry) barely changes intraday, so it is cached per (provider, symbol, expiry) for `chain_cache_seconds`,
    # concurrent callers share one in-flight request, a rate-limited / transient failure is retried twice with short
    # back-offs, and a failure after that serves a listing no older than `chain_cache_max_age_seconds` (labelled). PRICES
    # never come from here: every candidate is still re-priced on the live NBBO (`_quote_examined`), the expiry rule, the
    # stale-signal gate and the entry-time gates are untouched, and the listing's source/age is written on the verdict.
    _CHAIN_RETRY_SLEEPS = (0.8, 1.6)

    @staticmethod
    def _chain_key(provider, symbol: str, expiry: str | None) -> tuple:
        return (str(getattr(provider, "name", None) or type(provider).__name__), str(symbol).upper(), str(expiry or "*"))

    @staticmethod
    def _transient_chain_error(exc: BaseException) -> bool:
        msg = str(exc)
        return any(t in msg for t in ("429", "HTTP 5", "timed out", "timeout", "Timeout", "Too Many", "temporarily"))

    async def _cached_chain_call(self, key: tuple, fn, *, ttl_s: float, max_age_s: float) -> tuple[list, dict]:
        cache = self.__dict__.setdefault("_chain_cache", {})
        inflight = self.__dict__.setdefault("_chain_inflight", {})
        now = int(time.time() * 1000)
        hit = cache.get(key)
        if hit and now - int(hit["ts"]) <= ttl_s * 1000:
            return list(hit["rows"]), {"listingSource": "cache", "listingAgeMs": now - int(hit["ts"]), "listingFetchedAt": int(hit["ts"])}
        fut = inflight.get(key)
        owner = fut is None
        if owner:
            fut = asyncio.get_running_loop().create_future()
            inflight[key] = fut
            attempts = 0
            try:
                last: BaseException | None = None
                for i, sleep_s in enumerate((0.0,) + self._CHAIN_RETRY_SLEEPS):
                    if sleep_s:
                        await asyncio.sleep(sleep_s)
                    attempts = i + 1
                    try:
                        rows = await fn()
                        cache[key] = {"ts": int(time.time() * 1000), "rows": list(rows or [])}
                        last = None
                        break
                    except Exception as exc:  # noqa: BLE001
                        last = exc
                        if not self._transient_chain_error(exc):
                            break
                if last is not None:
                    fut.set_exception(last)
                else:
                    fut.set_result(attempts)
            finally:
                inflight.pop(key, None)
        try:
            attempts = await fut if not owner else fut.result()
        except Exception as exc:  # noqa: BLE001
            if hit and now - int(hit["ts"]) <= max_age_s * 1000:
                return list(hit["rows"]), {"listingSource": "stale-cache", "listingAgeMs": now - int(hit["ts"]),
                                           "listingFetchedAt": int(hit["ts"]), "listingError": str(exc)[:160]}
            raise
        h = cache.get(key) or {"ts": now, "rows": []}
        src = ("fetch" if attempts == 1 else "retry") if owner else "coalesced"
        return list(h["rows"]), {"listingSource": src, "listingAgeMs": int(time.time() * 1000) - int(h["ts"]),
                                 "listingFetchedAt": int(h["ts"]), "listingAttempts": attempts}

    def _chain_knob(self, key: str, default: float) -> float:
        try:
            return float(self.rt(key, default) or 0)
        except Exception:  # noqa: BLE001 - a rig without settings runs on the defaults
            return float(default)

    async def _listing(self, provider, symbol: str, expiry: str) -> tuple[list[dict], dict]:
        """The provider's listed contracts for one expiry (identity + the delayed chain row), through the bounded cache."""
        ttl = self._chain_knob("chain_cache_seconds", 900)
        max_age = self._chain_knob("chain_cache_max_age_seconds", 14400)
        return await self._cached_chain_call(self._chain_key(provider, symbol, expiry), lambda: provider.chain(symbol, expiry),
                                             ttl_s=ttl, max_age_s=max_age)

    async def _expiries(self, provider, symbol: str) -> tuple[list[str], dict]:
        ttl = self._chain_knob("chain_cache_seconds", 900)
        max_age = self._chain_knob("chain_cache_max_age_seconds", 14400)
        key = self._chain_key(provider, symbol, "expiries:" + dt.datetime.now(ET).date().isoformat())
        return await self._cached_chain_call(key, lambda: provider.expirations(symbol), ttl_s=ttl, max_age_s=max_age)

    async def _expiry_for(self, provider, symbol: str, rules: Team2Rules, today: dt.date) -> tuple[str | None, str | None]:
        exps, _meta = await self._expiries(provider, symbol)
        exps_d = sorted(e for e in (exps or []) if e)
        if rules.dte_policy == "0dte":
            expiry = next((e for e in exps_d if e == today.isoformat()), None)
            return expiry, (None if expiry else "no same-day expiry listed (dte_policy=0dte)")
        expiry = next((e for e in exps_d if e > today.isoformat()), None)
        return expiry, (None if expiry else "no expiry after today")

    async def _ensure_listing(self, ap: ArmedPlan, now_ms: int) -> None:
        """F104/F108 (2026-09-10): stamp today's LISTED strikes (the venue's, from the chain) on the plan so the
        read's premium gate walks real contracts instead of a synthetic grid. Once per plan per expiry; a failed
        fetch is retried every 5 minutes and the read runs on the grid (and says so) until it lands."""
        plan = ap.plan or {}
        have = plan.get("listedStrikes") if isinstance(plan.get("listedStrikes"), dict) else None
        if have and have.get("strikes"):
            return
        tried = self._listing_tried.get(ap.run_id, 0)
        if now_ms - tried < 5 * 60_000:
            return
        self._listing_tried[ap.run_id] = now_ms
        opts = getattr(self.engine, "options", None)
        if opts is None:
            return
        rules = self.rules_for(ap)
        try:
            provider = opts.provider()
            today = dt.datetime.now(ET).date()
            expiry, why = await self._expiry_for(provider, ap.symbol, rules, today)
            if expiry is None:
                raise RuntimeError(why or "no expiry")
            chain, lmeta = await self._listing(provider, ap.symbol, expiry)
            strikes = sorted({float(c.get("strike")) for c in (chain or []) if c.get("strike") is not None})
            if not strikes:
                raise RuntimeError("chain returned no strikes")
            plan["listedStrikes"] = {"expiry": expiry, "strikes": strikes, "count": len(strikes),
                                     "source": "chain", "provider": type(provider).__name__, "listing": lmeta,
                                     "capturedAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
            lo, hi = strikes[0], strikes[-1]
            self._log(ap, "listing", f"{len(strikes)} listed strikes for {expiry} ({lo:g}..{hi:g}) from the chain — the "
                      f"premium gate walks these, not the ${rules.strike_step:g} grid (F104)",
                      expiry=expiry, count=len(strikes), low=lo, high=hi)
            await self._trail(ap, ev.TECHNIQUE_PLAN_READ, "listing", f"{len(strikes)} listed strikes for {expiry} ({lo:g}..{hi:g})",
                              expiry=expiry, count=len(strikes), low=lo, high=hi, provider=plan["listedStrikes"]["provider"], listing=lmeta)
            with contextlib.suppress(Exception):
                await self._persist(ap)
        except Exception as exc:  # noqa: BLE001 - the read keeps working on the grid and says so
            if not self._listing_warned.get(ap.run_id):
                self._listing_warned[ap.run_id] = True
                self._log(ap, "listing_unavailable", f"could not read today's listed strikes from the chain ({exc}); the "
                          f"premium gate runs on the synthetic ${rules.strike_step:g} grid until it can (F104)", error=str(exc))
                await self._trail(ap, ev.TECHNIQUE_PLAN_READ, "listing_unavailable", f"no chain listing: {exc}", error=str(exc))

    async def pick_contract(self, ap: ArmedPlan, trade: Trade) -> dict | None:
        """The premium-targeted 0DTE contract (V1/F5): structural candidate -> the venue's LISTED contracts ->
        FRESH executable quotes -> the premium band -> the order.

        F105/F108 (2026-09-10): the chain the provider serves is ~15 min delayed and its ask disagreed with the
        live NBBO by exactly the cent that decides in-band/out-of-band (IWM 287.5P: CBOE $0.19 vs OPRA $0.20 at
        the $0.20 floor). A delayed ask therefore never conclusively vetoes a candidate: the nearest
        `quote_candidates` listed contracts whose delayed ask is anywhere near the band (or unquoted) are
        re-priced on the live NBBO first, and the band is judged on what would fill. The refusal names every
        candidate examined with its ask and which series spoke."""
        trade.contract_attempted = True
        opts = getattr(self.engine, "options", None)
        if opts is None:
            trade.errors.append("options service not attached")
            await self._trail(ap, ev.TECHNIQUE_PLAN_CONTRACT, "contract_deferred", "options service not attached",
                              trigger=trade.trigger_id, verdict="deferred", stage="service", examined=[], direction=trade.direction)
            self._record_unfilled(ap, trade.trigger_id)
            return None
        rules = self.rules_for(ap)
        try:
            from ...options.pick import select_by_premium
            provider = opts.provider()
            today = dt.datetime.now(ET).date()
            expiry, why = await self._expiry_for(provider, ap.symbol, rules, today)
            if expiry is None:
                trade.errors.append(why or "no expiry")
                await self._trail(ap, ev.TECHNIQUE_PLAN_CONTRACT, "contract_deferred", why or "no expiry",
                                  trigger=trade.trigger_id, verdict="deferred", stage="expiry", examined=[], direction=trade.direction)
                self._record_unfilled(ap, trade.trigger_id)
                return None
            chain, listing_meta = await self._listing(provider, ap.symbol, expiry)
            spot = float(trade.entry)
            q = self.engine.quotes.get(ap.symbol)
            if q is not None and q.last and q.last > 0:
                spot = float(q.last)
            want = "call" if trade.direction == "long" else "put"
            band_hi = float(rules.target_premium) * MAX_OVER_TARGET
            floor = float(rules.premium_floor)
            side = [c for c in (chain or []) if (c.get("option_type") or "").lower() == want
                    and c.get("strike") is not None and c.get("symbol")]
            otm = [c for c in side if (float(c["strike"]) > spot if want == "call" else float(c["strike"]) < spot)]
            otm.sort(key=lambda c: abs(float(c["strike"]) - spot))
            # F108: NO delayed price is read for selection. Candidates are the listed OTM contracts nearest spot,
            # quoted live one by one (bounded by `quote_candidates`); the walk stops early only on a FRESH ask
            # under the floor (further out is only cheaper). Whatever was not examined is reported as unexamined —
            # a deferral, never a "no contract" verdict.
            limit = max(1, int(rules.quote_candidates))
            qres = await self._quote_examined(opts, otm, spot, trade.direction, rules, expiry, today)
            examined, eligible, unpriced, unexamined, pick = (qres["examined"], qres["eligible"], qres["unpriced"],
                                                              qres["unexamined"], qres["pick"])
            # shadow (2026-09-16): the selected contract AND the alternatives examined, with their quotes and Greeks,
            # followed at 2/5/10 min and at the actual exit — a measurement, never a veto
            self._diag_candidates(ap, trade.trigger_id, qres, (pick.symbol if pick is not None else None), spot, rules, chain, opts)
            # R2: the quotes took time — re-check the actual clock before a contract can become an order
            now_et = dt.datetime.fromtimestamp(time.time(), ET)
            live_session = str(getattr(ap, "plan_for", "") or "") == now_et.strftime("%Y-%m-%d")
            if pick is not None and live_session and now_et.hour * 60 + now_et.minute >= int(rules.last_entry_min):
                why = (f"entry deferred — the cutoff passed while quoting ({now_et.strftime('%H:%M:%S')} ≥ "
                       f"{rules.last_entry_min // 60:02d}:{rules.last_entry_min % 60:02d}); {pick.symbol} was in band (R2)")
                trade.errors.append(why)
                self._log(ap, "contract_deferred", f"{trade.trigger_id}: {why}", trigger=trade.trigger_id, examined=examined,
                          spot=round(spot, 4), listed=len(otm), unexamined=0, unpriced=unpriced, expiry=expiry, stage="cutoff")
                await self._trail(ap, ev.TECHNIQUE_PLAN_CONTRACT, "contract_deferred", why, trigger=trade.trigger_id, verdict="deferred",
                                  stage="cutoff", examined=examined, spot=round(spot, 4), listed=len(otm), expiry=expiry,
                                  direction=trade.direction)
                self._record_unfilled(ap, trade.trigger_id)
                return None
            if pick is None:
                seen = ", ".join(f"{x['strike']:g} " + (f"ask {x['ask']:.2f} ({x['priced']}, chain {x['delayedAsk']:.2f})" if x['eligible']
                                                          else f"no live quote ({x['priced']}; chain {x['delayedAsk']:.2f})")
                                 for x in examined) or "no OTM contract listed"
                deferred = bool(unpriced) or unexamined > 0
                verdict = "deferred" if deferred else "refused"
                why = (f"{'entry deferred' if deferred else 'no ' + want} — nothing eligible between ${floor:.2f} and ${band_hi:.2f} "
                       f"(target ${rules.target_premium:.2f}) at {expiry} on the live quotes; examined {seen}"
                       + (f"; {unpriced} candidate(s) had no live quote" if unpriced else "")
                       + (f"; {unexamined} listed contract(s) further out not examined (quote bound {limit})" if unexamined else ""))
                trade.errors.append(why)
                self._log(ap, f"contract_{verdict}", f"{trade.trigger_id}: {why}", trigger=trade.trigger_id, examined=examined,
                          spot=round(spot, 4), listed=len(otm), unexamined=unexamined, unpriced=unpriced, expiry=expiry)
                await self._trail(ap, ev.TECHNIQUE_PLAN_CONTRACT, f"contract_{verdict}", why, trigger=trade.trigger_id, verdict=verdict,
                                  examined=examined, spot=round(spot, 4), listed=len(otm), unexamined=unexamined, unpriced=unpriced,
                                  expiry=expiry, direction=trade.direction, listing=listing_meta)
                self._record_unfilled(ap, trade.trigger_id)
                return None
            c = next(x for x in eligible if x.get("symbol") == pick.symbol)
            priced = c.get("priced")
            c = {**pick.to_dict(), "priced": priced}
            c["_sizeMult"] = float(getattr(trade, "_size_mult", 1.0) or 1.0)
            c["_bucket"] = getattr(trade, "_bucket", "?")
            trade.contract = c
            trade.order_symbol = c.get("symbol")
            self._log(ap, "contract", f"{trade.trigger_id}: {c.get('display') or c.get('symbol')} ask {c.get('ask')} "
                      f"({priced}; target ${rules.target_premium:.2f}, {expiry}; {len(examined)} candidate(s) quoted)",
                      trigger=trade.trigger_id, examined=examined, priced=priced)
            await self._trail(ap, ev.TECHNIQUE_PLAN_CONTRACT, "contract_picked",
                              f"{c.get('symbol')} ask {c.get('ask')} bid {c.get('bid')} ({priced})", trigger=trade.trigger_id,
                              verdict="picked", contract=c.get("symbol"), strike=c.get("strike"), ask=c.get("ask"), bid=c.get("bid"),
                              priced=priced, examined=examined, spot=round(spot, 4), listed=len(otm), expiry=expiry,
                              direction=trade.direction, listing=listing_meta)
            return c
        except Exception as exc:  # noqa: BLE001 - reported on the trade, never raised into the bar loop
            trade.errors.append(f"contract pick failed: {exc}")
            log.exception("team2 pick_contract failed")
            await self._trail(ap, ev.TECHNIQUE_PLAN_CONTRACT, "contract_deferred", f"contract pick failed: {exc}",
                              trigger=trade.trigger_id, verdict="deferred", stage="error", error=str(exc)[:200], examined=[],
                              direction=trade.direction)
            self._record_unfilled(ap, trade.trigger_id)
            return None

    async def _quote_examined(self, opts, otm: list[dict], spot: float, direction: str, rules: Team2Rules, expiry: str, today) -> dict:
        """The picker's quoting walk (F105/F108), factored so the shadow quote of a refused candidate examines exactly what
        the live pick would have: the nearest listed OTM contracts quoted live one by one, the walk stopping only on a
        FRESH ask under the floor; whatever was not examined is reported as unexamined."""
        from ...options.pick import select_by_premium
        limit = max(1, int(rules.quote_candidates))
        floor = float(rules.premium_floor)
        examined: list[dict] = []
        eligible: list[dict] = []
        unpriced = 0
        stopped_under_floor = False
        for raw in otm[:limit]:
            c = dict(raw)
            delayed_ask = float(c.get("ask") or 0)
            c["priced"] = "none"
            c["bid"], c["ask"] = 0.0, 0.0                 # the delayed quote is never the price
            try:
                await opts.reprice(c)                      # `priced: opra` when the live NBBO is served
            except Exception as exc:  # noqa: BLE001
                c["priced"] = "none"
                c["_error"] = str(exc)
            live = c.get("priced") == "opra" or c.get("source") == "opra" or c.get("delayed") is False
            fresh = live and float(c.get("ask") or 0) > 0
            if fresh:
                c["priced"] = "opra"
            if not fresh and not rules.require_fresh_quote and delayed_ask > 0:
                c["ask"], c["bid"], c["priced"] = delayed_ask, float(raw.get("bid") or 0), "chain"
                fresh = True
            # D2 binding (2026-09-16 review r3): the price, its provenance and its timestamps are captured TOGETHER, here, as
            # one immutable observation of this candidate — the Quote the re-price just read, verified to be the same
            # bid/ask. A later cache lookup is another observation and is never joined to this price.
            row = {"strike": float(c["strike"]), "symbol": c.get("symbol"), "delayedAsk": delayed_ask,
                   "ask": float(c.get("ask") or 0), "bid": float(c.get("bid") or 0), "priced": c.get("priced"),
                   "eligible": bool(fresh), "collectedTs": int(time.time() * 1000), "quoteTs": None, "receivedTs": None,
                   "source": (c.get("priced") if c.get("priced") in ("chain", "none") else None)}
            if c.get("priced") == "opra":
                qq = self.engine.quotes.get(str(c.get("symbol") or ""))
                if qq is not None and float(getattr(qq, "bid", 0) or 0) == row["bid"] and float(getattr(qq, "ask", 0) or 0) == row["ask"]:
                    row["quoteTs"] = int(getattr(qq, "source_ts", 0) or 0) or None      # the provider's confirmation of THIS bid/ask
                    row["receivedTs"] = int(getattr(qq, "ts", 0) or 0) or None          # when the app received it — kept apart
                    row["source"] = str(getattr(qq, "source", "") or "") or "opra"
                else:
                    row["source"] = "opra"
                    row["provenanceNote"] = "quote moved between re-price and capture — no source time attached"
            examined.append(row)
            if not fresh:
                unpriced += 1
                continue
            eligible.append(c)
            if float(c["ask"]) < floor:
                stopped_under_floor = True
                break
        unexamined = max(0, len(otm) - len(examined)) if not stopped_under_floor else 0
        pick = select_by_premium(eligible, spot, direction, target_premium=rules.target_premium,
                                 premium_floor=rules.premium_floor, expiry=expiry, today=today,
                                 is_0dte=(expiry == today.isoformat()), mode=rules.premium_pick) if eligible else None
        return {"examined": examined, "eligible": eligible, "unpriced": unpriced, "unexamined": unexamined, "pick": pick,
                "listed": len(otm)}

    # ------------------------------------------------------------- shadow diagnostics (2026-09-16, review team GO)
    # Measurements only: entry location, attempt context, the contract alternatives and their follow-up quotes, the
    # decision-time record. Nothing here changes an order decision; `techniques.team2.diagnostics=false` turns the
    # measurements off (the decision ledger below stays on — it is the close report's record).
    def _diag_on(self) -> bool:
        try:
            return bool(self.rt("diagnostics", True))
        except Exception:  # noqa: BLE001
            return True

    def _ledger_of(self, run_id: str) -> dict:
        return self.__dict__.setdefault("_ledger", {}).setdefault(run_id, {})

    def _diag_of(self, run_id: str) -> dict:
        return self.__dict__.setdefault("_diag", {}).setdefault(run_id, {"attempts": {}, "pending": []})

    def _diag_attempt(self, ap: ArmedPlan, tid: str) -> dict:
        d = self._diag_of(ap.run_id)
        return d["attempts"].setdefault(tid, {"trigger": tid, "setup": str(tid).split("#")[0], "observations": {}, "candidates": []})

    def note_decision(self, ap: ArmedPlan, rec: dict) -> None:
        """Every logged refusal / skip / contract verdict lands in the durable ledger under a STABLE identity (event,
        setup, source minute); a price revision of the same candidate is a version, not a second decision."""
        if not diag.is_decision(rec.get("event")):
            return
        r = dict(rec)
        if r.get("sourceTs") is None:
            t = ap.trades.get(str(r.get("trigger"))) if r.get("trigger") is not None else None
            if t is not None:
                r["sourceTs"] = t.fired_ts
        diag.note_decision(self._ledger_of(ap.run_id), r)

    def _diag_emit(self, ap: ArmedPlan, kind: str, payload: dict) -> None:
        journal = getattr(getattr(self, "engine", None), "journal", None)
        if journal is None:
            return

        async def _write():
            try:
                await journal.append(ev.TECHNIQUE_PLAN_DIAGNOSTIC, {"runId": ap.run_id, "symbol": ap.symbol, "kind": kind, **payload},
                                     aggregate_type="technique_run", aggregate_id=ap.run_id, portfolio_id=ap.config.portfolio_id)
            except Exception:  # noqa: BLE001
                log.debug("team2 diagnostic not journaled (%s)", kind, exc_info=True)
        try:
            task = asyncio.create_task(_write(), name=f"team2-diag-{ap.symbol}-{kind}")
            self.__dict__.setdefault("_diag_tasks", set()).add(task)
            task.add_done_callback(self.__dict__["_diag_tasks"].discard)
        except RuntimeError:
            pass

    def _diag_signal(self, ap: ArmedPlan, e: dict, setup: dict, trade: Trade, *, journal: bool) -> None:
        """At the fire: where the entry sits on the tape (confirmation close, pullback candle, level, entry line, ATR
        distances), which attempt into the setup this is, and the immutable decision-time record of what the desk knew."""
        if not journal or not self._diag_on():
            return
        try:
            rules = self.rules_for(ap)
            bars = list(self._bars.get(ap.run_id, []))
            today = [b for b in bars if session_date(b.ts) == ap.plan_for]
            loc = diag.entry_location(e, setup, today, confirm_tf_ms=int(rules.confirm_tf_min) * 60_000)
            att = diag.attempt_context(str(trade.setup_id), trade.trigger_id, int(trade.fired_ts or 0), list(ap.trades.values()),
                                       self._fees_paid, today, trade.direction)
            rec = self._diag_attempt(ap, trade.trigger_id)
            rec["entryLocation"], rec["attempt"] = loc, att
            import zargar as _pkg
            rec["decisionTime"] = {
                "trigger": trade.trigger_id, "setup": trade.setup_id, "signalTs": int(e.get("ts") or 0), "signalTime": e.get("time"),
                "confirmationCloseTs": loc.get("confirmationCloseTs"), "entryKind": e.get("entryKind"), "entryLine": e.get("spot"),
                "setupLevel": loc.get("setupLevel"), "bucket": e.get("bucket"), "sizeMult": e.get("sizeMult"), "direction": trade.direction,
                "stop": trade.stop, "targets": list(trade.targets), "targetKind": trade.target_kind,
                "modelStrike": e.get("strike"), "modelPremium": e.get("premium"), "why": str(e.get("why") or "")[:300],
                "inputs": {"tapeHash": diag.tape_hash(today, int(e.get("ts") or 0)), "bars": len(today),
                           "decisionWatermark": self._decision_wm.get(ap.run_id), "rulesHash": diag.rules_hash(rules),
                           "appVersion": getattr(_pkg, "__version__", None),
                           "build": (getattr(_pkg, "build_sha", lambda: None)() or None),
                           "experiment": (ap.plan or {}).get("experiment") if isinstance(ap.plan, dict) else None},
                "recordedAt": int(time.time() * 1000)}
            self._diag_emit(ap, "entry_location", {"trigger": trade.trigger_id, **loc})
            self._diag_emit(ap, "attempt", {"trigger": trade.trigger_id, **att})
            self._diag_emit(ap, "decision_time", rec["decisionTime"])
        except Exception:  # noqa: BLE001
            log.debug("team2 diagnostic (signal) failed", exc_info=True)

    def _diag_submission(self, ap: ArmedPlan, trade: Trade) -> None:
        """At the order boundary: the underlying NOW against the signal candle (has price moved on?)."""
        if not self._diag_on():
            return
        try:
            rec = self._diag_of(ap.run_id)["attempts"].get(trade.trigger_id)
            if rec is None or not rec.get("entryLocation") or "submission" in rec["entryLocation"]:
                return
            q = self.engine.quotes.get(ap.symbol)
            last = float(q.last) if q is not None and q.last and q.last > 0 else None
            disp = diag.submission_displacement(rec["entryLocation"], last, int(time.time() * 1000), getattr(q, "ts", None))
            # 2026-09-17 item 4: target / stop room from the ACTUAL underlying quote at the order boundary, the
            # source-level identity of the target, and a labelled payoff estimate for the selected contract
            room = diag.target_room(rec["entryLocation"], last, trade.targets[0] if trade.targets else None, trade.stop,
                                    getattr(trade, "_anchor", rec["entryLocation"].get("setupLevel")))
            disp.update(room)
            sel = next((c for c in rec.get("candidates") or [] if c.get("selected")), None) or {}
            fee = float(getattr(self.rules_for(ap), "fee_per_contract", 0) or 0)
            disp["payoffEstimate"] = diag.payoff_estimate(sel.get("ask"), sel.get("bid"), sel.get("delta"), sel.get("gamma"),
                                                          room.get("targetRoomPoints"), fee, greeks_source=sel.get("greeksSource"))
            rec["entryLocation"].update(disp)
            self._diag_emit(ap, "entry_submission", {"trigger": trade.trigger_id, **disp})
        except Exception:  # noqa: BLE001
            log.debug("team2 diagnostic (submission) failed", exc_info=True)

    def _diag_candidates(self, ap: ArmedPlan, tid: str, qres: dict, pick_symbol: str | None, spot: float, rules: Team2Rules,
                         chain, opts, *, shadow: bool = False, refusal: str | None = None) -> None:
        """The contracts the picker examined (selected + alternatives) with their quotes and Greeks at the signal, and
        the follow-up schedule: 2/5/10 min after the quote, plus the actual exit when a position follows."""
        if not self._diag_on():
            return
        try:
            now = int(time.time() * 1000)
            rows_by_sym: dict[str, dict] = {}
            provider_name = None
            try:
                provider_name = str(getattr(opts.provider(), "name", None) or "") if opts is not None and hasattr(opts, "provider") else None
            except Exception:  # noqa: BLE001
                provider_name = None
            for r in (chain or []):
                sym = str(r.get("symbol") or "")
                if not sym:
                    continue
                snap = opts.snapshot_cached(sym) if opts is not None and hasattr(opts, "snapshot_cached") else None
                # item 4 (2026-09-17): the Greeks come with their PROVENANCE — a served-live snapshot never hides the chain
                # row's Greeks (all three of the 09-17 candidates read null while the pick itself carried delta 0.461)
                row = dict(r)
                if snap:
                    row.update({k: v for k, v in snap.items() if v is not None and k != "greeks"})
                    sg = {k: v for k, v in (snap.get("greeks") or {}).items() if v is not None}
                    row["greeks"] = {**(r.get("greeks") or {}), **sg}
                    row["greeksSource"] = "live" if snap.get("greeksLive") and sg else ("chain" if (r.get("greeks") or {}).get("delta") is not None else "none")
                    row["greeksAsOf"] = (snap.get("greeksFieldAsOf") or {}).get("delta") if snap.get("greeksLive") else (snap.get("asOf") or None)
                else:
                    row["greeksSource"] = "chain" if (r.get("greeks") or {}).get("delta") is not None else "none"
                    row["greeksAsOf"] = None
                row["greeksProvider"] = provider_name
                rows_by_sym[sym] = row
            # D2 binding (review r3): every examined row already carries its own price, provenance and timestamps, captured
            # together in `_quote_examined`. Nothing is looked up again here — a later cache state is another observation.
            cands = diag.candidate_rows(qres.get("examined") or [], rows_by_sym, pick_symbol, floor=float(rules.premium_floor),
                                        band_hi=float(rules.target_premium) * MAX_OVER_TARGET, spot=spot, quote_ts=now)
            rec = self._diag_attempt(ap, tid)
            rec.update({"candidates": cands, "quoteTs": now, "shadow": bool(shadow), "refusal": refusal, "selected": pick_symbol,
                        "listed": qres.get("listed"), "unexamined": qres.get("unexamined"), "unpriced": qres.get("unpriced")})
            rec.setdefault("observations", {})
            d = self._diag_of(ap.run_id)
            if cands and not any(p["attempt"] == tid for p in d["pending"]):
                d["pending"] += diag.schedule(tid, now, with_exit=(not shadow and pick_symbol is not None))
            self._diag_emit(ap, "contract_candidates", {"trigger": tid, "shadow": bool(shadow), "refusal": refusal, "quoteTs": now,
                                                        "spot": spot, "selected": pick_symbol, "candidates": cands,
                                                        "listed": qres.get("listed"), "unexamined": qres.get("unexamined"),
                                                        "unpriced": qres.get("unpriced")})
        except Exception:  # noqa: BLE001
            log.debug("team2 diagnostic (candidates) failed", exc_info=True)

    def _diag_shadow(self, ap: ArmedPlan, e: dict, res, tid: str, refusal: str) -> None:
        """A candidate refused BEFORE the picker (allocation caps) is quoted in the shadow — the same walk the live pick
        would have made — so the review can see what the blocked contracts did. No trade, no verdict, no order."""
        if ap.config.mode != "auto" or not self._diag_on():
            return

        async def _run():
            try:
                opts = getattr(self.engine, "options", None)
                if opts is None:
                    return
                setup = next((s for s in res.setups if s["id"] == e.get("setup")), {})
                direction = setup.get("direction") or ("long" if (e.get("regime") or {}).get("stack") == "bull" else "short")
                rules = self.rules_for(ap)
                provider = opts.provider()
                today = dt.datetime.now(ET).date()
                expiry, _why = await self._expiry_for(provider, ap.symbol, rules, today)
                if expiry is None:
                    return
                chain, _lmeta = await self._listing(provider, ap.symbol, expiry)
                spot = float(e.get("spot") or 0)
                q = self.engine.quotes.get(ap.symbol)
                if q is not None and q.last and q.last > 0:
                    spot = float(q.last)
                want = "call" if direction == "long" else "put"
                side = [c for c in (chain or []) if (c.get("option_type") or "").lower() == want and c.get("strike") is not None and c.get("symbol")]
                otm = [c for c in side if (float(c["strike"]) > spot if want == "call" else float(c["strike"]) < spot)]
                otm.sort(key=lambda c: abs(float(c["strike"]) - spot))
                qres = await self._quote_examined(opts, otm, spot, direction, rules, expiry, today)
                rec = self._diag_attempt(ap, tid)
                rec["entryLocation"] = diag.entry_location(e, setup, [b for b in self._bars.get(ap.run_id, []) if session_date(b.ts) == ap.plan_for],
                                                           confirm_tf_ms=int(rules.confirm_tf_min) * 60_000)
                self._diag_candidates(ap, tid, qres, (qres["pick"].symbol if qres["pick"] is not None else None), spot, rules, chain, opts,
                                      shadow=True, refusal=refusal)
            except Exception:  # noqa: BLE001
                log.debug("team2 shadow quote failed", exc_info=True)
        try:
            task = asyncio.create_task(_run(), name=f"team2-shadow-{ap.symbol}-{tid}")
            self.__dict__.setdefault("_diag_tasks", set()).add(task)
            task.add_done_callback(self.__dict__["_diag_tasks"].discard)
        except RuntimeError:
            pass

    @staticmethod
    def _diag_routing(t: Trade, fees: float) -> dict:
        """The book's ACTUAL execution facts for an attempt (never a quoted return): the weighted exit price comes from
        exit records with a CONFIRMED positive `filledQty` and a fill price, whatever the cached order status says (the
        2026-09-16 QQQ exits kept `SUBMITTED` beside their confirmed fills); a requested `qty` is never a fill; duplicate
        updates of one order count once (last wins); an exit filled without a price is reported as unknown."""
        by_order: dict = {}
        for i, x in enumerate(t.exits or []):
            by_order[str(x.get("orderId") or f"#{i}")] = x
        filled = [(float(x.get("filledQty") or 0), x.get("price")) for x in by_order.values() if float(x.get("filledQty") or 0) > 0]
        qty = sum(q for q, _ in filled)
        priced = [(q, float(p)) for q, p in filled if p is not None]
        pq = sum(q for q, _ in priced)
        px = (sum(q * p for q, p in priced) / pq) if pq > 0 else None
        filled = float(t.filled_qty or 0) > 0
        gross = round(float(t.realized_pnl or 0), 2) if filled else None
        net = round(float(t.realized_pnl or 0) - float(fees or 0), 2) if filled else None
        return {"status": t.status, "filledQty": float(t.filled_qty or 0), "avgFill": t.avg_fill, "contract": t.order_symbol,
                "grossPnl": gross, "fees": (round(float(fees or 0), 2) if filled else None), "netPnl": net,
                # item 4 (2026-09-17): a gross-breakeven trade that costs commissions is a NET loss — said explicitly; the risk
                # counter's basis (gross) is unchanged pending the review team's accounting decision
                "grossBreakevenNetLoss": bool(filled and gross is not None and net is not None and gross >= 0 and net < 0),
                "exitFilledQty": qty, "exitPricedQty": pq,
                "exitPrice": (round(px, 4) if px is not None else None),
                "exitPriceUnknown": bool(qty > 0 and pq < qty), "openedTs": t.opened_ts, "closedTs": t.closed_ts,
                "submitUncertain": bool(getattr(t, "submit_uncertain", False))}

    async def _diag_tick(self) -> None:
        """Called from the ~2 s quote watch: refresh the routing snapshot of every diagnosed attempt, make the exit
        observation due when its position has closed, and take every follow-up observation that is due."""
        if not self._diag_on():
            return
        now = int(time.time() * 1000)
        plans = list(self._armed.values()) + list(getattr(self, "_closing", {}).values())
        for ap in plans:
            d = self.__dict__.get("_diag", {}).get(ap.run_id)
            if not d:
                continue
            for tid, rec in list(d["attempts"].items()):
                t = ap.trades.get(tid)
                if t is None:
                    continue
                rec["routing"] = self._diag_routing(t, self._fees_paid(t))
                if t.status == "closed" and float(t.filled_qty or 0) > 0:
                    for p in d["pending"]:
                        if p["attempt"] == tid and p["horizon"] == "exit" and p["status"] == "pending" and p["dueTs"] is None:
                            p["dueTs"] = int(t.closed_ts or now)
            for p in d["pending"]:
                if p["status"] == "pending" and p["dueTs"] is not None and int(p["dueTs"]) <= now:
                    p["status"] = "inflight"
                    task = asyncio.create_task(self._diag_observe(ap, p), name=f"team2-observe-{ap.symbol}-{p['attempt']}-{p['horizon']}")
                    self.__dict__.setdefault("_diag_tasks", set()).add(task)
                    task.add_done_callback(self.__dict__["_diag_tasks"].discard)

    async def _diag_observe(self, ap: ArmedPlan, p: dict) -> None:
        d = self._diag_of(ap.run_id)
        rec = d["attempts"].get(p["attempt"])
        opts = getattr(self.engine, "options", None)
        quotes: dict[str, dict | None] = {}
        unknown: dict[str, str] = {}
        try:
            for c in (rec or {}).get("candidates") or []:
                sym = str(c.get("symbol") or "")
                if not sym:
                    continue
                if not c.get("followed", True):
                    unknown[sym] = "not followed (collection bounded)"
                    continue
                if opts is None:
                    unknown[sym] = "options service unavailable"
                    continue
                q = None
                try:
                    # a NEW observation, never the cached quote the entry was priced on: the service's own forced refresh
                    refresh = getattr(opts, "refresh_now", None)
                    if refresh is not None:
                        qq = await refresh(sym)
                        live = (opts.served_live(sym) if hasattr(opts, "served_live") else True)
                        if qq is not None:
                            # price and its SOURCE confirmation time are read from the same Quote object, together; the
                            # receipt time (`ts`) rides beside them and never stands in for the source time
                            src = str(getattr(qq, "source", "") or "") or ("opra" if live else "chain")
                            q = {"bid": getattr(qq, "bid", None), "ask": getattr(qq, "ask", None), "priced": src,
                                 "quoteTs": (int(getattr(qq, "source_ts", 0) or 0) or None), "receivedTs": getattr(qq, "ts", None)}
                    else:
                        r = await opts.reprice({"symbol": sym})
                        qq = self.engine.quotes.get(sym)
                        if r:
                            q = {"bid": r.get("bid"), "ask": r.get("ask"), "priced": r.get("priced"),
                                 "quoteTs": (int(getattr(qq, "source_ts", 0) or 0) or None) if qq is not None else None,
                                 "receivedTs": getattr(qq, "ts", None) if qq is not None else None}
                except Exception as exc:  # noqa: BLE001
                    unknown[sym] = f"quote service error: {str(exc)[:80]}"
                    q = None
                quotes[sym] = q
            obs = diag.observation(p["horizon"], p.get("dueTs"), int(time.time() * 1000), quotes, unknown=unknown)
        except Exception as exc:  # noqa: BLE001
            obs = {"horizon": p["horizon"], "dueTs": p.get("dueTs"), "takenTs": int(time.time() * 1000), "status": "unknown",
                   "reason": str(exc)[:200], "quotes": {}, "unknown": {}}
        if rec is not None:
            rec.setdefault("observations", {})[p["horizon"]] = obs
        p["status"] = "done"
        self._diag_emit(ap, "contract_observation", {"trigger": p["attempt"], **obs})

    async def on_quote_watch(self) -> None:
        await super().on_quote_watch()
        try:
            await self._diag_tick()
        except Exception:  # noqa: BLE001
            log.debug("team2 diagnostic tick failed", exc_info=True)

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
        await self._trail_extrema(ap, "pre-open")
        await self._log_rederived(ap, "pre-open")
        return {"rows": [], "reference": ref, "gapPct": round(gap, 3), "replan": False}

    async def _trail_extrema(self, ap: ArmedPlan, when: str) -> None:
        """2026-09-17: the pre-market extremes the plan just froze, with the bar each came from and the input hash — the
        durable record that lets a frozen PML be reconciled against the bank and against replay (C6 evidence)."""
        ext = (ap.plan or {}).get("pmExtrema") if isinstance(ap.plan, dict) else None
        if not isinstance(ext, dict):
            return
        hi, lo = ext.get("pmh") or {}, ext.get("pml") or {}
        text = (f"{when}: PMH {hi.get('value')} from the {dt.datetime.fromtimestamp((hi.get('bar') or {}).get('ts', 0) / 1000, ET).strftime('%H:%M') if hi.get('bar') else '?'} bar, "
                f"PML {lo.get('value')} from the {dt.datetime.fromtimestamp((lo.get('bar') or {}).get('ts', 0) / 1000, ET).strftime('%H:%M') if lo.get('bar') else '?'} bar; "
                f"{(ext.get('inputs') or {}).get('bars')} pre-market bars, input hash {(ext.get('inputs') or {}).get('hash')}")
        await self._trail(ap, ev.TECHNIQUE_PLAN_READ, "premarket_extrema", text, when=when, pmExtrema=ext,
                          warmup=(ap.plan or {}).get("warmup"))

    async def _log_rederived(self, ap: ArmedPlan, when: str) -> None:
        """F110 (2026-09-11): the F81 re-derive moves the plan's target before a single entry is judged, so it
        belongs on the DURABLE record, not only in the plan's in-memory events (which a restart wipes — and
        this desk restarts mid-session). Journalled as TechniquePlanReplanned/`targets_rederived`."""
        red = (ap.plan or {}).get("targetsRederived") or {}
        if not red or ap.plan.get("_rederivedLogged") == red:
            return
        ap.plan["_rederivedLogged"] = red
        parts = [f"{side}: {v['was']:.2f} -> {v['now']:.2f} ({v['source']})" if v.get("now") is not None
                 else f"{side}: {v['was']:.2f} -> none" for side, v in red.items()]
        why = (f"the {when} reference {next(iter(red.values()))['reference']:.2f} had run "
               f"through the planned target — re-derived from the morning's structure: " + "; ".join(parts) + " (F81)")
        self._log(ap, "targets_rederived", why,
                  targets=ap.plan.get("targets"), planned=ap.plan.get("targetsPlanned"), rederived=red)
        await self._trail(ap, ev.TECHNIQUE_PLAN_READ, "targets_rederived", why, when=when,
                          targets=ap.plan.get("targets"), planned=ap.plan.get("targetsPlanned"), rederived=red)

    async def _finalize_open(self, ap: ArmedPlan, bars: list[Bar]) -> None:
        from .plan import complete_plan
        before = {k: ap.plan.get(k) for k in ("openPrice", "openSource", "dayType", "sizingAtOpen", "completedAt")}
        try:
            done = complete_plan(ap.plan, bars)
        except Exception:  # noqa: BLE001
            log.exception("team2 open finalize failed for %s", ap.symbol)
            return
        if done.get("openSource") != "rth_open":
            return
        ap.plan["preopenSnapshot"] = before
        ap.plan.update(done)
        ap.plan["openFinalizedAt"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        await self._trail_extrema(ap, "09:30 open")
        await self._log_rederived(ap, "09:30 open")
        why = (f"day type finalized on the 09:30 open {done.get('openPrice')}: "
               f"{before.get('dayType')} (09:25 estimate) -> {done.get('dayType')}, "
               f"sizing at open {done.get('sizingAtOpen')} (F49)")
        self._log(ap, "open_finalized", why, before=before, openPrice=done.get("openPrice"), dayType=done.get("dayType"))
        await self._trail(ap, ev.TECHNIQUE_PLAN_READ, "open_finalized", why, before=before,
                          openPrice=done.get("openPrice"), dayType=done.get("dayType"),
                          sizingAtOpen=done.get("sizingAtOpen"))
        svc = getattr(self.engine, "team2", None)
        if svc is not None:
            with contextlib.suppress(Exception):
                await svc.stamp_run(ap)

    # ------------------------------------------------------------- bars
    def _merge_revision(self, ap: ArmedPlan, bar: Bar) -> dict | None:
        """R3: merge a corrected / late minute into the private tape. Returns the revision record (None when the
        bar is identical to what the desk already holds — a duplicate delivery changes nothing and writes nothing);
        `_on_bar` journals it, so the decision-time inputs can be reconstructed from the record."""
        bars = self._bars.setdefault(ap.run_id, [])
        hhmm = dt.datetime.fromtimestamp(bar.ts / 1000, ET).strftime('%H:%M')
        for i, b in enumerate(bars):
            if b.ts == bar.ts:
                same = (b.open, b.high, b.low, b.close, b.volume) == (bar.open, bar.high, bar.low, bar.close, bar.volume)
                if same:
                    return None
                bars[i] = bar
                text = (f"the {hhmm} bar was corrected ({b.source or 'unknown'} o/h/l/c/v {b.open}/{b.high}/{b.low}/{b.close}/{b.volume} → "
                        f"{bar.source or 'unknown'} {bar.open}/{bar.high}/{bar.low}/{bar.close}/{bar.volume}); the next read runs on "
                        f"the corrected tape (R3)")
                rec = {"event": "bar_revised", "text": text, "ts_": bar.ts, "before": [b.open, b.high, b.low, b.close, b.volume],
                       "after": [bar.open, bar.high, bar.low, bar.close, bar.volume], "source": bar.source,
                       "decisionWatermark": self._decision_wm.get(ap.run_id)}
                self._log(ap, "bar_revised", text, **{k: v for k, v in rec.items() if k not in ("event", "text")})
                return rec
            if b.ts > bar.ts:
                bars.insert(i, bar)
                text = f"the missing {hhmm} bar arrived late and was inserted; the next read runs on the completed tape (R3)"
                rec = {"event": "bar_recovered", "text": text, "ts_": bar.ts, "source": bar.source,
                       "after": [bar.open, bar.high, bar.low, bar.close, bar.volume], "decisionWatermark": self._decision_wm.get(ap.run_id)}
                self._log(ap, "bar_recovered", text, **{k: v for k, v in rec.items() if k not in ("event", "text")})
                return rec
        bars.append(bar)
        text = f"the {hhmm} bar arrived late and was appended (R3)"
        rec = {"event": "bar_recovered", "text": text, "ts_": bar.ts, "source": bar.source,
               "after": [bar.open, bar.high, bar.low, bar.close, bar.volume], "decisionWatermark": self._decision_wm.get(ap.run_id)}
        self._log(ap, "bar_recovered", text, **{k: v for k, v in rec.items() if k not in ("event", "text")})
        return rec

    async def load_contract_verdicts(self) -> int:
        """R5: after a restart the in-memory verdict list is empty; re-read today's durable `TechniquePlanContract`
        rows for every armed plan so the close funnel is the same with or without a restart."""
        n = 0
        try:
            from sqlalchemy import select as _select
            from ...models import Event
            async with self.engine.sf() as session:
                for ap in list(self._armed.values()):
                    rows = (await session.execute(_select(Event).where(Event.aggregate_id == ap.run_id, Event.type == ev.TECHNIQUE_PLAN_CONTRACT)
                                                  .order_by(Event.id))).scalars().all()
                    if rows:
                        self._contract_verdicts[ap.run_id] = [dict(r.payload or {}) for r in rows]
                        n += len(rows)
                        # R1: reporting AND the read's exemption come back from the same durable rows
                        added = self._exempt_from_verdicts(ap)
                        if added:
                            self._log(ap, "execution_overlay_restored", f"{added} refused/deferred fire(s) re-exempted from the "
                                      f"read's proxy from the journal (R1)", restored=added)
                    # 2026-09-16: the decision ledger is rebuilt from the same durable rows plus the skip rows — one entry per
                    # (event, setup, source minute), so a restart neither loses nor duplicates a refusal
                    srows = (await session.execute(_select(Event).where(Event.aggregate_id == ap.run_id,
                                                                         Event.type == ev.TECHNIQUE_PLAN_TRIGGER_SKIPPED)
                                                   .order_by(Event.id))).scalars().all()
                    led = self._ledger_of(ap.run_id)
                    for r in list(rows) + list(srows):
                        p = dict(r.payload or {})
                        if p.get("sourceTs") is None and p.get("trigger") in ap.trades:
                            p["sourceTs"] = ap.trades[p["trigger"]].fired_ts
                        diag.note_journal_row(led, p)
        except Exception:  # noqa: BLE001
            log.warning("team2 contract verdicts not reloaded", exc_info=True)
        return n

    async def _load_warmup(self, ap: ArmedPlan) -> None:
        if ap.run_id in self._warm_loaded:
            return
        self._warm_loaded.add(ap.run_id)
        rules = self.rules_for(ap)
        try:
            from ...marketdata import load_bars
            rows = await load_bars(self.engine.sf, ap.symbol, "1m", limit=max(20000, int(rules.warmup_sessions) * 1200))
        except Exception:  # noqa: BLE001
            rows = []
        # F99 (2026-09-10): ONE warm-up rule for live, replay and sweep — the last `warmup_sessions` valid
        # sessions (F75 validation inside), stamped on the plan by content hash so replay can prove parity.
        # Before this the live path took the last 6,000 rows (~6 sessions), replay 12 and the sweep 12 dates.
        from .service import Team2Service
        prior = [b for b in rows if session_date(b.ts) < ap.plan_for]
        warm, rep = Team2Service.warmup_slice(prior, sessions=rules.warmup_sessions)
        if rep["excluded"]:
            self._log(ap, "history_excluded", f"warm-up skipped {len(rep['excluded'])} session(s) that are not market data: "
                      + ", ".join(f"{x['date']} ({x['reason']})" for x in rep["excluded"][:6]) + " (F75)",
                      excluded=rep["excluded"], used=rep["sessionsUsed"][-12:])
        ap.plan["contractAuthority"] = "quotes"      # F108: on the live path the model never vetoes a contract
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
            # the fetched tape goes through the same rule — the stamp below describes what the read consumes
            warm, rep = Team2Service.warmup_slice(warm, sessions=rules.warmup_sessions)
        ap.plan["warmup"] = {k: rep.get(k) for k in ("sessions", "sessionsUsed", "hash", "rows")}
        self._log(ap, "warmup", f"EMA warm-up: {rep['rows']} bars over {len(rep['sessionsUsed'])} valid session(s) "
                  f"(rule: last {rules.warmup_sessions}); identity {str(rep.get('hash') or '')[:12]} (F99)",
                  warmup=ap.plan["warmup"])
        await self._trail(ap, ev.TECHNIQUE_PLAN_READ, "warmup", f"{rep['rows']} bars, {len(rep['sessionsUsed'])} valid session(s)",
                          warmup=ap.plan["warmup"])
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

    @staticmethod
    def _fingerprint(e: dict) -> str:
        return f"{e.get('ts')}|{e.get('event')}|{e.get('setup') or e.get('scenario') or ''}|{e.get('touch') or ''}|{str(e.get('why'))[:48]}"

    async def _session_sigma(self, ap: ArmedPlan) -> float:
        """F51 (2026-09-08): the read's IV is a point-in-time input — captured ONCE per plan, from today's
        0DTE ATM chain IV when available (else the VIX proxy), stamped on the plan and the run row, and
        held for the whole session. A later IV can never rewrite an earlier signal (the read is
        recomputed every bar) — it may only inform the next session."""
        snap = (ap.plan or {}).get("sigma")
        if isinstance(snap, dict) and snap.get("value"):
            return float(snap["value"])
        value, source, detail = await self._sigma_snapshot(ap.symbol)
        ap.plan["sigma"] = {"value": round(float(value), 4), "source": source,
                            "lockedAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), **detail}
        self._log(ap, "sigma_locked", f"read IV locked at {value:.4f} from {source} — held for the session so the "
                  "read's history cannot change under it (F51)", source=source, **detail)
        svc = getattr(self.engine, "team2", None)
        if svc is not None:
            with contextlib.suppress(Exception):
                await svc.stamp_run(ap)                    # point-in-time provenance on the run row
        return float(value)

    async def _sigma_snapshot(self, symbol: str) -> tuple[float, str, dict]:
        """Today's 0DTE ATM IV from the chain (call/put mid_iv averaged at the strike nearest spot), with its
        provenance; the VIX proxy when the chain has none. The chain row is CBOE-delayed (~15 min): say so."""
        src = str(self.rt("sigma_source", "chain"))
        if src == "chain":
            try:
                opts = getattr(self.engine, "options", None)
                today = dt.datetime.now(ET).date().isoformat()
                q = self.engine.quotes.get(symbol)
                spot = float(q.last) if q is not None and q.last and q.last > 0 else None
                if opts is not None and spot:
                    rows = await opts.provider().chain(symbol, today)
                    priced = [c for c in rows if (c.get("greeks") or {}).get("mid_iv")]
                    if priced:
                        k = min({float(c.get("strike") or 0) for c in priced}, key=lambda x: abs(x - spot))
                        ivs = [float(c["greeks"]["mid_iv"]) for c in priced if float(c.get("strike") or 0) == k
                               and float(c["greeks"]["mid_iv"]) > 0]
                        if ivs:
                            iv = sum(ivs) / len(ivs)
                            return iv, "chain_atm", {"expiry": today, "strike": k, "spot": round(spot, 4), "chainDelayed": True,
                                                     "capturedAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
            except Exception:  # noqa: BLE001 - the proxy below is the fallback, and the source is stamped
                log.warning("team2 chain IV snapshot failed for %s — falling back to the VIX proxy", symbol)
        value = await self._sigma(symbol)
        return value, "vix_proxy", {"capturedAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}

    async def _sigma(self, symbol: str) -> float:
        """IV proxy for the premium model (B2): ^VIX1D → ^VIX×1.3 → 0.20, cached per day."""
        day = dt.datetime.now(ET).strftime("%Y-%m-%d")
        hit = self._sigma_cache.get(symbol)
        if hit and hit[0] == day:
            return hit[1]
        sigma = 0.20
        src = str(self.rt("sigma_source", "vix1d"))
        if src == "chain":
            src = "vix1d"                                  # the chain path lives in _sigma_snapshot; this is its fallback
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
            # R3 (2026-09-14): a minute the desk already passed is a REVISION (an exchange correction) or a RECOVERED
            # HOLE — merge it into the private tape by timestamp instead of dropping it. No decision is re-run here:
            # the next 2m close recomputes the read from the corrected history, `_seen_fp` keeps acted events from
            # repeating, and `read_rewritten` states when a conclusion changed. Decision-time inputs stay in the
            # journal; the revision is recorded with before/after.
            rec = self._merge_revision(ap, bar)
            if rec is not None and journal:
                await self._trail(ap, ev.TECHNIQUE_PLAN_READ, rec["event"], rec["text"],
                                  **{k: v for k, v in rec.items() if k not in ("event", "text")})
            return
        ap.last_bar_ts = bar.ts
        ap.stale = False
        ap.bar_index += 1
        await self._load_warmup(ap)
        await self._ensure_listing(ap, bar.ts)
        bars = self._bars.setdefault(ap.run_id, [])
        if not bars or bars[-1].ts < bar.ts:
            bars.append(bar)
        # F49 (2026-09-08): the 09:25 completion is an ESTIMATE from the last pre-market print; the first
        # regular bar finalizes the day type / open / sizing, keeping the estimate as a snapshot
        if bar_session(bar.ts) == "rth" and (ap.plan or {}).get("zones") and (ap.plan or {}).get("openSource") != "rth_open":
            await self._finalize_open(ap, bars)
        _, close_ms = session_bounds(ap.plan_for)
        rules = self.rules_for(ap)
        step = rules.entry_tf_min * 60_000
        end_ts = bar.ts + 60_000
        # C3/D-1 hard clock: whatever the model thinks, the BOOK is flat by flatten_min. The model's
        # position can already be gone (its stop fired, a restore-seeded read, an add the read never saw)
        # while the book still holds a 0DTE contract — and the shared clock-driven close is 16:05,
        # after expiry. Post-close audit 2026-09-04.
        if journal and minute_of_day(bar.ts) + 1 >= rules.flatten_min and bar_session(bar.ts) == "rth":
            await self._clock_flatten(ap, rules)
        # R1 (audit 2026-09-04): Team2 never ran the shared `_manage`, so a trim resting as a limit was
        # never re-priced — and the flatten was clamped by that pending quantity. Re-price stuck exits here.
        if journal and bar_session(bar.ts) == "rth":
            await self._reprice_stuck_exits(ap)
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
        sigma = await self._session_sigma(ap)
        plan["sigma"] = ap.plan.get("sigma")
        res = simulate_session(plan, self._bars.get(ap.run_id, []), rules, sigma=sigma, now_ms=now_ms,
                               warmup_1m=self._warm.get(ap.run_id, []))
        self._last_sim[ap.run_id] = res.to_dict()
        seen_fp = self._seen_fp.setdefault(ap.run_id, set())
        fps = [self._fingerprint(e) for e in res.events]
        missing = seen_fp - set(fps)
        if missing and not self._rewrite_noted.get(ap.run_id):
            self._rewrite_noted[ap.run_id] = len(missing)
            self._log(ap, "read_rewritten", f"{len(missing)} earlier read event(s) no longer appear in the recomputed read — "
                      "an input moved under it; events already acted on are never repeated, new ones still act", count=len(missing))
        new = [e for e, fp in zip(res.events, fps) if fp not in seen_fp]
        self._seen[ap.run_id] = len(res.events)
        halted = bool(self.engine.trading_halted(ap.config.portfolio_id))    # global switch OR this book's halt
        wm = self._decision_wm.get(ap.run_id)
        self._decision_wm[ap.run_id] = max(int(wm or 0), int(now_ms))
        for e in new:
            seen_fp.add(self._fingerprint(e))           # before handling: a failing event is dropped, the rest still act
            what = e["event"]
            if what in ("fire", "add", "trim", "exit") and wm is not None and int(e.get("ts") or 0) <= int(wm):
                # R3 (2026-09-14): this minute was already judged (decision at `wm`) and the event was not there —
                # a revision or a recovered hole surfaced it. It is a changed analytical conclusion, recorded here,
                # never a backdated order, add, trim or exit: the book's position stays under present-time
                # management (live trims, target breach, quote stop, clock flatten) and a setup price creates NOW
                # arrives as a new event with a current close.
                tid = f"{e.get('setup')}#{e.get('touch')}" if what == "fire" else str(e.get("setup") or "?")
                rec = {"sourceTs": int(e.get("ts") or 0), "judgedAt": int(wm), "decisionTs": int(now_ms), "instruction": what}
                self._log(ap, "backdated_signal_skip", f"{tid}: a {what} at {e.get('time') or e.get('ts')} surfaced by a revision "
                          f"after that minute was judged — recorded, not acted on (R3)", trigger=tid, **rec)
                if what == "fire":
                    self._record_unfilled(ap, tid)
                if journal:
                    await self.engine.journal.append(ev.TECHNIQUE_PLAN_TRIGGER_SKIPPED, {
                        "runId": ap.run_id, "symbol": ap.symbol, "trigger": tid, "event": "backdated_signal_skip", **rec,
                        "ts": e.get("ts"), "why": str(e.get("why") or "")}, aggregate_type="technique_run", aggregate_id=ap.run_id)
                continue
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
                                        "skip_reentries", "skip_last_entry", "skip_loss_cap",
                                        "skip_target_behind", "skip_target_collision", "model_out_of_band", "target_replanned",
                                        "skip_pm_room", "skip_target_near", "key_level_break", "key_level_setup",
                                        "key_level_flip", "key_level_rejected", "key_level_retired", "key_level_overruled",
                                        "key_level_pending", "key_level_retest", "fire_unfilled_live"):
                    # F28: the structural reads (a scenario, a PM break, a late touch) are not refusals —
                    # they get their own journal kind so skip counts mean skips
                    kind = ev.TECHNIQUE_PLAN_READ if (what in ("scenario", "pm_break", "late_touch", "pm_retest",
                                                               "model_out_of_band", "target_replanned", "fire_unfilled_live") or what.startswith("key_level_")) else ev.TECHNIQUE_PLAN_TRIGGER_SKIPPED
                    await self.engine.journal.append(kind, {
                        "runId": ap.run_id, "symbol": ap.symbol, "trigger": str(e.get("setup") or e.get("scenario") or what),
                        "event": what, "ts": e.get("ts"), "reason": e.get("why", "")},
                        aggregate_type="technique_run", aggregate_id=ap.run_id)
                    self._publish(ap, what)
        await self._guard_orphaned_positions(ap, res, bar, journal=journal)

    async def _guard_orphaned_positions(self, ap: ArmedPlan, res, bar: Bar, *, journal: bool) -> None:
        """G (2026-09-14): a book position the model no longer holds — its exit surfaced by a revision was recorded,
        not replayed (R3), or the read was rewritten under it — keeps the METHOD's present-time exit evaluation.
        On every 2m decision the S1 one-candle stop is judged on the CURRENT close against the line the entry
        leaned on (EMA13 / EMA48 / 200 EMA from the current regime, or the setup's level) and issued NOW with the
        current timestamp. Premium trims and the premium stop (live watch), the target breach, the quote stop and
        the 15:45 flatten stay on their own loops. No new threshold: the rule is session.py's S1, applied to the book."""
        if not journal:
            return
        open_pos = getattr(res, "open_position", None)
        held_setup = open_pos.get("setup") if isinstance(open_pos, dict) else None
        reg = getattr(res, "regime_last", None) or {}
        if not isinstance(reg, dict):
            reg = reg.to_dict() if hasattr(reg, "to_dict") else {}
        setups = getattr(res, "setups", None) or []
        for tr in list(ap.trades.values()):
            if tr.status != "open" or float(tr.remaining or 0) <= 0 or tr.pending_exit_qty > 1e-9 or tr.setup_id == held_setup:
                continue
            base = ap.trades.get(str(tr.trigger_id).split("+add")[0], tr)
            kind = getattr(base, "_entry_kind", None) or getattr(tr, "_entry_kind", None) or "ema"
            setup = next((x for x in setups if isinstance(x, dict) and x.get("id") == tr.setup_id), {})
            name, guard = {"ema": ("EMA13", reg.get("ema13")), "ema48": ("EMA48", reg.get("ema48")),
                           "ema200": ("200 EMA", reg.get("ema200"))}.get(kind, ("level", setup.get("anchor")))
            if guard is None:
                continue
            long = tr.direction == "long"
            through = (float(bar.close) < float(guard)) if long else (float(bar.close) > float(guard))
            if not through:
                continue
            why = (f"present-time S1: 2m close {float(bar.close):.2f} through the {name} {float(guard):.2f} on a position the "
                   f"model no longer holds — stop issued now (G)")
            self._log(ap, "orphan_stop", f"{tr.trigger_id}: {why}", trigger=tr.trigger_id, close=float(bar.close), guard=float(guard), line=name)
            await self._trail(ap, ev.TECHNIQUE_PLAN_READ, "orphan_stop", why, trigger=tr.trigger_id, decisionTs=int(time.time() * 1000),
                              barTs=bar.ts, close=float(bar.close), guard=float(guard), line=name)
            await self._exit(ap, tr, "stop", float(tr.remaining), journal=True, reason=why, force_market=True)

    async def _fire_from_event(self, ap: ArmedPlan, e: dict, bar: Bar, res, *, halted: bool, journal: bool) -> None:
        tid = f"{e.get('setup')}#{e.get('touch')}"
        if tid in ap.trades:
            return
        if ap.status == "paused":
            self._log(ap, "paused_skip", f"{tid}: conditions met but the plan is paused", trigger=tid, sourceTs=e.get("ts"))
            return
        # The kill switch blocks the MONEY modes. Alert mode places nothing (`_fire_rest` only
        # records `trade.status = "alert"`), so a halt on the shared portfolio — which another
        # technique's daily loss can engage — must not silence the desk's read of the tape: the
        # same rule the caps below and `_add_from_event`'s `would_add` already follow ("money
        # modes only; alert/proposal keep recording every read").
        if halted and ap.config.mode != "alert":
            why = self.engine.trading_halted(ap.config.portfolio_id) or "kill switch engaged"
            self._log(ap, "halt_skip", f"{tid}: conditions met but trading is halted on this book — {why}", trigger=tid, why=why,
                      sourceTs=e.get("ts"))
            return
        open_or_working = sum(1 for t in ap.trades.values() if t.status in ("fired", "submitting", "working", "open"))
        if ap.config.mode == "auto" and open_or_working >= max(1, ap.config.max_open_trades):
            self._log(ap, "max_open_skip", f"{tid}: fired but already holding {open_or_working}", trigger=tid, sourceTs=e.get("ts"))
            return
        # F29: the author trades ONE book — max_losses_per_day counts the whole desk (model losses across
        # every plan, plus real closed losers in money modes), not one budget per symbol
        rules_now = self.rules_for(ap)
        book = self._book(ap)
        if (ap.config.mode != "alert" and getattr(rules_now, "losses_desk_wide", True)
                and self.losses_across_plans(portfolio_id=book) >= int(rules_now.max_losses_per_day)):
            self._log(ap, "skip_loss_cap_desk",
                      f"{tid}: {self.losses_across_plans(portfolio_id=book)} losing trades across this book's plans today (max "
                      f"{rules_now.max_losses_per_day}, counted from the {self.losses_basis(portfolio_id=book)}) — done for the day (F29, per book)",
                      trigger=tid, sourceTs=e.get("ts"))
            if journal:
                await self.engine.journal.append(ev.TECHNIQUE_PLAN_TRIGGER_SKIPPED, {
                    "runId": ap.run_id, "symbol": ap.symbol, "trigger": tid, "event": "skip_loss_cap_desk",
                    "losses": self.losses_across_plans(portfolio_id=book), "max": int(rules_now.max_losses_per_day), "ts": e.get("ts"),
                    "portfolioId": book}, aggregate_type="technique_run", aggregate_id=ap.run_id)
                self._diag_shadow(ap, e, res, tid, "skip_loss_cap_desk")     # shadow: what the refused candidate's contracts did
            return
        # A12: SPY/QQQ/IWM fire together on index moves — one Team2 position across ALL its plans
        # (money modes only; alert/proposal keep recording every read)
        if ap.config.mode == "auto":
            cap = max(1, int(self.rules_for(ap).max_concurrent_positions))
            across = self.open_positions_across_plans(self._book(ap))
            if across >= cap:
                self._log(ap, "max_concurrent_skip",
                          f"{tid}: fired but this book already holds {across} Team2 position(s) across its plans (cap {cap}, A12, per book)",
                          trigger=tid, sourceTs=e.get("ts"))
                if journal:
                    await self.engine.journal.append(ev.TECHNIQUE_PLAN_TRIGGER_SKIPPED, {
                        "runId": ap.run_id, "symbol": ap.symbol, "trigger": tid, "event": "max_concurrent_positions",
                        "open": across, "max": cap, "ts": e.get("ts")},
                        aggregate_type="technique_run", aggregate_id=ap.run_id)
                    self._record_unfilled(ap, tid)          # R1: the book never held it
                    self._diag_shadow(ap, e, res, tid, "max_concurrent_skip")   # shadow: the blocked candidate's contracts
                return
        # R2 (2026-09-14): the read's clock is the bar's; the ORDER's clock is the wall. A signal recovered from a
        # delayed or replayed bar must not enter after the actual cutoff, outside its session, or when it is older
        # than `max_signal_age_min`. Recorded as a missed opportunity with source, receipt and decision times.
        if journal and ap.config.mode != "alert":
            stale = self._stale_signal(ap, e, rules_now)
            if stale is not None:
                self._log(ap, "stale_signal_skip", f"{tid}: {stale['why']}", trigger=tid, **{k: v for k, v in stale.items() if k != "why"})
                await self.engine.journal.append(ev.TECHNIQUE_PLAN_TRIGGER_SKIPPED, {
                    "runId": ap.run_id, "symbol": ap.symbol, "trigger": tid, "event": "stale_signal_skip", **stale,
                    "ts": e.get("ts")}, aggregate_type="technique_run", aggregate_id=ap.run_id)
                self._record_unfilled(ap, tid)              # R1: a zero-fill outcome outside the picker
                return
        direction = "long" if e.get("regime", {}).get("stack") == "bull" else "short"
        setup = next((s for s in res.setups if s["id"] == e.get("setup")), {})
        direction = setup.get("direction") or direction
        spot = float(e.get("spot") or bar.close)
        atr = float((e.get("regime") or {}).get("atr") or 0.0) or max(spot * 0.001, 0.05)
        # R13 (audit 2026-09-04): the ~2 s quote-stop watch reads `trade.stop`; a synthetic 1xATR stop let an
        # intra-minute spike market-sell a position the method (S1: a 2m CLOSE through the line) would keep.
        # Use the line the entry leaned on, one ATR further out than the model's close-based stop so the
        # quote watch is the crash brake, not the rule.
        rg = e.get("regime") or {}
        guard = {"ema": rg.get("ema13"), "ema48": rg.get("ema48"), "ema200": rg.get("ema200")}.get(str(e.get("entryKind")), setup.get("anchor"))
        try:
            guard_f = float(guard) if guard is not None else None
        except (TypeError, ValueError):
            guard_f = None
        if guard_f is None or (direction == "long" and guard_f >= spot) or (direction == "short" and guard_f <= spot):
            stop = spot - atr if direction == "long" else spot + atr
        else:
            stop = guard_f - atr if direction == "long" else guard_f + atr
        target, target_refusal = self.resolve_fire_target(e, setup, spot, direction, actionable=float(bar.close),
                                                          anchor=(setup.get("anchor") if getattr(rules_now, "target_identity_guard", True) else None),
                                                          tick=float(getattr(rules_now, "tick", 0.01) or 0.01))
        if target_refusal is not None:
            # F72: REFUSE, never enter targetless. See `resolve_fire_target`. 2026-09-17: a source-target collision is its
            # own decision kind — the setup's destination is the level it just broke, for every entry kind of the setup.
            kind_ = "skip_target_collision" if "source-target collision" in target_refusal else "skip_target_behind"
            self._log(ap, kind_, f"{tid}: {target_refusal}", trigger=tid, spot=spot, close=float(bar.close), anchor=setup.get("anchor"),
                      sourceTs=e.get("ts"))
            if journal:
                await self.engine.journal.append(ev.TECHNIQUE_PLAN_TRIGGER_SKIPPED, {
                    "runId": ap.run_id, "symbol": ap.symbol, "trigger": tid, "event": kind_,
                    "spot": spot, "close": float(bar.close), "anchor": setup.get("anchor"), "why": target_refusal, "ts": e.get("ts")},
                    aggregate_type="technique_run", aggregate_id=ap.run_id)
                self._record_unfilled(ap, tid)
            return
        trade = Trade(trigger_id=tid, kind=str(setup.get("kind") or "team2"), direction=direction, fired_ts=e["ts"],
                      window="team2", entry=spot, stop=stop, targets=[float(target)] if target else [],
                      fire_bar_index=ap.bar_index - 1, last_price=bar.close, instrument=ap.config.instrument,
                      multiplier=100.0 if ap.config.instrument == "options" else 1.0)
        trade._size_mult = float(e.get("sizeMult") or 1.0)        # read by size_multiplier via the contract
        trade._bucket = str(e.get("bucket") or "?")
        trade._entry_kind = str(e.get("entryKind") or "ema")      # G: the line the S1 one-candle stop is judged against
        trade._anchor = setup.get("anchor")                        # 2026-09-17: the setup's source level (diagnostics)
        trade.setup_id = str(e.get("setup"))
        trade.target_kind = str(e.get("targetKind") or "plan")
        ap.trades[tid] = trade
        self._diag_signal(ap, e, setup, trade, journal=journal)        # shadow: entry location + attempt context (2026-09-16)
        self._log(ap, "fired", f"{tid}: {e.get('why', '')}", trigger=tid, spot=spot, premiumModel=e.get("premium"),
                  strikeModel=e.get("strike"), modelBand=e.get("modelBand"), bucket=trade._bucket, early=e.get("early"), target=target,
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

    def _stale_signal(self, ap: ArmedPlan, e: dict, rules: Team2Rules) -> dict | None:
        """R2: None when the fire may be acted on NOW; else the record of why not (source/receipt/decision times)."""
        now = int(time.time() * 1000)
        src = int(e.get("ts") or 0)
        now_et = dt.datetime.fromtimestamp(now / 1000, ET)
        rec = {"sourceTs": src, "decisionTs": now, "ageMs": now - src}
        if now_et.strftime("%Y-%m-%d") != ap.plan_for:
            return {**rec, "why": f"signal from {ap.plan_for} judged on {now_et.strftime('%Y-%m-%d')} — not this session (R2)"}
        m = now_et.hour * 60 + now_et.minute
        if m >= int(rules.last_entry_min):
            return {**rec, "why": f"the entry cutoff ({rules.last_entry_min // 60:02d}:{rules.last_entry_min % 60:02d}) had passed at "
                                  f"decision time {now_et.strftime('%H:%M:%S')}; the signal's bar closed {(now - src) // 1000}s earlier (R2)"}
        max_age = int(rules.max_signal_age_min) * 60_000
        if max_age > 0 and now - src > max_age:
            return {**rec, "why": f"the signal's bar closed {(now - src) // 1000}s ago (> {rules.max_signal_age_min} min): a recovered "
                                  f"bar is analytical state, not an order (R2)"}
        return None

    async def _exit_from_event(self, ap: ArmedPlan, e: dict, *, journal: bool) -> None:
        # the simulation names the setup via the position; every trade of that setup (the entry and its
        # X5 adds) gets the same instruction — the position that just (partly) closed is either the
        # open one or the last trade
        sim = self._last_sim.get(ap.run_id) or {}
        pos = sim.get("openPosition") or (sim.get("trades") or [{}])[-1]
        setup_id = e.get("setup") or pos.get("setup")           # R7: the event names its setup since 2026-09-04
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
                need = self.rules_for(ap).trim_1_pct if level == 1 else self.rules_for(ap).trim_2_pct
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

    async def _reprice_stuck_exits(self, ap: ArmedPlan) -> None:
        from ...execution.exits import EXIT_REPRICE_BARS, stale_working_exit
        for tr in list(ap.trades.values()):
            if tr.status != "open" or tr.remaining <= 0:
                continue
            stale = stale_working_exit(tr, ap.bar_index - 1, reprice_bars=EXIT_REPRICE_BARS)
            if stale is None:
                continue
            with contextlib.suppress(Exception):
                await self.engine.orders.cancel(stale["orderId"])
            stale["status"] = "CANCELLED"
            self._log(ap, "exit_reprice", f"{tr.trigger_id}: {stale['kind']} not filled in {EXIT_REPRICE_BARS} bars — re-sending at market",
                      trigger=tr.trigger_id, kind=stale["kind"])
            await self._exit(ap, tr, stale["kind"], float(stale.get("qty") or tr.remaining), journal=True, force_market=True)

    async def _end_session(self, ap: ArmedPlan, *, journal: bool, reason: str = "session closed") -> None:
        """Nothing of a 0DTE book survives the close: flatten on the way out, then the shared close."""
        if journal and ap.status in ("armed", "paused"):
            with contextlib.suppress(Exception):
                await self._clock_flatten(ap, self.rules_for(ap))
        await super()._end_session(ap, journal=journal, reason=reason)

    async def _clock_flatten(self, ap: ArmedPlan, rules: Team2Rules) -> None:
        """Flatten every open Team2 trade and cancel every working entry at flatten_min, once.

        F106 (2026-09-10): the flatten used to log ONLY per trade, so on a day the desk ended flat
        it left no trace at all — "the flatten ran and found nothing" and "the flatten never ran"
        looked identical in the record. It runs on every bar from flatten_min, so the note is
        once per run, and it says what it found.
        """
        flat_hhmm = f"{rules.flatten_min // 60:02d}:{rules.flatten_min % 60:02d}"
        if ap.run_id not in self._flatten_noted:
            self._flatten_noted.add(ap.run_id)
            n_open = sum(1 for t in ap.trades.values() if t.status == "open" and t.remaining > 0)
            n_work = sum(1 for t in ap.trades.values() if t.status == "working" and t.entry_order_id)
            what = (f"closing {n_open} open and cancelling {n_work} working" if (n_open or n_work)
                    else "the book is already flat — nothing to close")
            self._log(ap, "clock_flatten", f"flatten time {flat_hhmm} ET reached — {what} (C3/D-1)",
                      openTrades=n_open, workingTrades=n_work)
        for tr in list(ap.trades.values()):
            if tr.status == "working" and tr.entry_order_id:
                with contextlib.suppress(Exception):
                    await self.engine.orders.cancel(tr.entry_order_id)
                tr.status = "cancelled"
                tr.reason = "flatten time — working entry cancelled (C3)"
                self._log(ap, "clock_flatten", f"{tr.trigger_id}: working entry cancelled at the flatten time", trigger=tr.trigger_id)
            elif tr.status == "open" and tr.remaining > 0 and tr.pending_exit_qty <= 1e-9:
                self._log(ap, "clock_flatten", f"{tr.trigger_id}: flatten time {flat_hhmm} ET — "
                          f"selling {tr.remaining:g} at market whatever the read says (C3/D-1)", trigger=tr.trigger_id)
                await self._exit(ap, tr, "flatten", tr.remaining, journal=True, force_market=True,
                                 reason="flatten: 0DTE flatten time reached on the clock (C3/D-1)")

    # ------------------------------------------------------------- the fire's target (F72)
    def resolve_fire_target(self, e: dict, setup: dict, spot: float,
                            direction: str, *, actionable: float | None = None, anchor: float | None = None,
                            tick: float = 0.01) -> tuple[float | None, str | None]:
        """The target a live trade will carry, or the reason to REFUSE the fire. Never both.

        `e["target"]` is the read's own resolved-and-validated target. The fallback to
        `setup["target"]` covers a fire that carried none — a restored or replayed event, a plan
        whose target was rewritten under a running session — and that fallback is the one path by
        which a target the read never judged can reach a live trade. It matters because
        `target_breach` runs on the ~2 s quote watch (planrunner 2b): a target at or behind the
        fill sells the whole position on the FIRST live print, before a single 2m bar closes.

        An invalid target is **never coerced to None**. Doing that would turn "this trade has no
        room" into permission to enter WITHOUT a target — a *weaker* outcome than the refusal the
        read already applies to the same condition, and a silent one. Invalid means refused, at
        both layers, so the baseline holds wherever the fire came from.

        A genuinely ABSENT target (no target on the fire and none on the setup) is a different
        thing and stays allowed: the read validated that shape, and the candle stop, premium stop,
        trims and the 15:45 flatten manage the trade. Entry-side only — a target already on an
        OPEN trade is never rewritten here.

        F91 (2026-09-10): a fire stamped `targetKind == "none"` is a THIRD shape, and it is not an
        absent target — it is the read's F81b decision that no structure is left ahead of this entry
        (`session.py`, the one place that stamps it). The setup keeps its stale planned target, so
        without this the fallback resurrects exactly the number the read just replanned away from and
        refuses the entry the read authorised. Live SPY 2026-09-10 10:06 ET: the read fired a 756 put
        and the runner logged `skip_target_behind` on the 757.90 the read had already dropped, which
        made F81b unreachable in live trading and unmeasurable against replay. Honour the read's
        verdict; the trims, the candle stop, the premium stop and the 15:45 flatten manage the trade,
        which is the same shape the branch above already blesses.
        """
        target, src = e.get("target"), "fire"
        if target is None and str(e.get("targetKind") or "") != "none":
            target, src = setup.get("target"), "setup"
        if target is None:
            return None, None                    # no target anywhere: the shape the read allowed
        try:
            t = float(target)
        except (TypeError, ValueError):
            return None, f"target {target!r} carried by the {src} is not a number — refusing the entry (F72)"
        # 2026-09-17 (QQQ 13:10): the destination must be distinct from the setup's source level — judged FIRST so the EMA
        # entry (target a hair above its line) and the level entry (target == its line) of one setup are refused alike.
        if anchor is not None and abs(t - float(anchor)) <= max(float(tick or 0.0), 0.0):
            _, why_ = destination_check(t, anchor, None, None, direction, tick)
            return None, f"{why_} (target from the {src})"
        if not target_is_ahead(t, spot, direction):
            side = "above" if direction == "short" else "below"
            return None, (f"target {t:.2f} (from the {src}) is {side} the {spot:.2f} entry — no room left, so the "
                          f"trade would exit on its first bar or its first live print; refusing the entry "
                          f"rather than entering with no target at all (F72)")
        # …and beyond that level and ahead of the current actionable price. No distance threshold: identity and order
        # only. A collision is refused, never re-planned or silently dropped.
        kind_, why_ = destination_check(t, anchor, None, actionable, direction, tick)
        if kind_ is not None:
            return None, f"{why_} (target from the {src})"
        return t, None

    # ------------------------------------------------------------- live premium (money modes)
    def target_breach(self, tr: Trade, last: float) -> str | None:
        """F50 (2026-09-08): the plan target is an UNDERLYING condition. The first fresh print at or through
        it sells the rest as a reduce-only limit at the contract's fresh bid (the shared `_exit` path; a
        resting unfilled limit is re-priced to market by `_reprice_stuck_exits`, duplicates are prevented by
        `pending_exit_qty`, partial fills reduce `remaining`). The model books the same exit at its mark on
        the touching bar and labels it `target_touch_intrabar` — replay is a claim, the book is the record."""
        if tr.instrument != "options" or not tr.targets or tr.remaining <= 0 or tr.status != "open":
            return None
        try:
            tgt = float(tr.targets[0])
        except (TypeError, ValueError):
            return None
        hit = last >= tgt if tr.direction == "long" else last <= tgt
        if not hit:
            return None
        return (f"target {tgt:.2f} touched on the live print {last:.2f} — selling the remaining {tr.remaining:g} at the "
                "contract's fresh bid (X3/V11, F50)")

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
        rules = self.rules_for(ap)
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
            why = "the plan is paused" if ap.status == "paused" else f"trading is halted on this book — {self.engine.trading_halted(ap.config.portfolio_id) or 'kill switch engaged'}"
            self._log(ap, "add_skip", f"{base.trigger_id}: add wanted but {why}", trigger=base.trigger_id, why=why)
            return
        if base.remaining <= 0 or base.instrument != "options" or not base.contract or frac <= 0:
            return
        # R2 (2026-09-14): an add increases exposure — it obeys the same session / cutoff / freshness rule as a fire
        # at its origin, and the shared entry gate again at the order boundary (it rides a cached contract, so the
        # picker's re-check never sees it)
        stale = self._stale_signal(ap, e, self.rules_for(ap))
        if stale is not None:
            self._log(ap, "stale_signal_skip", f"{tid}: add {stale['why']}", trigger=tid, **{k: v for k, v in stale.items() if k != "why"})
            await self.engine.journal.append(ev.TECHNIQUE_PLAN_TRIGGER_SKIPPED, {
                "runId": ap.run_id, "symbol": ap.symbol, "trigger": tid, "event": "stale_signal_skip", "instruction": "add", **stale,
                "ts": e.get("ts")}, aggregate_type="technique_run", aggregate_id=ap.run_id)
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
        if mode in ("auto", "proposal"):
            # R1 (2026-09-14): a money-mode plan is judged by its BOOK — filled, closed losers only. A refused
            # or deferred attempt (no order, no fill) is not a loss; neither is a routed order that never
            # filled. The model ledger never spends a Practice loss allowance (F125). Before this the model
            # counted until the first order was routed, so a zero-fill day could reach the two-loss cap.
            # R5: an X5 add rides the same position as its base trade — judge the POSITION
            groups: dict[str, list] = {}
            for t in trades:
                if float(getattr(t, "filled_qty", 0) or 0) > 0:
                    groups.setdefault(str(t.trigger_id).split("+add")[0], []).append(t)
            losers = sum(1 for ts in groups.values() if all(t.status == "closed" for t in ts) and sum(t.realized_pnl for t in ts) < 0)
            return losers, "book"
        return sum(1 for t in ((sim or {}).get("trades") or []) if not t.get("win")), "model"

    def losses_across_plans(self, day: str | None = None, portfolio_id: str | None = None) -> int:
        """F29/F37/F38: losing trades today across the desk — since 2026-09-15 PER BOOK when a book is given (the
        parallel Practice experiments keep their loss counters independent; the author's "one book" is one
        Practice book). Armed plans are counted live; a plan that disarmed (its own loss halt) keeps its losses in
        the day's tally — the cap must not loosen after the worst outcome a plan can have. Seeded at boot."""
        day = day or dt.datetime.now(ET).strftime("%Y-%m-%d")
        tally = self._loss_tally.setdefault(day, {})
        for ap in self._armed.values():
            n, basis = self._plan_losses(ap.config.mode, list(ap.trades.values()), self._last_sim.get(ap.run_id))
            tally[ap.run_id] = (n, basis, self._book(ap))
        for d in [k for k in self._loss_tally if k != day]:
            self._loss_tally.pop(d, None)
        return sum(n for n, _, pid in tally.values() if portfolio_id is None or pid == portfolio_id)

    def losses_basis(self, day: str | None = None, portfolio_id: str | None = None) -> str:
        day = day or dt.datetime.now(ET).strftime("%Y-%m-%d")
        bases = {b for _, b, pid in self._loss_tally.get(day, {}).values() if portfolio_id is None or pid == portfolio_id}
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
            n = 0
            for t in trades:
                if float(t.get("filledQty") or 0) <= 0:
                    continue
                if t.get("status") == "closed" and float(t.get("realizedPnl") or 0) < 0:
                    n += 1
                    continue
                # a pre-F40 record: the flatten filled but the plan never heard — judge it by its exit fills
                fills = [x for x in (t.get("exits") or []) if x.get("status") == "FILLED" and x.get("price") is not None]
                if t.get("status") == "open" and fills and t.get("avgFill"):
                    pnl = sum((float(x["price"]) - float(t["avgFill"])) * float(x.get("filledQty") or 0) for x in fills) * 100.0
                    if pnl < 0:
                        n += 1
            if n:
                tally[row.run_id] = (n, "book", row.portfolio_id)
                seeded += n
            # R3: the retired plan's net P&L keeps counting toward the technique day-loss halt
            net = 0.0
            for t in trades:
                fq = float(t.get("filledQty") or 0)
                if fq <= 0:
                    continue
                exited = sum(float(x.get("filledQty") or 0) for x in (t.get("exits") or []))
                fee = float(self.rules().fee_per_contract) * (fq + exited)
                net += float(t.get("realizedPnl") or 0) - fee
            if net:
                rk = (day, row.portfolio_id)
                self._retired_pnl[rk] = self._retired_pnl.get(rk, 0.0) + net
        return seeded

    def open_positions_across_plans(self, portfolio_id: str | None = None) -> int:
        """Open or in-flight Team2 trades across every armed plan (A12 concurrency cap) — per BOOK when given."""
        return sum(1 for ap in self._armed.values() for t in ap.trades.values()
                   if (portfolio_id is None or self._book(ap) == portfolio_id)
                   and t.status in ("fired", "submitting", "working", "open") and not getattr(t, "is_add", False))

    # ------------------------------------------------------------- the day's scorecard (F43)
    def _score_execution(self, ap: ArmedPlan) -> dict | None:
        """Team2 has no TriggerTrackers, so the shared scorecard was structurally empty (F43). The
        day's record is the session read's model trades against what the book actually did — and the
        skips that stood between them. Same journal shape as the shared one (rows / matched /
        theoreticalFires / actualFires / realizedPnl) plus Team2's own fields."""
        sim = self._last_sim.get(ap.run_id) or {}
        model = list(sim.get("trades") or [])
        real = [t for t in ap.trades.values() if float(t.filled_qty or 0) > 0]
        # R5 (2026-09-14): every ATTEMPT is on the record, not only the fills — a refused contract is the decisive
        # reason a model trade was not taken, and it must survive the close, a restart and the capped event list
        verdicts = getattr(self, "_contract_verdicts", {}).get(ap.run_id) or []
        by_trigger: dict[str, dict] = {}
        verdict_count: dict[str, int] = {}
        for v in verdicts:
            k = str(v.get("trigger"))
            by_trigger[k] = v                                         # the LAST verdict for a trigger is its final one
            verdict_count[k] = verdict_count.get(k, 0) + 1            # … the count keeps the retries visible
        attempts = [t for t in ap.trades.values() if float(t.filled_qty or 0) <= 0 and not getattr(t, "is_add", False)]
        # R5 (follow-up): attempt IDENTITIES come from the durable verdicts, then the trade projection is joined — a
        # verdict journaled before the projection was persisted (a crash in between) is still an attempt, reported
        # as journal-only evidence rather than silently counted as zero
        known = {str(t.trigger_id) for t in ap.trades.values()}
        journal_only = []
        for k, v in by_trigger.items():
            if k in known or k == "None":
                continue
            journal_only.append(SimpleNamespace(
                trigger_id=k, setup_id=k.split("#")[0], status="unknown", order_symbol=v.get("symbol") if str(v.get("symbol") or "") != ap.symbol else None,
                reason="journal-only: the trade projection was never persisted", errors=[], fired_ts=int(v.get("ts") or 0),
                entry_order_id=None, filled_qty=0.0, is_add=False, _journal_only=True))
        attempts += journal_only
        rows = []
        matched = 0
        used: set[str] = set()

        def _attempt_row(t) -> dict:
            v = by_trigger.get(str(t.trigger_id)) or {}
            kind = ("policy_refusal" if v.get("verdict") == "refused" else "transient_deferral" if v.get("verdict") == "deferred"
                    else "order_rejected" if t.status in ("failed", "cancelled", "rejected") and getattr(t, "entry_order_id", None)
                    else "not_sent")
            return {"trigger": t.trigger_id, "status": t.status, "attemptKind": kind, "contract": t.order_symbol,
                    "verdict": v.get("verdict"), "verdictStage": v.get("stage"), "verdictCount": verdict_count.get(str(t.trigger_id), 0),
                    "decisiveReason": v.get("reason") or t.reason or (t.errors[-1] if t.errors else None),
                    "examined": v.get("examined"), "livePrice": ({"bid": v.get("bid"), "ask": v.get("ask")} if v.get("ask") is not None else None),
                    "evidence": "journal-only" if getattr(t, "_journal_only", False) else "projection"}

        for mt in model:
            cands = [t for t in real if t.setup_id == mt.get("setup") and t.trigger_id not in used]
            hit = min(cands, key=lambda t: abs(int(t.fired_ts or 0) - int(mt.get("entryTs") or 0)), default=None)
            att = None
            if hit is None:
                acands = [t for t in attempts if t.setup_id == mt.get("setup") and t.trigger_id not in used]
                att = min(acands, key=lambda t: abs(int(t.fired_ts or 0) - int(mt.get("entryTs") or 0)), default=None)
            if hit is not None:
                used.add(hit.trigger_id)
                matched += 1
            elif att is not None:
                used.add(att.trigger_id)
            row = {"setup": mt.get("setup"), "entryTs": mt.get("entryTs"), "entryKind": mt.get("entryKind"),
                   "modelStrike": mt.get("strike"), "modelPremium": mt.get("entryPremium"),
                   "modelPnlPct": mt.get("pnlPct"), "modelExit": mt.get("exitReason"),
                   "trigger": hit.trigger_id if hit else (att.trigger_id if att else None),
                   "status": hit.status if hit else (att.status if att else "not taken"),
                   "avgFill": hit.avg_fill if hit else None, "qty": hit.filled_qty if hit else None,
                   "realizedPnl": round(hit.realized_pnl - self._fees_paid(hit), 2) if hit else None,
                   "contract": hit.order_symbol if hit else (att.order_symbol if att else None),
                   "note": ("" if hit else ("attempted, not filled — see attempt" if att else "model trade not taken by the book (see skips)"))}
            if att is not None:
                row["attempt"] = _attempt_row(att)
            rows.append(row)
        for t in attempts:
            if t.trigger_id not in used:
                rows.append({"setup": t.setup_id, "entryTs": t.fired_ts or None, "trigger": t.trigger_id, "status": t.status,
                             "qty": 0.0, "contract": t.order_symbol, "realizedPnl": 0.0, "attempt": _attempt_row(t),
                             "note": ("journaled verdict without a trade projection — incomplete evidence, not zero"
                                      if getattr(t, "_journal_only", False)
                                      else "attempted where the read (as recomputed now) shows no model trade")})
        for t in real:
            if t.trigger_id not in used:
                rows.append({"setup": t.setup_id, "entryTs": t.fired_ts, "trigger": t.trigger_id, "status": t.status,
                             "avgFill": t.avg_fill, "qty": t.filled_qty, "contract": t.order_symbol,
                             "realizedPnl": round(t.realized_pnl - self._fees_paid(t), 2),
                             "note": "the book traded where the read (as recomputed now) did not"})
        # 2026-09-16 (EOD review P2): the refusal funnel comes from the durable decision ledger — one entry per candidate
        # (event, setup, source minute), revisions kept as versions — never from the capped display buffer. A plan
        # restored from a release without the ledger falls back to the buffer, de-duplicated by the same rule.
        ledger = self._ledger_of(ap.run_id) or diag.ledger_from_events(ap.events)
        skips = diag.unique_counts(ledger)
        # D1 (2026-09-16 review): the SHADOW summary is isolated from core scoring and closure — a fault in it is
        # recorded as a diagnostic-incomplete record, and P&L, funnel and disarm proceed regardless
        diag_recs: list[dict] = []
        diagnostics = None
        try:
            diag_recs = list((self.__dict__.get("_diag", {}).get(ap.run_id) or {}).get("attempts", {}).values())
            for rec in diag_recs:                               # the routing facts as they stand at the close
                t = ap.trades.get(rec.get("trigger"))
                if t is not None:
                    rec["routing"] = self._diag_routing(t, self._fees_paid(t))
            fee = float(getattr(self.rules_for(ap), "fee_per_contract", 0) or 0)
            diagnostics = diag.summarize_day(diag_recs, fee) if diag_recs else None
        except Exception as exc:  # noqa: BLE001
            log.warning("team2 diagnostic summary failed for %s: %s", ap.run_id, exc)
            diagnostics = {"status": "error", "error": str(exc)[:300], "attempts": len(diag_recs),
                           "note": "shadow summary incomplete; core P&L, funnel and closure are unaffected"}
        # the durable funnel (from the verdict list, which the journal backs — not the capped event list)
        opportunities = {str(t.trigger_id) for t in attempts} | {str(t.trigger_id) for t in real}
        funnel = {"attempts": len(opportunities), "filled": len(real), "verdicts": len(verdicts), "journalOnly": len(journal_only),
                  "policyRefused": sum(1 for v in by_trigger.values() if v.get("verdict") == "refused"),
                  "transientDeferred": sum(1 for v in by_trigger.values() if v.get("verdict") == "deferred"),
                  "picked": sum(1 for v in by_trigger.values() if v.get("verdict") == "picked"),
                  "bookLosses": self._plan_losses(ap.config.mode, list(ap.trades.values()), sim)[0]}
        net = round(sum(t.realized_pnl - self._fees_paid(t) for t in ap.trades.values()), 2)
        return {"technique": self.TECHNIQUE_ID, "planFor": ap.plan_for, "basis": "session-read vs book", "funnel": funnel,
                "theoreticalFires": len(model), "actualFires": len(real), "matched": matched,
                "modelPnlPctSum": round(sum(float(mt.get("pnlPct") or 0) for mt in model), 2),
                "realizedPnl": net, "realizedPnlGross": round(sum(t.realized_pnl for t in ap.trades.values()), 2),
                "skips": skips, "skipRows": diag.row_counts(ledger), "decisions": diag.decisions_view(ledger),
                "rows": rows, "correctedHistory": True,
                "decisionTime": [dict(r["decisionTime"]) for r in diag_recs if isinstance(r, dict) and r.get("decisionTime")],
                "diagnostics": diagnostics,
                "views": {"rows": "corrected history: the read as recomputed on the final tape vs the book",
                          "decisionTime": "decision time: what the desk knew at each fire (immutable; inputs identified)",
                          "skips": "unique decisions from the durable ledger", "skipRows": "raw log rows (revisions counted)",
                          "diagnostics": "shadow measurements (entry location, attempts, contract alternatives after costs)"},
                "bias": (sim.get("bias") or {}).get("label"),
                "stopReason": ap.stop_reason or None}

    async def disarm(self, run_id: str, *, reason: str = "manual", flatten: bool = False) -> bool:
        """A plan that leaves mid-session (loss halt) is scored on the way out — the close never
        reaches it (F43)."""
        ap = self._armed.get(run_id)
        if ap is not None and ap.scorecard is None and ap.config.mode != "alert":
            with contextlib.suppress(Exception):
                ap.scorecard = self._score_execution(ap)
                if ap.scorecard:
                    await self.engine.journal.append(ev.TECHNIQUE_PLAN_SCORED, {"runId": ap.run_id, "symbol": ap.symbol,
                                                                              **ap.scorecard},
                                                     aggregate_type="technique_run", aggregate_id=ap.run_id,
                                                     portfolio_id=ap.config.portfolio_id)
        return await super().disarm(run_id, reason=reason, flatten=flatten)

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
        rules_now = self.rules_for(ap)
        d["trailGaps"] = self.trail_gaps(ap.run_id)      # cohort v2: failed audit writes are shown, never hidden
        plan = ap.plan or {}
        read = self._last_sim.get(ap.run_id) or {}
        q = self.engine.quotes.get(ap.symbol)
        last = float(q.last) if q is not None and q.last and q.last > 0 else None
        zones = plan.get("zones") or {}
        pdh, pdl = zones.get("pdh") or {}, zones.get("pdl") or {}
        trig: list[dict] = []

        def pseudo(tid: str, label: str, kind: str, status: str, entry: float | None, direction: str,
                   targets: list[float] | None = None, stop: float | None = None) -> dict:
            now_m = dt.datetime.now(ET).hour * 60 + dt.datetime.now(ET).minute
            row = {"id": tid, "label": label, "kind": kind, "status": status, "entry": entry, "stop": stop,
                   "targets": targets or [], "riskReward": None, "firedTs": None, "firedWindow": None,
                   "observedMidday": 0, "skipped": [], "gapUnchecked": False, "failedBreaks": 0, "grade": None,
                   "gradeScore": None, "conditions": None, "setupId": None, "direction": direction,
                   "levelTouches": None, "levelAge": None,
                   "windowOpenNow": rules_now.first_entry_min <= now_m < rules_now.last_entry_min}
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
        bias_dir = ((read.get("bias") or {}).get("direction")) if read else None
        for s in setups:
            label = (f"{s['kind'].replace('_', ' ')} at {s['anchor']:.2f} — buying the EMA13 pullbacks "
                     f"({'call' if s['direction'] == 'long' else 'put'}s), touches {s['touches']}")
            if bias_dir and s["direction"] != bias_dir and not s.get("dead"):
                # F123 (2026-09-14): `session.py` only ever selects a setup in the CURRENT bias direction, so a
                # PM break the other way (SPY/IWM pm_break_up under scenario 4) cannot take an entry until a
                # 15m close flips the bias. Say so on the label — the status stays `waiting` because the
                # Armed page treats status as a closed set (an unknown value renders as a failure badge).
                label += f" — inert while the bias is {'puts' if bias_dir == 'short' else 'calls'}: needs a bias flip (B1)"
            status = ("invalidated" if s.get("dead") else "fired" if (s["id"] in fired_setups or (open_pos and open_pos.get("setup") == s["id"]))
                      else "observed" if s.get("touches") else "waiting")
            trig.append(pseudo(s["id"], label, s["kind"], status, s.get("anchor"), s["direction"],
                               [s["target"]] if s.get("target") else []))
        if trig:
            d["triggers"] = trig
        # summary in the method's words
        regime = read.get("regimeLast") or {}
        bias = read.get("bias") or {}
        # F66 (2026-09-08, run 30): at 15:33 ET all three rows still read "waiting for the 1st/2nd 2m
        # pullback into the EMA13" although `session.py` had already minted `skip_last_entry` at 15:32 —
        # nothing can be entered after 15:30 (D6) and the book is flat at 15:45 (C3). The trigger rows
        # already carried `windowOpenNow: false`; the one line the Armed page and the phone show did not,
        # so the desk read as if the next EMA13 touch were still live. Same class as F53/F57/F60:
        # descriptive only — the cutoff itself lives in session.py. Taken from the session's own event
        # rather than the wall clock, so a replay of the day says exactly the same thing.
        entries_closed = any(e.get("event") == "skip_last_entry" for e in (read.get("events") or []))
        past_flatten = bool(ap.last_bar_ts) and minute_of_day(ap.last_bar_ts) + 1 >= rules_now.flatten_min
        last_hhmm = f"{rules_now.last_entry_min // 60:02d}:{rules_now.last_entry_min % 60:02d}"
        flat_hhmm = f"{rules_now.flatten_min // 60:02d}:{rules_now.flatten_min % 60:02d}"
        closed_s = ("" if not entries_closed else
                    "the desk is flat for the day (C3)" if past_flatten else
                    f"past {last_hhmm} — no new entries today, flat by {flat_hhmm} (D6/C3)")
        if ap.status in ("expired", "disarmed"):
            pass                                          # the base summary already says so
        elif ap.status == "paused":
            d["summary"] = "paused — reading, not firing"
        elif open_pos:
            guard = {"ema": "EMA13", "ema48": "EMA48", "ema200": "200 EMA"}.get(str(open_pos.get("entryKind")), "level")
            tgt = open_pos.get("target")
            tgt_word = {"hod": "high/low of day", "replan": "re-planned level"}.get(
                str(open_pos.get("targetKind")), "planned level")
            tgt_s = (f", target {tgt:.2f} ({tgt_word})"
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
            flat_s = f" · sold at {flat_hhmm} whatever the read says (C3/D-1)" if entries_closed and not past_flatten else ""
            d["summary"] = (f"in trade {open_pos.get('setup')}: {'call' if open_pos.get('call') else 'put'} {strike_s}, "
                            f"{open_pos.get('remaining', 1):.2f} left{adds_s}, model peak +{open_pos.get('peakPct', 0):.0f}%{tgt_s} — "
                            f"stop is a 2m close through the {guard}{live_s}{flat_s}")
        elif bias.get("scenario"):
            live = [s for s in setups if not s.get("dead")]
            # F24: report the allowance of the setup the session would actually enter — `session.py` takes the
            # NEWEST live setup in the bias direction, so a spent setup pointing the other way (SPY's
            # pm_break_down on 2026-09-04) must not be read as touches already used on this one.
            cands = [s for s in live if not bias.get("direction") or s.get("direction") == bias.get("direction")]
            picked = sorted(cands, key=lambda s: s.get("confirmedTs") or 0)[-1] if cands else None
            touches = picked.get("touches", 0) if picked else max((s.get("touches", 0) for s in live), default=0)
            # F53 (2026-09-08): E3/B9 (stack must agree) and E4 (no braided EMAs) are re-judged on every 2m
            # bar, so `session.py` skips them SILENTLY — no event is minted. That left a trigger the regime
            # cannot fire reading exactly like one the next EMA13 touch would take (QQQ 10:30 today: bias
            # flipped to scenario 3 → calls while the stack was still bear). Say it on the one line the
            # Armed page and the phone show. Purely descriptive — the gate itself lives in session.py.
            want = "bull" if bias.get("direction") == "long" else "bear"
            blocks = []
            if regime.get("stack") and regime.get("stack") != want:
                blocks.append(f"the stack turns {want}")
            if regime.get("fan") == "chop":
                blocks.append("the EMAs un-braid")
            if blocks:
                flush_s = (", or a 200 EMA flush (T8)"
                           if bias.get("rangeDay") and getattr(rules_now, "allow_ema200_flush", True) else "")
                blocked_s = f" — no entry until {' and '.join(blocks)} (E3/B9/E4){flush_s}"
            else:
                blocked_s = ""
            # F57 (2026-09-08): the "not a tradeable location" gates DO mint an event, but only once per
            # setup (F23) and only into the read — the one line the Armed page and the phone show still
            # said "waiting for the 1st/2nd 2m pullback (touches 0)" while every pullback was being turned
            # away at the door. Today it bit all three symbols (SPY 10:00, QQQ 10:16 + 11:00, IWM 11:26):
            # with a pre-market range 9–12× ATR wide the no-trade zone is not a moment price passes
            # through, it is the day. `_skipped` is the setup's CURRENT refusal — a real touch clears it —
            # so it can be stated in the present tense. Descriptive only; the gates live in session.py.
            # F59 (2026-09-08): `skip_no_contract` was already in the journal list above but never
            # reached this line — session.py recorded it with `note`, so the setup's `_skipped` stayed
            # None. IWM's 13:30 PM-break retest was refused on the MODELLED premium (296C $0.199 vs the
            # $0.20 floor) while the real 296C was 0.24/0.25, and the headline said only "touches 1".
            floor_s = getattr(rules_now, "premium_floor", 0.20)
            targ_s = getattr(rules_now, "target_premium", 0.60)
            # F82 (2026-09-09): the band's upper edge is 1.5x the target, not the target — saying
            # "$0.20–$0.60" understated the accepted range by 50%.
            band_s = targ_s * MAX_OVER_TARGET
            skip_why = {"skip_no_trade_zone": "the last pullback sat inside the pre-market range — no-trade zone (V6/B5)",
                        "skip_range_confirmation": "range day: price has not cleared the PM level (B3/A4)",
                        "skip_no_contract": f"the last pullback found no strike MODELLING ${floor_s:.2f}–${band_s:.2f} "
                                            f"(target ${targ_s:.2f}, V1) — modelled premium, not the live chain",
                        # F72 (2026-09-09): the same F57/F59 lesson — a refusal the headline never
                        # states is a refusal the desk cannot see. This one holds for the rest of the
                        # session unless price comes back through the level.
                        "skip_target_behind": "the planned target is already behind price — no room left "
                                              "on this setup, so an entry would exit on its next bar (F72)"}
            refused = skip_why.get(str((picked or {}).get("skipped") or ""), "")
            refused_s = f" · {refused}" if refused else ""
            # F60 (2026-09-08): once a setup has spent its D9 allowance every further touch is watch-only,
            # so "waiting for the 1st/2nd 2m pullback" is not what the desk is doing — IWM read
            # "waiting for the 1st/2nd 2m pullback into the EMA13 (touches 8)" while its pm_break_up@13:15
            # could not enter again today. Say whose touches they are and that they are spent. The count
            # comes from `picked`, which is often NOT the setup the scenario label names (F24), so name it.
            max_touch = int(getattr(rules_now, "pullback_max_touches", 2) or 2)
            if entries_closed:
                # F66: nothing is waiting on a pullback any more, and "no entry until the stack turns
                # bull" / "the last pullback sat inside the range" are answers to a question the clock
                # has already closed — drop them with it.
                state_s, blocked_s, refused_s = closed_s, "", ""
            elif picked and touches >= max_touch:
                state_s = (f"{picked.get('id')}: its first {max_touch} pullbacks are spent (touches {touches}) — "
                           "further touches are watch-only (D9/P6)")
            else:
                state_s = f"waiting for the 1st/2nd 2m pullback into the EMA13 (touches {touches})"
            d["summary"] = (f"scenario {bias['scenario']} ({bias.get('label')}) → {'calls' if bias.get('direction') == 'long' else 'puts'} · "
                            f"{state_s} · EMA stack {regime.get('stack', '?')}, "
                            f"{regime.get('fan', '?')}{blocked_s}{refused_s}")
        elif pdh and pdl:
            pm = (f" · PM {plan['pml']:.2f}–{plan['pmh']:.2f}" if plan.get("pmh") and plan.get("pml") else " · pre-market range at 09:25")
            day = f" · {str(plan.get('dayType')).replace('_', ' ')} day" if plan.get("dayType") else ""
            d["summary"] = (f"no scenario yet — needs a 15m close above {pdh.get('top', 0):.2f} (calls) or below "
                            f"{pdl.get('bottom', 0):.2f} (puts){pm}{day}"
                            + (f" · EMA stack {regime.get('stack')}, {regime.get('fan')}" if regime else "")
                            + (f" · {closed_s}" if closed_s else ""))
        live = [{"trigger": t.trigger_id, "livePct": t.live_pct, "trimsDone": t.trims_done, "isAdd": bool(getattr(t, "is_add", False))}
                for t in ap.trades.values() if t.status == "open" and getattr(t, "live_pct", None) is not None]
        d["team2"] = {"sheet": plan.get("sheet"), "dayType": plan.get("dayType"), "sizingAtOpen": plan.get("sizingAtOpen"),
                      # the 09:25 pre-open result, so a reader (or the watch job) can verify completion
                      # from the snapshot instead of parsing the sheet string
                      "pmh": plan.get("pmh"), "pml": plan.get("pml"), "complete": bool(plan.get("complete")),
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
        with contextlib.suppress(Exception):
            await runner.load_contract_verdicts()               # R5: the close funnel survives a restart
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
