"""Team2: the per-technique 0DTE policy in RiskGate (E6), the premium-targeted strike picker
(E7) and the registry entry. In-memory fakes, no DB."""
from __future__ import annotations

import datetime as dt

from zargar.options.pick import select_by_premium
from zargar.techniques.base import all_techniques, get_technique

from tests.test_riskgate import FakeQuotes, FakeSettings, P, check, intent, make_gate


def _sym(today: dt.date | None = None, strike: int = 100) -> str:
    today = today or dt.date.today()
    return f"SPY{today:%y%m%d}C{strike * 1000:08d}"


async def test_team2_zero_dte_policy_opens_the_never_list_only_with_a_policy():
    quotes = FakeQuotes()
    sym = _sym()
    quotes.set(sym, 0.55)
    # no policy → the hard reject stands (every other technique keeps the never-list)
    v = await make_gate(settings=FakeSettings(), quotes=quotes).evaluate(
        intent(symbol=sym, sec_type="OPT", qty=1, limit_price=0.55, technique_id="team2"), P)
    assert not check(v, "option_not_expired").passed
    assert "zero_dte policy" in check(v, "option_not_expired").detail
    # policy enabled, generous times → allowed
    settings = FakeSettings(**{"techniques.team2.zero_dte": {
        "enabled": True, "last_entry_et": "23:58", "flatten_et": "23:59", "max_contracts": 10, "premium_cap": 1000.0}})
    gate = make_gate(settings=settings, quotes=quotes)
    v = await gate.evaluate(intent(symbol=sym, sec_type="OPT", qty=2, limit_price=0.55, technique_id="team2"), P)
    assert check(v, "option_not_expired").passed
    assert check(v, "zero_dte_max_contracts").passed and check(v, "zero_dte_premium_cap").passed
    # another technique with the same intent is still rejected
    v2 = await gate.evaluate(intent(symbol=sym, sec_type="OPT", qty=2, limit_price=0.55, technique_id="flow"), P)
    assert not check(v2, "option_not_expired").passed


async def test_team2_zero_dte_policy_caps_and_times():
    quotes = FakeQuotes()
    sym = _sym()
    quotes.set(sym, 0.55)
    pol = {"enabled": True, "last_entry_et": "23:58", "flatten_et": "23:59", "max_contracts": 5, "premium_cap": 200.0}
    gate = make_gate(settings=FakeSettings(**{"techniques.team2.zero_dte": pol}), quotes=quotes)
    v = await gate.evaluate(intent(symbol=sym, sec_type="OPT", qty=6, limit_price=0.55, technique_id="team2"), P)
    assert not check(v, "zero_dte_max_contracts").passed
    assert not check(v, "zero_dte_premium_cap").passed          # 6 × 0.55 × 100 = $330 > $200
    # past the last-entry time a BUY is refused
    pol_late = dict(pol, last_entry_et="00:00", flatten_et="23:59")
    gate2 = make_gate(settings=FakeSettings(**{"techniques.team2.zero_dte": pol_late}), quotes=quotes)
    v = await gate2.evaluate(intent(symbol=sym, sec_type="OPT", qty=1, limit_price=0.55, technique_id="team2"), P)
    assert not check(v, "option_not_expired").passed and "no new entries after 00:00" in check(v, "option_not_expired").detail
    # disabled policy → reject
    gate3 = make_gate(settings=FakeSettings(**{"techniques.team2.zero_dte": dict(pol, enabled=False)}), quotes=quotes)
    v = await gate3.evaluate(intent(symbol=sym, sec_type="OPT", qty=1, limit_price=0.55, technique_id="team2"), P)
    assert not check(v, "option_not_expired").passed


def _chain(spot: float, asks: dict[float, float], kind: str = "call") -> list[dict]:
    rows = []
    for k, ask in asks.items():
        rows.append({"symbol": f"SPY260903{'C' if kind == 'call' else 'P'}{int(k * 1000):08d}", "underlying": "SPY",
                     "option_type": kind, "strike": k, "bid": round(ask - 0.02, 2), "ask": ask,
                     "volume": 5000, "open_interest": 8000, "greeks": {"delta": 0.2, "mid_iv": 0.2}})
    return rows


def test_select_by_premium_walks_otm_to_the_target_band():
    today = dt.date(2026, 9, 3)
    chain = _chain(768.4, {768: 1.90, 769: 1.10, 770: 0.62, 771: 0.34, 772: 0.15, 773: 0.06})
    pick = select_by_premium(chain, 768.4, "long", target_premium=0.60, premium_floor=0.20, expiry="2026-09-03",
                             today=today, is_0dte=True, mode="first_under")
    assert pick is not None and pick.strike == 771 and pick.ask == 0.34      # legacy walk: first ask <= 0.60 that is >= 0.20
    # F36 (default "closest"): the strike whose ask is nearest the target — 770 @ 0.62 beats 771 @ 0.34 for a $0.60 target
    close = select_by_premium(chain, 768.4, "long", target_premium=0.60, premium_floor=0.20, expiry="2026-09-03",
                              today=today, is_0dte=True)
    assert close is not None and abs(close.ask - 0.60) <= abs(0.34 - 0.60)
    pick2 = select_by_premium(chain, 768.4, "long", target_premium=0.40, premium_floor=0.20, expiry="2026-09-03",
                              today=today, is_0dte=True, mode="first_under")
    assert pick2.strike == 771
    # target below every floor-respecting ask: previous strike accepted only within 1.5×
    pick3 = select_by_premium(chain, 768.4, "long", target_premium=0.09, premium_floor=0.20, expiry="2026-09-03",
                              today=today, is_0dte=True, mode="first_under")
    assert pick3 is None
    pick4 = select_by_premium(chain, 768.4, "long", target_premium=0.12, premium_floor=0.20, expiry="2026-09-03",
                              today=today, is_0dte=True, mode="first_under")
    assert pick4 is not None and pick4.strike == 772          # 0.15 ≤ 1.5 × 0.12
    puts = _chain(768.4, {768: 1.80, 767: 1.05, 766: 0.58, 765: 0.30}, kind="put")
    pp = select_by_premium(puts, 768.4, "short", target_premium=0.60, premium_floor=0.20, expiry="2026-09-03",
                           today=today, is_0dte=True, mode="first_under")
    assert pp.strike == 766 and pp.option_type == "put" and pp.is_0dte and "V1" in pp.rules
    assert select_by_premium([], 768.4, "long", target_premium=0.6, premium_floor=0.2, expiry="2026-09-03",
                             today=today, is_0dte=True) is None


def test_registry_lists_team2():
    info = get_technique("team2")
    assert info is not None and info.settings_prefix == "techniques.team2." and info.page == "team2"
    assert "team2" in {t.id for t in all_techniques()}
