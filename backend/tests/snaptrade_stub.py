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
        self.unified_positions: dict[str, list] | None = None  # served at /positions/all when set
        self.recent_orders: dict[str, list] = {}
        self.place_response: dict = {"brokerage_order_id": "bo-1", "status": "PENDING"}
        self.place_error: int | Exception | None = None
        self.recent_error: Exception | None = None
        self.cancel_response: dict = {"brokerage_order_id": "bo-1"}
        # options endpoints (/accounts/{id}/trading/options[/impact])
        self.option_place_response: dict = {"brokerage_order_id": "obo-1", "orders": []}
        self.option_place_error: int | Exception | None = None
        self.option_impact_response: dict = {
            "estimated_cash_change": "21.0400", "cash_change_direction": "DEBIT",
            "estimated_fee_total": "1.0400"}
        # per-account override: account id -> (status, body) e.g. Wealthsimple's 1156
        self.option_impact_errors: dict[str, tuple[int, dict]] = {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        body = json.loads(request.content) if request.content else None
        self.requests.append((request.method, path, dict(request.url.params), body))

        if path.endswith("/symbols") and request.method == "POST":
            return httpx.Response(200, json=[
                {"id": "uni-aapl", "symbol": "AAPL", "raw_symbol": "AAPL"},
                {"id": "uni-aapl-to", "symbol": "AAPL.TO", "raw_symbol": "AAPL"},
            ])
        if path == "/api/v1/trade/impact":
            return httpx.Response(200, json={
                "trade": {"id": "trade-1"},
                "trade_impacts": [{"estimated_commission": 2.99, "forex_fees": 10.67,
                                   "remaining_cash": 55.5}],
                "combined_remaining_balance": {"cash": 55.5,
                                               "currency": {"code": "CAD"}},
            })
        if path.endswith("/trading/options/impact") and request.method == "POST":
            account_id = path.split("/")[4]
            err = self.option_impact_errors.get(account_id)
            if err is not None:
                return httpx.Response(err[0], json=err[1])
            return httpx.Response(200, json=self.option_impact_response)
        if path.endswith("/trading/options") and request.method == "POST":
            if isinstance(self.option_place_error, Exception):
                raise self.option_place_error
            if isinstance(self.option_place_error, int):
                return httpx.Response(self.option_place_error,
                                      json={"detail": "broker says no to options"})
            return httpx.Response(200, json=self.option_place_response)
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
        if path.endswith("/positions/all"):
            account_id = path.split("/")[4]
            if self.unified_positions is None:
                return httpx.Response(410, json={"detail": "endpoint retired"})
            return httpx.Response(
                200, json={"results": self.unified_positions.get(account_id, [])})
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
