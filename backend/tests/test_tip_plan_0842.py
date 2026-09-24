"""2026-09-23 improvement plan (0.8.42): after-hours market-order age (P-G companion), card alerts (P-C), rulebook-first
cache blocks (P-D), the Practice share substitution predicate (P-E) and the gap-stop study (P-B)."""
import asyncio
import datetime as dt
from types import SimpleNamespace as NS
from zoneinfo import ZoneInfo

import pytest

from zargar.approvals.proposals import card_alert_text, share_substitution_ok
from zargar.orders import market_order_age
from zargar.techniques.tip.review_context import stable_first_blocks
from zargar.tools.tip_gap_stop_study import simulate, stop_at

ET = ZoneInfo("America/New_York")


def t(*a):
    return dt.datetime(*a, tzinfo=ET)


def test_an_after_hours_market_order_ages_from_the_next_open():
    """FIVN 2026-09-22 21:48 ET was cancelled by an overnight restart as 'lost'; it was meant to fill at the open."""
    assert market_order_age(t(2026, 9, 22, 21, 48), t(2026, 9, 23, 0, 4)) < 0            # before the open: never stale
    assert market_order_age(t(2026, 9, 22, 21, 48), t(2026, 9, 23, 9, 32)) == 120.0       # two minutes into the session
    assert market_order_age(t(2026, 9, 23, 10, 0), t(2026, 9, 23, 10, 5)) == 300.0        # placed in session: wall clock
    assert market_order_age(t(2026, 9, 25, 17, 0), t(2026, 9, 28, 9, 31)) == 60.0         # Friday after the close -> Monday
    assert market_order_age(t(2026, 9, 23, 8, 0), t(2026, 9, 23, 9, 30, 30)) == 30.0      # pre-market -> same-day open


class _S(dict):
    def get(self, k, d=None):
        return super().get(k, d)


def test_the_card_alert_line_names_the_card_the_reason_and_the_share_alternative():
    p = {"side": "BUY", "qty": 1.0, "symbol": "GOOGL260925C00345000", "expiresAt": "2026-09-23T20:28:26+00:00",
         "context": {"sourceName": "muggzone", "reviewRequired": "no quantity satisfies the $92 risk budget",
                     "riskPlan": {"sharesAlternative": {"available": True, "qty": 5, "stop": 336.35}}}}
    text, url = card_alert_text(p)
    assert "GOOGL260925C00345000" in text and "muggzone" in text and "no quantity" in text
    assert "5 sh" in text and "20:28" in text and url == "/inbox"


def test_the_rulebook_moves_first_as_its_own_cached_block_and_nothing_is_lost():
    h = ("Today (ET): x\nMESSAGE:\nhello\n\nYOUR TRADING RULES (self-maintained):\n- RULE a\n- RULE b\n"
         "SHARED NOTES (desk knowledge):\n- [general] n\n")
    out = stable_first_blocks(h)
    assert isinstance(out, list) and out[0]["cache_control"] == {"type": "ephemeral"}
    assert "- RULE a" in out[0]["text"] and "MESSAGE:\nhello" in out[1]["text"] and "SHARED NOTES" in out[1]["text"]
    assert "cache_control" not in out[1]
    joined = out[0]["text"] + out[1]["text"]
    for line in h.splitlines():
        assert line in joined
    assert stable_first_blocks("no rules here") == "no rules here"


def test_the_share_substitution_is_practice_only_take_only_long_only_and_needs_the_knob():
    rp = NS(enforced=True, reviewRequired="no quantity satisfies the $92 risk budget: one unit risks $105")
    on = _S({"techniques.tip.shares_alternative_auto": True})
    ok = dict(sec_type="OPT", risk_plan=rp, settings=on, portfolio_kind="sim", verdict="take", direction="long",
              lotto=False, alt={"available": True})
    assert share_substitution_ok(**ok) is True
    assert share_substitution_ok(**{**ok, "settings": _S({})}) is False
    assert share_substitution_ok(**{**ok, "portfolio_kind": "live"}) is False
    assert share_substitution_ok(**{**ok, "portfolio_kind": "paper"}) is False
    assert share_substitution_ok(**{**ok, "verdict": "watch"}) is False
    assert share_substitution_ok(**{**ok, "direction": "short"}) is False
    assert share_substitution_ok(**{**ok, "lotto": True}) is False
    assert share_substitution_ok(**{**ok, "alt": {"available": False}}) is False
    assert share_substitution_ok(**{**ok, "risk_plan": NS(enforced=True, reviewRequired="no risk estimate: no stop")}) is False


def test_the_gap_stop_study_only_counts_mornings_the_rule_would_change():
    bars = [(45.83, 44.5, 45.0), (44.9, 41.6, 41.7)]
    # IONQ 09-23: the stop in force (41.79) was already above the prior close (40.75) -> the rule changes nothing
    assert simulate(40.6, 41.79, 40.75, bars, 14, 41.79, r_stop=38.5) is None
    got = simulate(40.0, 38.0, 42.0, [(45.0, 44.0, 44.5), (44.0, 41.5, 41.8)], 10, 39.0, r_stop=38.0)
    assert got["altExit"] == 42.0 and got["delta"] == pytest.approx(30.0)
    assert stop_at([(1, 38.0), (5, 39.5)], 3) == 38.0 and stop_at([(1, 38.0), (5, 39.5)], 9) == 39.5


# ---- P-C wiring: a pending card alerts once; a card that is no longer pending stays silent --------------------------
from zargar.engine import Engine  # noqa: E402
from zargar.models import Proposal  # noqa: E402
from zargar.signals.service import attach_signal_layer  # noqa: E402

from .conftest import make_test_config  # noqa: E402


@pytest.fixture
async def rig(fresh_db):
    eng = Engine(make_test_config())
    await eng.start()
    await attach_signal_layer(eng)
    yield eng
    await eng.stop()


class _Push:
    def __init__(self):
        self.sent = []

    async def send(self, title, body, **kw):
        self.sent.append((title, body))


async def test_a_pending_card_pages_once_and_a_decided_card_stays_quiet(rig):
    from zargar.domain import new_id
    eng = rig
    real_push, eng.push = eng.push, _Push()
    pid = eng.positions.portfolios()[0]["id"]
    ids = []
    for status in ("pending", "rejected"):
        pr = Proposal(id=new_id(), portfolio_id=pid, symbol="HOOD", sec_type="STK", side="BUY", qty=3.0,
                      order_type="LMT", limit_price=125.0, status=status,
                      context={"sourceName": "jon-and-kian", "reviewRequired": "no quantity fits"},
                      expires_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=30))
        async with eng.sf() as s:
            s.add(pr)
            await s.commit()
        ids.append(pr.id)
        eng.proposals._start_card_alert({"id": pr.id}, wait_s=0.01)
    await asyncio.sleep(0.5)
    sent, eng.push = eng.push.sent, real_push
    assert len(sent) == 1 and "HOOD" in sent[0][1]
