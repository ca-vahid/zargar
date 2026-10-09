"""2026-10-08 setup review of the C$3k IBKR rehearsal: small-position exits merge into fewer sell orders, one position
per stock, a minimum trade size, a per-book swing stale limit, and an approval that survives a concurrent refresh."""
import datetime as dt
from types import SimpleNamespace as NS

from zargar.approvals.proposals import ProposalService, min_trade_refusal
from zargar.techniques.tip import books as _books
from zargar.techniques.tip.lifecycle import merge_small_trims, policy_from_exit_plan


class _S(dict):
    def get(self, k, d=None):
        return super().get(k, d)


def _binding(**ov):
    return _books.Binding(portfolioId="pf", role="live", overrides=ov)


# ---------------------------------------------------------------- 1B: fewer sell orders on a small position
def test_a_tiny_position_sells_in_one_order_at_the_first_target():
    lad = {"targets": [128.8], "fractions": [0.3333]}            # INTC 3 sh @ 110.50: 1 sh trim + a 2 sh runner
    new, note = merge_small_trims(lad, qty=3, price=110.5, min_notional=250)
    assert new["targets"] == [128.8] and new["fractions"] == [1.0] and "2 sell orders -> 1" in note


def test_small_trims_merge_forward_and_a_tiny_runner_goes_with_the_last_trim():
    lad = {"targets": [95.0, 97.0, 99.0], "fractions": [0.25, 0.25, 0.25]}   # 8 sh @ 92 = $736: $184 per trim
    new, note = merge_small_trims(lad, qty=8, price=92.0, min_notional=250)
    # 0.25 alone is $184 < $250 -> merges into the second rung (0.5 = $368); the third 0.25 is too small for its own
    # order, so it rides with the 0.25 runner ($368, sold by the stop/trail): 4 sell orders -> 2
    assert new["targets"] == [97.0] and new["fractions"] == [0.5] and "4 sell orders -> 2" in note
    tiny_runner = {"targets": [95.0, 97.0], "fractions": [0.45, 0.45]}      # runner 0.1 = $74 goes with the last trim
    new, _ = merge_small_trims(tiny_runner, qty=8, price=92.0, min_notional=250)
    assert new["targets"] == [95.0, 97.0] and abs(sum(new["fractions"]) - 1.0) < 1e-6


def test_a_large_position_keeps_its_ladder_and_the_knob_off_changes_nothing():
    lad = {"targets": [282.0, 286.0, 290.0], "fractions": [0.43, 0.29, 0.28]}   # IWM 7 sh = $1,938
    assert merge_small_trims(lad, qty=7, price=276.82, min_notional=250) == (lad, None)
    small = {"targets": [128.8], "fractions": [0.3333]}
    assert merge_small_trims(small, qty=3, price=110.5, min_notional=0) == (small, None)


# ---------------------------------------------------------------- 4: minimum trade size
def test_a_trade_below_the_book_minimum_is_refused_and_one_at_it_passes():
    b = _binding(minTradeNotional=400)
    why = min_trade_refusal(b, _S(), sec_type="STK", limit=30.70, qty=8)            # MGM 8 = $246
    assert why and "minimum trade" in why and "$246" in why
    assert min_trade_refusal(b, _S(), sec_type="STK", limit=110.0, qty=4) is None    # $440
    assert min_trade_refusal(_binding(), _S(), sec_type="STK", limit=30.70, qty=8) is None   # off by default
    assert min_trade_refusal(b, _S(), sec_type="OPT", limit=2.0, qty=2) is None      # $400 premium (x100)


# ---------------------------------------------------------------- 2: the book's own swing stale limit
def test_the_book_swing_stale_limit_reaches_the_exit_policy():
    plan = {"underlyingStop": 27.4, "targets": [33.74], "fractions": [0.5], "horizon": "swing",
            "horizonApplied": True, "atrDaily": 1.2}
    base = _S({"techniques.tip.horizon_swing_sessions": 10})
    assert policy_from_exit_plan(plan, is_option=False, settings=base, entry_ref=30.57)["stale"]["sessions"] == 10
    view = _books.BookSettings(base, _binding(swingStaleSessions=5))
    assert policy_from_exit_plan(plan, is_option=False, settings=view, entry_ref=30.57)["stale"]["sessions"] == 5


# ---------------------------------------------------------------- 3: one position per stock
def _svc(book_kind="paper"):
    svc = ProposalService.__new__(ProposalService)
    svc.engine = NS(settings=_S({"techniques.tip.reserve_slots": 3}),
                    positions=NS(portfolio=lambda pid: {"cash": 5000.0, "name": "Tips IBKR Paper", "kind": "sim"}))

    async def zero(pid):
        return 0

    async def src(pid, name):
        return 0, 0.0
    svc._book_open_count = zero
    svc._source_open = src
    return svc


async def test_a_second_tip_on_a_held_stock_is_refused_when_the_book_asks_for_it():
    svc = _svc()
    pol = NS(budget_per_tip=2000.0, name="jon-and-kian", max_open_tips=0, budget_open_max=0)

    async def holds(pid, u):
        return "holds" if u.upper() == "INTC" else None
    svc._name_held_or_buying = holds
    on = _binding(onePerName=True)
    budget, _n, why = await svc._tip_budget(pol, "pf", underlying="INTC", binding=on)
    assert budget == 0.0 and "one position per stock" in why and "INTC" in why
    budget, _n, why = await svc._tip_budget(pol, "pf", underlying="IWM", binding=on)
    assert why is None and budget > 0
    budget, _n, why = await svc._tip_budget(pol, "pf", underlying="INTC", binding=_binding())   # off by default
    assert why is None


# ---------------------------------------------------------------- 5: the confirmed plan survives a concurrent refresh
def test_the_confirmed_plans_limit_is_found_by_fingerprint_within_its_validity():
    svc = ProposalService.__new__(ProposalService)
    svc.engine = NS(settings=_S({"techniques.tip.geometry_quote_max_age_seconds": 300}))
    now = dt.datetime(2026, 10, 8, 17, 20, tzinfo=dt.timezone.utc)
    seen = [{"fingerprint": "b91c", "limit": 276.90, "at": (now - dt.timedelta(seconds=40)).isoformat()},
            {"fingerprint": "7ecc", "limit": 276.82, "at": (now - dt.timedelta(seconds=5)).isoformat()}]
    assert svc._confirmed_limit(seen, "b91c", now=now) == 276.90
    assert svc._confirmed_limit(seen, "ffff", now=now) is None
    old = [{"fingerprint": "b91c", "limit": 276.90, "at": (now - dt.timedelta(seconds=900)).isoformat()}]
    assert svc._confirmed_limit(old, "b91c", now=now) is None          # past the card's validity window
