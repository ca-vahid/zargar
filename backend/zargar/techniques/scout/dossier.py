"""Scout dossier - an on-demand research note for ONE ticker (research only, never a signal, never an order).

Division of labour, kept deliberately simple so the note cannot invent numbers:

1. CODE gathers and computes every number: SEC XBRL fundamentals (`fundamentals.py`), daily-bar price
   statistics, valuation ratios, Form 4 open-market activity on file, filings and the next earnings date.
   Each becomes a FACT with an id (F1, F2, ...). A number the code could not establish is absent - the
   sheet says "not reported", it never estimates.
2. ONE model call writes the note from the fact sheet plus the latest results press release (source R1).
   Every point must cite fact ids or quote R1 verbatim.
3. CODE grounds the reply: unknown fact ids and quotes that are not in R1 are removed; a point left with
   no citation is dropped and kept on the record as dropped. The model's one-paragraph company background
   is the only uncited text and is labelled as unchecked.

Unlike the analyst lanes (analyst.py) nothing is masked: the note is read by a person, it is not a tested
signal and it feeds no book. Everything except `DossierDesk` is pure.
"""
from __future__ import annotations

import datetime as dt
import logging
import math
import re
import statistics
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from . import analyst as an
from . import fundamentals as fu
from .form4 import ET

log = logging.getLogger("zargar.scout.dossier")

PROMPT_VERSION = "scout-dossier-v1"
RELEASE_ID = "R1"
LEANS = ("constructive", "neutral", "cautious")
SECTIONS = {"strengths": 6, "concerns": 6, "valuation": 3, "watch": 5}     # section -> max points kept
MAX_QUESTIONS = 4

ITEM_NAMES = {
    "1.01": "material agreement", "1.02": "agreement terminated", "1.03": "bankruptcy", "2.01": "acquisition or disposal",
    "2.02": "results", "2.03": "new debt obligation", "2.05": "restructuring", "2.06": "impairment",
    "3.01": "listing notice", "3.02": "unregistered share sale", "4.01": "auditor change",
    "4.02": "prior statements unreliable", "5.01": "change of control", "5.02": "officer or director change",
    "5.03": "bylaw change", "5.07": "shareholder vote", "7.01": "disclosure", "8.01": "other event",
    "9.01": "exhibits",
}

SYSTEM_PROMPT = """You are an experienced, sceptical equity research analyst writing a short research note
for one private investor who buys shares (long only) and holds for weeks to months.

You are given a FACT SHEET: numbered facts (F1, F2, ...) computed by software from SEC filings and price
data, and possibly source R1, the company's latest results press release. These are your ONLY sources.

Rules - the system enforces them:
- Every point cites the facts it rests on by id ("facts": ["F3", "F12"]) and/or one VERBATIM quote copied
  character-for-character from R1 ("quote"). A point with no valid citation is deleted.
- Never state a number that is not in a cited fact or in your R1 quote. Do not compute new ratios; the
  fact sheet already holds the ones that could be established. "not reported" means unknown - do not guess.
- No price targets, no forecasts of the share price, no instruction to buy or sell. You give a LEAN
  (constructive / neutral / cautious) on the evidence shown, with a confidence of 1-5.
- Weigh the evidence like a professional: growth and its trend, margins, cash generation, balance-sheet
  strength, dilution, valuation against that quality, what insiders did, price behaviour, and what is
  coming up. Say what is weak or missing; a balanced note is worth more than an enthusiastic one.
- "background" is the one place for general knowledge: one or two sentences on what the company does. It
  is shown to the reader as unchecked. If you are not sure, write "unknown".
- "questions" are things the fact sheet cannot answer that a careful investor would look up next.
- Plain language, short sentences, no jargon without a reason.

Answer with ONE JSON object and nothing else:
{"background": "what the company does (unchecked)",
 "summary": "three sentences at most: the situation and what matters most",
 "lean": "constructive" | "neutral" | "cautious",
 "confidence": integer 1-5,
 "leanWhy": {"text": "one sentence", "facts": ["F.."]},
 "strengths": [{"text": "...", "facts": ["F.."], "quote": "optional verbatim R1 text"}],
 "concerns": [{"text": "...", "facts": ["F.."], "quote": "optional"}],
 "valuation": [{"text": "...", "facts": ["F.."]}],
 "watch": [{"text": "an upcoming event or a number to track", "facts": ["F.."], "quote": "optional"}],
 "questions": ["..."]}
At most 6 strengths, 6 concerns, 3 valuation points, 5 watch items, 4 questions."""


# --------------------------------------------------------------------------- formatting
def money(v: float | None, cur: str | None = "USD") -> str:
    if v is None:
        return "not reported"
    sym = "$" if (cur or "USD") == "USD" else f"{cur} "
    a, sign = abs(v), "-" if v < 0 else ""
    if a >= 1e9:
        return f"{sign}{sym}{a / 1e9:,.2f}B"
    if a >= 1e6:
        return f"{sign}{sym}{a / 1e6:,.1f}M"
    if a >= 1e3:
        return f"{sign}{sym}{a / 1e3:,.0f}K"
    return f"{sign}{sym}{a:,.2f}"


def pct(x: float | None, *, signed: bool = True) -> str:
    if x is None or not math.isfinite(x):
        return "n/a"
    return f"{x * 100:+.1f}%" if signed else f"{x * 100:.1f}%"


def mult(x: float | None) -> str:
    return "n/a" if x is None or not math.isfinite(x) else f"{x:.1f}x"


@dataclass
class Fact:
    id: str
    group: str
    label: str
    value: str
    as_of: str | None = None
    tone: str | None = None            # good | bad | None - a display hint only, set by simple sign rules

    def to_dict(self) -> dict:
        return {"id": self.id, "group": self.group, "label": self.label, "value": self.value, "asOf": self.as_of,
                "tone": self.tone}

    def line(self) -> str:
        return f"[{self.id}] {self.label}: {self.value}" + (f" (as of {self.as_of})" if self.as_of else "")


class Sheet:
    def __init__(self) -> None:
        self.facts: list[Fact] = []

    def add(self, group: str, label: str, value: str, *, as_of: str | None = None, tone: str | None = None) -> Fact:
        f = Fact(f"F{len(self.facts) + 1}", group, label, value, as_of, tone)
        self.facts.append(f)
        return f


def _tone(x: float | None) -> str | None:
    return None if x is None or x == 0 else ("good" if x > 0 else "bad")


# --------------------------------------------------------------------------- price statistics (pure)
def _sma(xs: Sequence[float], n: int) -> float | None:
    return sum(xs[-n:]) / n if len(xs) >= n else None


def _ret(xs: Sequence[float], n: int) -> float | None:
    return xs[-1] / xs[-1 - n] - 1.0 if len(xs) > n and xs[-1 - n] > 0 else None


def bar_day(b) -> str:
    return dt.datetime.fromtimestamp(b.ts / 1000, ET).date().isoformat()


def price_stats(bars: Sequence, bench: Sequence | None = None) -> dict:
    """Statistics from DAILY bars, oldest first. Anything the history is too short for is None."""
    b = sorted(bars or [], key=lambda x: x.ts)
    if len(b) < 2:
        return {}
    c = [float(x.close) for x in b]
    year = b[-252:]
    hi, lo = max(float(x.high) for x in year), min(float(x.low) for x in year)
    trs = [max(float(x.high) - float(x.low), abs(float(x.high) - float(p.close)), abs(float(x.low) - float(p.close)))
           for p, x in zip(b[-15:-1], b[-14:])]
    rets = [math.log(c[i] / c[i - 1]) for i in range(max(1, len(c) - 60), len(c)) if c[i - 1] > 0 and c[i] > 0]
    peak, dd = -1.0, 0.0
    for x in year:
        peak = max(peak, float(x.close))
        dd = min(dd, float(x.close) / peak - 1.0)
    adv = [float(x.close) * float(x.volume or 0) for x in b[-20:]]
    out = {"last": c[-1], "lastDate": bar_day(b[-1]), "sessions": len(b),
           "ret": {k: _ret(c, n) for k, n in (("1m", 21), ("3m", 63), ("6m", 126), ("12m", 252))},
           "high52": hi, "low52": lo, "fromHigh": c[-1] / hi - 1.0 if hi > 0 else None,
           "fromLow": c[-1] / lo - 1.0 if lo > 0 else None, "yearSessions": len(year),
           "sma50": _sma(c, 50), "sma200": _sma(c, 200),
           "atrPct": (sum(trs) / len(trs) / c[-1]) if len(trs) == 14 and c[-1] > 0 else None,
           "vol60": statistics.pstdev(rets) * math.sqrt(252) if len(rets) >= 30 else None,
           "maxDrawdown": dd, "advUsd": sum(adv) / len(adv) if adv else None, "bench": {}}
    if bench:
        bc = [float(x.close) for x in sorted(bench, key=lambda x: x.ts)]
        out["bench"] = {k: _ret(bc, n) for k, n in (("1m", 21), ("3m", 63), ("6m", 126), ("12m", 252))}
    return out


def price_chart(bars: Sequence, bench: Sequence | None = None, *, sessions: int = 252) -> dict:
    """The last `sessions` closes with their 50- and 200-session averages (None until enough history) and
    the benchmark rebased to the stock's first shown close."""
    b = sorted(bars or [], key=lambda x: x.ts)
    c = [float(x.close) for x in b]
    lo = max(0, len(b) - sessions)
    def ma(i: int, n: int):
        return round(sum(c[i - n + 1:i + 1]) / n, 4) if i - n + 1 >= 0 else None
    pts = [{"d": bar_day(b[i]), "c": round(c[i], 4), "ma50": ma(i, 50), "ma200": ma(i, 200)} for i in range(lo, len(b))]
    if bench and pts:
        by = {bar_day(x): float(x.close) for x in bench}
        base = by.get(pts[0]["d"])
        if base:
            for p in pts:
                v = by.get(p["d"])
                p["bench"] = round(v / base * pts[0]["c"], 4) if v else None
    return {"points": pts}


# --------------------------------------------------------------------------- the fact sheet (pure)
def is_financial(sic: str | int | None) -> bool:
    try:
        return 6000 <= int(sic) <= 6799
    except (TypeError, ValueError):
        return False


def _fresh(end: str | None, anchor: str | None, days: int = 130) -> bool:
    if not end or not anchor:
        return False
    return (dt.date.fromisoformat(anchor) - dt.date.fromisoformat(end)).days <= days


def anchor_date(series: Mapping[str, fu.Series]) -> str | None:
    """The latest period any core statement covers - everything older than ~a quarter before it is stale."""
    ends = [max(s.quarters) for s in (series["revenue"], series["netIncome"]) if s.quarters]
    ends += [max(s.annuals) for s in (series["revenue"], series["netIncome"]) if s.annuals]
    ends += [e for e in (series["assets"].latest_point()[0],) if e]
    return max(ends) if ends else None


def _quarter_rows(s: fu.Series, anchor: str | None, n: int = 8) -> list[dict]:
    ends = [e for e in sorted(s.quarters) if _fresh(e, anchor, 130 + 92 * n)][-n:]
    if not ends or not _fresh(ends[-1], anchor):
        return []
    return [{"end": e, "value": s.quarters[e]["value"], "derived": s.quarters[e]["derived"], "yoy": s.yoy(e)}
            for e in ends]


def _point(s: fu.Series, anchor: str | None) -> tuple[str | None, float | None]:
    e, v = s.latest_point()
    return (e, v) if _fresh(e, anchor) else (None, None)


def _ttm(s: fu.Series, anchor: str | None) -> tuple[float | None, str]:
    v, basis = s.ttm()
    end = basis.rsplit(" ", 1)[-1] if v is not None else None
    if v is None or not _fresh(end, anchor, 380):
        return None, "not reported"
    return v, basis


def build_sheet(*, ticker: str, profile: Mapping, series: Mapping[str, fu.Series] | None, px: Mapping,
                market_cap: float | None, market_cap_why: str = "", insiders: Mapping | None = None,
                filings: Sequence[Mapping] = (), earnings: tuple[list[str] | None, str] = (None, ""),
                candidates: Sequence[Mapping] = (), today: str | None = None) -> tuple[Sheet, dict]:
    """(facts, charts). `profile` = {name, sic, sicDescription, fiscalYearEnd, exchanges}."""
    sh = Sheet()
    charts: dict[str, Any] = {}
    today = today or dt.datetime.now(ET).date().isoformat()
    fin = is_financial(profile.get("sic"))

    # ---- company
    sh.add("company", "Company", f"{profile.get('name') or ticker} ({ticker})")
    if profile.get("sicDescription"):
        sh.add("company", "Industry (SEC classification)", str(profile["sicDescription"]))
    if profile.get("exchanges"):
        sh.add("company", "Listed on", ", ".join(profile["exchanges"]))

    # ---- price
    if px:
        last, ld = px["last"], px["lastDate"]
        sh.add("price", "Last close", f"${last:,.2f}", as_of=ld)
        for k, name in (("1m", "1 month"), ("3m", "3 months"), ("6m", "6 months"), ("12m", "12 months")):
            r, br = px["ret"].get(k), (px.get("bench") or {}).get(k)
            if r is None:
                continue
            v = pct(r) + (f"; S&P 500 (SPY) {pct(br)}; difference {pct(r - br)}" if br is not None else "")
            sh.add("price", f"Price change over {name}", v, as_of=ld, tone=_tone(r - (br or 0.0)))
        span = "52-week" if px["yearSessions"] >= 250 else f"{px['yearSessions']}-session"
        sh.add("price", f"{span} range", f"low ${px['low52']:,.2f}, high ${px['high52']:,.2f}; last close is "
               f"{pct(px['fromHigh'])} from the high and {pct(px['fromLow'])} from the low", as_of=ld)
        for n, key in ((50, "sma50"), (200, "sma200")):
            if px.get(key):
                d = last / px[key] - 1.0
                sh.add("price", f"Against its {n}-session average", f"{pct(d)} ({'above' if d >= 0 else 'below'} "
                       f"${px[key]:,.2f})", as_of=ld, tone=_tone(d))
        if px.get("atrPct") is not None:
            sh.add("price", "Typical daily range (14-session ATR)", pct(px["atrPct"], signed=False) + " of the price",
                   as_of=ld)
        if px.get("vol60") is not None:
            sh.add("price", "Volatility (60 sessions, annualised)", pct(px["vol60"], signed=False), as_of=ld)
        sh.add("price", f"Deepest fall from a peak within the {span} window", pct(px["maxDrawdown"]), as_of=ld)
        if px.get("advUsd"):
            sh.add("price", "Average daily traded value (20 sessions)", money(px["advUsd"]), as_of=ld)

    # ---- fundamentals
    cur = fu.currency(series) if series else None
    anchor = anchor_date(series) if series else None
    if not series or not anchor:
        sh.add("growth", "Financial statements", "none on file in the SEC's structured data for this company")
    else:
        if (dt.date.fromisoformat(today) - dt.date.fromisoformat(anchor)).days > 200:
            sh.add("growth", "Data warning", f"the latest statement period on file ends {anchor} - the figures below "
                   f"are stale", tone="bad")
        if cur and cur != "USD":
            sh.add("growth", "Reporting currency", f"{cur} - valuation ratios against the US-dollar share price are "
                   f"not computed")
        rev, ni = series["revenue"], series["netIncome"]
        rq, nq = _quarter_rows(rev, anchor), _quarter_rows(ni, anchor)
        if rq:
            r0 = rq[-1]
            sh.add("growth", "Revenue, latest quarter", f"{money(r0['value'], cur)}; {pct(r0['yoy'])} against the "
                   f"same quarter a year earlier" + (" (quarter derived from cumulative filings)" if r0["derived"] else ""),
                   as_of=r0["end"], tone=_tone(r0["yoy"]))
            trend = [f"{r['end']}: {pct(r['yoy'])}" for r in rq[-5:-1] if r["yoy"] is not None]
            if trend:
                sh.add("growth", "Revenue growth in the quarters before it (year over year, oldest first)",
                       "; ".join(trend))
        rt, rb = _ttm(rev, anchor)
        if rt is not None:
            sh.add("growth", "Revenue, trailing twelve months", f"{money(rt, cur)} ({rb})")
        fy = [(e, v) for e, v in sorted(rev.annuals.items()) if _fresh(e, anchor, 365 * 4)][-4:]
        if len(fy) >= 2:
            parts = [f"FY to {e}: {money(v, cur)}" + (f" ({pct(v / p - 1)})" if p and p > 0 else "")
                     for (e, v), p in zip(fy[1:], [x[1] for x in fy])]
            sh.add("growth", "Revenue by fiscal year (growth on the year before)", "; ".join(parts))
        if nq:
            n0 = nq[-1]
            prev = next((r["value"] for r in nq if 350 <= (dt.date.fromisoformat(n0["end"])
                         - dt.date.fromisoformat(r["end"])).days <= 380), None)
            sh.add("profit", "Net income, latest quarter", money(n0["value"], cur)
                   + (f"; same quarter a year earlier {money(prev, cur)}" if prev is not None else ""),
                   as_of=n0["end"], tone=_tone(n0["value"]))
        nt, nb = _ttm(ni, anchor)
        if nt is not None:
            sh.add("profit", "Net income, trailing twelve months", f"{money(nt, cur)} ({nb})", tone=_tone(nt))

        def margin(name: str, s: fu.Series) -> None:
            q = _quarter_rows(s, anchor)
            if not q or not rq:
                return
            rv = {r["end"]: r["value"] for r in rq}
            e = q[-1]["end"]
            if not rv.get(e):
                return
            m0 = q[-1]["value"] / rv[e]
            prior = next(((x["value"] / rv[x["end"]]) for x in q if rv.get(x["end"]) and 350 <= (
                dt.date.fromisoformat(e) - dt.date.fromisoformat(x["end"])).days <= 380), None)
            sh.add("profit", f"{name} margin, latest quarter", pct(m0, signed=False)
                   + (f"; a year earlier {pct(prior, signed=False)}" if prior is not None else ""), as_of=e,
                   tone=_tone(m0 - prior) if prior is not None else None)
        margin("Gross", series["grossProfit"])
        margin("Operating", series["operatingIncome"])
        if nt is not None and rt:
            sh.add("profit", "Net margin, trailing twelve months", pct(nt / rt, signed=False), tone=_tone(nt))

        ocf, ob = _ttm(series["operatingCashFlow"], anchor)
        cap, cb = _ttm(series["capex"], anchor)
        fcf = None
        if fin:
            sh.add("cash", "Cash flow", "not shown: operating cash flow and debt measures are not meaningful for a "
                   "financial company (deposits and lending run through them)")
        elif ocf is not None:
            sh.add("cash", "Cash from operations, trailing twelve months", f"{money(ocf, cur)} ({ob})", tone=_tone(ocf))
            if cap is not None and ob == cb:
                fcf = ocf - abs(cap)
                sh.add("cash", "Free cash flow, trailing twelve months (cash from operations minus capital spending "
                       f"of {money(abs(cap), cur)})", money(fcf, cur) + (f"; {pct(fcf / rt, signed=False)} of revenue"
                                                                        if rt and fcf > 0 else ""), tone=_tone(fcf))

        ce, cash = _point(series["cash"], anchor)
        de, debt = _point(series["longTermDebt"], anchor)
        ee, eq = _point(series["equity"], anchor)
        ae, assets = _point(series["assets"], anchor)
        le, liab = _point(series["liabilities"], anchor)
        if cash is not None:
            sh.add("balance", "Cash and equivalents", money(cash, cur), as_of=ce)
        if not fin:
            if debt is not None:
                sh.add("balance", f"Long-term debt (as tagged: {series['longTermDebt'].tag}; leases and short-term "
                       f"borrowings may be outside it)", money(debt, cur), as_of=de)
                if cash is not None:
                    nd = debt - cash
                    sh.add("balance", "Long-term debt minus cash", money(nd, cur) + (" (net cash)" if nd < 0 else ""),
                           as_of=max(ce, de), tone=_tone(-nd))
                    if ocf and ocf > 0 and nd > 0:
                        sh.add("balance", "Long-term debt minus cash, as years of cash from operations",
                               f"{nd / ocf:.1f} years")
            else:
                sh.add("balance", "Long-term debt", "not reported under the standard tags")
        if eq is not None:
            sh.add("balance", "Shareholders' equity", money(eq, cur), as_of=ee, tone=_tone(eq))
        if assets and liab is not None:
            sh.add("balance", "Liabilities as a share of assets", pct(liab / assets, signed=False), as_of=ae)
        dq = _quarter_rows(series["dilutedShares"], anchor)
        if dq and dq[-1]["yoy"] is not None:
            y = dq[-1]["yoy"]
            sh.add("balance", "Diluted share count against a year earlier", f"{pct(y)} "
                   f"({'more shares: dilution' if y > 0.005 else 'fewer shares: buybacks' if y < -0.005 else 'about flat'})",
                   as_of=dq[-1]["end"], tone=_tone(-y) if abs(y) > 0.005 else None)

        # ---- valuation (US-dollar reporters with a known market value)
        if market_cap and (cur in (None, "USD")):
            sh.add("valuation", "Market value", f"{money(market_cap)} ({market_cap_why})")
            if nt is not None:
                sh.add("valuation", "Price to earnings (market value / trailing net income)",
                       mult(market_cap / nt) if nt > 0 else "not meaningful: trailing net income is negative")
            if rt:
                sh.add("valuation", "Price to sales (market value / trailing revenue)", mult(market_cap / rt))
            if eq is not None:
                sh.add("valuation", "Price to book (market value / shareholders' equity)",
                       mult(market_cap / eq) if eq > 0 else "not meaningful: equity is negative")
            if fcf is not None:
                sh.add("valuation", "Free cash flow yield (trailing free cash flow / market value)",
                       pct(fcf / market_cap, signed=False) if fcf > 0 else "not meaningful: free cash flow is negative")
            if not fin and debt is not None and cash is not None and rt:
                sh.add("valuation", "Enterprise value to sales (market value + long-term debt - cash, over trailing "
                       "revenue; approximate)", mult((market_cap + debt - cash) / rt))
        elif not market_cap:
            sh.add("valuation", "Market value", f"unknown ({market_cap_why or 'no share count on file'}) - no "
                   f"valuation ratios")

        charts["quarters"] = [{"end": r["end"], "revenue": r["value"], "revenueYoy": r["yoy"],
                               "netIncome": next((n["value"] for n in nq if n["end"] == r["end"]), None)} for r in rq]
        charts["currency"] = cur or "USD"

    # ---- insiders (open-market Form 4 rows on file)
    if insiders is not None:
        for win, label in (("d90", "last 90 days"), ("d365", "last 12 months")):
            w = insiders.get(win) or {}
            b, s = w.get("buys") or {}, w.get("sells") or {}
            def side(verb: str, x: Mapping) -> str:
                if not x.get("n"):
                    return f"no open-market {verb}"
                return (f"{verb}: {money(x.get('value') or 0)} in {x['n']} trade{'s' if x['n'] != 1 else ''} by "
                        f"{x.get('insiders', 0)} insider{'s' if x.get('insiders') != 1 else ''}")
            sh.add("insiders", f"Insider open-market trades, {label}", f"{side('buying', b)}; {side('selling', s)}",
                   tone=_tone((b.get("value") or 0) - (s.get("value") or 0)) if (b.get("n") or s.get("n")) else None)
        if insiders.get("coverageStart"):
            sh.facts[-1].as_of = None
            sh.add("insiders", "Insider data on file since", str(insiders["coverageStart"]))

    # ---- events
    dates, src = earnings
    fut = [d for d in (dates or []) if d >= today]
    if fut:
        sh.add("events", "Next results date", (fut[0] if "projected" not in src else f"expected between {fut[0]} and "
               f"{fut[-1]}") + f" ({src})")
    else:
        sh.add("events", "Next results date", "unknown")
    recent = [f for f in filings if f.get("form") == "8-K"][:8]
    if recent:
        sh.add("events", "Recent 8-K reports (newest first)", "; ".join(
            f"{f['filed']}: " + (", ".join(ITEM_NAMES.get(i, f'item {i}') for i in f.get("items") or []
                                           if i != "9.01") or "unspecified") for f in recent))
    for form in ("10-K", "10-Q"):
        last_f = next((f for f in filings if f.get("form") == form), None)
        if last_f:
            sh.add("events", f"Latest {form} filed", last_f["filed"])
    for c in list(candidates)[:3]:
        sh.add("events", "Scout screen", f"flagged {c.get('signalDate')} as "
               f"{'an insider cluster' if str(c.get('kind', '')).startswith('s1') else 'an earnings reaction'} "
               f"(gates: {c.get('status')})")
    return sh, charts


def insider_summary(rows: Sequence[Mapping], today: str) -> dict:
    """Open-market buys (P) and sells (S) by window, de-duplicated on `row_key` (joint filings repeat rows)."""
    t = dt.date.fromisoformat(today)
    out: dict[str, Any] = {}
    for key, days in (("d90", 90), ("d365", 365)):
        lo = (t - dt.timedelta(days=days)).isoformat()
        agg = {}
        for code, name in (("P", "buys"), ("S", "sells")):
            seen, value, who = set(), 0.0, set()
            for r in rows:
                if r.get("trans_code") != code or not (lo <= str(r.get("trans_date") or "") <= today):
                    continue
                who.add(r.get("insider_cik"))
                if r.get("row_key") in seen:
                    continue
                seen.add(r.get("row_key"))
                value += float(r.get("value") or 0.0)
            agg[name] = {"n": len(seen), "value": value, "insiders": len(who)}
        out[key] = agg
    return out


def recent_filings(submissions: Mapping | None, *, limit: int = 60) -> list[dict]:
    r = ((submissions or {}).get("filings") or {}).get("recent") or {}
    out = []
    for form, filed, items, acc in zip(r.get("form", []), r.get("filingDate", []), r.get("items", []),
                                       r.get("accessionNumber", [])):
        if form in ("8-K", "10-K", "10-Q", "20-F", "40-F", "6-K"):
            out.append({"form": form, "filed": filed, "accession": acc,
                        "items": [i.strip() for i in str(items or "").split(",") if i.strip()]})
        if len(out) >= limit:
            break
    return out


def profile_of(submissions: Mapping | None, ticker: str) -> dict:
    d = submissions or {}
    return {"name": d.get("name"), "sic": d.get("sic"), "sicDescription": d.get("sicDescription"),
            "fiscalYearEnd": d.get("fiscalYearEnd"), "exchanges": [e for e in d.get("exchanges") or [] if e],
            "ticker": ticker}


# --------------------------------------------------------------------------- prompt + grounding (pure)
GROUP_TITLES = {"company": "COMPANY", "price": "PRICE", "growth": "GROWTH", "profit": "PROFITABILITY",
                "cash": "CASH FLOW", "balance": "BALANCE SHEET", "valuation": "VALUATION", "insiders": "INSIDERS",
                "events": "EVENTS"}


def render(sheet: Sheet, release: str | None, *, today: str) -> str:
    out = [f"Today is {today}.", "", "FACT SHEET"]
    for g, title in GROUP_TITLES.items():
        fs = [f for f in sheet.facts if f.group == g]
        if fs:
            out += ["", title] + [f.line() for f in fs]
    if release:
        out += ["", f"SOURCE {RELEASE_ID} - latest results press release (verbatim excerpt)", "<<<", release, ">>>"]
    else:
        out += ["", f"No results press release is available; source {RELEASE_ID} does not exist."]
    return "\n".join(out)


def _point_ok(p: Any, ids: set[str], release_norm: str, min_quote: int = 8) -> tuple[dict | None, str]:
    if not isinstance(p, dict) or not str(p.get("text") or "").strip():
        return None, "not a point"
    cited = p.get("facts") if isinstance(p.get("facts"), list) else []
    facts = [str(x).strip().strip("[]") for x in cited]
    good = [f for f in dict.fromkeys(facts) if f in ids]
    q = str(p.get("quote") or "").strip()
    quote_ok = bool(q) and len(an._norm(q)) >= min_quote and an._norm(q) in release_norm
    if not good and not quote_ok:
        why = "cites no fact on the sheet" if not q else "quote not found verbatim in the release, and no valid fact"
        return None, why
    return {"text": str(p["text"]).strip()[:700], "facts": good, "quote": q[:500] if quote_ok else None}, ""


def ground(obj: Mapping, sheet: Sheet, release: str | None) -> dict:
    """Validate the reply. Raises ValueError when it is not a note at all (no lean, no surviving point)."""
    ids = {f.id for f in sheet.facts}
    rn = an._norm(release or "")
    lean = str(obj.get("lean") or "").strip().lower()
    if lean not in LEANS:
        raise ValueError(f"lean must be one of {LEANS}, got {obj.get('lean')!r}")
    try:
        conf = max(1, min(5, int(obj.get("confidence"))))
    except (TypeError, ValueError):
        conf = None
    note: dict[str, Any] = {"lean": lean, "confidence": conf, "summary": str(obj.get("summary") or "").strip()[:900],
                            "background": str(obj.get("background") or "").strip()[:500]}
    dropped: list[dict] = []
    why, w = _point_ok(obj.get("leanWhy"), ids, rn)
    note["leanWhy"] = why
    if why is None and obj.get("leanWhy"):
        dropped.append({"section": "leanWhy", "point": obj.get("leanWhy"), "why": w})
    kept = 0
    for sec, cap in SECTIONS.items():
        pts = []
        for p in (obj.get(sec) if isinstance(obj.get(sec), list) else []):
            ok, w = _point_ok(p, ids, rn)
            if ok is None:
                dropped.append({"section": sec, "point": p, "why": w})
            elif len(pts) < cap:
                pts.append(ok)
        note[sec] = pts
        kept += len(pts)
    if kept == 0:
        raise ValueError("no point survived grounding")
    note["questions"] = [str(q).strip()[:300] for q in (obj.get("questions") if isinstance(obj.get("questions"), list)
                                                        else []) if str(q).strip()][:MAX_QUESTIONS]
    return {"note": note, "dropped": dropped}


# --------------------------------------------------------------------------- orchestration
class DossierDesk:
    """Gathers the facts, makes the one call, stores the result. Its spend has its OWN daily cap
    (`techniques.scout.dossier_budget_usd_day`) so on-demand notes can never starve the analyst lanes."""

    def __init__(self, svc) -> None:
        self.svc = svc
        self.engine = svc.engine
        self._tasks: set = set()
        self._tickers: dict[str, tuple[str, str]] | None = None      # ticker -> (cik, title)
        self.company_facts = self._company_facts                     # tests replace these
        self.cik_for_ticker = self._cik_for_ticker
        self.insider_rows = self._insider_rows
        self.call = self._call

    def s(self, key, default=None):
        return self.svc.s(key, default)

    # ---- providers
    async def _cik_for_ticker(self, ticker: str) -> tuple[str, str] | None:
        if self._tickers is None:
            client = self.svc.edgar_factory()
            try:
                r = await client.get("https://www.sec.gov/files/company_tickers.json")
                self._tickers = {str(row.get("ticker")).upper(): (str(row.get("cik_str")), str(row.get("title") or ""))
                                 for row in (r.json() or {}).values()}
            finally:
                await client.aclose()
        return self._tickers.get(ticker.upper()) or self._tickers.get(ticker.upper().replace(".", "-"))

    async def _company_facts(self, cik: str) -> dict | None:
        client = self.svc.edgar_factory()
        try:
            return await client.company_facts(cik)
        finally:
            await client.aclose()

    async def _insider_rows(self, cik: str, since: str) -> list[dict]:
        from sqlalchemy import select
        from ...models import ScoutInsiderTrade as T
        async with self.engine.sf() as s:
            rows = (await s.execute(select(T.row_key, T.insider_cik, T.trans_code, T.trans_date, T.value).where(
                T.issuer_cik.in_([str(cik), str(cik).lstrip("0"), f"{int(cik):010d}"]), T.trans_date >= since))).all()
        return [{"row_key": a, "insider_cik": b, "trans_code": c, "trans_date": d, "value": e} for a, b, c, d, e in rows]

    def _cfg(self) -> tuple[str, str, int]:
        return (str(self.s("dossier_model", "claude-opus-5-5")), str(self.s("dossier_effort", "high")),
                int(self.s("dossier_max_tokens", 12000)))

    async def _call(self, user: str) -> an.CallResult:
        client, why = self.svc.desk._client(an.CLAUDE)
        if client is None:
            raise RuntimeError(why or "no Claude client")
        model, effort, max_tokens = self._cfg()
        return await an.call_claude(client, model=model, effort=effort, system=SYSTEM_PROMPT, user=user,
                                    max_tokens=max_tokens, cache=bool(self.s("prompt_cache", True)),
                                    timeout_s=float(self.s("dossier_timeout_s", 240.0)))

    # ---- store
    async def spent_today(self, day: str) -> float:
        from sqlalchemy import func, select
        from ...models import ScoutDossier
        async with self.engine.sf() as s:
            v = (await s.execute(select(func.coalesce(func.sum(ScoutDossier.cost_usd), 0.0)).where(
                ScoutDossier.day == day))).scalar()
        return float(v or 0.0)

    async def _update(self, did: str, **fields) -> None:
        from ...models import ScoutDossier, utcnow
        async with self.engine.sf() as s:
            row = await s.get(ScoutDossier, did)
            for k, v in fields.items():
                setattr(row, k, v)
            row.updated_at = utcnow()
            await s.commit()

    async def get(self, did: str) -> dict | None:
        from ...models import ScoutDossier
        async with self.engine.sf() as s:
            row = await s.get(ScoutDossier, did)
        return dossier_dict(row, full=True) if row else None

    async def list(self, *, limit: int = 30, ticker: str | None = None) -> list[dict]:
        from sqlalchemy import select
        from ...models import ScoutDossier
        q = select(ScoutDossier).order_by(ScoutDossier.created_at.desc()).limit(limit)
        if ticker:
            q = q.where(ScoutDossier.ticker == ticker.upper())
        async with self.engine.sf() as s:
            rows = (await s.execute(q)).scalars().all()
        return [dossier_dict(r, full=False) for r in rows]

    # ---- run
    async def request(self, ticker: str, *, refresh: bool = False, wait: bool = False) -> dict:
        """Start (or reuse) today's dossier for `ticker`. Returns the row at once (status `running`)."""
        import asyncio
        from sqlalchemy import select
        from ...domain import new_id
        from ...models import ScoutDossier, utcnow
        t = re.sub(r"[^A-Z0-9.\-]", "", str(ticker or "").upper())[:12]
        if not t:
            raise ValueError("ticker required")
        if not bool(self.s("dossier_enabled", True)):
            raise ValueError("techniques.scout.dossier_enabled is off")
        day = dt.datetime.now(ET).date().isoformat()
        async with self.engine.sf() as s:
            prior = (await s.execute(select(ScoutDossier).where(ScoutDossier.ticker == t, ScoutDossier.day == day)
                                     .order_by(ScoutDossier.created_at.desc()))).scalars().first()
            if prior is not None and not refresh and (prior.status in ("ok", "facts_only") or (
                    prior.status == "running" and (utcnow() - prior.created_at).total_seconds() < 600)):
                return dossier_dict(prior, full=True)
            row = ScoutDossier(id=new_id(), ticker=t, day=day, status="running", created_at=utcnow(), updated_at=utcnow())
            s.add(row)
            await s.commit()
            did = row.id
        if wait:
            await self._run(did, t, day)
        else:
            task = asyncio.create_task(self._run(did, t, day))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        return await self.get(did)

    async def _run(self, did: str, ticker: str, day: str) -> None:
        try:
            await self._build(did, ticker, day)
        except Exception as exc:                 # noqa: BLE001 - the row must never stay `running`
            log.exception("scout dossier %s failed", ticker)
            await self._update(did, status="error", reason=f"{type(exc).__name__}: {str(exc)[:400]}")

    async def gather(self, ticker: str, day: str) -> dict:
        """The fact sheet for `ticker` as of `day`, without the model call (also the Scout agent's
        `fundamentals` tool). {"error": why} when the SEC has no filer for the ticker."""
        hit = await self.cik_for_ticker(ticker)
        if hit is None:
            return {"error": f"{ticker} is not in the SEC's company list (funds and foreign-only listings have no "
                             f"filings to read)"}
        cik, title = hit
        today = dt.date.fromisoformat(day)
        subs = await self.svc._submissions(cik)
        profile = profile_of(subs, ticker)
        profile["name"] = profile.get("name") or title
        bars = await self.svc.daily_bars(ticker, today - dt.timedelta(days=760), today)
        bench = await self.svc.daily_bars(str(self.s("s2_benchmark", "SPY")), today - dt.timedelta(days=760), today)
        px = price_stats(bars, bench)
        series = None
        try:
            cf = await self.company_facts(cik)
            series = fu.build(cf) if cf else None
        except Exception as exc:                 # noqa: BLE001 - a dossier without statements is still useful
            log.info("scout dossier %s companyfacts: %s", ticker, exc)
        mcap, mwhy = (None, "no price history")
        if px:
            mcap, mwhy = await self.svc.market_cap(cik, px["last"], day)
        rows = await self.insider_rows(cik, (today - dt.timedelta(days=366)).isoformat())
        insiders = insider_summary(rows, day)
        filings = recent_filings(subs)
        try:
            earnings = await self.svc.earnings_dates(ticker, cik, day)
        except Exception:                        # noqa: BLE001 - advisory
            earnings = (None, "")
        cands = [c for c in await self.svc.candidates(days=45) if c["ticker"] == ticker and not c["kind"].startswith("random")]
        sheet, charts = build_sheet(ticker=ticker, profile=profile, series=series, px=px, market_cap=mcap,
                                    market_cap_why=mwhy, insiders=insiders, filings=filings, earnings=earnings,
                                    candidates=cands, today=day)
        charts["price"] = price_chart(bars, bench)["points"]
        release, rel_meta = None, None
        res8k = next((f for f in filings if f["form"] == "8-K" and "2.02" in f["items"]), None)
        if res8k:
            text, _names = await self.svc.desk.filing_text(cik, res8k["accession"])
            if text:
                release = text[: int(self.s("dossier_release_max_chars", 14000))]
                rel_meta = {"id": RELEASE_ID, "filed": res8k["filed"], "accession": res8k["accession"],
                            "url": f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
                                   f"{res8k['accession'].replace('-', '')}/{res8k['accession']}-index.htm"}
        sources = {"release": rel_meta, "releaseText": release,
                   "edgar": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={int(cik)}&type=&dateb=&owner=include&count=40"}
        return {"cik": str(cik), "profile": profile, "sheet": sheet, "charts": charts, "release": release,
                "sources": sources}

    async def _build(self, did: str, ticker: str, day: str) -> None:
        from ... import events as ev
        g = await self.gather(ticker, day)
        if g.get("error"):
            await self._update(did, status="error", reason=g["error"])
            return
        cik, profile, sheet, charts, release, sources = (g["cik"], g["profile"], g["sheet"], g["charts"],
                                                         g["release"], g["sources"])
        base = dict(cik=str(cik), name=profile["name"], facts=[f.to_dict() for f in sheet.facts], charts=charts,
                    sources=sources, prompt_version=PROMPT_VERSION)
        model, _effort, max_tokens = self._cfg()
        user = render(sheet, release, today=day)
        rates = self.s("llm_rates", {}) or {}
        budget = float(self.s("dossier_budget_usd_day", 5.0) or 0)
        spent = await self.spent_today(day)
        proj = an.projected_cost(model, len(SYSTEM_PROMPT) + len(user), max_tokens, rates)
        if spent + proj > budget:
            await self._update(did, **base, status="facts_only", model=model,
                               reason=f"note not written: ${spent:.2f} spent on dossiers today + ${proj:.2f} worst "
                                      f"case > ${budget:.2f} (techniques.scout.dossier_budget_usd_day)")
            return
        try:
            res = await self.call(user)
        except Exception as exc:                 # noqa: BLE001 - the facts stand on their own
            await self._update(did, **base, status="facts_only", model=model,
                               reason=f"note not written: call failed ({type(exc).__name__}: {str(exc)[:200]})")
            return
        cost = an.cost_usd(model, res.usage, rates)
        usage = dict(tokens_in=int(res.usage.get("in", 0)) + int(res.usage.get("cacheRead", 0))
                     + int(res.usage.get("cacheWrite", 0)), tokens_out=int(res.usage.get("out", 0)),
                     cost_usd=cost, latency_ms=res.latency_ms, model=res.model or model, raw=(res.text or "")[:30000])
        try:
            g = ground(an.parse_json(res.text), sheet, release)
        except (ValueError, TypeError) as exc:
            await self._update(did, **base, **usage, status="facts_only",
                               reason=f"note not usable: {str(exc)[:200]}"
                                      + (" (reply cut off at the token limit)" if res.stop == "max_tokens" else ""))
            return
        await self._update(did, **base, **usage, status="ok", note=g["note"], dropped=g["dropped"], reason=None)
        await self.engine.journal.append(ev.SCOUT_DOSSIER, {
            "technique": "scout", "dossierId": did, "ticker": ticker, "model": usage["model"], "costUsd": cost,
            "lean": g["note"]["lean"], "confidence": g["note"]["confidence"], "facts": len(sheet.facts),
            "droppedPoints": len(g["dropped"]), "promptVersion": PROMPT_VERSION},
            aggregate_type="scout", aggregate_id=did)


def dossier_dict(r, *, full: bool) -> dict:
    d = {"id": r.id, "ticker": r.ticker, "name": r.name, "day": r.day, "status": r.status, "reason": r.reason,
         "lean": (r.note or {}).get("lean"), "confidence": (r.note or {}).get("confidence"),
         "summary": (r.note or {}).get("summary"), "model": r.model, "costUsd": r.cost_usd,
         "createdAt": r.created_at.isoformat() if r.created_at else None,
         "updatedAt": r.updated_at.isoformat() if r.updated_at else None}
    if full:
        src = dict(r.sources or {})
        src.pop("releaseText", None)
        d.update({"cik": r.cik, "facts": r.facts or [], "charts": r.charts or {}, "note": r.note or None,
                  "dropped": r.dropped or [], "sources": src, "tokensIn": r.tokens_in, "tokensOut": r.tokens_out,
                  "latencyMs": r.latency_ms, "promptVersion": r.prompt_version})
    return d
