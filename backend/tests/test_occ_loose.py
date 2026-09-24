"""2026-09-24: the analyst (Opus 5.5) wrote INTC260925C130; the card priced nothing and waited for a human."""
from zargar.options import occ


def test_a_short_contract_spelling_becomes_real_occ():
    assert occ.parse_loose("INTC260925C130").symbol == "INTC260925C00130000"
    assert occ.parse_loose("spy260925p742.5").symbol == "SPY260925P00742500"
    assert occ.parse_loose("INTC260925C00130000").symbol == "INTC260925C00130000"      # strict OCC unchanged


def test_a_string_that_is_not_a_contract_is_refused_not_guessed():
    for bad in ("INTC 130C", "INTC261399C130", "INTC260925X130", "", None, "INTC260925C0"):
        assert occ.parse_loose(bad) is None


def test_the_lotto_lane_is_decided_by_the_contract_actually_bought():
    """2026-09-24 RKLB 9/25 74C: no stated expiry, the analyst picked a 1-DTE call, the manager sold it 9 minutes later."""
    import datetime as dt
    from zoneinfo import ZoneInfo

    from zargar.techniques.tip.lotto import contract_lotto

    class S(dict):
        def get(self, k, d=None):
            return super().get(k, d)
    et = ZoneInfo("America/New_York")
    s = S({"techniques.tip.lotto_max_dte": 3, "techniques.tip.lotto_flatten_et": "15:45"})
    at = dt.datetime(2026, 9, 24, 12, 6, tzinfo=et)
    assert contract_lotto("RKLB260925C00074000", at, s) == "lotto"            # 1 DTE
    assert contract_lotto("RKLB261016C00074000", at, s) is None               # 22 DTE: an ordinary option
    assert contract_lotto("SPY260924P00742000", at, s) == "lotto"             # 0DTE before the flatten time
    assert contract_lotto("SPY260924P00742000", dt.datetime(2026, 9, 24, 15, 50, tzinfo=et), s) == "late"
    assert contract_lotto("RKLB", at, s) is None
