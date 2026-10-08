"""Scout's research books (PLAN 2.4) - which lane books exist, which a candidate enters, and the random
matched baseline. Pure except `ensure_book` (creates the portfolio row once).

Books are SHADOW research portfolios (`Portfolio.kind == "shadow"`, `book == "scout"`,
`source_name == "scout:<lane>"`): the engine routes them to the SIM executor only
(`Engine.executor_for`), every money total skips them (store/Dashboard/desk filter `kind == "shadow"`),
the daily-loss monitor skips them, and Tips' per-source scorecards ignore them (Tips reads only books
`immediate` / `armed` / `ownbook`). They never reach a broker or any real venue.

Lanes (one book each):
    s1_screen, s1_claude_keep, s1_claude_drop, s1_gpt_keep, s1_gpt_drop   (S1 insider cluster)
    s2_screen, s2_claude_keep, s2_claude_drop, s2_gpt_keep, s2_gpt_drop   (S2 earnings reaction)
    random                                                                  (random matched baseline)

Random matched baseline (documented method, preregistered 2026-10-07): for EVERY gate-passing S1/S2
candidate that gets a screen-book entry, one random twin is drawn with a seed derived from the matched
candidate's key (sha256 -> int), so the draw is reproducible and independent of the LLM lanes:
  * ticker = uniform from the POOL: every distinct ticker of a Scout candidate (any kind) recorded in the
    prior 365 days whose price and ADV gates passed at the time, minus the matched ticker and minus tickers
    with a Scout candidate in the prior 30 days; if that pool has < 20 names, the fixed liquid
    FALLBACK_POOL below is added;
  * entry date = the matched entry session + U{0..max_offset} sessions (same seed);
  * hold = the matched candidate's hold (S1 20 / S2 10 sessions);
  * the twin must pass the same pre-entry gates (price, ADV, corporate actions, Tips mention - market cap
    is shown but not required: the twin has no issuer CIK to read the SEC shares fact from);
    a failing draw is redrawn (next seed) up to 5 times, then the twin is recorded as `unmatched`;
  * the twin then follows the identical entry-spread rule, sizing, stop and time exit.
"""
from __future__ import annotations

import hashlib
import random as _random

SIGNALS = ("s1", "s2")
SIGNAL_OF_KIND = {"s1_insider": "s1", "s2_earnings": "s2"}
RANDOM = "random"
BOOK_TAG = "scout"
LANE_SOURCE_PREFIX = "scout:"

# liquid US names used only to top up a thin random pool (never traded unless drawn for the random book)
FALLBACK_POOL = ("AAPL", "MSFT", "AMZN", "GOOGL", "META", "NVDA", "JPM", "XOM", "JNJ", "PG", "KO", "PEP", "WMT",
                 "HD", "CVX", "MRK", "ABBV", "COST", "ORCL", "CSCO", "INTC", "AMD", "QCOM", "TXN", "IBM", "CAT",
                 "DE", "HON", "GE", "MMM", "UNH", "PFE", "T", "VZ", "DIS", "NKE", "MCD", "SBUX", "LOW", "TGT",
                 "BAC", "WFC", "C", "GS", "MS", "BA", "LMT", "UPS", "F", "GM")


def lane_label(lane: str) -> str:
    if lane == RANDOM:
        return "Scout random"
    sig, rest = lane.split("_", 1)
    rest = rest.replace("gpt_", "gpt ").replace("claude_", "claude ")
    return f"Scout {sig.upper()} {rest}"


def all_lanes() -> list[str]:
    out = []
    for sig in SIGNALS:
        out += [f"{sig}_screen", f"{sig}_claude_keep", f"{sig}_claude_drop", f"{sig}_gpt_keep", f"{sig}_gpt_drop"]
    return out + [RANDOM]


def lanes_for(kind: str, verdicts: dict[str, str | None]) -> list[str]:
    """Books a gate-passing candidate enters: the screen book always, plus <signal>_<lane>_<keep|drop>
    for every analyst lane that returned a verdict (a skipped/errored/budget lane adds nothing)."""
    sig = SIGNAL_OF_KIND.get(kind)
    if sig is None:
        return []
    out = [f"{sig}_screen"]
    for lane in ("claude", "gpt"):
        v = verdicts.get(lane)
        if v in ("keep", "drop"):
            out.append(f"{sig}_{lane}_{v}")
    return out


def seed_of(key: str, attempt: int = 0) -> int:
    return int(hashlib.sha256(f"{key}#{attempt}".encode()).hexdigest()[:16], 16)


def draw_random(key: str, pool: list[str], *, exclude: set[str], max_offset: int, attempt: int = 0) -> tuple[str, int] | None:
    """(ticker, entry offset in sessions) for the random twin of candidate `key` - reproducible."""
    names = sorted({p.upper() for p in pool} - {e.upper() for e in exclude})
    if not names:
        return None
    rng = _random.Random(seed_of(key, attempt))
    return rng.choice(names), rng.randint(0, max(0, int(max_offset)))


def build_pool(recent_ok: list[str], recent_30d: set[str], *, min_size: int = 20) -> list[str]:
    pool = sorted({t.upper() for t in recent_ok if t and t != "?"} - {t.upper() for t in recent_30d})
    if len(pool) < min_size:
        pool = sorted(set(pool) | (set(FALLBACK_POOL) - {t.upper() for t in recent_30d}))
    return pool


async def ensure_book(engine, lane: str, *, starting_cash: float = 100_000.0) -> dict:
    """The lane's SHADOW research book, created once. Matched on kind + book tag + source name, never by
    display name alone."""
    from ...domain import new_id
    from ...models import Portfolio as PortfolioRow
    source = LANE_SOURCE_PREFIX + lane
    for p in engine.positions.portfolios(include_archived=False):
        if p.get("kind") == "shadow" and p.get("book") == BOOK_TAG and p.get("sourceName") == source:
            return p
    row = PortfolioRow(id=new_id(), name=lane_label(lane), kind="shadow", starting_cash=starting_cash,
                       cash=starting_cash, source_name=source, book=BOOK_TAG)
    async with engine.sf() as s:
        s.add(row)
        await s.commit()
    engine.positions.register_portfolio(row)
    return engine.positions.portfolio(row.id)
