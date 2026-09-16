"""Independent P-02 research regressions at ba2eccb.

No real database, engine start, network, or orders. The first test passes an
actual production capture payload to the report reducer. The second exercises
report assembly through an in-memory asyncpg double, keeping fees from fills.
"""
import asyncio
import datetime as dt
from types import SimpleNamespace
from unittest.mock import AsyncMock

import asyncpg
import pytest

from zargar.tools import em_profitability as ep
from tests.test_em_forward_measurement import NOW, Quote, Quotes, plan, runner, trade


def test_p02_reducer_consumes_the_actual_production_capture_payload():
    quotes = Quotes({
        "X": Quote("X", bid=100.99, ask=101.01, last=101.0,
                   ts=NOW, source="iex", source_ts=NOW),
        "X260918C00101000": Quote("X260918C00101000", bid=1.9, ask=2.0,
                   last=1.95, bid_size=40, ask_size=40,
                   ts=NOW, source="opra", source_ts=NOW),
    })
    r = runner(quotes, settings={"execution.shadow_p02_candidate": True})
    tr = trade(entry_order_id="entry-p02", remaining=2.0, filled_qty=2.0,
               targets=[101.0, 103.0, 104.0])
    payloads = r._shadow_capture(plan(), [tr], quotes["X"], NOW, 0.25)
    assert len(payloads) == 1 and payloads[0]["rung"] == "tp1-candidate"
    assert payloads[0]["modeled"]["scorable"]
    assert payloads[0]["modeled"]["coveredQty"] == 1.0
    result = ep.p02_compare({
        "filledQty": 2, "avgFill": 1.0, "multiplier": 100.0,
        "productionRealized": 195.84, "productionPerContract": [97.92, 97.92],
        "entryOrderId": "entry-p02", "contract": {"symbol": tr.order_symbol},
    }, payloads, 1.04)
    assert result["outcome"] == "compared", result
    assert result["alternativeRealized"] == pytest.approx(185.84)
    assert result["delta"] == pytest.approx(-10.0)
    assert result["forgoneOnWinner"] == pytest.approx(10.0)


def test_p02_later_first_covered_bid_survives_an_unscorable_first_touch():
    underlying = Quote("X", bid=100.99, ask=101.01, last=101.0,
                       ts=NOW, source="iex", source_ts=NOW)
    quotes = Quotes({"X": underlying})  # no contract quote at the first touch
    r = runner(quotes, settings={"execution.shadow_p02_candidate": True})
    ap = plan()
    tr = trade(entry_order_id="entry-late-quote", remaining=2.0, filled_qty=2.0,
               targets=[101.0, 103.0, 104.0])
    first = r._shadow_capture(ap, [tr], underlying, NOW, 0.25)
    assert len(first) == 1 and not first[0]["modeled"]["scorable"]
    asyncio.run(r._shadow_record(ap, first))  # journal is an AsyncMock
    quotes[tr.order_symbol] = Quote(tr.order_symbol, bid=1.9, ask=2.0, last=1.95,
                                   bid_size=40, ask_size=40, ts=NOW + 500,
                                   source="opra", source_ts=NOW + 500)
    later = r._shadow_capture(ap, [tr], underlying, NOW + 500, 0.25)
    assert any(p["rung"] == "tp1-candidate" and p["modeled"]["scorable"]
               and p["modeled"]["coveredQty"] == 1.0 for p in later), later


class _FeeBook:
    """Two contracts: buy at $1, later sell at $2; entry fee $1/contract,
    exit fee $2/contract. At the same $2 alternative bid, with the same
    $2/contract exit fee, moving the first exit cannot change $194 net.
    """
    async def execute(self, sql):
        assert "read only" in sql

    async def close(self):
        pass

    async def fetch(self, sql, *args):
        moment = dt.datetime(2026, 9, 15, 14, 0, tzinfo=dt.timezone.utc)
        fired = int(moment.timestamp() * 1000)
        if "from technique_armed" in sql:
            return [{"run_id": "fee-run", "symbol": "X", "config": {},
                     "plan": {"triggers": [{"id": "b1", "kind": "bounce", "direction": "long",
                            "level": {"price": 100.0}, "targets": [{"price": 101.0, "basis": "next_resistance"}]}]},
                     "state": {"trades": [{"triggerId": "b1", "firedTs": fired,
                            "kind": "bounce", "direction": "long", "status": "closed", "instrument": "options",
                            "entry": 100.0, "stop": 99.0, "targets": [101.0, 103.0],
                            "filledQty": 2.0, "avgFill": 1.0, "multiplier": 100.0,
                            "entryOrderId": "entry-fee", "exits": [{"orderId": "exit-fee", "kind": "tp2"}]}]}}]
        if "select commission, symbol, qty from executions" in sql:
            return [{"commission": 2.0, "symbol": "X260918C00101000", "qty": 2.0},
                    {"commission": 4.0, "symbol": "X260918C00101000", "qty": 2.0}]
        if "from events" in sql:
            # The existing reducer's documented schema intentionally isolates the
            # fee calculation from the independent real-payload mismatch above.
            payloads = [
                ("TechniquePlanOrderIntent", {"trigger": "b1", "contract": {"symbol": "X260918C00101000", "bid": 0.99, "ask": 1.0}}),
                ("TechniqueTargetDistance", {"trigger": "b1", "stage": "fill", "nextRungDistanceR": 3.0}),
                ("TechniqueExitShadow", {"trigger": "b1", "tradeInstance": "entry-fee", "rung": "tp1-candidate",
                    "disposition": "covered", "bid": 2.0, "observedTs": fired + 60_000}),
            ]
            return [{"ts": moment, "type": ty, "payload": payload} for ty, payload in payloads]
        if "from bars" in sql:
            return [{"ts": fired, "open": 100.0, "high": 100.1, "low": 99.9, "close": 100.0}]
        if "select order_id, side, qty, price, commission, ts from executions" in sql:
            return [
                {"order_id": "entry-fee", "side": "BUY", "qty": 2.0, "price": 1.0, "commission": 2.0, "ts": moment},
                {"order_id": "exit-fee", "side": "SELL", "qty": 2.0, "price": 2.0, "commission": 4.0, "ts": moment + dt.timedelta(minutes=5)},
            ]
        raise AssertionError(f"Unexpected read: {sql}")


def test_p02_keeps_actual_entry_and_retained_exit_fees_in_the_pair(monkeypatch, tmp_path):
    from zargar import config
    monkeypatch.setattr(config, "AppConfig", lambda: SimpleNamespace(database_url="postgresql://unused/never-connected"))
    monkeypatch.setattr(asyncpg, "connect", AsyncMock(return_value=_FeeBook()))
    monkeypatch.setattr(ep, "LEDGER", str(tmp_path / "no-source-ledger.json"))
    result = asyncio.run(ep.build("2026-09-15"))
    row = result["trades"][0]
    assert row["netRealized"] == pytest.approx(194.0)
    assert row["p02"]["outcome"] == "compared"
    assert row["p02"]["alternativeRealized"] == pytest.approx(194.0), row["p02"]
    assert row["p02"]["delta"] == pytest.approx(0.0)
