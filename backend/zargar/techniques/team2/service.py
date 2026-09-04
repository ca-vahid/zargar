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

import datetime as dt
import logging
from dataclasses import replace

from sqlalchemy import select

from ...domain import Bar, new_id
from ...marketstructure.aggregate import aggregate, bar_session, filter_session
from ...marketstructure.market_calendar import is_trading_day, next_trading_day, previous_trading_day, trading_days
from ...marketstructure.sessions import ET, session_date
from ...models import TechniqueRun
from .plan import build_skeleton, complete_plan
from .rules import Team2Rules, rules_from_settings
from .session import simulate_session

log = logging.getLogger("zargar.techniques.team2.service")

CODE_VERSION = "team2-0.1"


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

    async def history_for(self, symbol: str, date: str, *, sessions: int = 12) -> tuple[list[Bar], list[Bar], list[Bar]]:
        """(prior-sessions 1m bars, previous-session 15m RTH bars incl. lookback, today's 1m bars)."""
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
        dates = sorted({session_date(b.ts) for b in prior})[-sessions:]
        prior = [b for b in prior if session_date(b.ts) in dates]
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
                            fifteen: list[Bar] | None = None) -> dict | None:
        rules = rules or rules_from_settings(self.engine.settings)
        if fifteen is None:
            _, fifteen, _ = await self.history_for(symbol, date, sessions=rules.target_lookback_sessions + 2)
        sk = build_skeleton(symbol, date, fifteen, rules)
        if sk is None:
            return None
        prev_rth = [b for b in fifteen if session_date(b.ts) == sk["prevSession"]]
        last_close = float(prev_rth[-1].close) if prev_rth else None
        plan = {**sk, "planFor": date, "triggers": [], "referencePrice": last_close, "lastClose": last_close,
                "triggerTf": "2m", **self._event_flags(date)}
        run = TechniqueRun(id=new_id(), technique="team2", tags=[], symbol=symbol.upper(), as_of=None,
                           primary_tf="2m", mode="plan", trigger="scan", status="done", verdict="plan",
                           setup_type="team2", confidence=None, grounded=True, facts={},
                           result={"plan": plan, "trace": [{"step": "skeleton", "reason": plan["sheet"]}]},
                           images={}, usage={}, llm={},
                           config={"thresholds": rules.to_dict(), "codeVersion": CODE_VERSION, "technique": "team2"})
        async with self.engine.sf() as session:
            session.add(run)
            await session.commit()
        return {"runId": run.id, "symbol": run.symbol, "planFor": date, "plan": plan}

    async def nightly_plans(self, for_date: str | None = None, *, arm: bool = True) -> dict:
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
        rules = rules_from_settings(self.engine.settings)
        out = {"planFor": for_date, "runs": [], "failed": [], "armed": []}
        mode = str(s.get("techniques.team2.mode", "alert"))
        for sym in symbols:
            try:
                r = await self.mint_plan_run(sym, for_date, rules=rules)
            except Exception as exc:  # noqa: BLE001
                log.exception("team2 nightly plan failed for %s", sym)
                out["failed"].append(f"{sym}: {exc}")
                continue
            if r is None:
                out["failed"].append(f"{sym}: no previous-session bars")
                continue
            out["runs"].append(r)
            if arm and self.runner is not None:
                try:
                    await self.runner.arm(r["runId"], {"mode": mode, "instrument": "options", "contracts": None,
                                                        "maxContracts": int(s.get("risk.max_option_contracts", 10)),
                                                        "premiumBudget": float(s.get("techniques.team2.budget_per_trade", 500.0)),
                                                        "useCritic": False, "maxOpenTrades": 1})
                    out["armed"].append(r["runId"])
                except Exception as exc:  # noqa: BLE001
                    log.exception("team2 arm failed for %s", sym)
                    out["failed"].append(f"{sym}: arm failed: {exc}")
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
        for ap in list(getattr(self.runner, "_armed", {}).values()):
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
                await self.runner._persist(ap)
                await self.stamp_run(ap)
                done.append(ap.run_id)
            except Exception:  # noqa: BLE001
                log.exception("team2 preopen completion failed for %s", ap.symbol)
        return {"completed": done}

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
                cfg["thresholds"] = rules_from_settings(self.engine.settings).to_dict()
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
        out = []
        for r in rows:
            plan = (r.result or {}).get("plan") or {}
            out.append({"runId": r.id, "symbol": r.symbol, "planFor": plan.get("planFor"), "sheet": plan.get("sheet"),
                        "complete": plan.get("complete"), "dayType": plan.get("dayType"),
                        "createdAt": r.created_at.isoformat() if getattr(r, "created_at", None) else None,
                        "armed": r.id in getattr(self.runner, "_armed", {})})
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
        sigma = await self.runner._sigma(run["symbol"]) if hasattr(self.runner, "_sigma") else 0.2
        res = simulate_session({**plan, "date": date}, today, rules, sigma=sigma, warmup_1m=prior)
        return {"runId": run_id, "plan": plan, "result": res.to_dict(), "overrides": overrides or {}}

    async def sweep(self, start: str, end: str, *, symbols: list[str] | None = None,
                    overrides: dict | None = None, sigma: float | None = None) -> dict:
        s = self.engine.settings
        symbols = [x.upper() for x in (symbols or s.get("techniques.team2.symbols", []) or [])]
        base = rules_from_settings(s)
        rules = Team2Rules.from_dict({**base.to_dict(), **(overrides or {})}) if overrides else base
        rows: list[dict] = []
        for sym in symbols:
            all_bars = await self.bars_1m(sym, limit=60000)
            by_day: dict[str, list[Bar]] = {}
            for b in all_bars:
                by_day.setdefault(session_date(b.ts), []).append(b)
            for d in trading_days(start, end):
                date = d.isoformat()
                today = by_day.get(date) or []
                if not today or not filter_session(today, "rth"):
                    rows.append({"symbol": sym, "date": date, "status": "no_bars"})
                    continue
                prior_dates = sorted(k for k in by_day if k < date)[-(rules.target_lookback_sessions + 2):]
                prior = [b for k in prior_dates for b in by_day[k]]
                fifteen = [b for b in aggregate(prior, 15) if bar_session(b.ts) == "rth"] if prior else []
                sk = build_skeleton(sym, date, fifteen, rules)
                if sk is None:
                    rows.append({"symbol": sym, "date": date, "status": "no_prev_session"})
                    continue
                plan = complete_plan({**sk, "planFor": date}, today)
                sg = sigma if sigma is not None else await self._sigma_for(date)
                res = simulate_session(plan, today, rules, sigma=sg, warmup_1m=prior)
                d_ = res.to_dict()
                rows.append({"symbol": sym, "date": date, "status": "ok", "dayType": plan.get("dayType"),
                             "scenario": d_["bias"].get("scenario"), "trades": d_["trades"],
                             "summary": d_["summary"], "setups": len(d_["setups"]), "sigma": sg})
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
        }
        return {"start": start, "end": end, "symbols": symbols, "rows": rows, "summary": summary,
                "thresholds": rules.to_dict()}

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
