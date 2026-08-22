"""OptionsService: chain API, contract quotes, venue capability, expiry housekeeping.

Option quotes are a merge: ``last`` (and bars) stream live from the Yahoo
chart feed for the unpadded OCC symbol; ``bid``/``ask``/sizes come from the
provider chain (CBOE, ~15-min delayed) and are laid over every incoming quote
through ``QuoteCache.set_overlay``. When the engine runs on the simulated
feed there is no live ``last`` for a contract, so this service publishes
whole quotes itself from the provider snapshot (re-stamped each cycle so the
risk gate's freshness clock measures *our* refresh, not CBOE's delay).
"""
from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import logging
import time
from typing import Any

from .. import bus as topics
from .. import events as ev
from ..domain import Quote, now_ms
from . import occ
from .chain import CboeClient, OptionsError, TradierClient

log = logging.getLogger("zargar.options")

ENRICH_FLOOR_SECONDS = 2.0
IMPACT_UNSUPPORTED_CODES = {"1156"}


class OptionsService:
    def __init__(self, engine) -> None:
        self.engine = engine
        self._cboe: CboeClient | None = None
        self._tradier: TradierClient | None = None
        self._tracked: set[str] = set()            # OCC symbols whose quotes we enrich/publish
        self._snapshots: dict[str, dict] = {}       # OCC -> latest normalized chain row (+ asOf)
        self._capabilities: dict[str, dict] = {}    # snaptrade account id -> verdict
        self._task: asyncio.Task | None = None
        self._expiry_task: asyncio.Task | None = None
        self._owns_quotes = False                   # True on the sim feed (no live last)

    # ------------------------------------------------------------ providers
    def provider(self):
        """CBOE by default; Tradier when a token exists and settings ask for it."""
        s = self.engine.settings
        pref = str(s.get("options.provider", s.get("technique.options.provider", "cboe")))
        if pref == "tradier":
            tok = getattr(self.engine.config, "tradier_token", "") or ""
            if tok:
                if self._tradier is None:
                    self._tradier = TradierClient(
                        tok, sandbox=bool(getattr(self.engine.config, "tradier_sandbox", False)))
                return self._tradier
        if self._cboe is None:
            self._cboe = CboeClient()
        return self._cboe

    def use_client(self, client) -> None:
        """Test seam: inject a provider (e.g. CBOE over a MockTransport)."""
        self._cboe = client

    # ------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        from ..brokers.sim import SimQuoteFeed
        self._owns_quotes = isinstance(self.engine.feed, SimQuoteFeed)
        if self._task is None:
            self._task = asyncio.create_task(self._enrich_loop(), name="options-enrich")
        if self._expiry_task is None:
            self._expiry_task = asyncio.create_task(self._expiry_loop(), name="options-expiry")

    async def stop(self) -> None:
        for t in (self._task, self._expiry_task):
            if t is not None:
                t.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await t
        self._task = self._expiry_task = None
        if self._cboe is not None:
            await self._cboe.aclose()
        if self._tradier is not None:
            await self._tradier.aclose()

    # ------------------------------------------------------------ chain API
    async def expiries(self, underlying: str) -> dict:
        client = self.provider()
        sym = underlying.upper().strip()
        today = dt.date.today()
        exps = await client.expirations(sym)
        uq = await client.underlying_quote(sym)
        out = []
        for e in exps:
            try:
                d = dt.date.fromisoformat(e)
            except ValueError:
                continue
            dte = (d - today).days
            if dte < 0:
                continue
            out.append({"date": e, "dte": dte, "is0dte": dte == 0,
                        "weekday": d.strftime("%a")})
        return {"underlying": sym, "spot": uq.get("spot"), "prevClose": uq.get("prevClose"),
                "iv30": uq.get("iv30"), "expiries": out,
                "provider": client.name, "delayed": bool(getattr(client, "delayed", True))}

    async def chain(self, underlying: str, expiry: str) -> dict:
        client = self.provider()
        sym = underlying.upper().strip()
        rows = await client.chain(sym, expiry)
        uq = await client.underlying_quote(sym)
        spot = uq.get("spot") or 0.0
        by_strike: dict[float, dict] = {}
        for r in rows:
            cell = by_strike.setdefault(float(r["strike"]), {"strike": float(r["strike"]),
                                                            "call": None, "put": None})
            cell["call" if r["option_type"] == "call" else "put"] = self._cell(r, spot)
            self._snapshots[r["symbol"]] = {**r, "asOf": now_ms()}
        ladder = [by_strike[k] for k in sorted(by_strike)]
        try:
            exp_d = dt.date.fromisoformat(expiry)
            dte = (exp_d - dt.date.today()).days
        except ValueError:
            dte = None
        return {"underlying": sym, "expiry": expiry, "dte": dte, "spot": spot or None,
                "rows": ladder, "asOf": now_ms(), "provider": client.name,
                "delayed": bool(getattr(client, "delayed", True))}

    def _cell(self, r: dict, spot: float) -> dict:
        g = r.get("greeks") or {}
        bid, ask = float(r.get("bid") or 0), float(r.get("ask") or 0)
        mid = (bid + ask) / 2 if (bid or ask) else 0.0
        live = self.engine.quotes.get(r["symbol"])
        itm = (r["option_type"] == "call" and spot > r["strike"]) or (
            r["option_type"] == "put" and 0 < spot < r["strike"])
        return {
            "symbol": r["symbol"], "bid": bid, "ask": ask, "mid": round(mid, 4),
            "last": (live.last if live and live.last > 0 else float(r.get("last") or 0)) or None,
            "spreadPct": round((ask - bid) / mid * 100, 2) if mid > 0 else None,
            "volume": int(r.get("volume") or 0), "openInterest": int(r.get("open_interest") or 0),
            "iv": g.get("mid_iv"), "delta": g.get("delta"), "gamma": g.get("gamma"),
            "theta": g.get("theta"), "vega": g.get("vega"), "inTheMoney": itm,
        }

    async def contract(self, symbol: str) -> dict:
        """One contract: identity + provider snapshot + merged live quote."""
        o = occ.parse(symbol)
        if o is None:
            raise OptionsError(f"not an OCC option symbol: {symbol!r}")
        snap = await self._snapshot(o, refresh=True)
        live = self.engine.quotes.get(o.symbol)
        spot = await self._spot(o.underlying)
        out: dict[str, Any] = {**o.to_dict(), "underlyingSpot": spot, "available": snap is not None}
        if snap is not None:
            out.update(self._cell(snap, spot or 0.0))
            out["asOf"] = snap.get("asOf")
        out["quote"] = live.to_dict() if live else None
        out["provider"] = self.provider().name
        out["delayed"] = bool(getattr(self.provider(), "delayed", True))
        return out

    async def _spot(self, underlying: str) -> float | None:
        q = self.engine.quotes.get(underlying)
        if q is not None and q.last > 0:
            return float(q.last)
        try:
            return await self.provider().spot(underlying)
        except (OptionsError, Exception):  # pragma: no cover - network
            return None

    async def _snapshot(self, o: occ.Occ, *, refresh: bool = False) -> dict | None:
        if not refresh and o.symbol in self._snapshots:
            return self._snapshots[o.symbol]
        try:
            rows = await self.provider().chain(o.underlying, o.expiry.isoformat())
        except OptionsError as exc:
            log.info("chain unavailable for %s: %s", o.symbol, exc)
            return self._snapshots.get(o.symbol)
        except Exception as exc:  # pragma: no cover - network
            log.warning("chain fetch failed for %s: %s", o.symbol, exc)
            return self._snapshots.get(o.symbol)
        now = now_ms()
        for r in rows:
            self._snapshots[r["symbol"]] = {**r, "asOf": now}
        return self._snapshots.get(o.symbol)

    # ------------------------------------------------------------ quotes
    async def track(self, symbol: str) -> None:
        """Start enriching (or, on the sim feed, publishing) quotes for a contract."""
        o = occ.parse(symbol)
        if o is None:
            return
        if o.symbol in self._tracked:
            return
        self._tracked.add(o.symbol)
        await self._refresh_one(o)

    @property
    def tracked(self) -> set[str]:
        return set(self._tracked)

    async def _refresh_one(self, o: occ.Occ) -> None:
        snap = await self._snapshot(o, refresh=True)
        if snap is None:
            return
        self._apply(o, snap)

    def _apply(self, o: occ.Occ, snap: dict) -> None:
        bid, ask = float(snap.get("bid") or 0), float(snap.get("ask") or 0)
        quotes = self.engine.quotes
        quotes.set_overlay(o.symbol, bid=bid, ask=ask, bid_size=0, ask_size=0)
        existing = quotes.get(o.symbol)
        if self._owns_quotes or existing is None:
            last = float(snap.get("last") or 0) or ((bid + ask) / 2 if (bid or ask) else 0.0)
            if last <= 0 and ask <= 0:
                return
            quotes.on_quote(Quote(
                symbol=o.symbol, bid=bid, ask=ask, last=last or ask,
                volume=int(snap.get("volume") or 0), ts=now_ms(), session="regular"))

    async def _enrich_loop(self) -> None:
        while True:
            try:
                interval = float(self.engine.settings.get("options.enrich_seconds", 5))
            except (TypeError, ValueError):
                interval = 5.0
            await asyncio.sleep(max(ENRICH_FLOOR_SECONDS, interval))
            if not self._tracked:
                continue
            try:
                await self.refresh_tracked()
            except Exception:  # pragma: no cover - defensive
                log.exception("options enrich failed")

    async def refresh_tracked(self) -> None:
        """One enrichment pass over every tracked contract (grouped per underlying)."""
        by_underlying: dict[str, list[occ.Occ]] = {}
        for sym in list(self._tracked):
            o = occ.parse(sym)
            if o is not None:
                by_underlying.setdefault(o.underlying, []).append(o)
        for underlying, contracts in by_underlying.items():
            try:
                rows = await self.provider().all_rows(underlying)
            except OptionsError as exc:
                log.info("enrich skipped for %s: %s", underlying, exc)
                continue
            except Exception as exc:  # pragma: no cover - network
                log.warning("enrich failed for %s: %s", underlying, exc)
                continue
            now = now_ms()
            index = {r["symbol"]: r for r in rows}
            for o in contracts:
                r = index.get(o.symbol)
                if r is None:
                    continue
                snap = {**r, "asOf": now}
                self._snapshots[o.symbol] = snap
                self._apply(o, snap)

    # ------------------------------------------------------------ venue capability
    def capability(self, account_id: str) -> dict | None:
        return self._capabilities.get(account_id)

    def capabilities(self) -> dict:
        """Per SnapTrade account: allowlist verdict + last live probe."""
        out: dict[str, dict] = {}
        sync = self.engine.snaptrade_sync
        if sync is None:
            return out
        allow = [str(b).lower() for b in self.engine.settings.get(
            "snaptrade.options_brokers", ["Webull Canada"])]
        for prov in sync.providers:
            broker = str(prov.get("broker") or "")
            listed = any(a and a in broker.lower() for a in allow)
            for acct in prov.get("accounts") or []:
                aid = str(acct.get("id") or "")
                probe = self._capabilities.get(aid)
                supported = probe.get("supported") if probe else None
                out[aid] = {
                    "accountId": aid, "portfolioId": acct.get("portfolioId"), "broker": broker,
                    "allowlisted": listed,
                    "supported": supported if supported is not None else (True if listed else None),
                    "probed": probe is not None,
                    "checkedAt": probe.get("checkedAt") if probe else None,
                    "detail": probe.get("detail") if probe else (
                        "on the options allowlist" if listed else
                        "not on snaptrade.options_brokers — options disabled for this account"),
                }
        return out

    def allows_options(self, portfolio_id: str) -> tuple[bool, str]:
        """Gate used by the OrderManager before routing an OPT order to SnapTrade."""
        sync = self.engine.snaptrade_sync
        if sync is None:
            return False, "SnapTrade is not configured"
        account_id = sync.account_for(portfolio_id)
        if account_id is None:
            return False, "portfolio is not linked to a SnapTrade account"
        probe = self._capabilities.get(account_id)
        if probe is not None and probe.get("supported") is False:
            return False, f"this brokerage does not support option orders via SnapTrade ({probe.get('detail')})"
        caps = self.capabilities().get(account_id)
        if caps is None:
            return False, "account not found in the last brokerage sync"
        if not caps["allowlisted"] and not (probe and probe.get("supported")):
            return False, caps["detail"]
        return True, ""

    async def impact(self, portfolio_id: str, *, symbol: str, side: str, qty: float,
                     order_type: str = "LMT", limit_price: float | None = None,
                     action: str | None = None) -> dict:
        """Broker-side preview of an option order via SnapTrade (places nothing).

        Doubles as the capability probe: the verdict is cached per account.
        """
        eng = self.engine
        if eng.snaptrade_sync is None or eng.snaptrade is None:
            return {"error": "SnapTrade is not configured", "supported": None}
        account_id = eng.snaptrade_sync.account_for(portfolio_id)
        if account_id is None:
            return {"error": "portfolio is not a SnapTrade account", "supported": None}
        from ..brokers.snaptrade import SnapTradeError, SnapTradeUnknownOutcome
        checked = dt.datetime.now(dt.timezone.utc).isoformat()
        try:
            result = await eng.snaptrade.option_impact(
                account_id, symbol=symbol, side=side, qty=qty, order_type=order_type,
                limit_price=limit_price, action=action)
        except SnapTradeError as exc:
            body = exc.body if isinstance(exc.body, dict) else {}
            code = str(body.get("code") or "")
            detail = body.get("detail") if body else (exc.body if isinstance(exc.body, str) else str(exc))
            supported = False if code in IMPACT_UNSUPPORTED_CODES else None
            if supported is False:
                self._capabilities[account_id] = {
                    "supported": False, "detail": str(detail), "code": code, "checkedAt": checked}
                await eng.journal.append(ev.BROKER_CAPABILITY_CHECKED, {
                    "broker": "snaptrade", "accountId": account_id, "feature": "options",
                    "supported": False, "detail": str(detail), "code": code},
                    aggregate_type="portfolio", aggregate_id=portfolio_id, portfolio_id=portfolio_id)
            return {"error": str(detail), "code": code or None, "supported": supported}
        except SnapTradeUnknownOutcome as exc:
            return {"error": f"broker preview unavailable: {exc}", "supported": None}
        prev = self._capabilities.get(account_id)
        self._capabilities[account_id] = {"supported": True, "detail": "broker preview succeeded",
                                          "checkedAt": checked}
        if not prev or not prev.get("supported"):
            await eng.journal.append(ev.BROKER_CAPABILITY_CHECKED, {
                "broker": "snaptrade", "accountId": account_id, "feature": "options",
                "supported": True},
                aggregate_type="portfolio", aggregate_id=portfolio_id, portfolio_id=portfolio_id)
        return {**result, "supported": True}

    # ------------------------------------------------------------ expiry housekeeping
    async def _expiry_loop(self) -> None:
        while True:
            try:
                await self.settle_expired()
            except Exception:  # pragma: no cover - defensive
                log.exception("option expiry housekeeping failed")
            await asyncio.sleep(60.0)

    async def settle_expired(self, today: dt.date | None = None) -> list[dict]:
        """Practice/shadow portfolios: cash-settle expired contracts at intrinsic
        value (the simulator has no exercise/assignment). Live portfolios are
        authoritative at the broker — we only flag them; the next brokerage sync
        reconciles the position away (or turns it into stock on assignment).
        """
        today = today or dt.date.today()
        pk = self.engine.positions
        settled: list[dict] = []
        for pos in pk.positions_list():
            if pos.get("secType") != "OPT" or abs(pos.get("qty", 0)) < 1e-9:
                continue
            o = occ.parse(pos["symbol"])
            if o is None or not o.is_expired(today):
                continue
            pf = pk.portfolio(pos["portfolioId"]) or {}
            if pf.get("kind") not in ("sim", "shadow"):
                continue
            spot = await self._spot(o.underlying) or 0.0
            intrinsic = max(0.0, spot - o.strike) if o.right == "C" else max(0.0, o.strike - spot)
            side = "SELL" if pos["qty"] > 0 else "BUY"
            await pk.apply_fill(pos["portfolioId"], o.symbol, "OPT", side,
                                abs(pos["qty"]), round(intrinsic, 4), 0.0)
            record = {"symbol": o.symbol, "display": o.display(), "qty": pos["qty"],
                      "expiry": o.expiry.isoformat(), "underlyingSpot": spot,
                      "intrinsic": round(intrinsic, 4), "kind": pf.get("kind")}
            await self.engine.journal.append(
                ev.OPTION_EXPIRED, record, aggregate_type="position",
                aggregate_id=f"{pos['portfolioId']}:{o.symbol}", portfolio_id=pos["portfolioId"])
            settled.append(record)
        return settled

    def expiring(self, within_days: int = 2) -> list[dict]:
        """Open option positions expiring soon (for the dashboard tile / banners)."""
        out = []
        today = dt.date.today()
        for pos in self.engine.positions.positions_list():
            if pos.get("secType") != "OPT" or abs(pos.get("qty", 0)) < 1e-9:
                continue
            o = occ.parse(pos["symbol"])
            if o is None:
                continue
            dte = o.dte(today)
            if dte <= within_days:
                out.append({**pos, "dte": dte, "expired": dte < 0, "display": o.display()})
        return out
