"""The trading universe (technique/universe.py): core + extras + the day's most active."""
from zargar.technique.universe import CORE_UNIVERSE, is_us_optionable_symbol, resolve


def test_core_universe_is_big_liquid_and_us_only():
    assert len(CORE_UNIVERSE) >= 100 and len(set(CORE_UNIVERSE)) == len(CORE_UNIVERSE)
    assert CORE_UNIVERSE[:4] == ["SPY", "QQQ", "TSLA", "NVDA"]       # most options-liquid first
    assert all(is_us_optionable_symbol(s) for s in CORE_UNIVERSE)
    assert "CHPT" not in CORE_UNIVERSE and "SOUN" not in CORE_UNIVERSE   # the names that hurt us are out


def test_symbol_shape_filter():
    assert is_us_optionable_symbol("AAPL") and is_us_optionable_symbol("BRK.B")
    assert not is_us_optionable_symbol("SHOP.TO") and not is_us_optionable_symbol("USDCAD=X")
    assert not is_us_optionable_symbol("AAPL260828C00230000") and not is_us_optionable_symbol("")


def test_resolve_merges_layers_with_floor_and_exclusions():
    auto = [{"symbol": "SOFI", "volume": 90_000_000, "price": 18.8},          # under the floor
            {"symbol": "SNDK", "volume": 50_000_000, "price": 45.0},
            {"symbol": "AAPL", "volume": 40_000_000, "price": 315.0},          # already core
            {"symbol": "SHOP.TO", "volume": 30_000_000, "price": 150.0},       # not US
            {"symbol": "RKLB", "volume": 20_000_000, "price": None},           # no price -> not added
            {"symbol": "IREN", "volume": 10_000_000, "price": 33.0}]
    r = resolve(core=["SPY", "AAPL", "T"], extra=["shop", "SPY"], exclude=["T", "IREN"], auto=auto,
                min_price=20.0, auto_top=5, prices={"RKLB": 41.0} if False else {})
    assert r["symbols"] == ["SPY", "AAPL", "SHOP", "SNDK"]
    assert r["provenance"] == {"SPY": "core", "AAPL": "core", "SHOP": "extra", "SNDK": "auto"}
    reasons = {d["symbol"]: d["reason"] for d in r["dropped"]}
    assert reasons["T"] == "excluded" and reasons["IREN"] == "excluded"
    assert reasons["SOFI"].startswith("price 18.80") and "US equity" in reasons["SHOP.TO"] and "no price" in reasons["RKLB"]
    assert r["counts"] == {"core": 2, "extra": 1, "auto": 1}
    # the auto cap
    r2 = resolve(core=[], extra=[], exclude=[], auto=auto, min_price=20.0, auto_top=1)
    assert r2["symbols"] == ["SNDK"]
