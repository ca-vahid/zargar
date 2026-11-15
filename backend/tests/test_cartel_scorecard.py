"""The trial's single score: closed campaigns only, net of every commission, never a mark."""
from zargar.tools.cartel_scorecard import score, verdict

OPT = "DHT261120C00022000"


def fill(side, qty, price, tag, fee):
    return {"side": side, "qty": qty, "price": price, "commission": fee, "symbol": OPT, "tags": [tag], "ts": 1}


def test_partial_exit_is_not_a_closed_trade_and_no_mark_is_counted():
    pos = [{"id": "p1", "symbol": "DHT", "status": "open", "runId": "r1", "openedMs": 10}]
    fills = [fill("BUY", 5, 1.8, "cartel_run:r1", 5.2), fill("SELL", 1, 2.2, "managed_exit:p1:x", 1.04)]
    card = score(pos, fills, start_ms=0)
    assert card["closedTrades"] == 0 and card["net"] == 0 and card["openTrades"] == 1
    t = card["trades"][0]
    assert t["net"] is None and t["bankedSoFar"] == 213.76 and t["costStillOpen"] == 720.0


def test_closed_trade_is_net_of_both_commissions_and_ignores_other_positions_fills():
    pos = [{"id": "p1", "symbol": "DHT", "status": "closed", "runId": "r1", "openedMs": 10},
           {"id": "old", "symbol": "APA", "status": "closed", "runId": "r0", "openedMs": 1}]
    fills = [fill("BUY", 2, 1.0, "cartel_run:r1", 2.08), fill("SELL", 1, 1.5, "managed_exit:p1:a", 1.04),
             fill("SELL", 1, 0.5, "managed_exit:p1:b", 1.04), fill("BUY", 1, 9.0, "cartel_run:r0", 1.04)]
    card = score(pos, fills, start_ms=5)
    assert [t["positionId"] for t in card["trades"]] == ["p1"]            # opened before the start: excluded
    assert card["closedTrades"] == 1 and card["net"] == round(200-200-4.16, 2) and card["winners"] == 0


def test_verdict_follows_the_preregistered_table_and_flags_one_trade_dependence():
    few = {"closedTrades": 3, "net": 500.0, "netWithoutBest": 100.0}
    assert verdict(few, sessions_run=20, sessions=20).startswith("STOP: fewer than 8")
    assert verdict(few, sessions_run=6, sessions=20).startswith("not final")
    lost = {"closedTrades": 9, "net": -1.0, "netWithoutBest": -50.0}
    assert verdict(lost, sessions_run=20, sessions=20).startswith("STOP: net")
    lucky = {"closedTrades": 9, "net": 300.0, "netWithoutBest": -20.0}
    assert verdict(lucky, sessions_run=20, sessions=20) == "KEEP: longer sample, never live money on this evidence alone (depends on one trade)"
