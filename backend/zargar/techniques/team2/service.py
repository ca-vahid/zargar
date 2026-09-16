"""Team2Service — plans as run records, the nightly/pre-open jobs, replay and the sweep.

- `nightly_plans(for_date=None)`: after the close, one plan run per symbol in
  `techniques.team2.symbols` for the next trading day (skeleton from the previous session's
  15m bars), stored as `TechniqueRun(technique="team2", mode="plan")`, and ARMED in the
  configured mode (`techniques.team2.mode`, alert by default) on the default portfolio.
- `preopen_complete()`: 09:25, completes every armed Team2 plan in place (PMH/PML, day type,
  sizing bucket) — the runner's pre-open hook does the same when the heartbeat fires it — and
  `stamp_run()` writes that completed plan plus the rules the session will actually run under back
  onto the plan run, so `replay()` reproduces the live session instead of re-deriving it (F-1/F-2).
- `replay(run_id)`: the pure session walk over the banked bars of the plan's date.
- `sweep(start, end, symbols=None, overrides=None)`: build+walk every trading day in the range
  from the banked extended-hours bars (`research.ext_bars`), returning per-day rows and a
  summary — the P2 walk-forward. Threshold overrides (`{"pullback_max_touches": 3}`) make it
  the variant harness (PLAN §3c B7 / F-5).
"""
from __future__ import annotations

import contextlib
import datetime as dt
import logging
from dataclasses import replace

from sqlalchemy import select

from ...domain import Bar, new_id
from ...marketstructure.aggregate import aggregate, bar_session, filter_session
from ...marketstructure.market_calendar import is_trading_day, next_trading_day, previous_trading_day, trading_days
from ...marketstructure.sessions import ET, session_date
from ...models import TechniqueArmed, TechniqueRun
from .plan import build_skeleton, complete_plan
from .rules import apply_overrides, rules_for_book, validate_experiments, Team2Rules, rules_from_settings
from .session import simulate_session

log = logging.getLogger("zargar.techniques.team2.service")

CODE_VERSION = "team2-0.1"


def _app_version() -> str:
    from ... import __version__
    return str(__version__)


def _build_sha() -> str | None:
    try:
        from ... import build_sha
        return str(build_sha())
    except Exception:  # noqa: BLE001 - the launch-bound helper lives on another desk's branch until it merges
        return None

#: once-per-session state notes (`session.py` mints each at most once) — the day said what it was
#: doing, it did not refuse a setup. Kept out of the refusal tally the History tab shows (F68).
DAY_NOTES = ("skip_last_entry", "skip_event_day", "skip_loss_cap")


def _day_result(arm) -> dict | None:
    """F67: the day's own grade, from the scorecard the runner writes at disarm (F43).

    The shared Armed > History table cannot show it — that list is ordered by BUILD time and
    capped, and Team2's plans are always built the previous session, so they fall off the
    window; its Realized column also reads the plan's GROSS p&l. The desk's own History tab
    therefore carries the net number and the model-vs-book comparison."""
    sc = (getattr(arm, "state", None) or {}).get("scorecard") if arm is not None else None
    if not sc:
        return None
    skips = sc.get("skips") or {}
    # F68 (2026-09-08): DAY_NOTES are minted once per session by `session.py` to say what state the
    # day is in — they are not setups the method turned down, so counting them as refusals inflated
    # the tally (2026-09-08 read "SPY no trade - 2 refused" for one real refusal plus the 15:30
    # cutoff note). Same principle as F28: skip counts must mean skips. The raw `skips` map stays
    # untouched; `refused` is the number a human should read, `notes` names the day-state rows.
    refused = sum(n for k, n in skips.items() if k not in DAY_NOTES and n > 0)
    return {"fires": sc.get("actualFires"), "matched": sc.get("matched"),
            "theoreticalFires": sc.get("theoreticalFires"),
            "modelPct": sc.get("modelPnlPctSum"), "net": sc.get("realizedPnl"),
            "gross": sc.get("realizedPnlGross"), "skips": skips, "refused": refused,
            "notes": [k for k in DAY_NOTES if skips.get(k)]}


class Team2Service:
    def __init__(self, engine, runner) -> None:
        self.engine = engine
        self.runner = runner

    # ------------------------------------------------------------- bars
    async def bars_1m(self, symbol: str, *, limit: int = 20000) -> list[Bar]:
        from ...marketdata import load_bars
        rows = await load_bars(self.engine.sf, symbol.upper(), "1m", limit=limit)
        if not rows:
            return []
        return rows

    @staticmethod
    def warmup_slice(prior: list[Bar], *, sessions: int) -> tuple[list[Bar], dict]:
        """F99 (2026-09-10): THE warm-up rule, shared by the live runner, `history_for` (replay) and the
        sweep — the last `sessions` VALID prior sessions (F75 validation), identified by content hash so
        a replay can prove it seeded the same EMAs the desk ran on (`warmupMatch`)."""
        from .history import validate_sessions
        from ...marketdata import hash_bars
        valid, rep = validate_sessions(prior)
        dates = list(rep["used"])[-int(sessions):]
        warm = [b for b in valid if session_date(b.ts) in dates]
        sym = warm[0].symbol if warm else ""
        ident: dict = {}
        try:
            ident = hash_bars({str(sym).upper(): warm}, start=(dates[0] if dates else None), end=(dates[-1] if dates else None))
        except Exception:  # noqa: BLE001
            log.warning("team2 warm-up identity not computed", exc_info=True)
        return warm, {"sessions": int(sessions), "sessionsUsed": dates, "excluded": list(rep["excluded"]),
                      "hash": ident.get("hash"), "rows": len(warm)}

    async def warmup_for(self, symbol: str, plan_for: str, *, sessions: int | None = None) -> tuple[list[Bar], dict]:
        """The warm-up bars for `plan_for` from the bank (F99): one loader for every path."""
        n = int(sessions if sessions is not None else rules_from_settings(self.engine.settings).warmup_sessions)
        rows = await self.bars_1m(symbol, limit=max(20000, n * 1200))
        prior = [b for b in rows if session_date(b.ts) < plan_for]
        return self.warmup_slice(prior, sessions=n)

    async def history_for(self, symbol: str, date: str, *, sessions: int | None = None) -> tuple[list[Bar], list[Bar], list[Bar]]:
        """(prior-sessions 1m bars, previous-session 15m RTH bars incl. lookback, today's 1m bars)."""
        if sessions is None:
            sessions = rules_from_settings(self.engine.settings).warmup_sessions
        rows = await self.bars_1m(symbol)
        prior = [b for b in rows if session_date(b.ts) < date]
        today = [b for b in rows if session_date(b.ts) == date]
        if not prior:
            # nothing banked yet: fetch straight from history (Yahoo keeps ~20 days of 1m)
            try:
                from ...marketstructure.history import fetch_window
                end = int(dt.datetime.fromisoformat(date).replace(tzinfo=ET).timestamp() * 1000)
                prior = await fetch_window(symbol, "1m", end - sessions * 2 * 86_400_000, end, session="ext")
                prior = [b for b in prior if session_date(b.ts) < date]
            except Exception:  # noqa: BLE001
                log.exception("team2 history fetch failed for %s", symbol)
                prior = []
        # F75 (2026-09-09): only VALID sessions feed the read — closed days, one-price and outlier
        # sessions are excluded (and remembered, so the plan can say so) and the lookback counts the
        # last N valid sessions, not the last N dates present
        from .history import validate_sessions
        prior, report = validate_sessions(prior)
        if not hasattr(self, "_history_reports"):
            self._history_reports = {}
        dates = list(report["used"])[-sessions:]
        prior = [b for b in prior if session_date(b.ts) in dates]
        # R8: the identity of the bars this plan is BUILT FROM (the rows in hand), not a later table read
        try:
            from ...marketdata import hash_bars
            ident = hash_bars({symbol.upper(): prior}, start=(dates[0] if dates else None), end=(dates[-1] if dates else None))
            report["datasetVersion"], report["datasetRows"] = ident["hash"], ident["rows"]
            report["datasetIdentity"] = ident
        except Exception:  # noqa: BLE001
            log.warning("team2: history identity not computed for %s %s", symbol, date, exc_info=True)
        self._history_reports[(symbol.upper(), date)] = report
        fifteen = [b for b in aggregate(prior, 15) if bar_session(b.ts) == "rth"] if prior else []
        return prior, fifteen, today

    # ------------------------------------------------------------- plans
    def _event_flags(self, date: str) -> dict:
        """D-4: the macro calendar (placeholder source) flags the day; the read skips entries when
        `techniques.team2.avoid_event_days` is on."""
        macro = getattr(self.engine, "macro", None)
        if macro is None:
            return {"eventDay": False}
        evs = macro.events_on(date)
        return {"eventDay": bool(evs), "eventDayName": ", ".join(e.name for e in evs) if evs else None}

    async def mint_plan_run(self, symbol: str, date: str, *, rules: Team2Rules | None = None,
                            fifteen: list[Bar] | None = None, experiment: dict | None = None) -> dict | None:
        rules = rules or rules_from_settings(self.engine.settings)
        prior_1m: list[Bar] | None = None
        if fifteen is None:
            prior_1m, fifteen, _ = await self.history_for(symbol, date, sessions=rules.target_lookback_sessions + 2)
        sk = build_skeleton(symbol, date, fifteen, rules, prev_bars_1m=prior_1m)
        if sk is None:
            log.info("team2: no usable prior history for %s %s — no plan minted", symbol, date)
            return None
        sk["history"] = await self._history_provenance(symbol, date, rules)
        prev_rth = [b for b in fifteen if session_date(b.ts) == sk["prevSession"]]
        last_close = float(prev_rth[-1].close) if prev_rth else None
        plan = {**sk, "planFor": date, "triggers": [], "referencePrice": last_close, "lastClose": last_close,
                "triggerTf": "2m", **self._event_flags(date),
                **({"experiment": dict(experiment)} if experiment else {})}      # FROZEN on the plan: the runner reads this, never the live map
        run = TechniqueRun(id=new_id(), technique="team2", tags=[], symbol=symbol.upper(), as_of=None,
                           primary_tf="2m", mode="plan", trigger="scan", status="done", verdict="plan",
                           setup_type="team2", confidence=None, grounded=True, facts={},
                           result={"plan": plan, "trace": [{"step": "skeleton", "reason": plan["sheet"]}]},
                           images={}, usage={}, llm={},
                           config={"thresholds": rules.to_dict(), "codeVersion": CODE_VERSION, "technique": "team2",
                                   # provenance the readiness receipt checks (PR #168 review): the APP release and build that
                                   # minted this plan — `codeVersion` above is the strategy/model schema id, not a release
                                   "appVersion": _app_version(), "build": _build_sha(),
                                   **({"experiment": dict(experiment)} if experiment else {})})
        async with self.engine.sf() as session:
            session.add(run)
            await session.commit()
        return {"runId": run.id, "symbol": run.symbol, "planFor": date, "plan": plan}

    async def nightly_plans(self, for_date: str | None = None, *, arm: bool = True,
                            force: bool = False) -> dict:
        s = self.engine.settings
        if not bool(s.get("techniques.team2.enabled", True)):
            return {"skipped": "disabled"}
        now = dt.datetime.now(ET)
        if for_date is None:
            today = now.date()
            # after the close (or on a non-trading day) plan the NEXT session; before it, today
            if not is_trading_day(today) or now.hour * 60 + now.minute >= 16 * 60:
                for_date = next_trading_day(today).isoformat()
            else:
                for_date = today.isoformat()
        symbols = [str(x).upper() for x in (s.get("techniques.team2.symbols", []) or [])]
        out = {"planFor": for_date, "runs": [], "failed": [], "armed": [], "skipped": []}
        mode = str(s.get("techniques.team2.mode", "alert"))
        # Parallel Practice experiments (2026-09-15): one plan per (symbol, BOOK). The default book runs the shared
        # baseline; every enabled experiment book gets its own plan minted under ITS rules (`rules_for_book`) and
        # labelled on the run. Experiment books must be Practice (sim) books — never real money.
        default_pid = str(s.get("techniques.team2.default_portfolio", "") or s.get("trading.default_portfolio", "") or "")
        books = [{"portfolioId": default_pid, "label": "", "role": "control", "overrides": {}}]
        # the map is validated AS A WHOLE against the live portfolios: invalid = no experiment plan is minted, the
        # errors are reported, the default book still gets its baseline plan
        v = validate_experiments(s, portfolio_lookup=self.engine.positions.portfolio)
        if v["enabled"] and v["errors"]:
            out["invalidExperiments"] = list(v["errors"])
            out["failed"].append("experiments: invalid configuration — no experiment plan minted: " + "; ".join(v["errors"]))
        elif v["enabled"]:
            if v["control"] and v["control"] != default_pid:
                out["failed"].append(f"experiments: the designated control {v['control']} is not the default book {default_pid} — "
                                     "set techniques.team2.default_portfolio to the control before activation; no experiment plan minted")
            else:
                for b in v["books"]:
                    if b["portfolioId"] != default_pid and not any(x["portfolioId"] == b["portfolioId"] for x in books):
                        books.append(b)
        out["books"] = [{"portfolioId": b["portfolioId"], "label": b["label"], "role": b.get("role"), "overrides": b["overrides"]} for b in books]
        # F41: one armed plan per symbol per session. The job is weekday-gated, not
        # trading-day-gated, so a weekday HOLIDAY runs it again for the same next session
        # (Fri 17:00 and Labor Day 17:00 both plan the Tuesday) — and each run minted AND
        # armed a second plan, which would trade the day twice. `force` is the manual
        # override behind `plan-now`.
        already = {(ap.symbol, ap.config.portfolio_id) for ap in list(getattr(self.runner, "_armed", {}).values())
                   if ap.plan_for == for_date}
        # R10 (audit 2026-09-04): a plan that disarmed on its own loss halt is no longer in memory — the
        # persisted rows are the record of "this symbol already had a plan for this session"
        try:
            from ...models import TechniqueArmed
            async with self.engine.sf() as session:
                rows = (await session.execute(select(TechniqueArmed).where(
                    TechniqueArmed.technique == "team2", TechniqueArmed.plan_for == for_date))).scalars().all()
            already |= {(r.symbol, r.portfolio_id) for r in rows}
        except Exception:  # noqa: BLE001
            log.exception("team2 nightly: could not read the day's armed rows")
            rows = []
        # Transition safety (review of 41ec565): plans for this session armed on books OUTSIDE the current set (the
        # previous default book after the default moved to the Control) would trade as an unreported fourth book.
        # Inventory them; without `force` nothing new is minted for the experiments; with `force` a plan WITHOUT
        # exposure is retired (its rows and history stay) and a book WITH exposure is PAUSED (entries and adds off,
        # its positions still managed by their plan) — never flattened, never erased.
        in_set = {b["portfolioId"] for b in books}
        outside: list[dict] = []
        for ap in list(getattr(self.runner, "_armed", {}).values()) if self.runner is not None else []:
            if ap.plan_for == for_date and ap.config.portfolio_id not in in_set:
                exposure = any(t.status in ("fired", "submitting", "working", "open") or t.pending_exit_qty > 1e-9 for t in ap.trades.values())
                outside.append({"runId": ap.run_id, "symbol": ap.symbol, "portfolioId": ap.config.portfolio_id, "exposure": exposure})
        if outside:
            out["outsideBooks"] = outside
            if len(books) > 1 and not force:
                out["failed"].append(f"experiments: {len(outside)} armed plan(s) for {for_date} on other books ({sorted({o['portfolioId'] for o in outside})}); "
                                     "not minting experiment plans — run again with force to retire (no exposure) or pause (exposure) them")
                books = books[:1]
            elif force:
                # PR #168 review: every step is VERIFIED; an exception, a false result or an unconfirmed state is a
                # transition failure — reported, exposure left under its plan, and the dependent experiment minting
                # does not happen (the old book must never trade beside the new ones while the receipt says otherwise)
                transition_failed: list[str] = []
                for o in outside:
                    if o["exposure"]:
                        eng = self.engine
                        try:
                            if not hasattr(eng, "pause_book"):
                                raise RuntimeError("engine has no book pause")
                            paused_before = eng.halt.book_paused(o["portfolioId"]) if hasattr(eng, "halt") else None
                            if not paused_before:
                                rec = await eng.pause_book(o["portfolioId"], f"experiment transition: plan {o['runId']} ({o['symbol']}) has exposure on a book outside "
                                                           "the experiment set — no new entries or adds; positions stay managed", source="team2", label="team2-transition")
                                if not rec:
                                    raise RuntimeError("pause_book returned no record")
                            if hasattr(eng, "halt") and not eng.halt.book_paused(o["portfolioId"]):
                                raise RuntimeError("the book does not read as paused after the pause")
                            out.setdefault("pausedOutside", []).append(o)
                        except Exception as exc:  # noqa: BLE001
                            transition_failed.append(f"pause of book {o['portfolioId']} (plan {o['runId']}, exposure kept under its plan) failed: {exc}")
                    else:
                        try:
                            ok = await self.runner.disarm(o["runId"], reason="retired: its book left the experiment set (no exposure)", flatten=False)
                            if not ok:
                                raise RuntimeError("disarm returned false")
                            if o["runId"] in getattr(self.runner, "_armed", {}):
                                raise RuntimeError("plan still armed after disarm")
                            out.setdefault("retiredOutside", []).append(o)
                        except Exception as exc:  # noqa: BLE001
                            transition_failed.append(f"retirement of plan {o['runId']} on book {o['portfolioId']} failed: {exc}")
                if transition_failed:
                    out["transitionFailed"] = transition_failed
                    out["failed"].append("experiments: transition NOT confirmed — no experiment plan minted: " + "; ".join(transition_failed))
                    books = books[:1]
        for sym in symbols:
          for book in books:
            pid = book["portfolioId"]; tag = f"{sym}" + (f" [{book['label']}]" if book["label"] else "")
            if book.get("role") != "control":
                # belt and braces on top of the schema: an experiment book is a Practice (sim) book, label or not
                pf = self.engine.positions.portfolio(pid) if pid else None
                if pf is None or str(pf.get("kind")) != "sim" or bool(pf.get("archived")):
                    out["failed"].append(f"{tag}: experiment book {pid} is not an unarchived Practice (sim) book — never real money; not minted")
                    continue
            key = (sym, pid)
            if key in already and not force:
                out["skipped"].append(f"{tag}: already armed for {for_date}")
                continue
            if key in already and force and self.runner is not None:
                # a forced re-plan REPLACES the symbol's plan for that session on that book — never a second armed
                # plan that would trade the day twice (post-close 2026-09-04: force added three duplicates) — and
                # never a plan that still manages exposure (review of 41ec565): that plan stays, the replan is refused
                blocked = False
                for ap in [a for a in list(self.runner._armed.values())
                           if a.symbol == sym and a.plan_for == for_date and a.config.portfolio_id == pid]:
                    if any(t.status in ("fired", "submitting", "working", "open") or t.pending_exit_qty > 1e-9 for t in ap.trades.values()):
                        out["failed"].append(f"{tag}: plan {ap.run_id} has unresolved exposure — not replaced (its positions stay managed)")
                        blocked = True
                        continue
                    try:
                        ok = await self.runner.disarm(ap.run_id, reason="replaced by a forced re-plan", flatten=False)
                        if not ok or ap.run_id in getattr(self.runner, "_armed", {}):
                            raise RuntimeError("disarm not confirmed")
                        out.setdefault("replaced", []).append(ap.run_id)
                    except Exception as exc:  # noqa: BLE001 - PR #168 review: an unconfirmed replacement is a failure, never a second plan
                        out["failed"].append(f"{tag}: replacement of plan {ap.run_id} failed ({exc}) — not re-planned")
                        blocked = True
                if blocked:
                    continue
            rules = apply_overrides(rules_from_settings(s), book["overrides"]) if book.get("role") != "control" else rules_from_settings(s)
            try:
                r = await self.mint_plan_run(sym, for_date, rules=rules,
                                             experiment=({"label": book["label"], "role": book["role"], "portfolioId": pid,
                                                          "overrides": book["overrides"]} if book.get("role") != "control" else None))
            except Exception as exc:  # noqa: BLE001
                log.exception("team2 nightly plan failed for %s", tag)
                out["failed"].append(f"{tag}: {exc}")
                continue
            if r is None:
                out["failed"].append(f"{tag}: no previous-session bars")
                continue
            r["portfolioId"] = pid; r["label"] = book["label"]
            out["runs"].append(r)
            if arm and self.runner is not None:
                try:
                    await self.runner.arm(r["runId"], {"mode": mode, "instrument": "options", "contracts": None,
                                                        **({"portfolioId": pid} if pid else {}),
                                                        "maxContracts": max(int(s.get("risk.max_option_contracts", 10)),
                                                                            int((s.get("techniques.team2.zero_dte") or {}).get("max_contracts", 10) or 10)),
                                                        "premiumBudget": float(s.get("techniques.team2.budget_per_trade", 2000.0)),
                                                        "riskPct": float(s.get("techniques.team2.risk_pct", 6.0)),
                                                        "flattenMinutesBeforeClose": 15,     # 15:45 (C3) — what the card prints
                                                        "useCritic": False, "maxOpenTrades": 1})
                    out["armed"].append(r["runId"])
                except Exception as exc:  # noqa: BLE001
                    log.exception("team2 arm failed for %s", tag)
                    out["failed"].append(f"{tag}: arm failed: {exc}")
        log.info("team2 nightly plans: %s", {k: (len(v) if isinstance(v, list) else v) for k, v in out.items()})
        return out

    async def fetch_today_ext(self, symbol: str, date: str) -> list[Bar]:
        """Today's 04:00-20:00 1m bars straight from history (Yahoo includePrePost), banked into the
        bars table so the runner, the replay and the sweep all see the same pre-market. The nightly
        job only banks after the close; at 09:25 this is the only source of the pre-market range."""
        try:
            from ...marketdata import persist_bars
            from ...marketstructure.history import fetch_extended_session
            bars = await fetch_extended_session(symbol, "1m", date)
            bars = [b for b in bars if b.close and b.close > 0]
            if bars:
                await persist_bars(self.engine.sf, bars)
            return bars
        except Exception:  # noqa: BLE001
            log.exception("team2: fetching today's extended bars failed for %s", symbol)
            return []

    async def preopen_complete(self) -> dict:
        done = []
        today = dt.datetime.now(ET).date().isoformat()
        for ap in list(getattr(self.runner, "_armed", {}).values()):
            # F42: never "complete" a plan whose session has not started. The 09:25 job
            # fires on weekday holidays too, and `complete_plan` on a date with no bars
            # writes pmh/pml None and complete=False over the plan it was handed.
            if ap.plan_for > today:
                continue
            try:
                fresh = await self.fetch_today_ext(ap.symbol, ap.plan_for)
                if fresh:
                    self.runner.merge_bars(ap, fresh)
                bars = await self.runner._today_bars(ap)
                if not bars:
                    rows = await self.bars_1m(ap.symbol, limit=1500)
                    bars = [b for b in rows if session_date(b.ts) == ap.plan_for]
                ap.plan.update(complete_plan(ap.plan, bars))
                ap.plan["planFor"] = ap.plan_for
                self.runner._log(ap, "preopen", str(ap.plan.get("sheet")), pmh=ap.plan.get("pmh"),
                                 pml=ap.plan.get("pml"), dayType=ap.plan.get("dayType"),
                                 sizing=ap.plan.get("sizingAtOpen"))
                # F110: this job re-runs `complete_plan`, so it can move the target the 09:25 bar-loop pass
                # already judged (fresher pre-market bars). Log/journal it here too; `_log_rederived` is
                # idempotent on the plan's own `_rederivedLogged` marker, so the common case writes nothing.
                await self.runner._log_rederived(ap, "pre-open")
                await self.runner._persist(ap)
                await self.stamp_run(ap)
                done.append(ap.run_id)
            except Exception:  # noqa: BLE001
                log.exception("team2 preopen completion failed for %s", ap.symbol)
        return {"completed": done}

    async def _history_provenance(self, symbol: str, date: str, rules) -> dict:
        """What the plan was built from (F75): the valid sessions used, the excluded ones with reasons,
        and the content version of the bars slice they came from."""
        rep = (getattr(self, "_history_reports", {}) or {}).get((symbol.upper(), date)) or {"used": [], "excluded": []}
        used = list(rep.get("used") or [])[-(int(rules.target_lookback_sessions) + 2):]
        out = {"sessionsUsed": used, "excluded": list(rep.get("excluded") or []),
               "datasetVersion": rep.get("datasetVersion"), "datasetRows": rep.get("datasetRows")}
        ident = rep.get("datasetIdentity")
        if ident:
            try:
                from ...marketdata import record_dataset_version
                await record_dataset_version(self.engine.sf, ident, note=f"team2 plan {symbol} {date}")
            except Exception:  # noqa: BLE001 - provenance must never block a plan
                log.warning("team2: dataset version not recorded for %s %s", symbol, date, exc_info=True)
        return out

    async def stamp_run(self, ap) -> None:
        """Write the COMPLETED plan and the rules the session actually runs under back onto the
        plan run (F-1/F-2).

        Two things drift between minting a plan (17:00 the night before) and trading it:

        - the run's `config.thresholds` are frozen at mint time, while the live runner always reads
          `rules_from_settings` — a rule change merged overnight makes replay run a different method
          than the desk did;
        - the completed plan (PMH/PML, day type, sizing) only ever lived in the armer's memory, so
          `replay()` re-derived it from whatever bars existed at replay time. After the open that
          picks the 09:30 RTH open instead of the 09:25 pre-market last price, which can flip the
          day type and the sizing bucket.

        Stamping both at the pre-open — before a single entry — makes replay reproduce the live
        session instead of approximating it, and keeps historical runs frozen as they were.
        """
        try:
            async with self.engine.sf() as session:
                run = await session.get(TechniqueRun, ap.run_id)
                if run is None:
                    return
                result = dict(run.result or {})
                result["plan"] = dict(ap.plan)
                run.result = result
                cfg = dict(run.config or {})
                cfg["thresholds"] = (self.runner.rules_for(ap) if self.runner is not None else rules_for_book(self.engine.settings, ap.config.portfolio_id)).to_dict()   # the plan's FROZEN rules (2026-09-15)
                run.config = cfg
                await session.commit()
        except Exception:  # noqa: BLE001
            log.exception("team2: stamping the completed plan failed for %s", ap.symbol)

    # ------------------------------------------------------------- reads
    async def runs(self, *, limit: int = 50, symbol: str | None = None) -> list[dict]:
        async with self.engine.sf() as session:
            stmt = select(TechniqueRun).where(TechniqueRun.technique == "team2").order_by(TechniqueRun.created_at.desc()).limit(limit)
            if symbol:
                stmt = stmt.where(TechniqueRun.symbol == symbol.upper())
            rows = (await session.execute(stmt)).scalars().all()
            # a plan that is no longer armed must say WHY (a loss halt disarms it mid-session and it
            # would otherwise just vanish from the desk) — the armed row is the projection that keeps it
            arm_rows = {}
            if rows:
                arm_stmt = select(TechniqueArmed).where(TechniqueArmed.run_id.in_([r.id for r in rows]))
                arm_rows = {a.run_id: a for a in (await session.execute(arm_stmt)).scalars().all()}
        out = []
        for r in rows:
            plan = (r.result or {}).get("plan") or {}
            live = r.id in getattr(self.runner, "_armed", {})
            arm = arm_rows.get(r.id)
            out.append({"runId": r.id, "symbol": r.symbol, "planFor": plan.get("planFor"), "sheet": plan.get("sheet"),
                        "complete": plan.get("complete"), "dayType": plan.get("dayType"),
                        "createdAt": r.created_at.isoformat() if getattr(r, "created_at", None) else None,
                        "armed": live,
                        "result": _day_result(arm),
                        "status": ("armed" if live else (arm.status if arm is not None else None)),
                        "stopReason": ((getattr(self.runner.get(r.id), "stop_reason", None) if (live and self.runner is not None) else None)
                                       if live else ((arm.state or {}).get("stopReason") or None)
                                       if arm is not None else None)})
        return out

    async def replay(self, run_id: str, *, overrides: dict | None = None) -> dict | None:
        run = await self.runner.load_plan(run_id)
        if run is None:
            return None
        plan = dict((run.get("result") or {}).get("plan") or {})
        date = plan.get("planFor") or plan.get("date")
        prior, _, today = await self.history_for(run["symbol"], date)
        rules = Team2Rules.from_dict((run.get("config") or {}).get("thresholds") or {})
        if overrides:
            rules = Team2Rules.from_dict({**rules.to_dict(), **overrides})
        if not plan.get("complete"):
            plan = complete_plan(plan, today)
        stamped = (plan.get("sigma") or {}).get("value") if isinstance(plan.get("sigma"), dict) else None
        sigma = float(stamped) if stamped else await self._sigma_for(str(run.get("planFor") or run.get("date") or dt.datetime.now(ET).strftime("%Y-%m-%d")))   # F51: the IV the desk ran on, else that day's proxy
        # F99: the replay seeds from the SAME warm-up rule the desk ran on and says whether it matched
        warm, wrep = self.warmup_slice(prior, sessions=rules.warmup_sessions)
        stamped = (plan.get("warmup") or {}) if isinstance(plan.get("warmup"), dict) else {}
        wrep["stamped"] = stamped.get("hash")
        wrep["match"] = (stamped.get("hash") == wrep.get("hash")) if stamped.get("hash") else None
        res = simulate_session({**plan, "date": date}, today, rules, sigma=sigma, warmup_1m=warm)
        return {"runId": run_id, "plan": plan, "result": res.to_dict(), "overrides": overrides or {},
                "warmup": wrep, "strikeSource": "listed" if (plan.get("listedStrikes") or {}).get("strikes") else "grid"}

    async def sweep(self, start: str, end: str, *, symbols: list[str] | None = None,
                    overrides: dict | None = None, sigma: float | None = None) -> dict:
        s = self.engine.settings
        symbols = [x.upper() for x in (symbols or s.get("techniques.team2.symbols", []) or [])]
        base = rules_from_settings(s)
        rules = Team2Rules.from_dict({**base.to_dict(), **(overrides or {})}) if overrides else base
        # R7/R8 (2026-09-09): load every symbol's tape ONCE, validate the sessions the same way plans and
        # warm-ups do, and hash the bars actually consumed (not a separate table read that a correction can
        # slip between). `coverage` says what was excluded and why.
        from .history import validate_sessions
        from ...marketdata import hash_bars, record_dataset_version
        tapes: dict[str, list[Bar]] = {}
        coverage: dict[str, dict] = {}
        end_ms = int((dt.datetime.combine(dt.date.fromisoformat(end), dt.time(0, 0), ET) + dt.timedelta(days=1)).timestamp() * 1000)
        for sym in symbols:
            loaded = [b for b in await self.bars_1m(sym, limit=60000) if b.ts < end_ms]
            valid, rep = validate_sessions(loaded)
            tapes[sym] = valid
            coverage[sym] = {"loaded": len(loaded), "used": len(valid), "sessionsUsed": rep["used"], "excluded": rep["excluded"]}
        dataset: dict | None = None
        try:
            dataset = hash_bars(tapes, start=None, end=end)
            dataset["loadedRows"] = sum(c["loaded"] for c in coverage.values())
            if getattr(self.engine, "sf", None) is not None:
                await record_dataset_version(self.engine.sf, dataset, note=f"team2 sweep {start}..{end} (validated sessions)")
        except Exception:  # noqa: BLE001
            log.warning("team2 sweep: dataset identity not computed", exc_info=True)
        rows: list[dict] = []
        for sym in symbols:
            all_bars = tapes[sym]
            by_day: dict[str, list[Bar]] = {}
            for b in all_bars:
                by_day.setdefault(session_date(b.ts), []).append(b)
            for d in trading_days(start, end):
                date = d.isoformat()
                today = by_day.get(date) or []
                if not today or not filter_session(today, "rth"):
                    rows.append({"symbol": sym, "date": date, "status": "no_bars"})
                    continue
                # F99: the same warm-up rule as live and replay (the tape is already validated)
                prior_dates = sorted(k for k in by_day if k < date)[-max(rules.warmup_sessions, rules.target_lookback_sessions + 2):]
                prior = [b for k in prior_dates for b in by_day[k]]
                warm, wrep = self.warmup_slice(prior, sessions=rules.warmup_sessions)
                fifteen = [b for b in aggregate(prior, 15) if bar_session(b.ts) == "rth"] if prior else []
                sk = build_skeleton(sym, date, fifteen, rules, prev_bars_1m=prior)
                # C2 evidence filter (reviewers 2026-09-13): every row says whether the previous session's 2m RTH bars
                # exist — knob on or off — so a paired comparison can drop such symbol-sessions from BOTH sides
                prev_sess = sorted(k for k in by_day if k < date)[-1:]
                prev_2m = [b for b in aggregate(by_day[prev_sess[0]], 2) if bar_session(b.ts) == "rth"] if prev_sess else []
                inputs_ok = len(prev_2m) >= 15
                if sk is None:
                    rows.append({"symbol": sym, "date": date, "status": "no_prev_session", "keyLevelInputsOk": inputs_ok})
                    continue
                plan = complete_plan({**sk, "planFor": date}, today)
                sg = sigma if sigma is not None else await self._sigma_for(date)
                res = simulate_session(plan, today, rules, sigma=sg, warmup_1m=warm)
                d_ = res.to_dict()
                rows.append({"symbol": sym, "date": date, "status": "ok", "dayType": plan.get("dayType"),
                             "scenario": d_["bias"].get("scenario"), "trades": d_["trades"],
                             "summary": d_["summary"], "setups": len(d_["setups"]), "sigma": sg,
                             "warmup": {"hash": wrep.get("hash"), "sessionsUsed": wrep.get("sessionsUsed")},
                             "strikeSource": "grid",       # F104: history carries no as-of listing — a stated limitation
                             "keyLevelInputsOk": inputs_ok,
                             "keyLevels": _key_level_funnel(plan, d_)})
        trades = [t for r in rows for t in (r.get("trades") or [])]
        wins = [t for t in trades if t["win"]]
        summary = {
            "days": len([r for r in rows if r["status"] == "ok"]), "noData": len([r for r in rows if r["status"] != "ok"]),
            "trades": len(trades), "wins": len(wins), "winRate": round(len(wins) / len(trades), 3) if trades else None,
            "pnlPctSum": round(sum(t["pnlPct"] for t in trades), 1),
            "avgWinPct": round(sum(t["pnlPct"] for t in wins) / len(wins), 1) if wins else None,
            "avgLossPct": round(sum(t["pnlPct"] for t in trades if not t["win"]) / max(1, len(trades) - len(wins)), 1)
            if len(trades) > len(wins) else None,
            "byScenario": _group(trades, rows, "scenario"), "byKind": _group_field(trades, "entryKind"),
            "byBucket": _group_field(trades, "bucket"), "early": _group_field(trades, "early"),
            "overrides": overrides or {}, "codeVersion": CODE_VERSION,
            "strikeSource": "grid", "strikeSourceNote": "the sweep walks the synthetic strike grid: no as-of listing "
                                                        "evidence exists for past sessions (F104)",
        }
        summary["rowsWithoutKeyLevelInputs"] = sum(1 for r in rows if r.get("keyLevelInputsOk") is False)
        summary["rowsInsufficientKeyLevelData"] = sum(1 for r in rows if (r.get("keyLevels") or {}).get("insufficientData"))
        return {"start": start, "end": end, "symbols": symbols, "rows": rows, "summary": summary,
                "datasetVersion": (dataset or {}).get("hash"), "datasetRows": (dataset or {}).get("rows"),
                "coverage": coverage, "thresholds": rules.to_dict()}

    async def _sigma_for(self, date: str) -> float:
        """VIX1D close of the previous session as the day's IV proxy; 0.20 when unknown."""
        try:
            from ...marketdata import load_bars
            for sym, mult in (("^VIX1D", 1.0), ("^VIX", 1.3)):
                rows = await load_bars(self.engine.sf, sym, "1d", limit=400)
                prev = [b for b in rows if session_date(b.ts) < date]
                if prev and prev[-1].close > 0:
                    return float(prev[-1].close) / 100.0 * mult
        except Exception:  # noqa: BLE001
            pass
        return 0.20


def paired_rows(*sweeps: dict) -> tuple[list[list[dict]], list[dict]]:
    """C2 paired comparison: the symbol-sessions eligible in EVERY sweep passed (status ok, C2 inputs present, no
    `insufficientData`), aligned by (symbol, date), plus the dropped keys with the reason. A cell missing its inputs in
    any variant is dropped from all of them — it is never counted as a fully evaluated no-effect observation."""
    keyed = [{(r["symbol"], r["date"]): r for r in s["rows"]} for s in sweeps]
    keys = sorted(set().union(*[set(k) for k in keyed]))
    kept: list[tuple] = []; dropped: list[dict] = []
    for k in keys:
        reasons = []
        for i, m in enumerate(keyed):
            r = m.get(k)
            if r is None:
                reasons.append(f"sweep {i}: missing")
            elif r.get("status") != "ok":
                reasons.append(f"sweep {i}: {r.get('status')}")
            elif r.get("keyLevelInputsOk") is False:
                reasons.append(f"sweep {i}: no 2m inputs")
            elif (r.get("keyLevels") or {}).get("insufficientData"):
                reasons.append(f"sweep {i}: insufficient key-level data")
        if reasons:
            dropped.append({"symbol": k[0], "date": k[1], "reasons": reasons})
        else:
            kept.append(k)
    return [[m[k] for k in kept] for m in keyed], dropped


def summarize_rows(rows: list[dict]) -> dict:
    """The sweep summary recomputed over a row subset (for the paired sample)."""
    trades = [t for r in rows for t in (r.get("trades") or [])]
    wins = [t for t in trades if t["win"]]
    return {"symbolSessions": len(rows), "trades": len(trades), "wins": len(wins),
            "winRate": round(len(wins) / len(trades), 3) if trades else None,
            "pnlPctSum": round(sum(t["pnlPct"] for t in trades), 1)}


def _key_level_funnel(plan: dict, read: dict) -> dict | None:
    """C2 funnel per symbol-session: levels built / masked / how often they acted (the spec's §3 report)."""
    kl = plan.get("keyLevels")
    if not isinstance(kl, dict):
        return None
    ev = [e.get("event") for e in (read.get("events") or [])]
    cands = kl.get("candidates") or []
    return {"definition": kl.get("definition"), "built": len(cands), "insufficientData": kl.get("insufficientData"),
            "atrBuildSource": kl.get("atrBuildSource"),
            "maskedZone": sum(1 for c in cands if c.get("maskedBy") in ("pdh", "pdl")),
            "maskedPm": len(kl.get("pmMasks") or []),
            "above": len(kl.get("above") or []), "below": len(kl.get("below") or []),
            "breaks": ev.count("key_level_break"), "setups": ev.count("key_level_setup"), "flips": ev.count("key_level_flip"),
            "rejected": ev.count("key_level_rejected"), "retired": ev.count("key_level_retired"),
            "overruled": ev.count("key_level_overruled"), "pending": ev.count("key_level_pending"),
            "retests": ev.count("key_level_retest"),
            "firesOnKeyLevels": sum(1 for e in (read.get("events") or []) if e.get("event") == "fire" and e.get("keyLevel"))}


def _group(trades: list[dict], rows: list[dict], key: str) -> dict:
    scen_by_setup = {}
    for r in rows:
        for t in r.get("trades") or []:
            scen_by_setup[(r["symbol"], r["date"], t["setup"])] = r.get(key)
    out: dict[str, dict] = {}
    for r in rows:
        for t in r.get("trades") or []:
            k = str(t["setup"].split("@")[0])
            g = out.setdefault(k, {"trades": 0, "wins": 0, "pnlPctSum": 0.0})
            g["trades"] += 1
            g["wins"] += int(t["win"])
            g["pnlPctSum"] = round(g["pnlPctSum"] + t["pnlPct"], 1)
    return out


def _group_field(trades: list[dict], field: str) -> dict:
    out: dict[str, dict] = {}
    for t in trades:
        k = str(t.get(field))
        g = out.setdefault(k, {"trades": 0, "wins": 0, "pnlPctSum": 0.0})
        g["trades"] += 1
        g["wins"] += int(t["win"])
        g["pnlPctSum"] = round(g["pnlPctSum"] + t["pnlPct"], 1)
    return out


__all__ = ["Team2Service", "CODE_VERSION"]
