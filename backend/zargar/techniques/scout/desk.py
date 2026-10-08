"""Scout P3 orchestration: analyst lanes -> research books -> entries -> accounting -> daily report.

Schedule (ET, weekdays):
  07:00  scout_daily       (P1) EDGAR catch-up + S1/S2 screens + gates -> scout_candidates
  09:00  scout_verdicts    today's entry candidates that pass every pre-entry gate: masked packet, both
                           analyst lanes (budgeted), lane-book entries planned (pending), random twins drawn
  10:00 .. 11:30 every 15 min  scout_entry_HHMM  the preregistered entry-spread rule (entry.py)
  16:30  scout_report      sync closed positions, after-cost lane P&L, LLM spend -> scout_reports

Research only: entries are BUY limit orders on SHADOW research books (sim executor - `Engine.executor_for`
never returns a broker for kind 'shadow'), every one through `OrderManager.place()` (RiskGate inside);
the fill is adopted by the shared durable position manager (`engine.position_manager.adopt`) with a
policy-as-data exit: fixed stop at fill - 2 x daily ATR (judged on the daily close + a resting GTC stop on
the sim executor), time stop after the hold, no trims. Kill switch / book halts are honoured
(`engine.trading_halted`). Journal: ScoutVerdict, ScoutBudgetStop, ScoutEntryAttempt, ScoutEntry,
ScoutGateResult (stage entry_attempt), ScoutDailyReport.
"""
from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import logging
import math
from typing import Any

from sqlalchemy import func, select

from ... import events as ev
from ...domain import new_id
from ...models import ManagedPositionRow, Order, ScoutCandidate, ScoutEntry, ScoutReport, ScoutVerdict, utcnow
from ...marketstructure import market_calendar as mcal
from . import analyst as an
from . import books as bk
from . import entry as er
from .form4 import ET
from .gates import overall
from .screens import S1_KIND, S1_UNCLASSIFIED_KIND, S2_KIND, add_sessions

log = logging.getLogger("zargar.scout.desk")
TECHNIQUE_ID = "scout"
RANDOM_KIND = "random"
_TERMINAL = ("FILLED", "REJECTED", "REJECTED_RISK", "CANCELLED", "EXPIRED", "ERROR")


def pre_entry_status(gates: dict) -> str:
    """Every gate except the entry spread (judged live at 10:00 ET by the entry rule)."""
    return overall({k: v for k, v in (gates or {}).items() if k != "spread"})


def entry_dict(e: ScoutEntry) -> dict:
    return {"id": e.id, "candidateId": e.candidate_id, "book": e.book, "bookLabel": bk.lane_label(e.book),
            "portfolioId": e.portfolio_id, "ticker": e.ticker, "entryDate": e.entry_date,
            "holdSessions": e.hold_sessions, "status": e.status, "reason": e.reason,
            "attempts": e.attempts or [], "spreadPct": e.spread_pct, "orderId": e.order_id,
            "positionId": e.position_id, "qty": e.qty, "entryPrice": e.entry_price,
            "entryTs": e.entry_ts.isoformat() if e.entry_ts else None, "stopPrice": e.stop_price, "atr": e.atr,
            "exitPrice": e.exit_price, "exitTs": e.exit_ts.isoformat() if e.exit_ts else None,
            "exitReason": e.exit_reason, "grossPnl": e.gross_pnl, "fees": e.fees,
            "halfSpreadCost": e.half_spread_cost, "netPnl": e.net_pnl, "ordersFilled": e.orders_filled}


def verdict_dict(v: ScoutVerdict) -> dict:
    return {"id": v.id, "candidateId": v.candidate_id, "lane": v.lane, "model": v.model, "day": v.day,
            "status": v.status, "verdict": v.verdict, "conviction": v.conviction, "reason": v.reason,
            "reasons": v.reasons or [], "claims": v.claims or [], "droppedClaims": v.dropped_claims or [],
            "tokensIn": v.tokens_in, "tokensOut": v.tokens_out, "cacheRead": v.cache_read,
            "cacheWrite": v.cache_write, "costUsd": v.cost_usd, "latencyMs": v.latency_ms,
            "createdAt": v.created_at.isoformat() if v.created_at else None}


class ScoutDesk:
    def __init__(self, svc) -> None:
        self.svc = svc
        self.engine = svc.engine
        # injectable (tests): provider clients, live quote, filing text, issuer facts
        self.claude_client = None
        self.openai_client = None
        self.quote_of = self._quote_of
        self.filing_text = self._filing_text
        self.issuer_facts = self._issuer_facts
        self._budget_stopped: dict[tuple[str, str], bool] = {}
        self.fill_poll_s = 0.25

    def s(self, key, default=None):
        return self.svc.s(key, default)

    # ------------------------------------------------------------------ schedule
    def rule(self) -> er.EntryRule:
        return er.EntryRule(start=str(self.s("entry_start", "10:00")), end=str(self.s("entry_end", "11:30")),
                            step_minutes=int(self.s("entry_retry_minutes", 15)),
                            max_spread_pct=float(self.s("gate_max_spread_pct", 0.5)))

    def start(self) -> None:
        sch = self.engine.scheduler
        sch.register("scout_verdicts", str(self.s("verdicts_at", "09:00")), self._sched_verdicts)
        for slot in self.rule().slots():
            sch.register(f"scout_entry_{slot.replace(':', '')}", slot, self._sched_entries)
        sch.register("scout_report", str(self.s("report_at", "16:30")), self._sched_report)

    def stop(self) -> None:
        sch = self.engine.scheduler
        for name in [j["name"] for j in sch.status()]:
            if name.startswith("scout_entry_") or name in ("scout_verdicts", "scout_report"):
                sch.unregister(name)

    def _on(self) -> bool:
        return bool(self.s("daily_enabled", True))

    async def _sched_verdicts(self):
        if not self._on() or not mcal.is_trading_day(dt.datetime.now(ET).date()):
            return {"skipped": "off or not a session"}
        return await self.prepare_day()

    async def _sched_entries(self):
        if not self._on() or not mcal.is_trading_day(dt.datetime.now(ET).date()):
            return {"skipped": "off or not a session"}
        return await self.attempt_entries()

    async def _sched_report(self):
        if not mcal.is_trading_day(dt.datetime.now(ET).date()):
            return {"skipped": "not a session"}
        return await self.daily_report()

    # ------------------------------------------------------------------ prepare (verdicts + plan)
    def tradeable_kinds(self) -> tuple[str, ...]:
        kinds = []
        if bool(self.s("s1_insider_enabled", True)):
            kinds.append(S1_KIND)
            if bool(self.s("trade_unclassified", False)):
                kinds.append(S1_UNCLASSIFIED_KIND)
        if bool(self.s("s2_earnings_enabled", True)):
            kinds.append(S2_KIND)
        return tuple(kinds)

    async def prepare_day(self, now: dt.datetime | None = None) -> dict:
        """Verdicts for today's gate-passing entry candidates, then the pending lane-book entries."""
        now = (now or dt.datetime.now(ET)).astimezone(ET)
        today = now.date().isoformat()
        async with self.engine.sf() as s:
            rows = (await s.execute(select(ScoutCandidate).where(
                ScoutCandidate.entry_date == today, ScoutCandidate.kind.in_(self.tradeable_kinds())))).scalars().all()
        from .service import candidate_dict
        out = {"day": today, "candidates": len(rows), "eligible": 0, "verdicts": 0, "entriesPlanned": 0,
               "random": 0, "notEligible": []}
        for c in rows:
            cd = candidate_dict(c)
            st = pre_entry_status(cd["gates"])
            if st != "pass":
                out["notEligible"].append({"ticker": c.ticker, "kind": c.kind, "preEntry": st})
                continue
            out["eligible"] += 1
            verdicts = await self.run_lanes(cd, now)
            out["verdicts"] += sum(1 for v in verdicts.values() if v and v.get("status") == "ok")
            if bool(self.s("books_enabled", True)):
                lanes = bk.lanes_for(c.kind, {k: (v or {}).get("verdict") if (v or {}).get("status") == "ok" else None
                                               for k, v in verdicts.items()})
                hold = self._hold(c.kind)
                for lane in lanes:
                    if await self._plan_entry(c.id, lane, c.ticker, today, hold):
                        out["entriesPlanned"] += 1
                if bool(self.s("random_lane_enabled", True)):
                    if await self.draw_random_twin(cd, now):
                        out["random"] += 1
            with contextlib.suppress(Exception):
                await self.engine.ensure_symbol(c.ticker)          # the live quote must flow by 10:00
        # random twins whose (offset) entry date is today need their quotes too
        async with self.engine.sf() as s:
            for t in (await s.execute(select(ScoutEntry.ticker).where(
                    ScoutEntry.entry_date == today, ScoutEntry.status == "pending"))).scalars().all():
                with contextlib.suppress(Exception):
                    await self.engine.ensure_symbol(t)
        return out

    def _hold(self, kind: str) -> int:
        return int(self.s("s2_hold_sessions", 10)) if kind == S2_KIND else int(self.s("s1_hold_sessions", 20))

    async def _plan_entry(self, cid: str, lane: str, ticker: str, entry_date: str, hold: int,
                          config: dict | None = None) -> bool:
        async with self.engine.sf() as s:
            exists = (await s.execute(select(ScoutEntry.id).where(
                ScoutEntry.candidate_id == cid, ScoutEntry.book == lane))).scalar_one_or_none()
            if exists:
                return False
            s.add(ScoutEntry(id=new_id(), candidate_id=cid, book=lane, ticker=ticker, entry_date=entry_date,
                             hold_sessions=hold, status="pending", attempts=[], config=config or self._rules_snapshot(),
                             created_at=utcnow(), updated_at=utcnow()))
            await s.commit()
        return True

    def _rules_snapshot(self) -> dict:
        r = self.rule()
        return {"positionUsd": float(self.s("position_usd", 600.0)), "stopAtrMult": float(self.s("stop_atr_mult", 2.0)),
                "atrDays": int(self.s("atr_days", 14)), "feePerOrder": float(self.s("fee_per_order", 1.0)),
                "entry": {"start": r.start, "end": r.end, "stepMinutes": r.step_minutes, "maxSpreadPct": r.max_spread_pct},
                "promptVersion": an.PROMPT_VERSION}

    # ------------------------------------------------------------------ analyst lanes
    async def _packet(self, cd: dict) -> an.Packet:
        entry = dt.date.fromisoformat(cd["entryDate"])
        bars = await self.svc.daily_bars(cd["ticker"], entry - dt.timedelta(days=60), entry - dt.timedelta(days=1))
        bars = [b for b in sorted(bars or [], key=lambda b: b.ts)
                if dt.datetime.fromtimestamp(b.ts / 1000, ET).date() < entry]
        names, sector = await self.issuer_facts(cd.get("issuerCik"))
        events: list[str] = []
        with contextlib.suppress(Exception):
            dates, src = await self.svc.earnings_dates(cd["ticker"], cd.get("issuerCik"), cd["signalDate"])
            fut = [d for d in (dates or []) if d >= cd["entryDate"]][:3]
            events.append(f"Next earnings date(s): {', '.join(fut)} ({src})" if fut else "Next earnings date: unknown")
        g = cd.get("gates") or {}
        for k in ("earningsInHold", "corporateActions"):
            if g.get(k):
                events.append(f"Gate {k}: {g[k].get('status')} - {g[k].get('why')}")
        text = None
        if cd["kind"] == S2_KIND:
            text, more = await self.filing_text(cd.get("issuerCik"), (cd.get("evidence") or {}).get("accession"))
            names = sorted(set(names) | set(more or []))
        return an.build_packet(cd, bars=bars, sector=sector, events=events, filing_text=text, company_names=names,
                               max_chars=int(self.s("packet_max_chars", 12000)), atr_days=int(self.s("atr_days", 14)))

    async def spent_today(self, day: str) -> dict:
        async with self.engine.sf() as s:
            rows = (await s.execute(select(ScoutVerdict.lane, func.coalesce(func.sum(ScoutVerdict.cost_usd), 0.0),
                                           func.count()).where(ScoutVerdict.day == day)
                                    .group_by(ScoutVerdict.lane))).all()
        by = {lane: {"usd": round(float(usd or 0), 6), "calls": int(n)} for lane, usd, n in rows}
        return {"total": round(sum(v["usd"] for v in by.values()), 6), "byLane": by}

    async def run_lanes(self, cd: dict, now: dt.datetime) -> dict[str, dict | None]:
        """Both lanes on the same packet. Existing verdicts are reused (one per candidate x lane)."""
        async with self.engine.sf() as s:
            have = {v.lane: verdict_dict(v) for v in (await s.execute(select(ScoutVerdict).where(
                ScoutVerdict.candidate_id == cd["id"]))).scalars().all()}
        if all(l in have for l in an.LANES):
            return have
        packet = await self._packet(cd)
        from . import ingest as ing
        await ing.put_state(self.engine.sf, f"packet:{cd['id']}", {"sources": packet.sources, "meta": packet.meta,
                                                                    "hash": packet.hash})
        out = dict(have)
        for lane in an.LANES:
            if lane not in out:
                out[lane] = await self._run_lane(lane, cd, packet, now)
        return out

    def _lane_cfg(self, lane: str) -> tuple[bool, str, str]:
        if lane == an.CLAUDE:
            return (bool(self.s("claude_enabled", True)), str(self.s("claude_model", "claude-opus-5-5")),
                    str(self.s("claude_effort", "medium")))
        return (bool(self.s("openai_enabled", True)), str(self.s("openai_model", "gpt-6.1-sol")),
                str(self.s("openai_effort", "medium")))

    def _client(self, lane: str):
        cfg = self.engine.config
        if lane == an.CLAUDE:
            if self.claude_client is not None:
                return self.claude_client, None
            key = getattr(cfg, "anthropic_api_key", "") or ""
            if not key:
                return None, "skipped: no ANTHROPIC_API_KEY"
            import anthropic
            self.claude_client = anthropic.AsyncAnthropic(api_key=key)
            return self.claude_client, None
        if self.openai_client is not None:
            return self.openai_client, None
        key = getattr(cfg, "openai_api_key", "") or ""
        if not key:
            return None, "skipped: no OPENAI_API_KEY"
        try:
            import openai
        except ImportError:
            return None, "skipped: the openai package is not installed"
        self.openai_client = openai.AsyncOpenAI(api_key=key)
        return self.openai_client, None

    async def _run_lane(self, lane: str, cd: dict, packet: an.Packet, now: dt.datetime) -> dict:
        day = now.date().isoformat()
        enabled, model, effort = self._lane_cfg(lane)
        rates = self.s("llm_rates", {}) or {}
        max_tokens = int(self.s("llm_max_tokens", 8000))
        user = packet.render()
        rec: dict[str, Any] = {"lane": lane, "model": model, "status": "ok"}
        if not enabled:
            rec.update(status="skipped", reason=f"skipped: techniques.scout.{'claude' if lane == an.CLAUDE else 'openai'}_enabled is off")
            return await self._save_verdict(cd, packet, day, rec)
        client, why = self._client(lane)
        if client is None:
            rec.update(status="skipped", reason=why)
            return await self._save_verdict(cd, packet, day, rec)
        budget = float(self.s("llm_budget_usd_day", 15.0) or 0)
        spent = (await self.spent_today(day))["total"]
        proj = an.projected_cost(model, len(an.SYSTEM_PROMPT) + len(user), max_tokens, rates)
        if self._budget_stopped.get((day, lane)) or spent + proj > budget:
            rec.update(status="budget", reason=f"budget: ${spent:.4f} spent today + ${proj:.4f} worst case for this "
                                               f"call > ${budget:.2f} (techniques.scout.llm_budget_usd_day)")
            if not self._budget_stopped.get((day, lane)):
                self._budget_stopped[(day, lane)] = True
                await self.engine.journal.append(ev.SCOUT_BUDGET_STOP, {
                    "technique": TECHNIQUE_ID, "lane": lane, "model": model, "day": day, "spentUsd": spent,
                    "projectedUsd": proj, "budgetUsd": budget}, aggregate_type="scout", aggregate_id=day)
            return await self._save_verdict(cd, packet, day, rec)
        try:
            if lane == an.CLAUDE:
                res = await an.call_claude(client, model=model, effort=effort, system=an.SYSTEM_PROMPT, user=user,
                                           max_tokens=max_tokens, cache=bool(self.s("prompt_cache", True)),
                                           timeout_s=float(self.s("llm_timeout_s", 120.0)))
            else:
                res = await an.call_openai(client, model=model, effort=effort, system=an.SYSTEM_PROMPT, user=user,
                                           max_tokens=max_tokens, timeout_s=float(self.s("llm_timeout_s", 120.0)))
        except Exception as exc:                 # noqa: BLE001 - a lane failure never fails the run
            rec.update(status="error", reason=f"call failed: {type(exc).__name__}: {str(exc)[:300]}")
            return await self._save_verdict(cd, packet, day, rec)
        rec.update(usage=res.usage, latencyMs=res.latency_ms, raw=(res.text or "")[:20000],
                   costUsd=an.cost_usd(model, res.usage, rates))
        if res.stop == "refusal":
            rec.update(status="error", reason="refusal: the provider declined the request")
            return await self._save_verdict(cd, packet, day, rec)
        try:
            g = an.ground(an.parse_json(res.text), packet)
        except (ValueError, TypeError) as exc:
            rec.update(status="error", reason=f"unparseable reply: {str(exc)[:200]}"
                       + (" (max_tokens)" if res.stop in ("max_tokens", "incomplete") else ""))
            return await self._save_verdict(cd, packet, day, rec)
        rec.update(verdict=g.verdict, conviction=g.conviction, reasons=g.reasons, claims=g.claims,
                   droppedClaims=g.dropped_claims, reason=g.reason)
        return await self._save_verdict(cd, packet, day, rec)

    async def _save_verdict(self, cd: dict, packet: an.Packet, day: str, rec: dict) -> dict:
        u = rec.get("usage") or {}
        row = ScoutVerdict(id=new_id(), candidate_id=cd["id"], lane=rec["lane"], model=rec.get("model"), day=day,
                           status=rec["status"], verdict=rec.get("verdict"), conviction=rec.get("conviction"),
                           reason=rec.get("reason"), reasons=rec.get("reasons") or [], claims=rec.get("claims") or [],
                           dropped_claims=rec.get("droppedClaims") or [], packet_hash=packet.hash, raw=rec.get("raw"),
                           tokens_in=int(u.get("in") or 0), tokens_out=int(u.get("out") or 0),
                           cache_read=int(u.get("cacheRead") or 0), cache_write=int(u.get("cacheWrite") or 0),
                           cost_usd=float(rec.get("costUsd") or 0.0), latency_ms=float(rec.get("latencyMs") or 0.0),
                           created_at=utcnow())
        async with self.engine.sf() as s:
            s.add(row)
            await s.commit()
        d = verdict_dict(row)
        await self.engine.journal.append(ev.SCOUT_VERDICT, {
            "technique": TECHNIQUE_ID, "candidateId": cd["id"], "ticker": cd["ticker"], "kind": cd["kind"],
            **{k: d[k] for k in ("lane", "model", "status", "verdict", "conviction", "reason", "reasons", "claims",
                                 "droppedClaims", "tokensIn", "tokensOut", "cacheRead", "cacheWrite", "costUsd",
                                 "latencyMs")},
            "packetHash": packet.hash, "promptVersion": an.PROMPT_VERSION}, aggregate_type="scout", aggregate_id=cd["id"])
        return d

    # ------------------------------------------------------------------ random matched baseline
    async def draw_random_twin(self, cd: dict, now: dt.datetime) -> bool:
        """books.py documents the method. Idempotent per matched candidate."""
        key = f"random:{cd['key']}"[:160]
        async with self.engine.sf() as s:
            if (await s.execute(select(ScoutCandidate.id).where(ScoutCandidate.key == key))).scalar_one_or_none():
                return False
            lo365 = (now.date() - dt.timedelta(days=365)).isoformat()
            lo30 = (now.date() - dt.timedelta(days=30)).isoformat()
            past = (await s.execute(select(ScoutCandidate.ticker, ScoutCandidate.gates, ScoutCandidate.signal_date)
                                    .where(ScoutCandidate.signal_date >= lo365,
                                           ScoutCandidate.kind != RANDOM_KIND))).all()
        ok = [t for t, g, _ in past if (g or {}).get("price", {}).get("status") == "pass"
              and (g or {}).get("adv", {}).get("status") == "pass"]
        recent = {t for t, _, d in past if d >= lo30}
        pool = bk.build_pool(ok, recent)
        max_off = int(self.s("random_max_offset_sessions", 4))
        hold = self._hold(cd["kind"])
        tried = []
        for attempt in range(5):
            pick = bk.draw_random(cd["key"], pool, exclude={cd["ticker"], *tried}, max_offset=max_off, attempt=attempt)
            if pick is None:
                break
            ticker, off = pick
            tried.append(ticker)
            entry = add_sessions(cd["entryDate"], off)
            exit_date = add_sessions(entry, hold - 1)
            gates = await self.svc.evaluate_gates(RANDOM_KIND, ticker, None, now, entry, exit_date, now)
            gates.pop("spread", None)
            gates["spread"] = {"status": "unknown", "why": f"pending: judged live at the entry attempt ({entry})",
                               "value": None, "threshold": float(self.s("gate_max_spread_pct", 0.5))}
            if pre_entry_status({k: v for k, v in gates.items() if k != "marketCap"}) != "pass":
                continue
            cid = new_id()
            evidence = {"matchedCandidateId": cd["id"], "matchedKey": cd["key"], "matchedTicker": cd["ticker"],
                        "matchedKind": cd["kind"], "seedAttempt": attempt, "offsetSessions": off,
                        "poolSize": len(pool), "rejectedDraws": tried[:-1], "exitDate": exit_date,
                        "method": "books.py random matched baseline (2026-10-07)"}
            row = ScoutCandidate(id=cid, key=key, kind=RANDOM_KIND, ticker=ticker, issuer_cik=None, signal_ts=now,
                                 signal_date=now.date().isoformat(), entry_date=entry, status=overall(gates),
                                 evidence=evidence, gates=gates, config=self.svc.config_snapshot(),
                                 created_at=utcnow(), updated_at=utcnow())
            async with self.engine.sf() as s:
                s.add(row)
                await s.commit()
            await self.engine.journal.append(ev.SCOUT_CANDIDATE_FOUND, {
                "technique": TECHNIQUE_ID, "candidateId": cid, "key": key, "kind": RANDOM_KIND, "ticker": ticker,
                "entryDate": entry, "evidence": evidence}, aggregate_type="scout", aggregate_id=cid)
            await self._plan_entry(cid, bk.RANDOM, ticker, entry, hold)
            return True
        await self.engine.journal.append(ev.SCOUT_CANDIDATE_FOUND, {
            "technique": TECHNIQUE_ID, "candidateId": None, "key": key, "kind": RANDOM_KIND, "ticker": None,
            "status": "unmatched", "evidence": {"matchedCandidateId": cd["id"], "rejectedDraws": tried,
                                                "poolSize": len(pool)}}, aggregate_type="scout", aggregate_id=cd["id"])
        return False

    # ------------------------------------------------------------------ entries (10:00 - 11:30 ET)
    async def _quote_of(self, ticker: str):
        q = self.engine.quotes.get(ticker)
        if q is None:
            return None
        now_ms = int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)
        if q.ts and now_ms - int(q.ts) > 120_000:
            return None                                         # stale: never judged as the live quote
        return {"bid": float(q.bid or 0), "ask": float(q.ask or 0), "ts": int(q.ts or 0)}

    async def attempt_entries(self, now: dt.datetime | None = None) -> dict:
        now = (now or dt.datetime.now(ET)).astimezone(ET)
        today = now.date().isoformat()
        rule = self.rule()
        async with self.engine.sf() as s:
            rows = (await s.execute(select(ScoutEntry).where(
                ScoutEntry.status == "pending", ScoutEntry.entry_date <= today))).scalars().all()
        groups: dict[str, list[ScoutEntry]] = {}
        for e in rows:
            groups.setdefault(e.candidate_id, []).append(e)
        out = {"at": now.isoformat(), "candidates": len(groups), "entered": 0, "skipped": 0, "retry": 0, "unfilled": 0}
        for cid, es in groups.items():
            ticker = es[0].ticker
            q = await self.quote_of(ticker) if es[0].entry_date == today else None
            sp = er.spread_pct((q or {}).get("bid"), (q or {}).get("ask"))
            seen = any(a.get("spreadPct") is not None for a in (es[0].attempts or []))
            action, why = er.decide(now, es[0].entry_date, sp, rule, seen_quote=seen or sp is not None)
            if action == er.WAIT:
                continue
            att = {"at": now.isoformat(), "bid": (q or {}).get("bid"), "ask": (q or {}).get("ask"),
                   "spreadPct": None if sp is None else round(sp, 4), "action": action, "reason": why}
            await self.engine.journal.append(ev.SCOUT_ENTRY_ATTEMPT, {
                "technique": TECHNIQUE_ID, "candidateId": cid, "ticker": ticker, "books": [e.book for e in es], **att},
                aggregate_type="scout", aggregate_id=cid)
            for e in es:
                await self._update_entry(e.id, attempts=[*(e.attempts or []), att])
            if action == er.RETRY:
                out["retry"] += 1
                continue
            if action == er.SKIP:
                code = er.reason_code(why)
                for e in es:
                    await self._finish(e.id, status="skipped", reason=why, code=code, spread=sp)
                await self._spread_gate(cid, sp, why)
                out["skipped"] += len(es)
                continue
            await self._spread_gate(cid, sp, why)
            results = await asyncio.gather(*[self._enter(e.id, q, sp, now) for e in es], return_exceptions=True)
            for r in results:
                if isinstance(r, Exception):
                    log.exception("scout entry failed", exc_info=r)
                    out["unfilled"] += 1
                else:
                    out[r] = out.get(r, 0) + 1
        return out

    async def _spread_gate(self, cid: str, sp: float | None, why: str) -> None:
        from .gates import gate_spread
        from .service import _jsonable
        async with self.engine.sf() as s:
            c = await s.get(ScoutCandidate, cid)
            if c is None:
                return
            g = dict(c.gates or {})
            g["spread"] = gate_spread(sp, self.svc.gate_params(), pending_why=why)
            c.gates = _jsonable(g)
            c.status = overall(g)
            c.updated_at = utcnow()
            await s.commit()
            kind, ticker, status = c.kind, c.ticker, c.status
        await self.engine.journal.append(ev.SCOUT_GATE_RESULT, {
            "technique": TECHNIQUE_ID, "candidateId": cid, "kind": kind, "ticker": ticker, "status": status,
            "gates": {"spread": g["spread"]}, "stage": "entry_attempt"}, aggregate_type="scout", aggregate_id=cid)

    async def _update_entry(self, eid: str, **fields) -> None:
        async with self.engine.sf() as s:
            e = await s.get(ScoutEntry, eid)
            for k, v in fields.items():
                setattr(e, k, v)
            e.updated_at = utcnow()
            await s.commit()

    async def _finish(self, eid: str, *, status: str, reason: str, code: str | None = None,
                      spread: float | None = None, **extra) -> str:
        await self._update_entry(eid, status=status, reason=reason, spread_pct=spread, **extra)
        async with self.engine.sf() as s:
            e = await s.get(ScoutEntry, eid)
            d = entry_dict(e)
        await self.engine.journal.append(ev.SCOUT_ENTRY, {
            "technique": TECHNIQUE_ID, "stage": status, "code": code, **{k: d[k] for k in (
                "id", "candidateId", "book", "portfolioId", "ticker", "entryDate", "reason", "spreadPct", "orderId",
                "positionId", "qty", "entryPrice", "stopPrice", "atr")}},
            aggregate_type="scout", aggregate_id=d["candidateId"], portfolio_id=d["portfolioId"])
        return status

    async def _atr(self, ticker: str, entry_date: str) -> float:
        from ...marketstructure.levels import atr as _atr
        d = dt.date.fromisoformat(entry_date)
        bars = await self.svc.daily_bars(ticker, d - dt.timedelta(days=60), d - dt.timedelta(days=1))
        bars = [b for b in sorted(bars or [], key=lambda b: b.ts) if dt.datetime.fromtimestamp(b.ts / 1000, ET).date() < d]
        return float(_atr(bars, int(self.s("atr_days", 14)))) if len(bars) >= 2 else 0.0

    async def _enter(self, eid: str, q: dict, sp: float | None, now: dt.datetime) -> str:
        from ...orders import OrderIntent
        async with self.engine.sf() as s:
            e = await s.get(ScoutEntry, eid)
            lane, ticker, cid, entry_date, hold = e.book, e.ticker, e.candidate_id, e.entry_date, e.hold_sessions
        book = await bk.ensure_book(self.engine, lane)
        pid = book["id"]
        await self._update_entry(eid, portfolio_id=pid)
        if book.get("kind") != "shadow" or self.engine.executor_for(book) is not self.engine.sim_executor:
            return await self._finish(eid, status="skipped", reason="refused: not a simulated research book", code="refused")
        halted = self.engine.trading_halted(pid)
        if halted:
            return await self._finish(eid, status="skipped", reason=f"halted: {halted}", code="halted", spread=sp)
        a = await self._atr(ticker, entry_date)
        if a <= 0:
            return await self._finish(eid, status="skipped", reason="no_atr: no daily history for the ATR stop", code="no_atr", spread=sp)
        ask, bid = float(q["ask"]), float(q["bid"])
        qty = math.floor(float(self.s("position_usd", 600.0)) / ask)
        if qty < 1:
            return await self._finish(eid, status="skipped", reason=f"size: ${float(self.s('position_usd', 600.0)):g} buys < 1 share at {ask}", code="size", spread=sp)
        # marketable limit: never above the observed ask by more than the gate's half spread
        limit = round(ask * (1 + float(self.s("gate_max_spread_pct", 0.5)) / 200.0), 2)
        intent = OrderIntent(portfolio_id=pid, symbol=ticker, sec_type="STK", side="BUY", qty=qty, order_type="LMT",
                             limit_price=limit, tif="DAY", source="technique", technique_id=TECHNIQUE_ID,
                             tags=["scout", f"scout:{lane}"])
        await self._update_entry(eid, status="ordering", spread_pct=sp, atr=a)       # write-ahead
        try:
            res = await self.engine.orders.place(intent)
        except Exception as exc:                 # noqa: BLE001
            return await self._finish(eid, status="unfilled", reason=f"order failed: {type(exc).__name__}: {exc}", code="error", spread=sp)
        oid = res.get("id")
        await self._update_entry(eid, order_id=oid)
        if res.get("status") in ("REJECTED", "REJECTED_RISK", "ERROR"):
            return await self._finish(eid, status="unfilled", reason=f"rejected: {res.get('rejectReason') or res.get('status')}",
                                      code="rejected", spread=sp)
        order = await self._await_fill(oid, float(self.s("entry_fill_wait_s", 30.0)))
        if order is None or order.status != "FILLED":
            with contextlib.suppress(Exception):
                await self.engine.orders.cancel(oid)
            return await self._finish(eid, status="unfilled", reason=f"unfilled: limit {limit} not filled within "
                                      f"{float(self.s('entry_fill_wait_s', 30.0)):g}s - cancelled", code="unfilled", spread=sp)
        fill, fq = float(order.avg_fill_price), float(order.filled_qty)
        stop = round(fill - float(self.s("stop_atr_mult", 2.0)) * a, 2)
        policy = {"timeframe": "1d", "stop": {"kind": "fixed", "price": stop},
                  "time_stop_sessions": max(1, hold - 1), "gap_exit": True}
        pos = await self.engine.position_manager.adopt({
            "portfolioId": pid, "symbol": ticker, "direction": "long", "techniqueId": TECHNIQUE_ID,
            "tags": ["scout", f"scout:{lane}", f"candidate:{cid}"], "runId": cid, "entry": fill,
            "risk": max(fill - stop, 0.01),
            "legs": [{"symbol": ticker, "secType": "STK", "qty": fq, "avgFill": fill, "entryOrderId": oid,
                      "origin": "adoption"}],
            "overnight": "venue_stop", "policy": policy, "extras": {"scoutEntryId": eid, "lane": lane}})
        fee = float(self.s("fee_per_order", 1.0))
        await self._update_entry(eid, status="entered", position_id=pos["id"], qty=fq, entry_price=fill,
                                 entry_ts=utcnow(), stop_price=stop, fees=fee, orders_filled=1,
                                 half_spread_cost=round(max(0.0, ask - bid) / 2 * fq, 4), reason=None)
        await self._finish(eid, status="entered", reason=f"filled {fq:g} @ {fill:.2f}; stop {stop:.2f} "
                           f"(fill - {float(self.s('stop_atr_mult', 2.0)):g} x ATR {a:.2f}); time exit after {hold} sessions",
                           code="entered", spread=sp)
        return "entered"

    async def _await_fill(self, oid: str | None, timeout_s: float):
        if not oid:
            return None
        loop = asyncio.get_running_loop()
        end = loop.time() + max(0.0, timeout_s)
        while True:
            async with self.engine.sf() as s:
                o = await s.get(Order, oid)
            if o is not None and o.status in _TERMINAL:
                return o
            if loop.time() >= end:
                return o
            await asyncio.sleep(self.fill_poll_s)

    # ------------------------------------------------------------------ accounting
    async def sync_entries(self) -> int:
        """Entered rows whose managed position closed: exit price, gross/net P&L (after $1 per filled order;
        the half spread is embodied in the ask/bid fills and reported apart, never charged twice)."""
        async with self.engine.sf() as s:
            rows = (await s.execute(select(ScoutEntry).where(ScoutEntry.status == "entered"))).scalars().all()
            pids = [r.position_id for r in rows if r.position_id]
            pos = {p.id: p for p in (await s.execute(select(ManagedPositionRow).where(
                ManagedPositionRow.id.in_(pids)))).scalars().all()} if pids else {}
        n = 0
        fee = float(self.s("fee_per_order", 1.0))
        for e in rows:
            p = pos.get(e.position_id)
            if p is None or p.status != "closed":
                continue
            st = p.state or {}
            exits = [x for x in st.get("exits") or [] if float(x.get("filledQty") or 0) > 0]
            qty = sum(float(x["filledQty"]) for x in exits)
            px = (sum(float(x["filledQty"]) * float(x.get("price") or 0) for x in exits) / qty) if qty else None
            gross = float(st.get("realizedPnl") or 0.0)
            orders = 1 + len(exits)
            closed_ms = st.get("closedMs")
            await self._update_entry(e.id, status="closed", exit_price=px, gross_pnl=round(gross, 4),
                                     exit_ts=dt.datetime.fromtimestamp(closed_ms / 1000, dt.timezone.utc) if closed_ms else utcnow(),
                                     exit_reason=st.get("closeReason"), orders_filled=orders, fees=orders * fee,
                                     net_pnl=round(gross - orders * fee, 4))
            await self._finish(e.id, status="closed", reason=f"closed: {st.get('closeReason')}", code="closed",
                               spread=e.spread_pct)
            n += 1
        return n

    def _mark(self, ticker: str) -> float | None:
        q = self.engine.quotes.get(ticker)
        if q is None:
            return None
        return float(q.bid) if q.bid and q.bid > 0 else (float(q.last) if q.last else None)

    async def lanes(self) -> list[dict]:
        """Per-lane book stats: open/closed trades, after-cost P&L (closed realized + open marked at the bid
        less the entry fee and the exit fee still to pay), hit rate on closed trades."""
        async with self.engine.sf() as s:
            rows = (await s.execute(select(ScoutEntry))).scalars().all()
        fee = float(self.s("fee_per_order", 1.0))
        books = {p.get("sourceName", "")[len(bk.LANE_SOURCE_PREFIX):]: p for p in self.engine.positions.portfolios()
                 if p.get("kind") == "shadow" and p.get("book") == bk.BOOK_TAG}
        out = []
        for lane in bk.all_lanes():
            mine = [r for r in rows if r.book == lane]
            closed = [r for r in mine if r.status == "closed"]
            open_ = [r for r in mine if r.status == "entered"]
            realized = sum(float(r.net_pnl or 0) for r in closed)
            unreal = 0.0
            open_rows = []
            for r in open_:
                m = self._mark(r.ticker)
                u = ((m - float(r.entry_price or 0)) * float(r.qty or 0) - 2 * fee) if m is not None else None
                if u is not None:
                    unreal += u
                open_rows.append({**entry_dict(r), "mark": m, "openNetPnl": None if u is None else round(u, 2)})
            wins = sum(1 for r in closed if float(r.net_pnl or 0) > 0)
            out.append({"lane": lane, "label": bk.lane_label(lane), "portfolioId": (books.get(lane) or {}).get("id"),
                        "entries": len(mine), "open": len(open_), "closed": len(closed),
                        "skipped": sum(1 for r in mine if r.status in ("skipped", "unfilled")),
                        "pending": sum(1 for r in mine if r.status in ("pending", "ordering")),
                        "realizedNet": round(realized, 2), "openNet": round(unreal, 2),
                        "totalNet": round(realized + unreal, 2),
                        "hitRate": round(wins / len(closed), 4) if closed else None,
                        "openTrades": open_rows, "closedTrades": [entry_dict(r) for r in closed][-50:]})
        return out

    # ------------------------------------------------------------------ reads
    async def verdicts_for(self, cids: list[str]) -> dict[str, list[dict]]:
        if not cids:
            return {}
        async with self.engine.sf() as s:
            rows = (await s.execute(select(ScoutVerdict).where(ScoutVerdict.candidate_id.in_(cids)))).scalars().all()
        out: dict[str, list[dict]] = {}
        for v in rows:
            out.setdefault(v.candidate_id, []).append(verdict_dict(v))
        return out

    async def entries_for(self, cids: list[str]) -> dict[str, list[dict]]:
        if not cids:
            return {}
        async with self.engine.sf() as s:
            rows = (await s.execute(select(ScoutEntry).where(ScoutEntry.candidate_id.in_(cids)))).scalars().all()
        out: dict[str, list[dict]] = {}
        for e in rows:
            out.setdefault(e.candidate_id, []).append(entry_dict(e))
        return out

    # ------------------------------------------------------------------ daily report
    async def daily_report(self, now: dt.datetime | None = None) -> dict:
        now = (now or dt.datetime.now(ET)).astimezone(ET)
        day = now.date().isoformat()
        closed_now = await self.sync_entries()
        async with self.engine.sf() as s:
            cands = (await s.execute(select(ScoutCandidate.kind, ScoutCandidate.status, func.count()).where(
                ScoutCandidate.signal_date == day).group_by(ScoutCandidate.kind, ScoutCandidate.status))).all()
            verdicts = (await s.execute(select(ScoutVerdict.lane, ScoutVerdict.status, ScoutVerdict.verdict,
                                               func.count()).where(ScoutVerdict.day == day)
                                        .group_by(ScoutVerdict.lane, ScoutVerdict.status, ScoutVerdict.verdict))).all()
            todays = (await s.execute(select(ScoutEntry).where(ScoutEntry.entry_date == day))).scalars().all()
            exits = (await s.execute(select(ScoutEntry).where(ScoutEntry.status == "closed"))).scalars().all()
        lo = dt.datetime.combine(now.date(), dt.time(0, 0), ET)
        exits_today = [entry_dict(e) for e in exits if e.exit_ts and e.exit_ts >= lo]
        lanes = await self.lanes()
        spend = await self.spent_today(day)
        data = {
            "day": day, "at": now.isoformat(),
            "candidates": [{"kind": k, "status": st, "n": n} for k, st, n in cands],
            "verdicts": [{"lane": l, "status": st, "verdict": v, "n": n} for l, st, v, n in verdicts],
            "entries": [{"ticker": e.ticker, "book": e.book, "status": e.status, "reason": e.reason,
                         "entryPrice": e.entry_price, "qty": e.qty} for e in todays],
            "exits": [{"ticker": e["ticker"], "book": e["book"], "exitReason": e["exitReason"], "netPnl": e["netPnl"]}
                      for e in exits_today],
            "closedNow": closed_now,
            "lanes": [{k: l[k] for k in ("lane", "label", "entries", "open", "closed", "realizedNet", "openNet",
                                         "totalNet", "hitRate")} for l in lanes],
            "llm": {**spend, "budgetUsd": float(self.s("llm_budget_usd_day", 15.0))},
        }
        async with self.engine.sf() as s:
            row = await s.get(ScoutReport, day)
            if row is None:
                s.add(ScoutReport(day=day, data=data, created_at=utcnow()))
            else:
                row.data = data
                row.created_at = utcnow()
            await s.commit()
        await self.engine.journal.append(ev.SCOUT_DAILY_REPORT, {"technique": TECHNIQUE_ID, **data},
                                         aggregate_type="scout", aggregate_id=day)
        return data

    async def reports(self, limit: int = 10) -> list[dict]:
        async with self.engine.sf() as s:
            rows = (await s.execute(select(ScoutReport).order_by(ScoutReport.day.desc()).limit(limit))).scalars().all()
        return [r.data for r in rows]

    # ------------------------------------------------------------------ default providers
    async def _issuer_facts(self, cik: str | None) -> tuple[list[str], str | None]:
        if not cik:
            return [], None
        data = await self.svc._submissions(cik)
        if not data:
            return [], None
        names = [data.get("name") or ""] + [f.get("name") or "" for f in data.get("formerNames") or []]
        return [n for n in names if n], data.get("sicDescription")

    async def _filing_text(self, cik: str | None, accession: str | None) -> tuple[str | None, list[str]]:
        if not cik or not accession:
            return None, []
        client = self.svc.edgar_factory()
        try:
            raw = await client.submission_text(f"edgar/data/{int(str(cik))}/{accession}.txt")
        except Exception as exc:                 # noqa: BLE001 - the packet says "no text", the lane still runs
            log.info("scout 8-K text %s: %s", accession, exc)
            return None, []
        finally:
            await client.aclose()
        return an.release_text(raw)
