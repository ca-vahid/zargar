"""Scout's LLM analyst - a FILTER and EXPLAINER, never an idea generator (PLAN 2.3, F5-F7).

For one candidate the rules already found (and that passed every pre-entry gate) the model reads a MASKED
fact packet - the insider rows or the 8-K item 2.02 text, recent price/volume numbers, sector, upcoming
events - with the company name and ticker replaced by placeholders where possible [F6], and answers in
prompted JSON:

    {"verdict": "keep" | "drop", "conviction": 1-5,
     "claims":  [{"text": ..., "quote": "<verbatim from the packet>", "source_id": "<packet source id>"}],
     "reasons": [{"text": ..., "claims": [<claim index>, ...]}]}

Grounding (deterministic, here): a claim whose quote is not found verbatim (whitespace-collapsed,
case-insensitive) in the cited source of the packet is DISCARDED (kept on the record as dropped); a reason
survives only if it cites at least one surviving claim. No surviving reason -> verdict `drop`, reason
`ungrounded`, whatever the model said. The model never adds a candidate - it only judges the one given.

Two lanes run the SAME packet: Anthropic Claude (official `anthropic` SDK, mirrors the Tips analyst's call
shape: `output_config.effort`, `cache_control` on the stable system prompt) and OpenAI (official `openai`
SDK, Responses API, `reasoning.effort`). Clients are injected (tests use fakes - never a real call), keys
are read from the app config and never logged.

Everything except the two `call_*` coroutines is pure.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

PROMPT_VERSION = "scout-analyst-v1"

CLAUDE, GPT = "claude", "gpt"
LANES = (CLAUDE, GPT)

SYSTEM_PROMPT = """You are a sceptical equity research analyst working as a FILTER for a rules-based screen.

A deterministic screen has already selected the candidate below; you cannot add, swap or suggest other
securities. Your only job is to decide whether this one candidate should be KEPT for a long position held
for a few weeks (insider-cluster signals: about 20 sessions; earnings-reaction signals: about 10 sessions),
or DROPPED, and to explain why using ONLY the facts in the packet.

The company name and ticker are masked as [COMPANY] and [TICKER]; insiders as Insider A, Insider B, ...
Do not try to identify the company and do not use outside knowledge about it - judge the facts given.
Things that argue for DROP include: the "purchase" looks like a placement, rights issue, plan or
non-discretionary buy; the earnings move is explained by a one-off item; the stock is already extended;
a binary event (trial readout, regulatory decision, vote) or earnings falls inside the hold; liquidity or
volatility make the position unreasonable. Absence of a red flag is a reason to KEEP.

Every factual statement must be a claim with a VERBATIM quote copied character-for-character from ONE
packet source, and that source's id. Keep quotes short (a phrase or a number with its words). A claim
whose quote is not in the cited source is discarded by the system; a reason that cites no surviving claim
is discarded; with no surviving reason the candidate is dropped as ungrounded.

Answer with ONE JSON object and nothing else:
{"verdict": "keep" or "drop",
 "conviction": integer 1-5 (5 = strongest confidence in the verdict),
 "claims": [{"text": "your factual statement", "quote": "verbatim text from the packet", "source_id": "id"}],
 "reasons": [{"text": "why this matters for keep/drop", "claims": [indexes into claims, starting at 0]}]}"""


# --------------------------------------------------------------------------- masking + packet
_SUFFIXES = re.compile(r"[\s,.]+(inc|incorporated|corp|corporation|co|company|ltd|limited|plc|llc|lp|l\.p|n\.v|"
                       r"s\.a|ag|se|holdings?|group|trust|bancorp|technologies|therapeutics)\.?$", re.I)


def name_variants(names: list[str]) -> list[str]:
    """Company-name spellings to mask, longest first: the full names and their cores without the legal
    suffix ("ACME CORP /DE/" -> "ACME CORP", "ACME"). One- and two-letter cores are never masked."""
    out: set[str] = set()
    for n in names:
        n = re.sub(r"/[A-Z]{2,3}/?$", "", str(n or "")).strip(" ,.")
        if not n:
            continue
        out.add(n)
        core = n
        for _ in range(3):
            stripped = _SUFFIXES.sub("", core).strip(" ,.")
            if stripped == core:
                break
            core = stripped
            if len(core) >= 3:
                out.add(core)
    return sorted((v for v in out if len(v) >= 3), key=len, reverse=True)


def mask(text: str, *, names: list[str], ticker: str | None, insiders: dict[str, str] | None = None) -> str:
    """Replace company names (case-insensitive), the ticker (whole word; case-sensitive for <= 2 letters)
    and insider names with placeholders."""
    s = str(text or "")
    for real, alias in sorted((insiders or {}).items(), key=lambda kv: -len(kv[0])):
        if real and len(real) >= 3:
            s = re.sub(re.escape(real), alias, s, flags=re.I)
    for v in name_variants(names):
        s = re.sub(r"(?<![A-Za-z0-9])" + re.escape(v) + r"(?![A-Za-z0-9])", "[COMPANY]", s, flags=re.I)
    t = (ticker or "").strip().upper()
    if t and t != "?":
        flags = 0 if len(t) <= 2 else re.I
        s = re.sub(r"(?<![A-Za-z0-9$])\$?" + re.escape(t) + r"(?![A-Za-z0-9])", "[TICKER]", s, flags=flags)
    return s


@dataclass
class Packet:
    sources: list[dict]                 # [{id, label, text}] - what the model sees (already masked)
    meta: dict = field(default_factory=dict)

    def render(self) -> str:
        parts = [f"<source id=\"{s['id']}\" label=\"{s['label']}\">\n{s['text']}\n</source>" for s in self.sources]
        return "FACT PACKET\n\n" + "\n\n".join(parts)

    def text_of(self, source_id: str) -> str | None:
        for s in self.sources:
            if s["id"] == source_id:
                return s["text"]
        return None

    @property
    def hash(self) -> str:
        return hashlib.sha256(self.render().encode("utf-8")).hexdigest()


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:+.1f}%"


def price_facts(bars: list, *, atr_days: int = 14) -> str:
    """Recent price/volume numbers from DAILY bars (oldest first, sessions BEFORE entry). Plain text."""
    from ...marketstructure.levels import atr as _atr
    b = list(bars or [])
    if len(b) < 2:
        return "No daily price history available."
    c = [float(x.close) for x in b]
    v = [float(x.volume or 0) for x in b]
    last = c[-1]

    def ret(n):
        return (last / c[-1 - n] - 1) * 100 if len(c) > n and c[-1 - n] else None
    avg20 = sum(v[-21:-1]) / max(1, len(v[-21:-1])) if len(v) > 1 else 0
    a = _atr(b, atr_days)
    hi, lo = max(float(x.high) for x in b), min(float(x.low) for x in b)
    lines = [f"Last close: {last:.2f}",
             f"1-session return: {_pct(ret(1))}", f"5-session return: {_pct(ret(5))}",
             f"20-session return: {_pct(ret(20))}",
             f"Range of the last {len(b)} sessions: {lo:.2f} to {hi:.2f}",
             f"Average daily volume (20 sessions before the last): {avg20:,.0f}",
             f"Last session volume: {v[-1]:,.0f}" + (f" ({v[-1] / avg20:.1f}x average)" if avg20 else ""),
             f"{atr_days}-session average true range: {a:.2f} ({a / last * 100:.1f}% of the close)" if last else ""]
    return "\n".join(x for x in lines if x)


def insider_facts(evidence: dict, insiders: dict[str, str]) -> list[dict]:
    """One packet source per purchase row (S1). `insiders` maps insider CIK -> alias."""
    out = []
    for i, r in enumerate(evidence.get("rows") or [], 1):
        alias = insiders.get(str(r.get("insider_cik")), "Insider ?")
        role = ", ".join(x for x in ("officer" if r.get("is_officer") else "", "director" if r.get("is_director") else "") if x)
        title = r.get("officer_title") or ""
        val = r.get("value")
        lines = [f"Insider: {alias}", f"Role: {role or 'n/a'}" + (f" ({title})" if title else ""),
                 f"Transaction: open-market purchase (Form 4 code P) on {r.get('trans_date')}",
                 f"Shares: {float(r['shares']):,.0f}" if r.get("shares") else "Shares: n/a",
                 f"Price per share: {float(r['price']):.2f}" if r.get("price") else "Price per share: n/a",
                 f"Value: ${float(val):,.0f}" if val else "Value: n/a",
                 f"Filed: {r.get('filed_date')}" + (f", accepted {r.get('acceptance_ts')}" if r.get("acceptance_ts") else "")]
        out.append({"id": f"F4-{i}", "label": "Form 4 purchase row", "text": "\n".join(lines)})
    cls = evidence.get("classifications") or {}
    summary = [f"Distinct insiders buying: {len(evidence.get('insiders') or [])}",
               f"Cluster total value: ${float(evidence.get('totalValue') or 0):,.0f}",
               f"Cluster window: {' to '.join(evidence.get('window') or [])}"]
    for cik, alias in insiders.items():
        c = cls.get(cik) if isinstance(cls, dict) else None
        if c:
            summary.append(f"{alias} classification: {c.get('label') if isinstance(c, dict) else c}"
                           + (f" ({c.get('reason')})" if isinstance(c, dict) and c.get("reason") else ""))
    out.insert(0, {"id": "S1", "label": "Insider cluster summary (Cohen-Malloy-Pomorski filter)", "text": "\n".join(summary)})
    return out


def earnings_facts(evidence: dict) -> dict:
    e = evidence
    lines = [f"Event: 8-K item 2.02 (results of operations) accepted {e.get('acceptanceTs')}",
             f"Reaction day 0: {e.get('day0')}; day +1: {e.get('day1')}",
             f"Stock return day 0 to day +1 (vs prior close): {_pct((e.get('stockReturn') or 0) * 100 if e.get('stockReturn') is not None else None)}",
             f"Benchmark ({e.get('benchmark')}) return: {_pct((e.get('benchReturn') or 0) * 100 if e.get('benchReturn') is not None else None)}",
             f"Abnormal return: {_pct((e.get('abnormalReturn') or 0) * 100 if e.get('abnormalReturn') is not None else None)}",
             f"Day 0 volume vs 20-session average: {float(e['volumeRatio']):.1f}x" if e.get("volumeRatio") else "",
             f"Rank among the period's releases: {e.get('rank')} of {e.get('of')}"]
    return {"id": "S2", "label": "Earnings reaction (S2 screen)", "text": "\n".join(x for x in lines if x)}


def build_packet(candidate: dict, *, bars: list, sector: str | None, events: list[str],
                 filing_text: str | None, company_names: list[str], max_chars: int = 12000,
                 atr_days: int = 14) -> Packet:
    """The masked fact packet for one candidate (`candidate` = `candidate_dict`)."""
    ev = candidate.get("evidence") or {}
    ticker = candidate.get("ticker")
    kind = str(candidate.get("kind") or "")
    insiders: dict[str, str] = {}
    names_by_cik: dict[str, str] = {}
    if kind.startswith("s1"):
        for r in ev.get("rows") or []:
            cik = str(r.get("insider_cik"))
            if cik not in insiders:
                insiders[cik] = f"Insider {chr(ord('A') + len(insiders))}" if len(insiders) < 26 else f"Insider {len(insiders) + 1}"
            if r.get("insider_name"):
                names_by_cik[cik] = str(r["insider_name"])
    real_to_alias = {names_by_cik[c]: a for c, a in insiders.items() if c in names_by_cik}

    def m(t: str) -> str:
        return mask(t, names=company_names, ticker=ticker, insiders=real_to_alias)

    sources: list[dict] = []
    if kind.startswith("s1"):
        sources += insider_facts(ev, insiders)
    elif kind == "s2_earnings":
        sources.append(earnings_facts(ev))
        if filing_text:
            body = filing_text[:max_chars]
            if len(filing_text) > max_chars:
                body += f"\n[... excerpt: first {max_chars} of {len(filing_text)} characters]"
            sources.append({"id": "8K", "label": "8-K item 2.02 release text (excerpt)", "text": body})
    sources.append({"id": "PX", "label": "Recent daily price and volume", "text": price_facts(bars, atr_days=atr_days)})
    sources.append({"id": "SEC", "label": "Sector (SEC SIC description)", "text": f"Sector: {sector or 'unknown'}"})
    hold = int((candidate.get("config") or {}).get("s1HoldSessions" if kind.startswith("s1") else "s2HoldSessions") or 0)
    ev_lines = [f"Planned entry session: {candidate.get('entryDate')}",
                f"Planned hold: {hold} sessions" if hold else "",
                f"Planned time exit: {ev.get('exitDate')}" if ev.get("exitDate") else ""]
    ev_lines += [str(e) for e in events]
    sources.append({"id": "EV", "label": "Upcoming events and calendar", "text": "\n".join(x for x in ev_lines if x) or "none known"})
    for s in sources:
        s["text"] = m(s["text"])
    return Packet(sources=sources, meta={"kind": kind, "masked": {"ticker": bool(ticker), "names": len(company_names),
                                                                    "insiders": len(insiders)},
                                         "promptVersion": PROMPT_VERSION})


def release_text(submission: str) -> tuple[str | None, list[str]]:
    """(plain text of the earnings release, company names from the header) from an 8-K full submission
    `.txt`. The release is the first EX-99* document; without one, the 8-K body itself."""
    import html as _html
    raw = str(submission or "")
    names = re.findall(r"COMPANY CONFORMED NAME:\s*(.+)", raw)
    docs = re.findall(r"<DOCUMENT>(.*?)</DOCUMENT>", raw, flags=re.S)
    pick = None
    for d in docs:
        t = re.search(r"<TYPE>\s*([^\s<]+)", d)
        if t and t.group(1).upper().startswith("EX-99"):
            pick = d
            break
    if pick is None and docs:
        pick = docs[0]
    if pick is None:
        return None, [n.strip() for n in names]
    body = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", pick, flags=re.S | re.I)
    body = re.sub(r"<br\s*/?>|</p>|</div>|</tr>", "\n", body, flags=re.I)
    body = re.sub(r"<[^>]+>", " ", body)
    body = _html.unescape(body)
    body = re.sub(r"[ \t\xa0]+", " ", body)
    body = re.sub(r"\n\s*\n+", "\n", body).strip()
    return body or None, sorted({n.strip() for n in names if n.strip()})


# --------------------------------------------------------------------------- parse + ground
_WS = re.compile(r"\s+")


def _norm(s: str) -> str:
    return _WS.sub(" ", str(s or "")).strip().casefold()


def parse_json(text: str) -> dict:
    """The first JSON object in the reply (code fences tolerated). Raises ValueError."""
    t = str(text or "").strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    start = t.find("{")
    if start < 0:
        raise ValueError("no JSON object in the reply")
    obj, _ = json.JSONDecoder().raw_decode(t[start:])
    if not isinstance(obj, dict):
        raise ValueError("reply JSON is not an object")
    return obj


@dataclass
class Grounded:
    verdict: str
    conviction: int | None
    reasons: list[dict]
    claims: list[dict]
    dropped_claims: list[dict]
    reason: str | None = None           # 'ungrounded' / model verdict override note

    def to_dict(self) -> dict:
        return {"verdict": self.verdict, "conviction": self.conviction, "reasons": self.reasons,
                "claims": self.claims, "droppedClaims": self.dropped_claims, "reason": self.reason}


def ground(obj: dict, packet: Packet, *, min_quote_chars: int = 3) -> Grounded:
    """Validate the reply and apply the grounding filter (module doc). Raises ValueError on a reply that
    is not a verdict at all (unknown verdict)."""
    verdict = str(obj.get("verdict") or "").strip().lower()
    if verdict not in ("keep", "drop"):
        raise ValueError(f"verdict must be keep|drop, got {obj.get('verdict')!r}")
    try:
        conviction = int(obj.get("conviction"))
        conviction = max(1, min(5, conviction))
    except (TypeError, ValueError):
        conviction = None
    raw_claims = obj.get("claims") if isinstance(obj.get("claims"), list) else []
    kept: list[dict] = []
    dropped: list[dict] = []
    index_map: dict[int, int] = {}
    for i, c in enumerate(raw_claims):
        if not isinstance(c, dict):
            dropped.append({"index": i, "claim": c, "why": "not an object"})
            continue
        q, sid = str(c.get("quote") or ""), str(c.get("source_id") or c.get("sourceId") or "")
        src = packet.text_of(sid)
        rec = {"text": str(c.get("text") or "")[:600], "quote": q[:600], "sourceId": sid}
        if src is None:
            dropped.append({**rec, "index": i, "why": f"unknown source id {sid!r}"})
        elif len(_norm(q)) < min_quote_chars:
            dropped.append({**rec, "index": i, "why": "quote too short"})
        elif _norm(q) not in _norm(src):
            dropped.append({**rec, "index": i, "why": "quote not found verbatim in the cited source"})
        else:
            index_map[i] = len(kept)
            kept.append(rec)
    reasons: list[dict] = []
    for r in obj.get("reasons") if isinstance(obj.get("reasons"), list) else []:
        if isinstance(r, str):
            continue                                             # an uncited reason never survives
        if not isinstance(r, dict):
            continue
        refs = r.get("claims") if isinstance(r.get("claims"), list) else (
            [r["claim"]] if isinstance(r.get("claim"), int) else [])
        valid = sorted({index_map[x] for x in refs if isinstance(x, int) and x in index_map})
        if valid:
            reasons.append({"text": str(r.get("text") or "")[:800], "claims": valid})
    if not reasons:
        return Grounded("drop", conviction, [], kept, dropped,
                        reason="ungrounded" + ("" if verdict == "drop" else " (model said keep)"))
    return Grounded(verdict, conviction, reasons, kept, dropped)


# --------------------------------------------------------------------------- cost + budget
def rate_for(model: str, rates: dict) -> dict:
    r = (rates or {}).get(model)
    if r is None:
        # longest configured prefix ("gpt-6.1-sol-2026..." -> "gpt-6.1-sol")
        hits = sorted((k for k in (rates or {}) if str(model).startswith(k)), key=len, reverse=True)
        r = rates[hits[0]] if hits else None
    return dict(r or {"in": 0.0, "out": 0.0, "note": "no rate configured - cost unknown (counted 0)"})


def cost_usd(model: str, usage: dict, rates: dict) -> float:
    """USD from a usage record {in, out, cacheRead, cacheWrite} and USD-per-million rates. Claude reports
    cached tokens apart from `in`; OpenAI's `in` already includes them (`cacheRead` 0 there)."""
    r = rate_for(model, rates)
    rin, rout = float(r.get("in") or 0), float(r.get("out") or 0)
    rcr = float(r.get("cacheRead", rin * 0.1) or 0)
    rcw = float(r.get("cacheWrite", rin * 1.25) or 0)
    tot = (usage.get("in", 0) * rin + usage.get("out", 0) * rout + usage.get("cacheRead", 0) * rcr
           + usage.get("cacheWrite", 0) * rcw) / 1e6
    return round(tot, 6)


def projected_cost(model: str, prompt_chars: int, max_tokens: int, rates: dict) -> float:
    """Worst-case cost of one call before it is made (input ~ chars/3.5 tokens, the FULL output cap)."""
    return cost_usd(model, {"in": int(prompt_chars / 3.5) + 1, "out": int(max_tokens)}, rates)


# --------------------------------------------------------------------------- lane calls
@dataclass
class CallResult:
    text: str
    usage: dict
    latency_ms: float
    stop: str | None = None
    model: str | None = None


async def call_claude(client, *, model: str, effort: str | None, system: str, user: str, max_tokens: int,
                      cache: bool, timeout_s: float) -> CallResult:
    """One Messages API call, shaped like the Tips analyst's (`output_config.effort`, `cache_control` on the
    stable system block). Opus 5.5 thinks adaptively by default - no `thinking` parameter is sent."""
    import asyncio
    sys_param: Any = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}] if cache else system
    kw: dict = dict(model=model, max_tokens=int(max_tokens), system=sys_param,
                    messages=[{"role": "user", "content": user}])
    e = str(effort or "").strip().lower()
    if e in ("low", "medium", "high", "xhigh", "max") and not str(model).startswith(("claude-haiku", "claude-3")):
        kw["output_config"] = {"effort": e}
    t0 = time.perf_counter()
    resp = await asyncio.wait_for(client.messages.create(**kw), timeout=max(1.0, float(timeout_s)))
    ms = (time.perf_counter() - t0) * 1000.0
    text = "".join(getattr(b, "text", "") or "" for b in (getattr(resp, "content", None) or [])
                   if getattr(b, "type", "") == "text")
    u = getattr(resp, "usage", None)
    usage = {"in": int(getattr(u, "input_tokens", 0) or 0), "out": int(getattr(u, "output_tokens", 0) or 0),
             "cacheRead": int(getattr(u, "cache_read_input_tokens", 0) or 0),
             "cacheWrite": int(getattr(u, "cache_creation_input_tokens", 0) or 0)}
    return CallResult(text=text, usage=usage, latency_ms=ms, stop=getattr(resp, "stop_reason", None),
                      model=getattr(resp, "model", None) or model)


async def call_openai(client, *, model: str, effort: str | None, system: str, user: str, max_tokens: int,
                      timeout_s: float) -> CallResult:
    """One Responses API call (`instructions` = the system prompt, `reasoning.effort`)."""
    import asyncio
    kw: dict = dict(model=model, instructions=system, input=user, max_output_tokens=int(max_tokens))
    e = str(effort or "").strip().lower()
    if e in ("minimal", "low", "medium", "high", "xhigh"):
        kw["reasoning"] = {"effort": e}
    t0 = time.perf_counter()
    resp = await asyncio.wait_for(client.responses.create(**kw), timeout=max(1.0, float(timeout_s)))
    ms = (time.perf_counter() - t0) * 1000.0
    text = getattr(resp, "output_text", None) or ""
    u = getattr(resp, "usage", None)
    usage = {"in": int(getattr(u, "input_tokens", 0) or 0), "out": int(getattr(u, "output_tokens", 0) or 0),
             "cacheRead": 0, "cacheWrite": 0}
    return CallResult(text=text, usage=usage, latency_ms=ms, stop=getattr(resp, "status", None),
                      model=getattr(resp, "model", None) or model)
