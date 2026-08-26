"""Alpaca full-SIP streaming feed (Algo Trader Plus plan).

Pushed trades / NBBO quotes / 1-minute bars over one websocket — replacing the
polled Yahoo pipe for US-listed symbols. The 2026-08-25 session showed why:
Yahoo 429-throttled the box, bars stalled 180s+, a volume-blind critic killed a
good fire and a phantom touch fired another. A push feed has none of that.

Division of labour (see HybridQuoteFeed):
  - Alpaca: real-time bid/ask/last + true consolidated volume + closed 1m bars
    for every US-listed symbol that is watched (armed plans, holdings, charts).
  - Yahoo: non-US symbols (.TO/.V, FX pairs like USDCAD=X), the session context
    Alpaca doesn't carry (prev_close / session phase — the day-change basis),
    and all history fetches (fetch_bars / fetch_day_bars / technique history).
"""
from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import json
import logging
from typing import Callable

import websockets

from zoneinfo import ZoneInfo

from ..domain import Bar, Quote, now_ms
from .base import QuoteFeed

log = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")


def _expect_traffic() -> bool:
    """True when the SIP tape should be printing (weekdays 4:00-20:00 ET).
    Outside that window silence is normal, not an outage — overnight the
    health check must not degrade an authenticated idle socket to 'down'."""
    now = dt.datetime.now(ET)
    return now.weekday() < 5 and 4 * 60 <= now.hour * 60 + now.minute < 20 * 60

WS_URL = "wss://stream.data.alpaca.markets/v2/{feed}"
# SIP trade conditions that do not update the consolidated last price
# (T/U extended-hours prints stay eligible so pre/post keeps a live tape)
_NO_LAST_CONDS = frozenset(
    ["B", "C", "G", "H", "I", "M", "N", "P", "Q", "R", "W", "Z", "4", "7", "9"])
# Emit at most one Quote per symbol per this window — the SIP quote stream can
# tick hundreds of times a second on liquid names; the app conflates at ~10Hz
# for the UI anyway and the engine reads the book, not every message.
EMIT_MS = 250


def is_us_equity(symbol: str) -> bool:
    """Alpaca serves US-listed equities only — no .TO/.V listings, no =X FX."""
    s = symbol.upper()
    return bool(s) and "." not in s and "=" not in s and "/" not in s


def parse_rfc3339_ms(t: str) -> int:
    """Alpaca timestamps are RFC3339, sometimes with nanosecond precision."""
    s = t.replace("Z", "+00:00")
    if "." in s:
        head, rest = s.split(".", 1)
        off = ""
        for i, ch in enumerate(rest):
            if ch in "+-":
                rest, off = rest[:i], rest[i:]
                break
        s = f"{head}.{rest[:6].ljust(6, '0')}{off}"
    return int(dt.datetime.fromisoformat(s).timestamp() * 1000)


class AlpacaQuoteFeed(QuoteFeed):
    def __init__(self, on_quote: Callable[[Quote], None], key_id: str, secret: str, *,
                 on_bars: Callable[[list], None] | None = None, feed: str = "sip") -> None:
        self._on_quote = on_quote
        self._on_bars = on_bars
        self._key = key_id
        self._secret = secret
        self._feed = feed
        self._symbols: set[str] = set()
        self._state: dict[str, dict] = {}
        self._context: dict[str, Quote] = {}    # last Yahoo quote per symbol (prev_close etc.)
        self._ws = None
        self._task: asyncio.Task | None = None
        self._last_msg = 0
        self._authed = False

    # ------------------------------------------------------------- lifecycle
    @property
    def symbols(self) -> set[str]:
        return set(self._symbols)

    @property
    def connected(self) -> bool:
        # Honest health: an open socket that never authenticated is NOT up
        # (Alpaca allows ONE concurrent stream per subscription — a second
        # consumer is told 406 "connection limited" on a perfectly open
        # socket). And a silent overnight socket IS up — traffic is only
        # expected while the tape prints (SPY is always subscribed as a
        # heartbeat, so in-hours silence really means trouble).
        if self._ws is None or not self._authed:
            return False
        if not _expect_traffic():
            return True
        return now_ms() - self._last_msg < 60_000

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="alpaca-stream")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def watch(self, symbol: str) -> None:
        s = symbol.upper()
        if not is_us_equity(s) or s in self._symbols:
            return
        self._symbols.add(s)
        if self._ws is not None:
            with contextlib.suppress(Exception):
                await self._ws.send(json.dumps(self._sub_msg([s])))

    def absorb_context(self, q: Quote) -> None:
        """Session context from the slow Yahoo poll (prev_close, session phase,
        regular-session price) — merged into every fast Alpaca emission so the
        day-change basis never degrades to 0."""
        self._context[q.symbol.upper()] = q

    # ------------------------------------------------------------- streaming
    @staticmethod
    def _sub_msg(syms: list[str]) -> dict:
        return {"action": "subscribe", "trades": syms, "quotes": syms, "bars": syms}

    async def _run(self) -> None:
        backoff = 1.0
        while True:
            try:
                async with websockets.connect(WS_URL.format(feed=self._feed), max_size=2 ** 23) as ws:
                    self._ws = ws
                    await ws.send(json.dumps({"action": "auth", "key": self._key, "secret": self._secret}))
                    # SPY is always on the wire as a liveness heartbeat: during
                    # market hours (incl. extended) it prints every second, so
                    # "no message in 60s" is a real outage, not a quiet book.
                    await ws.send(json.dumps(self._sub_msg(sorted(self._symbols | {"SPY"}))))
                    backoff = 1.0
                    async for raw in ws:
                        self._last_msg = now_ms()
                        try:
                            msgs = json.loads(raw)
                        except (TypeError, ValueError):
                            continue
                        for m in msgs if isinstance(msgs, list) else [msgs]:
                            self.handle(m)
            except asyncio.CancelledError:
                self._ws = None
                self._authed = False
                raise
            except Exception as exc:
                log.warning("alpaca stream dropped: %s — reconnecting in %.0fs", exc, backoff)
            self._ws = None
            self._authed = False
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)

    # ------------------------------------------------------------- messages
    def _st(self, s: str) -> dict:
        return self._state.setdefault(s, {
            "bid": 0.0, "ask": 0.0, "bid_size": 0, "ask_size": 0,
            "last": 0.0, "volume": 0, "day_high": 0.0, "day_low": 0.0, "emit_ms": 0,
        })

    def handle(self, m: dict) -> None:
        t = m.get("T")
        s = str(m.get("S") or "").upper()
        if t == "q" and s:
            st = self._st(s)
            st["bid"] = float(m.get("bp") or 0)
            st["ask"] = float(m.get("ap") or 0)
            st["bid_size"] = int((m.get("bs") or 0) * 100)     # round lots → shares
            st["ask_size"] = int((m.get("as") or 0) * 100)
            self._emit(s, st)
        elif t == "t" and s:
            st = self._st(s)
            px = float(m.get("p") or 0)
            # Prints that are NOT eligible to update the last price (odd lots,
            # out-of-sequence, prior-reference, average-price, derivatively
            # priced, official open/close...) still count volume but must not
            # touch last/high/low — one such print painted a PM 1m bar with a
            # low 5 points under the tape (2026-08-26 09:55, low 190.045).
            conds = set(m.get("c") or [])
            if px > 0 and not (conds & _NO_LAST_CONDS):
                st["last"] = px
                st["day_high"] = max(st["day_high"], px)
                st["day_low"] = px if not st["day_low"] else min(st["day_low"], px)
            st["volume"] += int(m.get("s") or 0)
            self._emit(s, st)
        elif t == "b" and s:
            st = self._st(s)
            bar = Bar(symbol=s, tf="1m", ts=parse_rfc3339_ms(str(m.get("t"))),
                      open=float(m.get("o") or 0), high=float(m.get("h") or 0),
                      low=float(m.get("l") or 0), close=float(m.get("c") or 0),
                      volume=int(m.get("v") or 0))
            if bar.close > 0:
                st["last"] = bar.close
            if self._on_bars is not None and bar.open > 0:
                self._on_bars([bar])
        elif t == "error":
            code = m.get("code")
            if code in (406, "406"):
                # the single-stream slot is taken by ANOTHER consumer — a
                # duplicate app instance or a `zargar.tools.alpaca_check --ws`
                self._authed = False
                log.error("alpaca stream REFUSED (406 connection limited): another "
                          "process holds this account's single SIP stream — find and "
                          "stop the duplicate (second app instance / alpaca_check --ws)")
            else:
                log.warning("alpaca stream error: %s %s", code, m.get("msg"))
        elif t == "success":
            if "authenticated" in str(m.get("msg") or ""):
                self._authed = True
            log.info("alpaca stream: %s", m.get("msg"))

    def _emit(self, s: str, st: dict, *, force: bool = False) -> None:
        now = now_ms()
        if not force and now - st["emit_ms"] < EMIT_MS:
            return
        st["emit_ms"] = now
        ctx = self._context.get(s)
        q = Quote(symbol=s, bid=st["bid"], ask=st["ask"],
                  last=st["last"] or (st["bid"] + st["ask"]) / 2 if (st["bid"] and st["ask"]) else st["last"],
                  bid_size=st["bid_size"], ask_size=st["ask_size"], volume=st["volume"],
                  prev_close=(ctx.prev_close if ctx else 0.0),
                  reg_price=(ctx.reg_price if ctx else 0.0),
                  day_high=st["day_high"] or (ctx.day_high if ctx else 0.0),
                  day_low=st["day_low"] or (ctx.day_low if ctx else 0.0),
                  session=(ctx.session if ctx else ""))
        q.ts = now
        self._on_quote(q)


class HybridQuoteFeed(QuoteFeed):
    """Alpaca streams the US names; Yahoo keeps everything Alpaca can't do —
    non-US listings, FX pairs, session context, and history fetches."""

    def __init__(self, alpaca: AlpacaQuoteFeed, yahoo) -> None:
        self.alpaca = alpaca
        self.yahoo = yahoo

    @property
    def symbols(self) -> set[str]:
        return set(self.alpaca.symbols) | set(self.yahoo.symbols)

    @property
    def connected(self) -> bool:
        return self.alpaca.connected or self.yahoo.connected

    async def start(self) -> None:
        await self.yahoo.start()
        await self.alpaca.start()

    async def stop(self) -> None:
        await self.alpaca.stop()
        await self.yahoo.stop()

    async def watch(self, symbol: str) -> None:
        if is_us_equity(symbol):
            await self.alpaca.watch(symbol)
        # Yahoo watches everything: sole source for non-US symbols, slow
        # context poll (prev_close / session) for the Alpaca-streamed ones.
        await self.yahoo.watch(symbol)

    # history stays on Yahoo (deep 1m/1d archives; Alpaca REST can join later)
    async def fetch_bars(self, *args, **kwargs):
        return await self.yahoo.fetch_bars(*args, **kwargs)

    async def fetch_day_bars(self, *args, **kwargs):
        return await self.yahoo.fetch_day_bars(*args, **kwargs)
