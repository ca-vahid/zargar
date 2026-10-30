"""Scout agent (PLAN section 9, user decision 2026-10-14): a tool-using research agent that finds swing ideas
each morning and proposes trades for a SIMULATED research book - no human in the loop, never a broker.

Day (ET, weekdays):
  07:30  scout_agent         chart-read the universe (code), then each model lane runs: tools -> proposals ->
                             code checks -> research-book entries (pending) + the comparison lanes' entries
  10:00 .. 11:30             the existing Scout entry rule fills them (desk.attempt_entries; spread gate, limit
                             gate for limit plans), the position manager runs the exits
  16:30  scout_report        closed trades become cases (R, best/worst excursion, SPY over the hold)
  16:45 Fri scout_agent_review  one model call over the closed cases -> lessons, supplied from next Monday

Lanes (one shadow book each, $10k): agent_claude, agent_gpt (same tools, other model), agent_random (a
random twin per Claude pick drawn from the same screen, same geometry in ATR units), agent_screen (the
screen's top names on a fixed plan). The scorecard (agent_score) compares them; the gate decides nothing on
its own. Every decision is journaled (ScoutAgentRun, ScoutAgentProposal, ScoutAgentLesson, ScoutEntry).
"""
from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import json
import logging
import time
from typing import Any

from sqlalchemy import func, select

from ... import events as ev
from ...domain import new_id
from ...models import ScoutAgentLesson, ScoutAgentRun, ScoutCandidate, ScoutEntry, utcnow
from ...marketstructure import market_calendar as mcal
from . import agent_plan as ap
from . import agent_score as sc
from . import agent_tools as at
from . import analyst as an
from .form4 import ET

log = logging.getLogger("zargar.scout.agent")
TECHNIQUE_ID = "scout"
PROMPT_VERSION = "scout-agent-v2"    # v2 2026-10-21: a limit is worked 10:00-15:30 ET for 3 sessions
LANES = ("claude", "gpt")
BOOK_OF = {"claude": "agent_claude", "gpt": "agent_gpt"}
RANDOM_BOOK, SCREEN_BOOK = "agent_random", "agent_screen"
AGENT_BOOKS = ("agent_claude", "agent_gpt", RANDOM_BOOK, SCREEN_BOOK)
PICK_KIND, RANDOM_KIND, SCREEN_KIND = "agent_pick", "agent_random", "agent_screen"
PAPER_BOOK = "paper"          # PLAN 9.10: the same pick, entered on the configured paper book (never a live book)
AGENT_KINDS = (PICK_KIND, RANDOM_KIND, SCREEN_KIND)

# The screen's universe (2026-10-14): liquid US common stocks across sectors, large and mid caps. Fixed for the
# sample (a change is a new screen version); the day's price / dollar-volume floors still apply.
AGENT_UNIVERSE = (
    # technology / communication
    "AAPL", "MSFT", "NVDA", "AVGO", "AMD", "INTC", "QCOM", "TXN", "MU", "AMAT", "LRCX", "KLAC", "ADI", "MRVL", "ON",
    "ARM", "SMCI", "ORCL", "CRM", "ADBE", "NOW", "INTU", "PANW", "CRWD", "ZS", "NET", "DDOG", "SNOW", "PLTR", "SHOP",
    "UBER", "ABNB", "DASH", "PYPL", "SQ", "COIN", "HOOD", "META", "GOOGL", "NFLX", "DIS", "SPOT", "RBLX", "TTD", "APP",
    "DELL", "HPQ", "IBM", "CSCO", "ANET", "MDB", "TEAM", "WDAY", "DOCU", "ROKU", "SNAP", "PINS", "EA", "TTWO", "T",
    "VZ", "TMUS", "CMCSA",
    # consumer
    "AMZN", "TSLA", "HD", "LOW", "NKE", "SBUX", "MCD", "CMG", "LULU", "TGT", "WMT", "COST", "BKNG", "MAR", "GM", "F",
    "RIVN", "DKNG", "CAVA", "ELF", "DECK", "ULTA", "KO", "PEP", "PG", "MDLZ", "PM", "MO", "CL",
    # health care
    "LLY", "UNH", "JNJ", "MRK", "ABBV", "PFE", "BMY", "AMGN", "GILD", "VRTX", "REGN", "ISRG", "DXCM", "MRNA", "TMO",
    "ABT", "MDT", "CVS", "HIMS",
    # financials
    "JPM", "BAC", "WFC", "C", "GS", "MS", "SCHW", "AXP", "V", "MA", "BLK", "KKR", "APO", "SOFI", "AFRM",
    # industrials / energy / materials
    "CAT", "DE", "GE", "HON", "BA", "LMT", "RTX", "UPS", "FDX", "UNP", "ETN", "VRT", "PWR", "GEV", "XOM", "CVX", "COP",
    "OXY", "SLB", "HAL", "FCX", "NEM", "LIN", "NUE", "CEG", "VST", "NEE", "ENPH", "FSLR",
)

SYSTEM_PROMPT = """You are the Scout agent: an experienced, sceptical swing trader and equity analyst running a
SIMULATED research book of US shares. Each morning before the open you look for at most five long swing
trades (held 3 to 20 sessions) and propose them with a full plan. Proposing nothing is a valid, often correct
answer: a trade must earn its place.

How you work
- You see numbers, not pictures. Your tools compute everything: `chart` reads a daily chart (trend, averages,
  ranges, swing support/resistance levels, ATR, volume, returns against SPY, the last ten sessions);
  `fundamentals` gives the company's SEC fact sheet and its latest results release; `options_view` gives
  implied volatility and the expected move; `events` gives the next earnings date; `book` shows what the book
  holds; `past_cases` shows how your earlier picks ended. The idea screen and the book are already below.
- Never state a number you did not read from a tool result. Your own knowledge of a company is background
  only and may be outdated; prices and dates after your training are unknown to you except through tools.
- Look before you propose: call `chart` on every name you might propose (proposals for names you did not chart
  are refused), and check `events` - a report inside the hold cuts the horizon.
- Budget: about 20 tool calls. Then call `submit_proposals` exactly once; it ends the run.

What a proposal must contain (the code checks every one and refuses what fails)
- long only (shares, no shorting); entry "now" (bought between 10:00 and 11:30 ET today) or "limit" with a
  limit price at or below the last close (worked 10:00 to 15:30 ET today and the next two sessions, bought only
  if the price comes to it; the horizon still counts from today);
- a stop below the entry, 0.5 to 4 ATR away, placed where the idea is proven wrong (under support, not an
  arbitrary percentage); one or two ascending targets, the first at least 1.5R (R = entry - stop);
- a horizon of 3 to 20 sessions; a conviction from 1 (weak) to 5 (strong);
- a thesis, the invalidation (what would show you are wrong), and EVIDENCE: at least two items, each quoting
  a tool result verbatim (copy the exact text) with its result id, e.g. {"result_id": "T4", "quote": "trend:
  uptrend", "point": "the trend is up"}. Evidence that is not a verbatim quote is discarded.
Position size is set by code from the stop (1% of the book at risk per trade); you never choose a size.

What tends to matter: trend and relative strength, a clear level for the stop, room to the next resistance,
volume that confirms, no report inside the hold, a reward worth the risk after costs. What tends to hurt:
chasing extended moves (RSI far above 70, far above the 20-day average), stops inside daily noise, crowded
names with nothing specific, buying ahead of earnings. Your past cases and lessons outrank these generalities.
"""

TOOLS: list[dict] = [
    {"name": "chart", "description": "Daily chart read of one US ticker as numbers: trend, 20/50/200-day averages, "
     "ATR, returns vs SPY, RSI, ranges, swing support/resistance levels, volume, the last 10 sessions.",
     "input_schema": {"type": "object", "properties": {"ticker": {"type": "string"}}, "required": ["ticker"]}},
    {"name": "fundamentals", "description": "The company's SEC fact sheet (revenue, margins, cash flow, balance "
     "sheet, valuation, insider trades, recent filings) and an excerpt of its latest results release.",
     "input_schema": {"type": "object", "properties": {"ticker": {"type": "string"}}, "required": ["ticker"]}},
    {"name": "options_view", "description": "30-day implied volatility, the implied 1- and 10-session move and the "
     "at-the-money straddle for one ticker (delayed data).",
     "input_schema": {"type": "object", "properties": {"ticker": {"type": "string"}}, "required": ["ticker"]}},
    {"name": "events", "description": "The next earnings date(s) for one ticker and where the date comes from.",
     "input_schema": {"type": "object", "properties": {"ticker": {"type": "string"}}, "required": ["ticker"]}},
    {"name": "book", "description": "The research book: cash, equity, open positions with stops and targets.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "past_cases", "description": "Your closed picks (result in R, exit reason, best and worst move while "
     "open, SPY over the hold) and the active lessons from your weekly reviews.",
     "input_schema": {"type": "object", "properties": {"ticker": {"type": "string",
                                                                     "description": "optional: only this ticker"}}}},
    {"name": "submit_proposals", "description": "Submit today's proposals (0 to 3) and end the run.",
     "input_schema": {"type": "object", "properties": {
         "proposals": {"type": "array", "items": {"type": "object", "properties": {
             "ticker": {"type": "string"}, "side": {"type": "string", "enum": ["long"]},
             "entry": {"type": "object", "properties": {"kind": {"type": "string", "enum": ["now", "limit"]},
                                                        "limit_price": {"type": "number"}}, "required": ["kind"]},
             "stop": {"type": "number"}, "targets": {"type": "array", "items": {"type": "number"}},
             "horizon_sessions": {"type": "integer"}, "conviction": {"type": "integer"},
             "thesis": {"type": "string"}, "invalidation": {"type": "string"},
             "evidence": {"type": "array", "items": {"type": "object", "properties": {
                 "result_id": {"type": "string"}, "quote": {"type": "string"}, "point": {"type": "string"}},
                 "required": ["result_id", "quote"]}}},
             "required": ["ticker", "entry", "stop", "targets", "horizon_sessions", "conviction", "thesis",
                          "evidence"]}},
         "no_trade_reason": {"type": "string", "description": "when proposing nothing: why"}},
         "required": ["proposals"]}},
]

REVIEW_PROMPT = """You review the closed trades of a simulated swing-trading research book (the Scout agent's
own picks) and write LESSONS for its future runs. A lesson is one or two sentences of concrete, checkable
guidance (what to prefer or avoid, with the numbers that define it) that more than one closed case supports.
Every lesson must cite at least two case ids from the list. Do not restate generic trading advice; do not
write a lesson from a single trade; prefer fewer, sharper lessons. You may retire an active lesson the cases
contradict. Reply with JSON only:
{"lessons": [{"text": "...", "cases": ["<case id>", "..."]}], "retire": ["<active lesson id>"], "summary": "..."}"""


def run_dict(r: ScoutAgentRun, *, full: bool = False) -> dict:
    d = {"id": r.id, "day": r.day, "lane": r.lane, "model": r.model, "status": r.status, "reason": r.reason,
         "proposals": r.proposals or [], "toolCalls": r.tool_calls, "tokensIn": r.tokens_in, "tokensOut": r.tokens_out,
         "cacheRead": r.cache_read, "cacheWrite": r.cache_write, "costUsd": r.cost_usd, "latencyMs": r.latency_ms,
         "lessonsVersion": r.lessons_version, "promptVersion": r.prompt_version,
         "createdAt": r.created_at.isoformat() if r.created_at else None}
    if full:
        d["transcript"] = r.transcript or []
        d["screen"] = r.screen or []
    return d


def lesson_dict(x: ScoutAgentLesson) -> dict:
    return {"id": x.id, "text": x.text, "cases": x.cases or [], "status": x.status, "effectiveFrom": x.effective_from,
            "retiredFrom": x.retired_from, "reviewDay": x.review_day}


class RunState:
    """One lane's run: tool results by id (the grounding corpus), the chart reads, the transcript."""

    def __init__(self) -> None:
        self.results: dict[str, str] = {}
        self.charts: dict[str, dict] = {}
        self.earnings: dict[str, list[str]] = {}
        self.transcript: list[dict] = []
        self.n = 0
        self.usage = {"in": 0, "out": 0, "cacheRead": 0, "cacheWrite": 0}
        self.cost = 0.0
        self.latency = 0.0
        self.submitted: dict | None = None

    def add(self, name: str, args: dict, text: str, *, max_chars: int = 12000) -> str:
        self.n += 1
        rid = f"T{self.n}"
        body = text[:max_chars] + ("\n[truncated]" if len(text) > max_chars else "")
        self.results[rid] = body
        self.transcript.append({"id": rid, "tool": name, "args": args, "text": body})
        return f"[{rid}] {body}"


class AgentDesk:
    def __init__(self, svc) -> None:
        self.svc = svc
        self.engine = svc.engine
        self.claude_client = None          # injectable (tests)
        self.openai_client = None
        self.options_view_of = self._options_view
        self._reads: dict[str, dict[str, dict]] = {}
        self._bars: dict[tuple[str, str], list] = {}
        self._running: set[str] = set()
        self.tasks: set = set()

    def s(self, key, default=None):
        return self.svc.s("agent_" + key, default)

    # ------------------------------------------------------------------ schedule
    def start(self) -> None:
        sch = self.engine.scheduler
        sch.register("scout_agent", str(self.s("at", "07:30")), self._sched_run)
        sch.register("scout_agent_review", str(self.s("review_at", "16:45")), self._sched_review)

    def stop(self) -> None:
        for name in ("scout_agent", "scout_agent_review"):
            with contextlib.suppress(Exception):
                self.engine.scheduler.unregister(name)

    async def _sched_run(self):
        now = dt.datetime.now(ET)
        if not bool(self.s("enabled", True)) or not mcal.is_trading_day(now.date()):
            return {"skipped": "off or not a session"}
        return await self.run_day(now)

    async def _sched_review(self):
        now = dt.datetime.now(ET)
        if not bool(self.s("enabled", True)) or not mcal.is_trading_day(now.date()):
            return {"skipped": "off or not a session"}
        nxt = mcal.next_trading_day(now.date())
        last_of_week = nxt.isocalendar()[1] != now.date().isocalendar()[1]
        if not last_of_week:
            return {"skipped": "the review runs on the week's last session"}
        return await self.review_week(now)

    # ------------------------------------------------------------------ data
    async def bars(self, ticker: str, day: str, days: int = 400) -> list:
        key = (ticker.upper(), day)
        if key not in self._bars:
            d = dt.date.fromisoformat(day)
            raw = await self.svc.daily_bars(ticker.upper(), d - dt.timedelta(days=days), d - dt.timedelta(days=1))
            self._bars[key] = [b for b in sorted(raw or [], key=lambda b: b.ts)
                               if dt.datetime.fromtimestamp(b.ts / 1000, ET).date() < d]
        return self._bars[key]

    def universe(self) -> list[str]:
        """Scout's own list (never another desk's) + `agent_universe_extra`; the price/liquidity floors are
        applied by the screen on the day's numbers."""
        extra = [str(t).upper() for t in (self.s("universe_extra", []) or [])]
        bench = str(self.svc.s("s2_benchmark", "SPY")).upper()
        return sorted({t for t in list(AGENT_UNIVERSE) + extra if t and t != bench})

    async def reads(self, day: str) -> dict[str, dict]:
        """Chart reads of the whole universe as of the previous close (cached per day)."""
        if day in self._reads:
            return self._reads[day]
        bench = await self.bars(str(self.svc.s("s2_benchmark", "SPY")), day)
        sem = asyncio.Semaphore(int(self.s("fetch_concurrency", 6)))

        async def one(t: str):
            async with sem:
                with contextlib.suppress(Exception):
                    return t, at.chart_read(await self.bars(t, day), bench)
                return t, {}

        out = dict(await asyncio.gather(*[one(t) for t in self.universe()]))
        self._reads = {day: out}
        self._bars = {k: v for k, v in self._bars.items() if k[1] == day}
        return out

    async def event_candidates(self, day: str) -> list[dict]:
        from .desk import pre_entry_status
        from .service import candidate_dict
        async with self.engine.sf() as s:
            rows = (await s.execute(select(ScoutCandidate).where(
                ScoutCandidate.entry_date == day,
                ScoutCandidate.kind.in_(("s1_insider", "s1_unclassified", "s2_earnings"))))).scalars().all()
        out = []
        for c in rows:
            cd = candidate_dict(c)
            if pre_entry_status(cd["gates"]) != "pass":
                continue
            what = ("insider-purchase cluster" if c.kind.startswith("s1") else "earnings reaction")
            ev_ = cd.get("evidence") or {}
            if c.kind.startswith("s1"):
                what += f": {len(ev_.get('insiders') or [])} insiders, ${float(ev_.get('totalValue') or 0):,.0f} bought"
            else:
                r = ev_.get("abnormalReturn")
                what += f": abnormal day-0..1 return {float(r) * 100:+.1f}%" if r is not None else ""
            out.append({"ticker": c.ticker, "what": what})
        return out

    async def lane_book(self, book: str) -> dict:
        from . import books as bk
        return await bk.ensure_book(self.engine, book, starting_cash=float(self.s("book_cash", 10_000.0)))

    async def book_text(self, book: str) -> tuple[str, set[str]]:
        p = await self.lane_book(book)
        pid = p["id"]
        eq = await self.engine.positions.equity(pid)
        async with self.engine.sf() as s:
            open_ = (await s.execute(select(ScoutEntry).where(ScoutEntry.book == book,
                                                              ScoutEntry.status.in_(("entered", "pending", "ordering")))
                                     )).scalars().all()
        held = {e.ticker.upper() for e in open_}
        lines = [f"research book {p.get('name')}: equity ${eq:,.2f}, cash ${float(p.get('cash') or 0):,.2f}; "
                 f"risk per trade {float(self.s('risk_pct', 1.0)):g}% of equity; max position "
                 f"{float(self.s('max_position_pct', 20.0)):g}% of equity"]
        for e in open_:
            plan = (e.config or {}).get("plan") or {}
            lines.append(f"- {e.ticker}: {e.status}" + (f", {e.qty:g} sh @ {e.entry_price:.2f}" if e.entry_price else "")
                         + f", stop {plan.get('stop') or e.stop_price}, targets {plan.get('targets')}, "
                           f"horizon {e.hold_sessions} sessions from {e.entry_date}")
        if not open_:
            lines.append("no open positions")
        return "\n".join(lines), held

    async def cases(self, *, books: tuple[str, ...] = AGENT_BOOKS, ticker: str | None = None,
                    limit: int = 60) -> list[dict]:
        from .desk import entry_dict
        q = select(ScoutEntry).where(ScoutEntry.book.in_(books), ScoutEntry.status == "closed") \
            .order_by(ScoutEntry.exit_ts.desc()).limit(limit)
        if ticker:
            q = q.where(ScoutEntry.ticker == ticker.upper())
        async with self.engine.sf() as s:
            rows = (await s.execute(q)).scalars().all()
        out = []
        for e in rows:
            d = entry_dict(e)
            d["case"] = (e.config or {}).get("case") or {}
            d["plan"] = (e.config or {}).get("plan") or {}
            d["r"] = sc.r_multiple(d)
            out.append(d)
        return out

    async def active_lessons(self, day: str) -> list[dict]:
        async with self.engine.sf() as s:
            rows = (await s.execute(select(ScoutAgentLesson).where(
                ScoutAgentLesson.status == "active", ScoutAgentLesson.effective_from <= day))).scalars().all()
        return [lesson_dict(x) for x in rows
                if not x.retired_from or x.retired_from > day][: int(self.s("max_lessons", 8))]

    async def cases_text(self, ticker: str | None, day: str) -> str:
        cs = await self.cases(books=(BOOK_OF["claude"], BOOK_OF["gpt"]), ticker=ticker, limit=40)
        lines = [f"closed picks{' for ' + ticker.upper() if ticker else ''}: {len(cs)}"]
        for c in cs:
            k = c["case"]
            r = c["r"]
            lines.append(f"- case {c['id'][:8]} {c['ticker']} {c['bookLabel']} entered {c['entryDate']} @ "
                         f"{c['entryPrice']}, exit {c['exitReason']}, result {'n/a' if r is None else f'{r:+.2f}R'}, "
                         f"best {k.get('mfeR', 'n/a')}R, worst {k.get('maeR', 'n/a')}R, SPY over the hold "
                         f"{'n/a' if k.get('spyRet') is None else f'{k['spyRet'] * 100:+.1f}%'}; thesis: "
                         f"{(c['plan'].get('thesis') or '')[:200]}")
        ls = await self.active_lessons(day)
        lines.append(f"active lessons: {len(ls)}")
        for x in ls:
            lines.append(f"- lesson {x['id'][:8]}: {x['text']}")
        return "\n".join(lines)

    async def _options_view(self, ticker: str) -> str:
        svc = getattr(self.engine, "options", None)
        if svc is None:
            return f"{ticker}: options data is not available."
        t = ticker.upper()
        try:
            ex = await asyncio.wait_for(svc.expiries(t), timeout=20)
            exps = [e for e in ex.get("expiries") or [] if e.get("dte", 0) >= 5]
            spot, iv30 = ex.get("spot"), ex.get("iv30")
            straddle, expiry, dte = None, None, None
            if exps:
                expiry, dte = exps[0]["date"], exps[0]["dte"]
                ch = await asyncio.wait_for(svc.chain(t, expiry), timeout=20)
                rows = [r for r in ch.get("rows") or [] if r.get("call") and r.get("put")]
                if rows and spot:
                    atm = min(rows, key=lambda r: abs(float(r["strike"]) - float(spot)))
                    cm, pm = float(atm["call"].get("mid") or 0), float(atm["put"].get("mid") or 0)
                    straddle = cm + pm if cm > 0 and pm > 0 else None
                    if iv30 is None:
                        ivs = [x for x in (atm["call"].get("iv"), atm["put"].get("iv")) if x]
                        iv30 = sum(ivs) / len(ivs) if ivs else None
            em = at.expected_move(spot=spot, straddle_mid=straddle, dte=dte, iv30=iv30)
            return at.render_options(t, em, expiry=expiry, provider=ex.get("provider"))
        except Exception as exc:                 # noqa: BLE001 - a tool failure is a tool result
            return f"{t}: options data failed ({type(exc).__name__})."

    # ------------------------------------------------------------------ tools
    async def run_tool(self, st: RunState, name: str, args: dict, day: str, book: str) -> str:
        t = str((args or {}).get("ticker") or "").upper().strip()[:12]
        try:
            if name == "chart":
                if not t:
                    return st.add(name, args, "ticker required")
                bench = await self.bars(str(self.svc.s("s2_benchmark", "SPY")), day)
                r = at.chart_read(await self.bars(t, day), bench)
                if r:
                    st.charts[t] = r
                return st.add(name, args, at.render_chart(t, r))
            if name == "fundamentals":
                g = await asyncio.wait_for(self.svc.dossier.gather(t, day), timeout=90)
                if g.get("error"):
                    return st.add(name, args, g["error"])
                from .dossier import render
                rel = (g.get("release") or "")[: int(self.s("release_chars", 4000))] or None
                return st.add(name, args, render(g["sheet"], rel, today=day))
            if name == "options_view":
                return st.add(name, args, await self.options_view_of(t))
            if name == "events":
                cik = None
                with contextlib.suppress(Exception):
                    hit = await self.svc.dossier.cik_for_ticker(t)
                    cik = hit[0] if hit else None
                dates, src = await self.svc.earnings_dates(t, cik, day)
                fut = sorted(d for d in (dates or []) if d >= day)[:4]
                st.earnings[t] = fut
                txt = (f"{t} next earnings date(s): {', '.join(fut)} ({src})" if fut
                       else f"{t} next earnings date: unknown (no calendar entry and no filing history)")
                return st.add(name, args, txt)
            if name == "book":
                txt, _ = await self.book_text(book)
                return st.add(name, args, txt)
            if name == "past_cases":
                return st.add(name, args, await self.cases_text(t or None, day))
        except Exception as exc:                 # noqa: BLE001
            return st.add(name, args, f"{name} failed: {type(exc).__name__}: {str(exc)[:200]}")
        return st.add(name, args, f"unknown tool {name}")

    # ------------------------------------------------------------------ budget
    async def spent_today(self, day: str) -> float:
        async with self.engine.sf() as s:
            v = (await s.execute(select(func.coalesce(func.sum(ScoutAgentRun.cost_usd), 0.0)).where(
                ScoutAgentRun.day == day))).scalar()
        return float(v or 0.0)

    def _client(self, lane: str):
        if lane == "claude":
            if self.claude_client is None:
                c, why = self.svc.desk._client(an.CLAUDE)
                if c is None:
                    return None, why
                self.claude_client = c
            return self.claude_client, None
        if self.openai_client is None:
            c, why = self.svc.desk._client(an.GPT)
            if c is None:
                return None, why
            self.openai_client = c
        return self.openai_client, None

    # ------------------------------------------------------------------ the day
    async def run_day(self, now: dt.datetime | None = None, *, lanes: tuple[str, ...] | None = None) -> dict:
        now = (now or dt.datetime.now(ET)).astimezone(ET)
        day = now.date().isoformat()
        if day in self._running:
            return {"skipped": "already running"}
        self._running.add(day)
        try:
            reads = await self.reads(day)
            rows = at.screen(reads, min_price=float(self.svc.s("gate_min_price", 5.0)),
                             min_adv_usd=float(self.svc.s("gate_min_adv_usd", 5e6)),
                             top=int(self.s("screen_top", 25)))
            extra = []
            with contextlib.suppress(Exception):
                extra = await self.event_candidates(day)
            screen_text = at.render_screen(rows, extra, universe=sum(1 for r in reads.values() if r))
            out: dict[str, Any] = {"day": day, "universe": len(reads), "screen": len(rows), "lanes": {}}
            for lane in lanes or LANES:
                if not bool(self.s(f"{lane}_enabled", True)):
                    out["lanes"][lane] = {"status": "skipped", "reason": f"techniques.scout.agent_{lane}_enabled is off"}
                    continue
                try:
                    out["lanes"][lane] = await self.run_lane(lane, now, rows, screen_text)
                except Exception as exc:         # noqa: BLE001 - one lane never fails the day
                    log.exception("scout agent lane %s failed", lane)
                    out["lanes"][lane] = {"status": "error", "reason": f"{type(exc).__name__}: {exc}"}
            if bool(self.s("screen_lane_enabled", True)):
                out["screenLane"] = await self.plan_screen_lane(day, now, rows)
            return out
        finally:
            self._running.discard(day)

    async def run_lane(self, lane: str, now: dt.datetime, rows: list[dict], screen_text: str) -> dict:
        day = now.date().isoformat()
        async with self.engine.sf() as s:
            prior = (await s.execute(select(ScoutAgentRun).where(ScoutAgentRun.day == day,
                                                                 ScoutAgentRun.lane == lane))).scalar_one_or_none()
            if prior is not None and prior.status not in ("error",):
                return run_dict(prior)
            if prior is not None:
                await s.delete(prior)
                await s.commit()
        model = str(self.s(f"{lane}_model", "claude-opus-5-5" if lane == "claude" else "gpt-6.1-sol"))
        run = ScoutAgentRun(id=new_id(), day=day, lane=lane, model=model, status="running", screen=rows,
                            prompt_version=PROMPT_VERSION, created_at=utcnow(), updated_at=utcnow())
        async with self.engine.sf() as s:
            s.add(run)
            await s.commit()
        rid = run.id
        book = BOOK_OF[lane]
        st = RunState()
        lessons = await self.active_lessons(day)
        lv = ap.lessons_version([x["text"] for x in lessons])
        book_txt, held = await self.book_text(book)
        intro = [f"Today is {day} (US session; you are running before the open; prices are as of the last close).",
                 st.add("screen", {}, screen_text), st.add("book", {}, book_txt)]
        if lessons:
            intro.append("Lessons from your weekly reviews (they outrank general advice):\n"
                         + "\n".join(f"- {x['text']}" for x in lessons))
        intro.append("Research, then call submit_proposals once.")
        client, why = self._client(lane)
        status, reason = "ok", None
        if client is None:
            status, reason = "skipped", why
        else:
            try:
                if lane == "claude":
                    await self._loop_claude(client, model, st, "\n\n".join(intro), day, book)
                else:
                    await self._loop_openai(client, model, st, "\n\n".join(intro), day, book)
            except BudgetStop as exc:
                status, reason = "budget", str(exc)
            except Exception as exc:             # noqa: BLE001
                log.exception("scout agent %s loop", lane)
                status, reason = "error", f"{type(exc).__name__}: {str(exc)[:300]}"
        proposals: list[dict] = []
        if st.submitted is not None:
            proposals = await self.accept(lane, day, now, st, rid, lv, held)
            if not any(p["check"]["ok"] for p in proposals) and status == "ok":
                status = "no_trade"
                reason = (st.submitted.get("no_trade_reason") or "no proposal passed the checks")[:1000]
        elif status == "ok":
            status, reason = "no_trade", "the run ended without submit_proposals"
        async with self.engine.sf() as s:
            r = await s.get(ScoutAgentRun, rid)
            r.status, r.reason, r.transcript, r.proposals = status, reason, st.transcript, proposals
            r.lessons_version, r.tool_calls = lv, max(0, st.n - 2)
            r.tokens_in, r.tokens_out = st.usage["in"], st.usage["out"]
            r.cache_read, r.cache_write = st.usage["cacheRead"], st.usage["cacheWrite"]
            r.cost_usd, r.latency_ms, r.updated_at = round(st.cost, 6), st.latency, utcnow()
            await s.commit()
            d = run_dict(r)
        await self.engine.journal.append(ev.SCOUT_AGENT_RUN, {
            "technique": TECHNIQUE_ID, **{k: d[k] for k in ("id", "day", "lane", "model", "status", "reason",
                                                            "toolCalls", "costUsd", "lessonsVersion", "promptVersion")},
            "accepted": [p["ticker"] for p in proposals if p["check"]["ok"]],
            "refused": [p["ticker"] for p in proposals if not p["check"]["ok"]]},
            aggregate_type="scout", aggregate_id=rid)
        return d

    # ------------------------------------------------------------------ provider loops
    def _limits(self) -> tuple[int, int, int, float]:
        return (int(self.s("max_turns", 16)), int(self.s("max_tool_calls", 24)), int(self.s("max_tokens", 12000)),
                float(self.s("call_timeout_s", 240.0)))

    async def _check_budget(self, st: RunState, day: str, model: str, chars: int, max_tokens: int) -> bool:
        """True when one more call fits the day's agent budget (worst case: every input token uncached)."""
        budget = float(self.s("budget_usd_day", 10.0) or 0)
        spent = await self.spent_today(day) + st.cost
        proj = an.projected_cost(model, chars, max_tokens, self.svc.s("llm_rates", {}) or {})
        return spent + proj <= budget

    def _charge(self, st: RunState, model: str, usage: dict, ms: float) -> None:
        for k in st.usage:
            st.usage[k] += int(usage.get(k, 0) or 0)
        st.cost += an.cost_usd(model, usage, self.svc.s("llm_rates", {}) or {})
        st.latency += ms

    async def _loop_claude(self, client, model: str, st: RunState, intro: str, day: str, book: str) -> None:
        max_turns, max_calls, max_tokens, timeout = self._limits()
        effort = str(self.s("claude_effort", "high"))
        system = [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}]
        messages: list[dict] = [{"role": "user", "content": [{"type": "text", "text": intro}]}]
        calls = 0
        tools_chars = len(json.dumps(TOOLS))
        for turn in range(max_turns):
            for m in messages:                   # one moving cache breakpoint on the newest user block
                if m["role"] == "user" and isinstance(m["content"], list):
                    for b in m["content"]:
                        if isinstance(b, dict):
                            b.pop("cache_control", None)
            messages[-1]["content"][-1]["cache_control"] = {"type": "ephemeral"}
            chars = len(SYSTEM_PROMPT) + tools_chars + sum(len(json.dumps(m["content"], default=str)) for m in messages)
            if not await self._check_budget(st, day, model, chars, max_tokens):
                raise BudgetStop(f"the agent budget (techniques.scout.agent_budget_usd_day "
                                 f"${float(self.s('budget_usd_day', 10.0)):g}) would be exceeded by the next call")
            kw: dict = dict(model=model, max_tokens=max_tokens, system=system, tools=TOOLS, messages=messages)
            if effort in ("low", "medium", "high", "xhigh", "max"):
                kw["output_config"] = {"effort": effort}
            t0 = time.perf_counter()
            resp = await asyncio.wait_for(client.messages.create(**kw), timeout=timeout)
            u = getattr(resp, "usage", None)
            self._charge(st, model, {"in": getattr(u, "input_tokens", 0) or 0, "out": getattr(u, "output_tokens", 0) or 0,
                                     "cacheRead": getattr(u, "cache_read_input_tokens", 0) or 0,
                                     "cacheWrite": getattr(u, "cache_creation_input_tokens", 0) or 0},
                         (time.perf_counter() - t0) * 1000)
            content = list(getattr(resp, "content", None) or [])
            messages.append({"role": "assistant", "content": content})
            uses = [b for b in content if getattr(b, "type", "") == "tool_use"]
            if not uses:
                if getattr(resp, "stop_reason", "") == "refusal":
                    raise RuntimeError("the provider declined the request")
                messages.append({"role": "user", "content": [{"type": "text", "text":
                                 "Call submit_proposals now (an empty list is fine)."}]})
                continue
            results = []
            for b in uses:
                args = dict(getattr(b, "input", None) or {})
                if b.name == "submit_proposals":
                    st.submitted = args
                    return
                calls += 1
                if calls > max_calls:
                    txt = f"tool budget used ({max_calls} calls): call submit_proposals now."
                else:
                    txt = await self.run_tool(st, b.name, args, day, book)
                results.append({"type": "tool_result", "tool_use_id": b.id, "content": txt})
            if turn >= max_turns - 2:
                results.append({"type": "text", "text": "Last turn: call submit_proposals now."})
            messages.append({"role": "user", "content": results})

    async def _loop_openai(self, client, model: str, st: RunState, intro: str, day: str, book: str) -> None:
        max_turns, max_calls, max_tokens, timeout = self._limits()
        effort = str(self.s("gpt_effort", "high"))
        tools = [{"type": "function", "name": t["name"], "description": t["description"],
                  "parameters": t["input_schema"]} for t in TOOLS]
        prev, inp, calls, chars = None, intro, 0, len(SYSTEM_PROMPT) + len(intro)
        for turn in range(max_turns):
            if not await self._check_budget(st, day, model, chars, max_tokens):
                raise BudgetStop("the agent budget would be exceeded by the next call")
            kw: dict = dict(model=model, instructions=SYSTEM_PROMPT, input=inp, tools=tools,
                            max_output_tokens=max_tokens)
            if prev:
                kw["previous_response_id"] = prev
            if effort in ("minimal", "low", "medium", "high", "xhigh"):
                kw["reasoning"] = {"effort": effort}
            t0 = time.perf_counter()
            resp = await asyncio.wait_for(client.responses.create(**kw), timeout=timeout)
            u = getattr(resp, "usage", None)
            self._charge(st, model, {"in": getattr(u, "input_tokens", 0) or 0, "out": getattr(u, "output_tokens", 0) or 0},
                         (time.perf_counter() - t0) * 1000)
            prev = getattr(resp, "id", None)
            fcs = [o for o in getattr(resp, "output", None) or [] if getattr(o, "type", "") == "function_call"]
            if not fcs:
                inp = "Call submit_proposals now (an empty list is fine)."
                continue
            outs = []
            for f in fcs:
                try:
                    args = json.loads(getattr(f, "arguments", "") or "{}")
                except ValueError:
                    args = {}
                if f.name == "submit_proposals":
                    st.submitted = args if isinstance(args, dict) else {"proposals": []}
                    return
                calls += 1
                txt = (f"tool budget used ({max_calls} calls): call submit_proposals now." if calls > max_calls
                       else await self.run_tool(st, f.name, args if isinstance(args, dict) else {}, day, book))
                outs.append({"type": "function_call_output", "call_id": f.call_id, "output": txt})
                chars += len(txt)
            if turn >= max_turns - 2:
                outs.append({"role": "user", "content": "Last turn: call submit_proposals now."})
            inp = outs

    # ------------------------------------------------------------------ checks -> entries
    def _sessions_ahead(self, day: str, n: int = 40) -> list[str]:
        d = dt.date.fromisoformat(day)
        out = []
        while len(out) < n:
            d += dt.timedelta(days=1)
            if mcal.is_trading_day(d):
                out.append(d.isoformat())
        return out

    def _limits_obj(self) -> ap.Limits:
        return ap.Limits(min_price=float(self.svc.s("gate_min_price", 5.0)),
                         min_adv_usd=float(self.svc.s("gate_min_adv_usd", 5e6)),
                         min_r1=float(self.s("min_r1", 1.5)), max_proposals=int(self.s("max_proposals", 3)))

    async def accept(self, lane: str, day: str, now: dt.datetime, st: RunState, run_id: str, lv: str,
                     held: set[str]) -> list[dict]:
        raw = (st.submitted or {}).get("proposals")
        raw = raw if isinstance(raw, list) else []
        lim = self._limits_obj()
        ahead = self._sessions_ahead(day)
        out, proposed = [], set()
        for p in raw[: lim.max_proposals * 2]:
            if not isinstance(p, dict):
                continue
            t = str(p.get("ticker") or "").upper().strip()
            earn = st.earnings.get(t)
            if earn is None:
                with contextlib.suppress(Exception):
                    dates, _src = await self.svc.earnings_dates(t, None, day)
                    earn = dates or []
            chk = ap.check(p, chart=st.charts.get(t), results=st.results, held=held, proposed=proposed,
                           earnings=earn, today=day, sessions_ahead=ahead, lim=lim)
            if chk.ok and len([x for x in out if x["check"]["ok"]]) >= lim.max_proposals:
                chk.ok, chk.reasons = False, [f"more than {lim.max_proposals} proposals: kept the first {lim.max_proposals}"]
            rec = {"ticker": chk.ticker, "proposal": p, "check": chk.to_dict()}
            if chk.ok:
                proposed.add(chk.ticker)
                rec["candidateId"] = await self._enqueue(PICK_KIND, BOOK_OF[lane], chk.ticker, day, now, chk.plan,
                                                         {"runId": run_id, "lane": lane, "lessonsVersion": lv,
                                                          "evidence": chk.evidence})
                if lane == "claude" and bool(self.s("random_lane_enabled", True)):
                    rec["twin"] = await self._twin(rec["candidateId"], chk.ticker, chk.plan, day, now, st)
            out.append(rec)
            await self.engine.journal.append(ev.SCOUT_AGENT_PROPOSAL, {
                "technique": TECHNIQUE_ID, "runId": run_id, "lane": lane, "ticker": chk.ticker, "ok": chk.ok,
                "reasons": chk.reasons, "notes": chk.notes, "plan": chk.plan, "evidence": chk.evidence,
                "droppedEvidence": chk.dropped_evidence, "candidateId": rec.get("candidateId"),
                "twin": rec.get("twin")}, aggregate_type="scout", aggregate_id=run_id)
        return out

    async def _enqueue(self, kind: str, book: str, ticker: str, day: str, now: dt.datetime, plan: dict,
                       evidence: dict) -> str | None:
        key = f"{kind}:{day}:{book}:{ticker}"[:160]
        async with self.engine.sf() as s:
            if (await s.execute(select(ScoutCandidate.id).where(ScoutCandidate.key == key))).scalar_one_or_none():
                return None
        cid = new_id()
        max_pct = float(self.s("max_position_pct", 20.0))
        if kind == SCREEN_KIND:
            # the screen lane adds names every session: its cap fits picks x horizon positions (PLAN 9.9)
            max_pct = ap.rolling_position_pct(max_pct, int(self.s("screen_lane_picks", 3)),
                                              int(self.s("screen_lane_horizon", 10)))
        cfg = {"plan": plan, "riskPct": float(self.s("risk_pct", 1.0)),
               "maxPositionPct": max_pct, **({"minOneShare": True} if kind == SCREEN_KIND else {}),
               "bookCash": float(self.s("book_cash", 10_000.0)), "promptVersion": PROMPT_VERSION,
               **self.svc.desk._rules_snapshot()}
        async with self.engine.sf() as s:
            s.add(ScoutCandidate(id=cid, key=key, kind=kind, ticker=ticker, issuer_cik=None, signal_ts=now,
                                 signal_date=day, entry_date=day, status="pass", evidence={**evidence, "plan": plan},
                                 gates={}, config=cfg, created_at=utcnow(), updated_at=utcnow()))
            await s.commit()
        await self.svc.desk._plan_entry(cid, book, ticker, day, int(plan["horizon"]), config=cfg)
        lanes = {x.strip() for x in str(self.svc.s("paper_lanes", "") or "").split(",") if x.strip()}
        if bool(self.svc.s("paper_enabled", False)) and book in lanes and not await self._paper_holds(ticker):
            # PLAN 9.10: the same pick and plan on the paper book, judged by the same entry rule at the same slot;
            # one paper position per name (2026-10-30: the agent and the screen both picked GILD -> two entries)
            await self.svc.desk._plan_entry(cid, PAPER_BOOK, ticker, day, int(plan["horizon"]),
                                            config={**cfg, "paper": True, "mirrorOf": book,
                                                    "riskPct": float(self.svc.s("paper_risk_pct", 1.0))})
        await self.engine.journal.append(ev.SCOUT_CANDIDATE_FOUND, {
            "technique": TECHNIQUE_ID, "candidateId": cid, "key": key, "kind": kind, "ticker": ticker,
            "entryDate": day, "evidence": {**evidence, "plan": plan}}, aggregate_type="scout", aggregate_id=cid)
        with contextlib.suppress(Exception):
            await self.engine.ensure_symbol(ticker)
        return cid

    async def _paper_holds(self, ticker: str) -> bool:
        """A paper entry for this name is already pending, ordering or held."""
        async with self.engine.sf() as s:
            return bool((await s.execute(select(func.count()).select_from(ScoutEntry).where(
                ScoutEntry.book == PAPER_BOOK, ScoutEntry.ticker == ticker,
                ScoutEntry.status.in_(("pending", "ordering", "entered"))))).scalar_one())

    async def _twin(self, cid: str | None, ticker: str, plan: dict, day: str, now: dt.datetime, st: RunState) -> dict:
        """The random twin: a name drawn (seeded by the pick) from the same screen + universe the agent saw,
        with the pick's geometry in ATR units on the twin's own chart."""
        reads = await self.reads(day)
        pool = [t for t, r in reads.items() if r and r.get("last", 0) >= float(self.svc.s("gate_min_price", 5.0))
                and (r.get("advUsd20") or 0) >= float(self.svc.s("gate_min_adv_usd", 5e6))]
        exclude = {ticker} | {x.upper() for x in st.charts}
        for attempt in range(10):
            tw = ap.draw_twin(f"{day}:{ticker}:{cid}", pool, exclude, attempt)
            if tw is None:
                break
            tp = ap.like_plan(plan, reads.get(tw) or {})
            if tp is None:
                exclude.add(tw)
                continue
            tcid = await self._enqueue(RANDOM_KIND, RANDOM_BOOK, tw, day, now, tp,
                                       {"matchedCandidateId": cid, "matchedTicker": ticker, "seedAttempt": attempt,
                                        "poolSize": len(pool), "method": "agent random twin v1 (same screen universe, "
                                                                         "same ATR geometry)"})
            return {"ticker": tw, "candidateId": tcid}
        return {"ticker": None, "why": "no eligible twin"}

    async def plan_screen_lane(self, day: str, now: dt.datetime, rows: list[dict]) -> dict:
        async with self.engine.sf() as s:                # once per day: a re-run never picks further down the list
            done = (await s.execute(select(ScoutCandidate.ticker).where(ScoutCandidate.kind == SCREEN_KIND,
                                                                        ScoutCandidate.signal_date == day))).scalars().all()
        if done:
            return {"picked": sorted(done), "already": True}
        reads = await self.reads(day)
        _txt, held = await self.book_text(SCREEN_BOOK)
        n = int(self.s("screen_lane_picks", 3))
        picked = []
        for r in rows:
            if len(picked) >= n:
                break
            if r["ticker"] in held:
                continue
            plan = ap.default_plan(reads.get(r["ticker"]) or {}, horizon=int(self.s("screen_lane_horizon", 10)))
            if plan is None:
                continue
            cid = await self._enqueue(SCREEN_KIND, SCREEN_BOOK, r["ticker"], day, now, plan,
                                      {"screenRank": rows.index(r) + 1, "score": r["score"]})
            if cid:
                picked.append(r["ticker"])
        return {"picked": picked}

    # ------------------------------------------------------------------ cases (16:30 report)
    async def enrich_cases(self) -> int:
        """Closed agent-lane entries without a case: R, best/worst excursion in R, SPY over the hold."""
        async with self.engine.sf() as s:
            rows = (await s.execute(select(ScoutEntry).where(ScoutEntry.book.in_(AGENT_BOOKS),
                                                             ScoutEntry.status == "closed"))).scalars().all()
        n = 0
        for e in rows:
            cfg = dict(e.config or {})
            if cfg.get("case") or not e.entry_ts or not e.entry_price:
                continue
            d0 = e.entry_ts.astimezone(ET).date()
            d1 = (e.exit_ts or utcnow()).astimezone(ET).date()
            case: dict = {"exitReason": e.exit_reason}
            try:
                raw = await self.svc.daily_bars(e.ticker, d0, d1)
                spy = await self.svc.daily_bars(str(self.svc.s("s2_benchmark", "SPY")), d0 - dt.timedelta(days=7), d1)
            except Exception:                    # noqa: BLE001
                raw, spy = [], []
            risk = (float(e.entry_price) - float(e.stop_price or 0)) if e.stop_price else None
            hold = [b for b in raw or [] if d0 <= dt.datetime.fromtimestamp(b.ts / 1000, ET).date() <= d1]
            if hold and risk and risk > 0:
                case["mfeR"] = round((max(float(b.high) for b in hold) - float(e.entry_price)) / risk, 2)
                case["maeR"] = round((min(float(b.low) for b in hold) - float(e.entry_price)) / risk, 2)
            sp = sorted(spy or [], key=lambda b: b.ts)
            before = [b for b in sp if dt.datetime.fromtimestamp(b.ts / 1000, ET).date() < d0]
            through = [b for b in sp if dt.datetime.fromtimestamp(b.ts / 1000, ET).date() <= d1]
            if before and through:
                case["spyRet"] = round(float(through[-1].close) / float(before[-1].close) - 1.0, 5)
            if e.exit_price:
                case["ret"] = round(float(e.exit_price) / float(e.entry_price) - 1.0, 5)
                if case.get("spyRet") is not None:
                    case["excessVsSpy"] = round(case["ret"] - case["spyRet"], 5)
            case["sessions"] = len(hold)
            cfg["case"] = case
            async with self.engine.sf() as s:
                row = await s.get(ScoutEntry, e.id)
                row.config = cfg
                row.updated_at = utcnow()
                await s.commit()
            n += 1
        return n

    # ------------------------------------------------------------------ weekly review (P4)
    async def review_week(self, now: dt.datetime | None = None) -> dict:
        now = (now or dt.datetime.now(ET)).astimezone(ET)
        day = now.date().isoformat()
        await self.enrich_cases()
        cs = await self.cases(books=(BOOK_OF["claude"], BOOK_OF["gpt"]), limit=80)
        if len(cs) < int(self.s("review_min_cases", 4)):
            return {"skipped": f"{len(cs)} closed cases (min {int(self.s('review_min_cases', 4))})"}
        async with self.engine.sf() as s:
            if (await s.execute(select(ScoutAgentRun.id).where(ScoutAgentRun.day == day,
                                                              ScoutAgentRun.lane == "review"))).scalar_one_or_none():
                return {"skipped": "already reviewed today"}
        active = await self.active_lessons(day)
        ids = {c["id"][:8]: c["id"] for c in cs}
        lines = ["CLOSED CASES"]
        for c in cs:
            k, p = c["case"], c["plan"]
            lines.append(f"case {c['id'][:8]} | {c['ticker']} | {c['bookLabel']} | entered {c['entryDate']} | "
                         f"result {c['r'] if c['r'] is None else round(c['r'], 2)}R | exit {c['exitReason']} | best "
                         f"{k.get('mfeR')}R worst {k.get('maeR')}R | SPY {k.get('spyRet')} | stop {p.get('stopAtr')} ATR | "
                         f"targets {p.get('targetsR')}R | horizon {p.get('horizon')} | conviction {p.get('conviction')} | "
                         f"thesis: {(p.get('thesis') or '')[:300]}")
        lines.append("ACTIVE LESSONS")
        lines += [f"lesson {x['id'][:8]}: {x['text']}" for x in active] or ["(none)"]
        user = "\n".join(lines)
        model = str(self.s("claude_model", "claude-opus-5-5"))
        client, why = self._client("claude")
        run = ScoutAgentRun(id=new_id(), day=day, lane="review", model=model, status="running",
                            prompt_version="scout-agent-review-v1", created_at=utcnow(), updated_at=utcnow())
        async with self.engine.sf() as s:
            s.add(run)
            await s.commit()
        st = RunState()
        status, reason, added, retired = "ok", None, [], []
        if client is None:
            status, reason = "skipped", why
        elif not await self._check_budget(st, day, model, len(REVIEW_PROMPT) + len(user), 8000):
            status, reason = "budget", "the agent budget would be exceeded"
        else:
            try:
                res = await an.call_claude(client, model=model, effort="high", system=REVIEW_PROMPT, user=user,
                                           max_tokens=8000, cache=False, timeout_s=240)
                self._charge(st, model, res.usage, res.latency_ms)
                obj = an.parse_json(res.text)
                nxt = self._next_week_start(now.date())
                act = {x["id"][:8]: x["id"] for x in active}
                for L in (obj.get("lessons") or [])[: int(self.s("max_lessons", 8))]:
                    cited = [ids[c[:8]] for c in (L.get("cases") or []) if str(c)[:8] in ids]
                    text = str(L.get("text") or "").strip()[:600]
                    if len(set(cited)) < 2 or not text:
                        continue
                    lid = new_id()
                    async with self.engine.sf() as s:
                        s.add(ScoutAgentLesson(id=lid, text=text, cases=sorted(set(cited)), status="active",
                                               effective_from=nxt, review_day=day, created_at=utcnow()))
                        await s.commit()
                    added.append({"id": lid, "text": text, "cases": sorted(set(cited))})
                for rid_ in obj.get("retire") or []:
                    full = act.get(str(rid_)[:8])
                    if not full:
                        continue
                    async with self.engine.sf() as s:
                        x = await s.get(ScoutAgentLesson, full)
                        x.retired_from = nxt
                        x.status = "retired"
                        await s.commit()
                    retired.append(full)
                reason = str(obj.get("summary") or "")[:1000] or None
            except Exception as exc:             # noqa: BLE001
                status, reason = "error", f"{type(exc).__name__}: {str(exc)[:300]}"
        async with self.engine.sf() as s:
            r = await s.get(ScoutAgentRun, run.id)
            r.status, r.reason = status, reason
            r.proposals = [{"lessons": added, "retired": retired}]
            r.tokens_in, r.tokens_out = st.usage["in"], st.usage["out"]
            r.cost_usd, r.latency_ms, r.updated_at = round(st.cost, 6), st.latency, utcnow()
            await s.commit()
        for x in added:
            await self.engine.journal.append(ev.SCOUT_AGENT_LESSON, {"technique": TECHNIQUE_ID, "stage": "active",
                                                                     **x, "effectiveFrom": self._next_week_start(now.date())},
                                             aggregate_type="scout", aggregate_id=x["id"])
        for x in retired:
            await self.engine.journal.append(ev.SCOUT_AGENT_LESSON, {"technique": TECHNIQUE_ID, "stage": "retired",
                                                                     "id": x}, aggregate_type="scout", aggregate_id=x)
        return {"status": status, "reason": reason, "added": len(added), "retired": len(retired)}

    @staticmethod
    def _next_week_start(d: dt.date) -> str:
        n = d + dt.timedelta(days=(7 - d.weekday()))
        while not mcal.is_trading_day(n):
            n += dt.timedelta(days=1)
        return n.isoformat()

    # ------------------------------------------------------------------ reads (API / report)
    async def runs(self, *, limit: int = 20) -> list[dict]:
        async with self.engine.sf() as s:
            rows = (await s.execute(select(ScoutAgentRun).order_by(ScoutAgentRun.created_at.desc()).limit(limit))
                    ).scalars().all()
        return [run_dict(r) for r in rows]

    async def run(self, rid: str) -> dict | None:
        async with self.engine.sf() as s:
            r = await s.get(ScoutAgentRun, rid)
        return run_dict(r, full=True) if r else None

    async def lessons(self) -> list[dict]:
        async with self.engine.sf() as s:
            rows = (await s.execute(select(ScoutAgentLesson).order_by(ScoutAgentLesson.created_at.desc()))).scalars().all()
        return [lesson_dict(x) for x in rows]

    async def scorecard(self, today: str | None = None) -> dict:
        from .desk import entry_dict
        today = today or dt.datetime.now(ET).date().isoformat()
        async with self.engine.sf() as s:
            rows = (await s.execute(select(ScoutEntry).where(ScoutEntry.book.in_(AGENT_BOOKS)))).scalars().all()
        by: dict[str, list[dict]] = {b: [] for b in AGENT_BOOKS}
        for e in rows:
            if e.status == "closed":
                d = entry_dict(e)
                d["case"] = (e.config or {}).get("case") or {}
                by[e.book].append(d)
        lanes = {b: {**sc.lane_stats(v), "open": sum(1 for e in rows if e.book == b and e.status == "entered"),
                     "pending": sum(1 for e in rows if e.book == b and e.status in ("pending", "ordering"))}
                 for b, v in by.items()}
        start = str(self.s("sample_start", "2026-10-15"))
        g = sc.gate(by["agent_claude"], by[RANDOM_BOOK], start=start, today=today)
        return {"lanes": lanes, "vsScreen": sc.clustered_diff(by["agent_claude"], by[SCREEN_BOOK]),
                "gptVsRandom": sc.clustered_diff(by["agent_gpt"], by[RANDOM_BOOK]), "gate": g,
                "sampleStart": start}

    async def summary(self, day: str) -> dict:
        await self.enrich_cases()
        async with self.engine.sf() as s:
            runs = (await s.execute(select(ScoutAgentRun).where(ScoutAgentRun.day == day))).scalars().all()
        card = await self.scorecard(day)
        return {"runs": [{k: run_dict(r)[k] for k in ("lane", "status", "reason", "toolCalls", "costUsd")}
                         | {"accepted": [p["ticker"] for p in r.proposals or [] if (p.get("check") or {}).get("ok")]}
                         for r in runs],
                "spentUsd": round(await self.spent_today(day), 4),
                "budgetUsd": float(self.s("budget_usd_day", 10.0)),
                "lanes": card["lanes"], "gate": {"passed": card["gate"]["passed"], "verdict": card["gate"]["verdict"]}}


class BudgetStop(Exception):
    pass
