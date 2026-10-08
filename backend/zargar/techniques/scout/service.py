"""ScoutService - the daily job and the candidate store (research only).

Orchestration only: parsing (`form4`, `datasets`), classification (`classify`), screens
(`screens`) and gate verdicts (`gates`) are pure and tested on fixtures. This module
gathers facts and writes `scout_candidates`, journaling every decision
(ScoutCandidateFound / ScoutGateResult / ScoutDailyRun).

Scout places NO orders: there is no import of the order path, no portfolio, no RiskGate
call. Fact providers (bars, spread, market cap, corporate actions, earnings dates, Tips
mentions, CIK->ticker) are plain async attributes so tests replace them without network.
"""
from __future__ import annotations

import datetime as dt
import logging
import statistics
from dataclasses import asdict
from typing import Any

import httpx
from sqlalchemy import func, or_, select

from ... import events as ev
from ...domain import new_id
from ...models import ScoutCandidate, ScoutFiling, ScoutInsiderTrade, Signal, utcnow
from ...marketstructure import market_calendar as mcal
from . import SCREEN_VERSION
from . import ingest as ing
from .classify import Classification, classify_one, history_by_insider
from .edgar import DEFAULT_UA, EdgarClient, EdgarError
from .form4 import ET
from .gates import (GateParams, gate_adv, gate_corporate_actions, gate_earnings_in_hold, gate_market_cap,
                    gate_price, gate_spread, gate_tips_mention, overall)
from .screens import (S1_KIND, S1_UNCLASSIFIED_KIND, S2_KIND, S1Params, S2Params, add_sessions,
                      measure_reaction, reaction_day0, s1_purchases, screen_s1, screen_s2)

log = logging.getLogger("zargar.scout")
P = "techniques.scout."


def _f(v):
    return float(v) if v is not None else None


def candidate_dict(c: ScoutCandidate) -> dict:
    return {"id": c.id, "key": c.key, "kind": c.kind, "ticker": c.ticker, "issuerCik": c.issuer_cik,
            "signalTs": c.signal_ts.isoformat() if c.signal_ts else None, "signalDate": c.signal_date,
            "entryDate": c.entry_date, "status": c.status, "evidence": c.evidence or {}, "gates": c.gates or {},
            "config": c.config or {}, "createdAt": c.created_at.isoformat() if c.created_at else None,
            "updatedAt": c.updated_at.isoformat() if c.updated_at else None}


class ScoutService:
    def __init__(self, engine) -> None:
        self.engine = engine
        self.last_run: dict | None = None
        self.running = False
        self._tickers: dict[str, str] | None = None
        self._shares_cache: dict[str, Any] = {}
        self._submissions_cache: dict[str, Any] = {}
        self.edgar_factory = self._make_edgar
        # fact providers (tests replace these)
        self.daily_bars = self._daily_bars
        self.entry_spread_pct = self._entry_spread_pct
        self.market_cap = self._market_cap
        self.corporate_actions = self._corporate_actions
        self.earnings_dates = self._earnings_dates
        self.tips_mentions = self._tips_mentions
        self.ticker_for_cik = self._ticker_for_cik

    # ------------------------------------------------------------------ settings
    def s(self, key: str, default=None):
        return self.engine.settings.get(P + key, default)

    def s1_params(self) -> S1Params:
        return S1Params(window_days=int(self.s("s1_window_days", 10)), min_insiders=int(self.s("s1_min_insiders", 2)),
                        min_value_usd=float(self.s("s1_min_value_usd", 100_000.0)))

    def s2_params(self) -> S2Params:
        return S2Params(top_pct=float(self.s("s2_top_pct", 10.0)), volume_mult=float(self.s("s2_volume_mult", 2.0)),
                        volume_avg_days=int(self.s("s2_volume_avg_days", 20)),
                        entry_offset_sessions=int(self.s("s2_entry_offset_sessions", 2)))

    def gate_params(self) -> GateParams:
        return GateParams(min_price=_f(self.s("gate_min_price", 5.0)), min_adv_usd=_f(self.s("gate_min_adv_usd", 5e6)),
                          adv_days=int(self.s("gate_adv_days", 20)),
                          max_spread_pct=_f(self.s("gate_max_spread_pct", 0.5)),
                          min_market_cap_usd=_f(self.s("gate_min_market_cap_usd", 3e8)),
                          no_earnings_in_hold=bool(self.s("gate_no_earnings_in_hold", True)),
                          corp_action_days=int(self.s("gate_corp_action_days", 183)),
                          tips_mention_days=int(self.s("gate_tips_mention_days", 5)))

    def config_snapshot(self) -> dict:
        return {"screenVersion": SCREEN_VERSION, "s1": asdict(self.s1_params()), "s2": asdict(self.s2_params()),
                "gates": asdict(self.gate_params()), "cmpYears": int(self.s("cmp_years", 3)),
                "s1HoldSessions": int(self.s("s1_hold_sessions", 20)),
                "s2HoldSessions": int(self.s("s2_hold_sessions", 10)), "benchmark": self.s("s2_benchmark", "SPY")}

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        at = str(self.s("daily_at", "07:00"))
        self.engine.scheduler.register("scout_daily", at, self._scheduled)

    async def stop(self) -> None:
        self.engine.scheduler.unregister("scout_daily")

    async def _scheduled(self):
        if not bool(self.s("daily_enabled", True)):
            return {"skipped": "techniques.scout.daily_enabled is off"}
        return await self.run_daily()

    def _make_edgar(self) -> EdgarClient:
        return EdgarClient(user_agent=str(self.s("edgar_user_agent", DEFAULT_UA)),
                           max_rps=float(self.s("edgar_max_rps", 5.0)))

    # ------------------------------------------------------------------ daily job
    async def run_daily(self, *, now: dt.datetime | None = None, ingest: bool = True) -> dict:
        if self.running:
            return {"skipped": "already running"}
        self.running = True
        now = (now or dt.datetime.now(ET)).astimezone(ET)
        s1_on, s2_on = bool(self.s("s1_insider_enabled", True)), bool(self.s("s2_earnings_enabled", True))
        summary: dict[str, Any] = {"at": now.isoformat(), "s1Enabled": s1_on, "s2Enabled": s2_on,
                                   "ingest": [], "s1": None, "s2": None, "recheck": None, "errors": []}
        try:
            if ingest and (s1_on or s2_on):
                summary["ingest"] = await self._catch_up(now, forms8k=s2_on)
            if s1_on:
                summary["s1"] = await self.run_s1(now)
            if s2_on:
                summary["s2"] = await self.run_s2(now)
            summary["recheck"] = await self.recheck_spreads(now)
        except Exception as exc:  # pragma: no cover - surfaced on the record + status
            log.exception("scout daily run failed")
            summary["errors"].append(str(exc)[:300])
        finally:
            self.running = False
        self.last_run = summary
        await ing.put_state(self.engine.sf, "last_run", summary)
        await self.engine.journal.append(ev.SCOUT_DAILY_RUN, {**summary, "technique": "scout"},
                                         aggregate_type="scout", aggregate_id=now.date().isoformat())
        return summary

    async def _catch_up(self, now: dt.datetime, *, forms8k: bool) -> list[dict]:
        """Daily indexes not yet ingested, oldest first, up to yesterday (today too after 22:30 ET)."""
        done = await ing.get_state(self.engine.sf, "daily_days")
        last = now.date() if now.time() >= dt.time(22, 30) else now.date() - dt.timedelta(days=1)
        n = int(self.s("catchup_days", 7))
        days = [last - dt.timedelta(days=k) for k in range(n - 1, -1, -1)]
        days = [d for d in days if mcal.is_trading_day(d) and d.isoformat() not in done]
        out = []
        client = self.edgar_factory()
        try:
            for d in days:
                try:
                    out.append(await ing.ingest_daily(self.engine.sf, client, d, forms8k=forms8k,
                                                      ticker_for_cik=self.ticker_for_cik))
                except EdgarError as exc:
                    out.append({"day": d.isoformat(), "error": str(exc)[:200]})
        finally:
            await client.aclose()
        return out

    # ------------------------------------------------------------------ classification
    async def _classifier(self, insiders: set[str], years: set[int]):
        """CMP labels for (insider, year), from PAST trades only, coverage-aware."""
        nyears = int(self.s("cmp_years", 3))
        cov = ing.coverage_start(await ing.get_state(self.engine.sf, "datasets"),
                                 await ing.get_state(self.engine.sf, "daily_days"))
        lo = f"{min(years) - nyears}-01-01" if years else "1900-01-01"
        rows: list[dict] = []
        async with self.engine.sf() as s:
            ins = sorted(insiders)
            for i in range(0, len(ins), 500):
                q = (select(ScoutInsiderTrade.insider_cik, ScoutInsiderTrade.trans_date, ScoutInsiderTrade.trans_code,
                            ScoutInsiderTrade.filed_date)
                     .where(ScoutInsiderTrade.insider_cik.in_(ins[i:i + 500]),
                            ScoutInsiderTrade.trans_date >= lo, ScoutInsiderTrade.trans_code.in_(("P", "S"))))
                rows += [{"insider_cik": a, "trans_date": b, "trans_code": c, "filed_date": d}
                         for a, b, c, d in (await s.execute(q)).all()]
        hist = {y: history_by_insider(rows, y, years=nyears) for y in years}
        cache: dict[tuple[str, int], Classification] = {}

        def classify(cik: str, year: int) -> Classification:
            k = (cik, year)
            if k not in cache:
                h = hist.get(year)
                if h is None:
                    h = hist[year] = history_by_insider(rows, year, years=nyears)
                cache[k] = classify_one(h.get(cik, {}), year, years=nyears, coverage_start=cov)
            return cache[k]

        return classify, cov

    # ------------------------------------------------------------------ S1
    async def run_s1(self, now: dt.datetime) -> dict:
        p = self.s1_params()
        lookback = int(self.s("signal_lookback_days", 3))
        since = (now.date() - dt.timedelta(days=p.window_days + lookback + 10)).isoformat()
        async with self.engine.sf() as s:
            rows = (await s.execute(select(ScoutInsiderTrade).where(
                ScoutInsiderTrade.trans_code == "P", ScoutInsiderTrade.trans_date >= since,
                or_(ScoutInsiderTrade.is_officer.is_(True), ScoutInsiderTrade.is_director.is_(True))))).scalars().all()
        dicts = [{c.name: getattr(r, c.name) for c in ScoutInsiderTrade.__table__.columns} for r in rows]
        purchases = [r for r in s1_purchases(dicts, p)
                     if (r.get("acceptance_ts") is None or r["acceptance_ts"] <= now)]
        classify, cov = await self._classifier({str(r["insider_cik"]) for r in purchases},
                                               {int(r["trans_date"][:4]) for r in purchases} or {now.year})
        hits = screen_s1(purchases, classify, p)
        if bool(self.s("s1_track_unclassified", True)):
            hits += screen_s1(purchases, classify, p, include_unclassified=True)
        recent = [h for h in hits if now - dt.timedelta(days=lookback) <= h.signal_ts <= now]
        written = 0
        hold = int(self.s("s1_hold_sessions", 20))
        for h in recent:
            evidence = {"insiders": h.insiders, "totalValue": h.total_value, "window": list(h.window),
                        "anchorDate": h.anchor_date, "signalTimeApprox": h.signal_time_approx,
                        "coverageStart": cov, "classifications": h.classifications,
                        "rows": [{k: (v.isoformat() if isinstance(v, dt.datetime) else v) for k, v in r.items()
                                  if k in ("accession", "insider_cik", "insider_name", "trans_date", "shares",
                                           "price", "value", "filed_date", "acceptance_ts", "officer_title",
                                           "is_officer", "is_director", "source")} for r in h.rows],
                        "exitDate": add_sessions(h.entry_date, hold - 1)}
            if await self._record(h.kind, h.key, h.ticker, h.issuer_cik, h.signal_ts, h.entry_date, evidence, now):
                written += 1
        return {"purchases": len(purchases), "clusters": len(hits), "recent": len(recent), "new": written,
                "coverageStart": cov}

    # ------------------------------------------------------------------ S2
    async def run_s2(self, now: dt.datetime) -> dict:
        p = self.s2_params()
        lookback = int(self.s("signal_lookback_days", 3))
        since = now - dt.timedelta(days=lookback + 7)
        async with self.engine.sf() as s:
            events = (await s.execute(select(ScoutFiling).where(
                ScoutFiling.form_type == "8-K",
                ScoutFiling.items.like("%2.02%"), ScoutFiling.acceptance_ts >= since,
                ScoutFiling.acceptance_ts <= now))).scalars().all()
        bench_sym = str(self.s("s2_benchmark", "SPY"))
        last_closed = self._last_closed_session(now)
        reactions, skipped = [], []
        bench_cache: list | None = None
        for e in events:
            ticker = e.ticker or await self.ticker_for_cik(e.issuer_cik or "")
            if not ticker:
                skipped.append({"accession": e.accession, "why": "no ticker for CIK"})
                continue
            d0 = reaction_day0(e.acceptance_ts)
            d1 = add_sessions(d0, 1)
            if d1 > last_closed:
                skipped.append({"accession": e.accession, "ticker": ticker, "why": f"day +1 ({d1}) not closed"})
                continue
            start = dt.date.fromisoformat(d0) - dt.timedelta(days=45)
            end = dt.date.fromisoformat(d1)
            if bench_cache is None:
                bench_cache = await self.daily_bars(bench_sym, now.date() - dt.timedelta(days=lookback + 60), now.date())
            bars = await self.daily_bars(ticker, start, end)
            reactions.append(measure_reaction({"ticker": ticker, "accession": e.accession,
                                               "acceptance_ts": e.acceptance_ts}, bars, bench_cache or [], p))
        hits, verdicts = screen_s2(reactions, p)
        recent = [h for h in hits if now - dt.timedelta(days=lookback) <= h.signal_ts <= now]
        hold = int(self.s("s2_hold_sessions", 10))
        written = 0
        for h in recent:
            r = h.reaction
            evidence = {"accession": r.accession, "acceptanceTs": r.acceptance_ts.isoformat(), "day0": r.day0,
                        "day1": r.day1, "abnormalReturn": r.abnormal_return, "stockReturn": r.stock_return,
                        "benchReturn": r.bench_return, "benchmark": bench_sym, "volumeRatio": r.volume_ratio,
                        "rank": h.rank, "of": h.of, "cutoffRank": h.cutoff_rank,
                        "exitDate": add_sessions(h.entry_date, hold - 1)}
            cik = next((e.issuer_cik for e in events if e.accession == r.accession), None)
            if await self._record(S2_KIND, h.key, r.ticker, cik, h.signal_ts, h.entry_date, evidence, now):
                written += 1
        return {"events": len(events), "measured": sum(1 for r in reactions if r.abnormal_return is not None),
                "skipped": skipped[:50], "hits": len(hits), "recent": len(recent), "new": written,
                "verdicts": verdicts[:200]}

    @staticmethod
    def _last_closed_session(now: dt.datetime) -> str:
        d = now.date()
        if mcal.is_trading_day(d) and now.hour * 60 + now.minute >= mcal.session_close_minutes(d):
            return d.isoformat()
        return mcal.previous_trading_day(d).isoformat()

    # ------------------------------------------------------------------ gates + record
    async def evaluate_gates(self, kind: str, ticker: str, cik: str | None, signal_ts: dt.datetime,
                             entry_date: str | None, exit_date: str | None, now: dt.datetime) -> dict:
        gp = self.gate_params()
        sig_et = signal_ts.astimezone(ET)
        last_close_day = self._last_closed_session(sig_et)
        bars = await self.daily_bars(ticker, dt.date.fromisoformat(last_close_day) - dt.timedelta(days=60),
                                     dt.date.fromisoformat(last_close_day))
        daily = []
        for b in sorted(bars or [], key=lambda b: b.ts):
            d = dt.datetime.fromtimestamp(b.ts / 1000, ET).date().isoformat()
            if d <= last_close_day:
                daily.append((float(b.close), float(b.volume or 0)))
        close = daily[-1][0] if daily else None
        gates: dict[str, dict] = {"price": gate_price(close, gp), "adv": gate_adv(daily, gp)}
        spread, why = await self.entry_spread_pct(ticker, entry_date, now)
        gates["spread"] = gate_spread(spread, gp, pending_why=why)
        mcap, mwhy = await self.market_cap(cik, close, sig_et.date().isoformat())
        gates["marketCap"] = gate_market_cap(mcap, gp, why_unknown=mwhy)
        if kind in (S1_KIND, S1_UNCLASSIFIED_KIND):
            dates, src = await self.earnings_dates(ticker, cik, sig_et.date().isoformat())
            gates["earningsInHold"] = gate_earnings_in_hold(entry_date, exit_date, dates, gp, source=src)
        sd = sig_et.date().isoformat()
        start = (sig_et.date() - dt.timedelta(days=gp.corp_action_days or 0)).isoformat()
        gates["corporateActions"] = gate_corporate_actions(await self.corporate_actions(ticker, start, sd), sd, gp)
        gates["tipsMention"] = gate_tips_mention(
            await self.tips_mentions(ticker, signal_ts - dt.timedelta(days=gp.tips_mention_days or 0), signal_ts), gp)
        return gates

    async def _record(self, kind, key, ticker, cik, signal_ts, entry_date, evidence, now) -> bool:
        """Insert a new candidate (journaled) - an existing key is left alone (idempotent)."""
        if not ticker:
            ticker = "?"
        async with self.engine.sf() as s:
            exists = (await s.execute(select(ScoutCandidate.id).where(ScoutCandidate.key == key))).scalar_one_or_none()
        if exists:
            return False
        gates = await self.evaluate_gates(kind, ticker, cik, signal_ts, entry_date, evidence.get("exitDate"), now)
        status = overall(gates)
        cid = new_id()
        row = ScoutCandidate(id=cid, key=key, kind=kind, ticker=ticker, issuer_cik=cik, signal_ts=signal_ts,
                             signal_date=signal_ts.astimezone(ET).date().isoformat(), entry_date=entry_date,
                             status=status, evidence=_jsonable(evidence), gates=_jsonable(gates),
                             config=self.config_snapshot(), created_at=utcnow(), updated_at=utcnow())
        async with self.engine.sf() as s:
            s.add(row)
            await s.commit()
        await self.engine.journal.append(ev.SCOUT_CANDIDATE_FOUND, {
            "technique": "scout", "candidateId": cid, "key": key, "kind": kind, "ticker": ticker,
            "signalTs": signal_ts.isoformat(), "entryDate": entry_date, "evidence": _jsonable(evidence),
            "screenVersion": SCREEN_VERSION}, aggregate_type="scout", aggregate_id=cid)
        await self.engine.journal.append(ev.SCOUT_GATE_RESULT, {
            "technique": "scout", "candidateId": cid, "kind": kind, "ticker": ticker, "status": status,
            "gates": _jsonable(gates), "stage": "found"}, aggregate_type="scout", aggregate_id=cid)
        return True

    async def recheck_spreads(self, now: dt.datetime) -> dict:
        """Candidates whose spread gate is still unknown and whose entry session has opened:
        measure the entry spread now (journaled as a new ScoutGateResult)."""
        lo = (now.date() - dt.timedelta(days=10)).isoformat()
        async with self.engine.sf() as s:
            rows = (await s.execute(select(ScoutCandidate).where(
                ScoutCandidate.entry_date >= lo, ScoutCandidate.entry_date <= now.date().isoformat()))).scalars().all()
        gp = self.gate_params()
        changed = 0
        for c in rows:
            g = dict(c.gates or {})
            if (g.get("spread") or {}).get("status") != "unknown":
                continue
            spread, why = await self.entry_spread_pct(c.ticker, c.entry_date, now)
            if spread is None:
                continue
            g["spread"] = gate_spread(spread, gp)
            status = overall(g)
            async with self.engine.sf() as s:
                row = await s.get(ScoutCandidate, c.id)
                row.gates = _jsonable(g)
                row.status = status
                row.updated_at = utcnow()
                await s.commit()
            await self.engine.journal.append(ev.SCOUT_GATE_RESULT, {
                "technique": "scout", "candidateId": c.id, "kind": c.kind, "ticker": c.ticker, "status": status,
                "gates": _jsonable(g), "stage": "spread_recheck"}, aggregate_type="scout", aggregate_id=c.id)
            changed += 1
        return {"checked": len(rows), "updated": changed}

    # ------------------------------------------------------------------ default fact providers
    async def _daily_bars(self, symbol: str, start: dt.date, end: dt.date) -> list:
        from ...marketstructure.history import HistoryError, fetch_window
        s_ms = int(dt.datetime.combine(start, dt.time(0, 0), ET).timestamp() * 1000)
        e_ms = int(dt.datetime.combine(end, dt.time(23, 59), ET).timestamp() * 1000)
        try:
            return await fetch_window(symbol, "1d", s_ms, e_ms)
        except (HistoryError, httpx.HTTPError) as exc:
            log.info("scout bars %s: %s", symbol, exc)
            return []

    def _alpaca_headers(self) -> dict | None:
        cfg = self.engine.config
        if not (cfg.alpaca_key_id and cfg.alpaca_secret):
            return None
        return {"APCA-API-KEY-ID": cfg.alpaca_key_id, "APCA-API-SECRET-KEY": cfg.alpaca_secret}

    async def _entry_spread_pct(self, symbol: str, entry_date: str | None, now: dt.datetime) -> tuple[float | None, str]:
        """Median quoted spread (% of mid) over 09:35-09:40 ET of the entry session (Alpaca SIP quotes)."""
        if not entry_date:
            return None, "no entry date"
        start = dt.datetime.combine(dt.date.fromisoformat(entry_date), dt.time(9, 35), ET)
        if now < start + dt.timedelta(minutes=5):
            return None, f"pending: entry session {entry_date} 09:35-09:40 ET not reached"
        h = self._alpaca_headers()
        if h is None:
            return None, "no Alpaca data keys - spread unknown"
        params = {"start": start.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
                  "end": (start + dt.timedelta(minutes=5)).astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
                  "limit": 1000, "feed": "sip"}
        try:
            async with httpx.AsyncClient(timeout=20) as c:
                r = await c.get(f"https://data.alpaca.markets/v2/stocks/{symbol}/quotes", params=params, headers=h)
            if r.status_code >= 400:
                return None, f"Alpaca quotes HTTP {r.status_code}"
            qs = r.json().get("quotes") or []
        except (httpx.HTTPError, ValueError) as exc:
            return None, f"Alpaca quotes failed: {exc}"
        sp = [(q["ap"] - q["bp"]) / ((q["ap"] + q["bp"]) / 2) * 100 for q in qs
              if q.get("ap") and q.get("bp") and q["ap"] >= q["bp"] > 0]
        if not sp:
            return None, "no two-sided quotes 09:35-09:40 ET"
        return statistics.median(sp), f"median of {len(sp)} quotes"

    async def _market_cap(self, cik: str | None, close: float | None, as_of: str) -> tuple[float | None, str]:
        """SEC XBRL `dei:EntityCommonStockSharesOutstanding` (latest cover-page fact FILED on or
        before `as_of`, all classes of that date summed) x the last close."""
        if not cik or not close:
            return None, "no CIK or close"
        data = self._shares_cache.get(cik)
        if data is None:
            client = self.edgar_factory()
            try:
                data = await client.shares_outstanding(cik) or {}
            except EdgarError as exc:
                return None, f"SEC shares fact failed: {exc}"
            finally:
                await client.aclose()
            self._shares_cache[cik] = data
        return shares_market_cap(data, close, as_of)

    async def _submissions(self, cik: str) -> dict | None:
        if cik in self._submissions_cache:
            return self._submissions_cache[cik]
        client = self.edgar_factory()
        try:
            data = await client.submissions(cik)
        except EdgarError:
            data = None
        finally:
            await client.aclose()
        self._submissions_cache[cik] = data
        return data

    async def _earnings_dates(self, ticker: str, cik: str | None, as_of: str) -> tuple[list[str] | None, str]:
        """Upcoming earnings: the engine calendar (Yahoo, advisory) first; an empty answer is
        not "none" - fall back to projecting the issuer's 8-K item 2.02 cadence (last release
        + 84..98 days, every day in that fortnight counts); no history at all = unknown."""
        cal = getattr(self.engine, "calendar", None)
        if cal is not None:
            try:
                rec = await cal.get(ticker)
                fut = [d for d in rec.get("earnings") or [] if d >= as_of]
                if fut:
                    return fut, "yahoo calendar"
            except Exception:  # pragma: no cover - advisory source
                pass
        if not cik:
            return None, ""
        data = await self._submissions(cik)
        if not data:
            return None, ""
        r = (data.get("filings") or {}).get("recent") or {}
        dates = sorted(fd for f, it, fd in zip(r.get("form", []), r.get("items", []), r.get("filingDate", []))
                       if f == "8-K" and "2.02" in (it or "") and fd <= as_of)
        if not dates:
            return None, ""
        last = dt.date.fromisoformat(dates[-1])
        proj = [(last + dt.timedelta(days=k)).isoformat() for k in range(84, 99)]
        return proj, f"projected from 8-K 2.02 {dates[-1]}"

    async def _corporate_actions(self, symbol: str, start: str, end: str) -> list[dict] | None:
        h = self._alpaca_headers()
        if h is None:
            return None
        params = {"symbols": symbol, "types": "reverse_split,name_change", "start": start, "end": end, "limit": 1000}
        try:
            async with httpx.AsyncClient(timeout=20) as c:
                r = await c.get("https://data.alpaca.markets/v1/corporate-actions", params=params, headers=h)
            if r.status_code >= 400:
                return None
            ca = r.json().get("corporate_actions") or {}
        except (httpx.HTTPError, ValueError):
            return None
        out = [{"type": "reverse_split", "date": a.get("ex_date") or a.get("process_date"),
                "ratio": f"{a.get('old_rate')}:{a.get('new_rate')}"} for a in ca.get("reverse_splits") or []]
        out += [{"type": "symbol_change", "date": a.get("process_date"), "from": a.get("old_symbol"),
                 "to": a.get("new_symbol")} for a in ca.get("name_changes") or []]
        return out

    async def _tips_mentions(self, ticker: str, since: dt.datetime, until: dt.datetime) -> list[dict] | None:
        try:
            async with self.engine.sf() as s:
                rows = (await s.execute(select(Signal.id, Signal.source_name, Signal.created_at).where(
                    func.upper(Signal.ticker) == ticker.upper(), Signal.created_at >= since,
                    Signal.created_at <= until))).all()
        except Exception:  # pragma: no cover
            return None
        return [{"signalId": i, "source": src, "at": at.isoformat()} for i, src, at in rows]

    async def _ticker_for_cik(self, cik: str) -> str | None:
        if self._tickers is None:
            self._tickers = {}
            client = self.edgar_factory()
            try:
                r = await client.get("https://www.sec.gov/files/company_tickers.json")
                for row in (r.json() or {}).values():
                    self._tickers.setdefault(str(row.get("cik_str")), str(row.get("ticker")).upper())
            except (EdgarError, ValueError) as exc:
                log.warning("scout: company_tickers.json failed: %s", exc)
            finally:
                await client.aclose()
        return self._tickers.get(str(cik).lstrip("0"))

    # ------------------------------------------------------------------ reads
    async def candidates(self, *, days: int = 7, kind: str | None = None) -> list[dict]:
        lo = (dt.datetime.now(ET).date() - dt.timedelta(days=max(0, days))).isoformat()
        async with self.engine.sf() as s:
            q = select(ScoutCandidate).where(ScoutCandidate.signal_date >= lo)
            if kind:
                q = q.where(ScoutCandidate.kind == kind)
            rows = (await s.execute(q.order_by(ScoutCandidate.signal_ts.desc()))).scalars().all()
        return [candidate_dict(r) for r in rows]

    async def status(self) -> dict:
        sf = self.engine.sf
        datasets_done = await ing.get_state(sf, "datasets")
        daily_done = await ing.get_state(sf, "daily_days")
        backfill = await ing.get_state(sf, "backfill")
        async with sf() as s:
            cand = (await s.execute(select(ScoutCandidate.kind, ScoutCandidate.status, func.count())
                                    .group_by(ScoutCandidate.kind, ScoutCandidate.status))).all()
        return {
            "technique": "scout", "researchOnly": True, "screenVersion": SCREEN_VERSION,
            "enabled": {"daily": bool(self.s("daily_enabled", True)), "s1": bool(self.s("s1_insider_enabled", True)),
                        "s2": bool(self.s("s2_earnings_enabled", True))},
            "running": self.running,
            "lastRun": self.last_run or await ing.get_state(sf, "last_run") or None,
            "ingest": {"datasetsDone": sorted(datasets_done), "dailyDays": sorted(daily_done)[-15:],
                       "dailyDaysCount": len(daily_done),
                       "coverageStart": ing.coverage_start(datasets_done, daily_done),
                       "backfill": backfill or None, **(await ing.counts(sf))},
            "candidates": [{"kind": k, "status": st, "n": n} for k, st, n in cand],
            "config": self.config_snapshot(),
        }


def shares_market_cap(data: dict, close: float, as_of: str) -> tuple[float | None, str]:
    facts = (((data or {}).get("units") or {}).get("shares")) or []
    known = [f for f in facts if str(f.get("filed") or "") <= as_of and f.get("val")]
    if not known:
        return None, "no shares-outstanding fact filed before the signal"
    latest_end = max(str(f.get("end")) for f in known)
    same = {}
    for f in known:
        if str(f.get("end")) == latest_end:
            same[(f.get("accn"), f.get("frame"), f.get("val"))] = f   # dedupe repeats of one fact
    by_accn: dict[str, float] = {}
    for f in same.values():
        by_accn[f.get("accn")] = by_accn.get(f.get("accn"), 0.0) + float(f["val"])
    shares = max(by_accn.values())
    return shares * close, f"{shares:,.0f} shares (as of {latest_end}) x ${close:.2f}"


def _jsonable(v):
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if isinstance(v, dt.datetime):
        return v.isoformat()
    return v


def attach_scout_layer(engine) -> None:
    """Called from the FastAPI lifespan after the engine starts (registers the daily job only)."""
    if getattr(engine, "scout_service", None) is not None:
        return
    engine.scout_service = ScoutService(engine)
    engine.scout_service.start()
