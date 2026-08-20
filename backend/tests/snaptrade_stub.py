"""Programmable httpx.MockTransport stub of the SnapTrade API for tests."""
import json

import httpx


class StubSnapTrade:
    def __init__(self):
        self.requests: list[tuple[str, str, dict, dict | None]] = []
        self.connections: list[dict] = []
        self.accounts: list[dict] = []
        self.balances: dict[str, list] = {}
        self.positions: dict[str, list] = {}
        self.recent_orders: dict[str, list] = {}
        self.place_response: dict = {"brokerage_order_id": "bo-1", "status": "PENDING"}
        self.place_error: int | Exception | None = None
        self.recent_error: Exception | None = None
        self.cancel_response: dict = {"brokerage_order_id": "bo-1"}

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        body = json.loads(request.content) if request.content else None
        self.requests.append((request.method, path, dict(request.url.params), body))

        if path == "/api/v1/trade/place":
            if isinstance(self.place_error, Exception):
                raise self.place_error
            if isinstance(self.place_error, int):
                return httpx.Response(self.place_error, json={"detail": "broker says no"})
            return httpx.Response(200, json=self.place_response)
        if path == "/api/v1/authorizations":
            return httpx.Response(200, json=self.connections)
        if path == "/api/v1/accounts":
            return httpx.Response(200, json=self.accounts)
        if path.endswith("/recentOrders"):
            if self.recent_error is not None:
                raise self.recent_error
            account_id = path.split("/")[4]
            return httpx.Response(200, json=self.recent_orders.get(account_id, []))
        if path.endswith("/balances"):
            account_id = path.split("/")[4]
            return httpx.Response(200, json=self.balances.get(account_id, []))
        if path.endswith("/positions"):
            account_id = path.split("/")[4]
            return httpx.Response(200, json=self.positions.get(account_id, []))
        if path.endswith("/trading/cancel"):
            return httpx.Response(200, json=self.cancel_response)
        return httpx.Response(404, json={"detail": f"unstubbed path {path}"})

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)

    def calls(self, path_suffix: str) -> list:
        return [r for r in self.requests if r[1].endswith(path_suffix)]


def stub_account(account_id="acct-1", institution="Webull", name="CASH",
                 number="123", currency="CAD", total=20000.0, conn="conn-1"):
    return {
        "id": account_id,
        "brokerage_authorization": conn,
        "institution_name": institution,
        "name": name,
        "number": number,
        "balance": {"total": {"amount": total, "currency": currency}},
        "meta": {"type": "CASH"},
    }


def stub_connection(conn_id="conn-1", broker="Webull Canada", ctype="trade", disabled=False):
    return {"id": conn_id, "type": ctype, "disabled": disabled,
            "brokerage": {"display_name": broker}}


class FakeSettings:
    def __init__(self, **overrides):
        self.values = {
            "snaptrade.reconcile_seconds": 0.5,
            "snaptrade.order_poll_seconds": 0.05,
            "snaptrade.sync_minutes": 15,
            "snaptrade.allow_brackets": False,
        }
        self.values.update(overrides)

    def get(self, key, default=None):
        return self.values.get(key, default)
