"""P1.2 venue-cost lines: the pure restatement (no database)."""
from zargar.tools.team2_cost_lines import cost_lines


def test_a_round_trip_is_restated_per_venue():
    rows = [{"book": "4b28156b", "symbol": "QQQ260925P00736000", "side": "BUY", "qty": 17, "price": 0.56},
            {"book": "4b28156b", "symbol": "QQQ260925P00736000", "side": "SELL", "qty": 17, "price": 0.3999}]
    r = cost_lines(rows)["4b28156b"]
    gross = (0.3999 - 0.56) * 17 * 100
    assert abs(r["gross"] - round(gross, 2)) < 0.01
    assert abs(r["webull_1.04"] - round(gross - 1.04 * 34, 2)) < 0.01          # the sim book's own net (-$306.54)
    assert abs(r["ibkr_0.65"] - round(gross - 0.65 * 34, 2)) < 0.01
    assert r["webull_fx1.5"] < r["webull_1.04"] and r["roundTrips"] == 1 and r["contracts"] == 17


def test_an_open_series_is_left_out():
    rows = [{"book": "012f595c", "symbol": "SPY260924C00768000", "side": "BUY", "qty": 18, "price": 0.60},
            {"book": "012f595c", "symbol": "SPY260924C00768000", "side": "SELL", "qty": 6, "price": 1.02}]
    r = cost_lines(rows)["012f595c"]
    assert r["roundTrips"] == 0 and r["openContracts"] == 1 and r["gross"] == 0.0
