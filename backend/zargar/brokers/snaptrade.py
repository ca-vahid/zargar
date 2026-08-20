"""SnapTrade venue: signed API client, order executor, and account sync.

SnapTrade fronts brokerages that lack public APIs (here: Wealthsimple and
Webull Canada). Personal-account auth: requests are HMAC-signed with the
consumer key; userId/userSecret are omitted (the key identifies the user).

Money-path rules honored here:
  - The OrderManager persists intent + SUBMITTED before submit() runs.
  - On an unknown submit outcome we reconcile against recentOrders using our
    client_order_id — we never resubmit.
  - Fills are emitted as incremental deltas with deterministic exec ids, so
    re-polling the same broker state can never double-apply an execution.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import datetime as dt
import hashlib
import hmac
import json
import logging
import time
import uuid
from typing import Any, Callable

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from .. import bus as topics
from .. import events as ev
from ..domain import new_id
from ..models import BrokerageAccount, Order, Portfolio
from .base import BrokerOrder, ExecReport, Executor

log = logging.getLogger("zargar.snaptrade")

# Test seam: when set, SnapTradeClient uses this transport unless one is passed
# explicitly. Lets the engine integration tests stub the HTTP layer without
# touching the engine's construction path.
DEFAULT_TRANSPORT: httpx.AsyncBaseTransport | None = None

OPEN_STATUSES = ("SUBMITTED", "ACCEPTED", "PARTIALLY_FILLED")

_ORDER_TYPE = {"MKT": "Market", "LMT": "Limit", "STP": "Stop", "STP_LMT": "StopLimit"}
_TIF = {"DAY": "Day", "GTC": "GTC", "IOC": "IOC"}

# SnapTrade recentOrders statuses that mean "broker acknowledged, working"
_WORKING = {"ACCEPTED", "ACTIVATED", "TRIGGERED", "REPLACE_PENDING", "CANCEL_PENDING", "REPLACED"}
_NO_ACTION = {"NONE", "PENDING", "QUEUED"}


class SnapTradeError(Exception):
    """Definitive API rejection (4xx with a response body)."""

    def __init__(self, status: int, body: Any):
        self.status = status
        self.body = body
        detail = body
        if isinstance(body, dict):
            detail = body.get("detail") or body.get("message") or body
        super().__init__(f"SnapTrade {status}: {str(detail)[:300]}")


class SnapTradeUnknownOutcome(Exception):
    """Timeout / transport failure / 5xx: the request MAY have been applied."""


class SnapTradeClient:
    """Minimal signed client for SnapTrade personal-account auth."""

    def __init__(
        self,
        client_id: str,
        consumer_key: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        base_url: str = "https://api.snaptrade.com",
        timeout: float = 30.0,
    ) -> None:
        self._client_id = client_id
        self._consumer_key = consumer_key
        self._http = httpx.AsyncClient(
            transport=transport or DEFAULT_TRANSPORT, timeout=timeout, base_url=base_url)

    def _sign(self, path: str, query: str, body: dict | None) -> str:
        payload = {"content": body, "path": path, "query": query}
        data = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        digest = hmac.new(self._consumer_key.encode(), data.encode(), hashlib.sha256).digest()
        return base64.b64encode(digest).decode()

    async def request(self, method: str, path: str, body: dict | None = None) -> Any:
        query = f"clientId={self._client_id}&timestamp={int(time.time())}"
        headers = {"Signature": self._sign(path, query, body)}
        try:
            resp = await self._http.request(
                method, f"{path}?{query}", headers=headers,
                json=body if body is not None else None)
        except httpx.HTTPError as exc:
            raise SnapTradeUnknownOutcome(f"{method} {path}: {exc}") from exc
        if resp.status_code >= 500:
            raise SnapTradeUnknownOutcome(f"{method} {path} -> {resp.status_code}")
        if resp.status_code >= 400:
            try:
                body_json = resp.json()
            except ValueError:
                body_json = resp.text[:300]
            raise SnapTradeError(resp.status_code, body_json)
        return resp.json()

    async def aclose(self) -> None:
        await self._http.aclose()


# --- symbol helpers ----------------------------------------------------------

_TSX_CODES = {"TSX", "TSE", "TOR", "XTSE"}
_TSXV_CODES = {"TSXV", "CDNX", "VENTURE", "XTSX"}

# instrument.kind values from /positions/all that map onto our STK handling
_EQUITY_KINDS = {"stock", "etf", "adr", "cef", "mutualfund"}


def normalize_symbol(raw: str, exchange_code: str | None) -> str:
    """SnapTrade symbol + exchange → zargar symbol (Yahoo-style suffixes)."""
    sym = (raw or "").upper().strip()
    if sym.endswith(".TO") or sym.endswith(".V"):
        return sym
    code = (exchange_code or "").upper()
    if code in _TSX_CODES:
        return f"{sym}.TO"
    if code in _TSXV_CODES:
        return f"{sym}.V"
    return sym


def extract_unified_position(raw: dict) -> dict | None:
    """Parse one row of GET /accounts/{id}/positions/all (the current API).

    Shape: {instrument: {kind, symbol, raw_symbol, currency, exchange(MIC)},
            units: "60", price: "139.42", cost_basis: "159.67", currency}
    Numbers arrive as strings. `instrument.symbol` already carries suffix
    conventions (e.g. AAPL.TO for CDRs).
    """
    instrument = raw.get("instrument") or {}
    kind = str(instrument.get("kind") or "").lower()
    sec_type = "STK" if kind in _EQUITY_KINDS else "OPT" if kind == "option" else None
    if sec_type is None:
        log.info("skipping unsupported position kind=%s symbol=%s",
                 kind, instrument.get("symbol"))
        return None
    ticker = instrument.get("symbol") or instrument.get("raw_symbol")
    if not ticker:
        return None
    try:
        qty = float(raw.get("units") or 0.0)
        price = float(raw.get("price") or 0.0)
        avg = float(raw.get("cost_basis") or 0.0)
    except (TypeError, ValueError):
        return None
    if abs(qty) < 1e-12:
        return None
    return {
        "symbol": normalize_symbol(str(ticker), instrument.get("exchange")),
        "secType": sec_type,
        "qty": qty,
        "avgCost": avg,
        "price": price or None,
        "currency": str(raw.get("currency") or instrument.get("currency") or "") or None,
    }


def extract_position(raw: dict) -> dict | None:
    """Defensively parse one SnapTrade position row into our shape."""
    sym_obj = raw.get("symbol") or {}
    # positions nest: position.symbol (account symbol) . symbol (universal symbol)
    uni = sym_obj.get("symbol") if isinstance(sym_obj.get("symbol"), dict) else sym_obj
    ticker = None
    exchange = None
    if isinstance(uni, dict):
        ticker = uni.get("symbol") or uni.get("raw_symbol")
        exch = uni.get("exchange") or {}
        exchange = exch.get("code") if isinstance(exch, dict) else None
    elif isinstance(sym_obj, str):
        ticker = sym_obj
    if not ticker:
        return None
    qty = raw.get("units")
    if qty is None:
        qty = raw.get("fractional_units") or 0.0
    return {
        "symbol": normalize_symbol(str(ticker), exchange),
        "secType": "STK",
        "qty": float(qty or 0.0),
        "avgCost": float(raw.get("average_purchase_price") or 0.0),
        "price": float(raw.get("price") or 0.0) or None,
        "currency": ((uni or {}).get("currency") or {}).get("code")
        if isinstance(uni, dict) else None,
    }


def dashed_uuid(hex_id: str) -> str:
    """Our uuid4().hex order id → SnapTrade's dashed-UUID client_order_id."""
    return str(uuid.UUID(hex=hex_id))


def exec_id_for(broker_order_id: str, cum_qty: float) -> str:
    """Deterministic executions PK: re-polling identical state can't double-insert."""
    return hashlib.sha256(f"snaptrade:{broker_order_id}:{cum_qty:g}".encode()).hexdigest()[:32]


# --- executor -----------------------------------------------------------------

class _Tracked:
    __slots__ = ("order_id", "account_id", "broker_order_id", "client_order_id",
                 "cum", "avg", "accepted_emitted", "cancel_requested")

    def __init__(self, order_id: str, account_id: str, client_order_id: str,
                 broker_order_id: str | None = None, cum: float = 0.0):
        self.order_id = order_id
        self.account_id = account_id
        self.client_order_id = client_order_id
        self.broker_order_id = broker_order_id
        self.cum = cum
        self.avg = 0.0
        self.accepted_emitted = False
        self.cancel_requested = False


class SnapTradeBroker(Executor):
    """Order executor for SnapTrade-linked accounts (polling, no push)."""

    def __init__(
        self,
        client: SnapTradeClient,
        session_factory: async_sessionmaker,
        journal,
        settings,
        account_for: Callable[[str], str | None],  # portfolio_id -> snaptrade account id
    ) -> None:
        super().__init__()
        self._client = client
        self._sf = session_factory
        self._journal = journal
        self._settings = settings
        self._account_for = account_for
        self._tracked: dict[str, _Tracked] = {}       # our order id -> state
        self._last_submit: dict[str, float] = {}      # account id -> monotonic ts
        self._submit_locks: dict[str, asyncio.Lock] = {}
        self._task: asyncio.Task | None = None
        self._healthy = True

    # ---------------------------------------------------------------- lifecycle
    async def start(self) -> None:
        await self._resume_tracking()
        self._task = asyncio.create_task(self._poll_loop(), name="snaptrade-order-poll")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _resume_tracking(self) -> None:
        """Re-adopt open SnapTrade orders after a restart."""
        async with self._sf() as session:
            rows = (await session.execute(
                select(Order).where(Order.status.in_(OPEN_STATUSES)))).scalars().all()
        for order in rows:
            account_id = self._account_for(order.portfolio_id)
            if account_id is None:
                continue
            t = _Tracked(order.id, account_id, dashed_uuid(order.id),
                         broker_order_id=order.broker_order_id,
                         cum=order.filled_qty or 0.0)
            t.accepted_emitted = True  # already past SUBMITTED in a prior run
            self._tracked[order.id] = t

    @property
    def connected(self) -> bool:
        return self._healthy

    # ---------------------------------------------------------------- submit
    async def submit(self, order: BrokerOrder) -> None:
        account_id = self._account_for(order.portfolio_id or "")
        if account_id is None:
            await self.emit(ExecReport(
                kind="rejected", order_id=order.id,
                reason="portfolio is not linked to a SnapTrade account"))
            return
        client_order_id = dashed_uuid(order.id)
        body: dict[str, Any] = {
            "account_id": account_id,
            "action": order.side.value,
            "order_type": _ORDER_TYPE[order.order_type.value],
            "time_in_force": _TIF[order.tif.value],
            "symbol": order.symbol,
            "units": order.qty,
            "client_order_id": client_order_id,
        }
        if order.limit_price is not None:
            body["price"] = order.limit_price
        if order.stop_price is not None:
            body["stop"] = order.stop_price

        tracked = _Tracked(order.id, account_id, client_order_id)
        try:
            async with self._throttle(account_id):
                result = await self._client.request("POST", "/api/v1/trade/place", body)
            self._healthy = True
        except SnapTradeError as exc:
            await self.emit(ExecReport(kind="rejected", order_id=order.id, reason=str(exc)))
            return
        except SnapTradeUnknownOutcome as exc:
            await self._journal.append(
                ev.BROKER_SUBMIT_UNKNOWN,
                {"error": str(exc), "clientOrderId": client_order_id},
                aggregate_type="order", aggregate_id=order.id)
            await self._reconcile_unknown(order, tracked)
            return

        broker_id = str(result.get("brokerage_order_id") or "") or None
        tracked.broker_order_id = broker_id
        self._tracked[order.id] = tracked
        if broker_id:
            await self._link_broker_order(order.id, broker_id)
        tracked.accepted_emitted = True
        await self.emit(ExecReport(kind="accepted", order_id=order.id))

    def _throttle(self, account_id: str):
        return _SubmitThrottle(self, account_id)

    async def _link_broker_order(self, order_id: str, broker_order_id: str) -> None:
        async with self._sf() as session:
            order = await session.get(Order, order_id)
            if order is not None:
                order.broker_order_id = broker_order_id
                await session.commit()
        await self._journal.append(
            ev.BROKER_ORDER_LINKED, {"brokerOrderId": broker_order_id},
            aggregate_type="order", aggregate_id=order_id)

    async def _reconcile_unknown(self, order: BrokerOrder, tracked: _Tracked) -> None:
        """Submit outcome unknown: search the broker for our client_order_id.

        Never resubmits. Found → adopt and track; not found after the window →
        the order was (as far as we can tell) never accepted, so reject.
        """
        window = float(self._settings.get("snaptrade.reconcile_seconds", 60))
        poll_interval = min(2.0, max(0.05, window / 5))
        deadline = time.monotonic() + window
        while time.monotonic() < deadline:
            try:
                rows = await self._client.request(
                    "GET", f"/api/v1/accounts/{tracked.account_id}/recentOrders")
            except (SnapTradeError, SnapTradeUnknownOutcome):
                rows = None
            match = self._find_reconcile_match(rows or {}, order, tracked)
            if match is not None:
                broker_id = str(match.get("brokerage_order_id") or "") or None
                tracked.broker_order_id = broker_id
                self._tracked[order.id] = tracked
                if broker_id:
                    await self._link_broker_order(order.id, broker_id)
                tracked.accepted_emitted = True
                await self.emit(ExecReport(kind="accepted", order_id=order.id))
                return
            await asyncio.sleep(poll_interval)
        await self.emit(ExecReport(
            kind="rejected", order_id=order.id,
            reason="submit outcome unknown; order not found at broker after reconcile"))

    def _find_reconcile_match(self, payload: Any, order: BrokerOrder,
                              tracked: _Tracked) -> dict | None:
        rows = payload.get("orders") if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            return None
        known = {t.broker_order_id for t in self._tracked.values() if t.broker_order_id}
        for row in rows:
            if not isinstance(row, dict):
                continue
            if str(row.get("client_order_id") or "") == tracked.client_order_id:
                return row
            # fallback heuristic when the broker doesn't echo client ids
            if (str(row.get("brokerage_order_id") or "") not in known
                    and self._row_symbol(row) == order.symbol
                    and str(row.get("action") or "").startswith(order.side.value)
                    and abs(float(row.get("total_quantity") or 0) - order.qty) < 1e-9):
                return row
        return None

    # ---------------------------------------------------------------- cancel
    async def cancel(self, order_id: str) -> None:
        t = self._tracked.get(order_id)
        if t is None:
            return
        if not t.broker_order_id:
            t.cancel_requested = True  # acted on once the reconcile links it
            return
        try:
            await self._client.request(
                "POST", f"/api/v1/accounts/{t.account_id}/trading/cancel",
                {"brokerage_order_id": t.broker_order_id})
        except SnapTradeError as exc:
            log.warning("snaptrade cancel rejected for %s: %s", order_id, exc)
        except SnapTradeUnknownOutcome:
            pass  # final state arrives via poll either way

    # ---------------------------------------------------------------- polling
    async def _poll_loop(self) -> None:
        while True:
            interval = float(self._settings.get("snaptrade.order_poll_seconds", 2.0))
            if not self._tracked:
                await asyncio.sleep(max(interval, 1.0))
                continue
            try:
                await self.poll_once()
            except Exception:  # pragma: no cover - defensive
                log.exception("snaptrade order poll failed")
            await asyncio.sleep(interval)

    async def poll_once(self) -> None:
        """One pass over accounts with tracked orders; emits deltas."""
        by_account: dict[str, list[_Tracked]] = {}
        for t in self._tracked.values():
            by_account.setdefault(t.account_id, []).append(t)
        for account_id, tracked_list in by_account.items():
            try:
                payload = await self._client.request(
                    "GET", f"/api/v1/accounts/{account_id}/recentOrders")
                self._healthy = True
            except (SnapTradeError, SnapTradeUnknownOutcome) as exc:
                log.warning("recentOrders failed for %s: %s", account_id, exc)
                self._healthy = False
                continue
            rows = payload.get("orders") if isinstance(payload, dict) else payload
            if not isinstance(rows, list):
                continue
            by_broker_id = {
                str(r.get("brokerage_order_id") or ""): r
                for r in rows if isinstance(r, dict)}
            for t in list(tracked_list):
                row = by_broker_id.get(t.broker_order_id or "")
                if row is None and t.client_order_id:
                    row = next((r for r in rows if isinstance(r, dict)
                                and str(r.get("client_order_id") or "") == t.client_order_id),
                               None)
                if row is not None:
                    await self._apply_row(t, row)
                # act on cancels that were requested before the broker id existed
                if t.cancel_requested and t.broker_order_id:
                    t.cancel_requested = False
                    await self.cancel(t.order_id)

    @staticmethod
    def _row_symbol(row: dict) -> str | None:
        uni = row.get("universal_symbol") or {}
        ticker = uni.get("symbol") if isinstance(uni, dict) else None
        exch = (uni.get("exchange") or {}) if isinstance(uni, dict) else {}
        code = exch.get("code") if isinstance(exch, dict) else None
        return normalize_symbol(str(ticker), code) if ticker else None

    async def _apply_row(self, t: _Tracked, row: dict) -> None:
        if not t.broker_order_id and row.get("brokerage_order_id"):
            t.broker_order_id = str(row["brokerage_order_id"])
            await self._link_broker_order(t.order_id, t.broker_order_id)
        status = str(row.get("status") or "").upper()
        if status in _NO_ACTION:
            return
        if status in _WORKING and not t.accepted_emitted:
            t.accepted_emitted = True
            await self.emit(ExecReport(kind="accepted", order_id=t.order_id))
            return
        cum = float(row.get("filled_quantity") or 0.0)
        price = float(row.get("execution_price") or 0.0)
        if cum > t.cum + 1e-9:
            delta = cum - t.cum
            # derive the tranche price from cumulative averages when possible
            fill_price = price
            if t.cum > 0 and price > 0 and t.avg > 0:
                fill_price = max(0.0, (cum * price - t.cum * t.avg) / delta)
            t.cum, t.avg = cum, price or t.avg
            await self.emit(ExecReport(
                kind="fill", order_id=t.order_id, fill_qty=delta,
                fill_price=fill_price or price,
                exec_id=exec_id_for(t.broker_order_id or t.order_id, cum)))
        if status in ("EXECUTED",):
            self._tracked.pop(t.order_id, None)
        elif status in ("CANCELED", "PARTIAL_CANCELED"):
            self._tracked.pop(t.order_id, None)
            await self.emit(ExecReport(kind="cancelled", order_id=t.order_id,
                                       reason=status.lower()))
        elif status in ("REJECTED", "FAILED"):
            self._tracked.pop(t.order_id, None)
            await self.emit(ExecReport(kind="rejected", order_id=t.order_id,
                                       reason=f"broker status {status}"))
        elif status == "EXPIRED":
            self._tracked.pop(t.order_id, None)
            await self.emit(ExecReport(kind="expired", order_id=t.order_id))


class _SubmitThrottle:
    """Async context manager enforcing >=1.1s between trade/place per account."""

    MIN_SPACING = 1.1

    def __init__(self, broker: SnapTradeBroker, account_id: str) -> None:
        self._broker = broker
        self._account_id = account_id
        self._lock = broker._submit_locks.setdefault(account_id, asyncio.Lock())

    async def __aenter__(self):
        await self._lock.acquire()
        last = self._broker._last_submit.get(self._account_id, 0.0)
        wait = last + self.MIN_SPACING - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        return self

    async def __aexit__(self, *exc):
        self._broker._last_submit[self._account_id] = time.monotonic()
        self._lock.release()
        return False


# --- account sync ---------------------------------------------------------------

class SnapTradeSync:
    """Periodic authoritative sync of connections, accounts, balances, positions."""

    def __init__(
        self,
        client: SnapTradeClient,
        session_factory: async_sessionmaker,
        positions,           # PositionKeeper
        journal,
        settings,
        bus,
        ensure_symbol,       # async Callable[[str], None]
    ) -> None:
        self._client = client
        self._sf = session_factory
        self._positions = positions
        self._journal = journal
        self._settings = settings
        self._bus = bus
        self._ensure_symbol = ensure_symbol
        self._account_to_portfolio: dict[str, str] = {}
        self._portfolio_to_account: dict[str, str] = {}
        self.last_sync_at: str | None = None
        self.providers: list[dict] = []
        self._sync_lock = asyncio.Lock()

    def account_for(self, portfolio_id: str) -> str | None:
        return self._portfolio_to_account.get(portfolio_id)

    async def load_links(self) -> None:
        async with self._sf() as session:
            for acct in (await session.execute(select(BrokerageAccount))).scalars():
                self._account_to_portfolio[acct.id] = acct.portfolio_id
                self._portfolio_to_account[acct.portfolio_id] = acct.id

    # ---------------------------------------------------------------- loop
    async def run(self) -> None:
        while True:
            try:
                await self.sync_once()
            except Exception:  # pragma: no cover - defensive
                log.exception("snaptrade sync failed")
            minutes = float(self._settings.get("snaptrade.sync_minutes", 15))
            await asyncio.sleep(max(60.0, minutes * 60))

    async def sync_once(self) -> dict:
        async with self._sync_lock:
            return await self._sync_once_inner()

    async def _sync_once_inner(self) -> dict:
        connections = await self._client.request("GET", "/api/v1/authorizations")
        accounts = await self._client.request("GET", "/api/v1/accounts")
        conn_by_id: dict[str, dict] = {}
        for conn in connections or []:
            cid = str(conn.get("id") or "")
            brokerage = (conn.get("brokerage") or {})
            conn_by_id[cid] = {
                "connectionId": cid,
                "broker": brokerage.get("display_name") or brokerage.get("name") or "?",
                "type": str(conn.get("type") or "read"),
                "disabled": bool(conn.get("disabled")),
                "accounts": [],
            }
            if conn.get("disabled"):
                await self._journal.append(
                    ev.BROKER_DISCONNECTED,
                    {"broker": "snaptrade", "connection": conn_by_id[cid]["broker"],
                     "error": "connection disabled — re-authorize via snaptrade_check"})

        for acct in accounts or []:
            await self._sync_account(acct, conn_by_id)

        self.providers = list(conn_by_id.values())
        self.last_sync_at = dt.datetime.now(dt.timezone.utc).isoformat()
        payload = self.payload()
        self._bus.publish(topics.SYSTEM, {"kind": "brokerage", **payload})
        return payload

    def payload(self) -> dict:
        return {
            "enabled": True,
            "lastSyncAt": self.last_sync_at,
            "providers": self.providers,
        }

    async def _sync_account(self, acct: dict, conn_by_id: dict[str, dict]) -> None:
        account_id = str(acct.get("id") or "")
        if not account_id:
            return
        institution = str(acct.get("institution_name") or "?")
        acct_name = str(acct.get("name") or acct.get("number") or account_id[:8])
        number = str(acct.get("number") or "")
        currency = self._account_currency(acct)
        conn_id = str(acct.get("brokerage_authorization") or "")
        # "Webull MARGIN" already names the broker — don't produce "Webull Canada Webull MARGIN"
        display_name = (acct_name if institution.split()[0].lower() in acct_name.lower()
                        else f"{institution} {acct_name}")

        portfolio_id = self._account_to_portfolio.get(account_id)
        if portfolio_id is None:
            portfolio_id = await self._provision(
                account_id, conn_id, institution, display_name, number, currency, acct)
        else:
            await self._maybe_rename(portfolio_id, display_name)

        cash = await self._fetch_cash(account_id, currency, acct)
        positions = await self._fetch_positions(account_id)
        for p in positions:
            try:
                await self._ensure_symbol(p["symbol"])
            except Exception:  # pragma: no cover
                log.debug("ensure_symbol failed for %s", p["symbol"])

        await self._positions.sync_portfolio_state(
            portfolio_id, cash=cash,
            positions=[{"symbol": p["symbol"], "secType": p.get("secType", "STK"),
                        "qty": p["qty"], "avgCost": p["avgCost"]} for p in positions])

        now = dt.datetime.now(dt.timezone.utc)
        async with self._sf() as session:
            row = await session.get(BrokerageAccount, account_id)
            if row is not None:
                row.last_synced_at = now
                row.meta = {"balance": acct.get("balance"), "rawName": acct.get("name")}
                await session.commit()

        equity = await self._positions.equity(portfolio_id)
        entry = {
            "id": account_id,
            "portfolioId": portfolio_id,
            "institution": institution,
            "name": display_name,
            "number": number,
            "currency": currency,
            "accountType": str((acct.get("meta") or {}).get("type") or acct.get("raw_type") or ""),
            "cash": round(cash, 2),
            "equity": round(equity, 2),
            "syncedAt": now.isoformat(),
            "positions": positions,
        }
        target = conn_by_id.get(conn_id)
        if target is None:
            target = conn_by_id.setdefault(conn_id or account_id, {
                "connectionId": conn_id, "broker": institution, "type": "read",
                "disabled": False, "accounts": []})
        target["accounts"].append(entry)

    def _account_currency(self, acct: dict) -> str:
        bal = ((acct.get("balance") or {}).get("total") or {})
        cur = bal.get("currency")
        if isinstance(cur, dict):
            cur = cur.get("code")
        return str(cur or "CAD").upper()

    async def _maybe_rename(self, portfolio_id: str, name: str) -> None:
        pf = self._positions.portfolio(portfolio_id)
        if pf is None or pf.get("name") == name:
            return
        async with self._sf() as session:
            row = await session.get(Portfolio, portfolio_id)
            if row is not None:
                row.name = name
                await session.commit()
        pf["name"] = name

    async def _provision(self, account_id: str, conn_id: str, institution: str,
                         name: str, number: str, currency: str, acct: dict) -> str:
        pid = new_id()
        async with self._sf() as session:
            portfolio = Portfolio(
                id=pid, name=name, kind="live", base_currency=currency,
                starting_cash=0.0, cash=0.0, source_name="snaptrade")
            session.add(portfolio)
            await session.commit()  # link's FK needs the portfolio row first
            link = BrokerageAccount(
                id=account_id, portfolio_id=pid, venue="snaptrade",
                connection_id=conn_id or None, institution=institution,
                number=number or None, currency=currency,
                account_type=str((acct.get("meta") or {}).get("type") or "") or None)
            session.add(link)
            await session.commit()
        self._account_to_portfolio[account_id] = pid
        self._portfolio_to_account[pid] = account_id
        self._positions.register_portfolio(portfolio, venue="snaptrade")
        await self._journal.append(
            ev.BROKERAGE_ACCOUNT_LINKED,
            {"accountId": account_id, "institution": institution, "name": name,
             "currency": currency},
            portfolio_id=pid)
        self._bus.publish(topics.PORTFOLIO, {
            "id": pid, "name": name, "kind": "live", "cash": 0.0, "ts": now_iso()})
        return pid

    async def _fetch_cash(self, account_id: str, currency: str, acct: dict) -> float:
        """Cash for the account's primary currency; falls back to balance.total."""
        try:
            balances = await self._client.request(
                "GET", f"/api/v1/accounts/{account_id}/balances")
        except (SnapTradeError, SnapTradeUnknownOutcome):
            balances = None
        if isinstance(balances, list):
            for bal in balances:
                cur = (bal.get("currency") or {})
                code = cur.get("code") if isinstance(cur, dict) else cur
                if str(code or "").upper() == currency and bal.get("cash") is not None:
                    return float(bal["cash"])
            # single-entry accounts: take the first cash figure we can find
            for bal in balances:
                if bal.get("cash") is not None:
                    return float(bal["cash"])
        total = ((acct.get("balance") or {}).get("total") or {})
        return float(total.get("amount") or 0.0)

    async def _fetch_positions(self, account_id: str) -> list[dict]:
        """Parsed positions via the unified endpoint, legacy as fallback."""
        try:
            payload = await self._client.request(
                "GET", f"/api/v1/accounts/{account_id}/positions/all")
            rows = payload.get("results") if isinstance(payload, dict) else None
            return [p for p in (extract_unified_position(r) for r in rows or []) if p]
        except SnapTradeError as exc:
            if exc.status not in (404, 410):
                log.warning("positions/all failed for %s: %s", account_id, exc)
                return []
        except SnapTradeUnknownOutcome as exc:
            log.warning("positions/all failed for %s: %s", account_id, exc)
            return []
        # older accounts: the pre-2026 positions endpoint
        try:
            rows = await self._client.request(
                "GET", f"/api/v1/accounts/{account_id}/positions")
        except (SnapTradeError, SnapTradeUnknownOutcome) as exc:
            log.warning("positions fetch failed for %s: %s", account_id, exc)
            return []
        rows = rows if isinstance(rows, list) else []
        return [p for p in (extract_position(r) for r in rows) if p]


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()
