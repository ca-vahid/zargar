"""Quantity-specific exits and bounded premium evidence, without trading calls."""
from types import SimpleNamespace

import pytest

from zargar.techniques.options_cartel.exits import (
    ExitCampaign,
    allocation_preview,
    allocations,
    record_fill,
)
from zargar.techniques.options_cartel.premium_replay import required_quote_evidence
from zargar.techniques.options_cartel.replay_service import CampaignReplayRequest, replay_quantity

from .test_options_cartel_exits import evaluate, position


def september(policy="legacy"):
    return ExitCampaign.for_profile("september_2026", [110],
        september_fractions=(.25, .25, .2, .2, .1), allocation_policy=policy)


@pytest.mark.parametrize("quantity,expected", [(1, [0, 0, 0, 0, 1]),
    (2, [1, 0, 0, 0, 1]), (3, [1, 0, 1, 0, 1]), (4, [1, 1, 0, 1, 1])])
def test_v2_small_lots_have_a_reachable_first_trim_and_preserve_runner(quantity, expected):
    campaign = september("whole_contracts_v2")
    assert list(allocations(campaign, quantity).values()) == expected
    state = position(quantity)
    read = evaluate(campaign, state)
    assert not state.breakeven and state.stop == 95
    if quantity == 1:
        assert read["decisions"] == []
    else:
        decision = read["decisions"][0]
        assert decision["rung"] == "target1" and decision["qty"] == 1
        filled = record_fill(campaign, state, fill_id="first", rung="target1", qty=1)
        assert filled.breakeven and filled.stop == 100
        assert record_fill(campaign, filled, fill_id="first", rung="target1", qty=1) == filled


def test_legacy_campaign_snapshot_and_larger_allocations_remain_unchanged():
    legacy = september()
    snapshot = legacy.model_dump()
    snapshot.pop("allocation_policy")
    restored = ExitCampaign.model_validate(snapshot)
    assert restored.allocation_policy == "legacy"
    assert list(allocations(restored, 2).values()) == [0, 1, 0, 0, 1]
    assert list(allocations(restored, 3).values()) == [0, 1, 1, 0, 1]
    v2 = september("whole_contracts_v2")
    for quantity in range(4, 201):
        assert allocations(v2, quantity) == allocations(legacy, quantity)
    assert ExitCampaign.model_validate_json(v2.model_dump_json()) == v2


def test_preview_explains_unreachable_legacy_extension_and_one_lot():
    preview = allocation_preview(september(), 2)
    extension = next(r for r in preview["rungs"] if r["id"] == "extension")
    assert extension["quantity"] == 1 and not extension["reachable"]
    assert "final EMA" in extension["reason"]
    assert "no target breakeven" in allocation_preview(september("whole_contracts_v2"), 1)["note"]
    with pytest.raises(ValueError, match="requires the September"):
        ExitCampaign.for_profile("may_2026", [110], allocation_policy="whole_contracts_v2")


def quote_row(index, *, available=None, gap=False):
    at = index if available is None else available
    return SimpleNamespace(id=f"q{index:07}", run_id="plan", contract="HOOD260515C00050000",
        source_at=None if gap else at, available_at=at, confirmed_at=at,
        bid=0. if gap else 1., ask=0. if gap else 1.1, bid_size=1, ask_size=1,
        source="gap:unavailable" if gap else "opra", feed_mode="live", delayed=gap, halted=False)


async def pages(rows, size=2000):
    for start in range(0, len(rows), size):
        yield rows[start:start+size]


async def test_valuation_streams_beyond_40000_rows_and_keeps_only_required_evidence():
    rows = [quote_row(i) for i in range(45_003)]
    selected, sources, coverage = await required_quote_evidence(pages(rows), [1, 40_001, 45_002])
    assert [r.available_at for r in selected] == [1, 40_001, 45_002]
    assert coverage["observationsRead"] == 45_003 and coverage["selectedObservations"] == 3
    assert coverage["gapObservations"] == 0 and len(coverage["windowSha256"]) == 64
    assert sources == ["opra (feed mode live)"]


async def test_gap_at_fill_time_blocks_older_quote_even_across_page_boundary():
    rows = [quote_row(10), quote_row(11, gap=True), quote_row(12)]
    selected, _, coverage = await required_quote_evidence(pages(rows, size=1), [11])
    assert len(selected) == 1 and selected[0].source == "gap:unavailable"
    assert coverage["gapObservations"] == 1
    conflict = [quote_row(1), quote_row(2, available=1, gap=True)]
    with pytest.raises(ValueError, match="conflicting"):
        await required_quote_evidence(pages(conflict, size=1), [1])


async def test_explicit_replay_quantity_never_claims_account_funding():
    assert CampaignReplayRequest().quantity is None
    quantity, basis = await replay_quantity(None, "plan", 100, 1000)
    assert quantity == 100 and basis["kind"] == "hypothetical"


async def test_replay_quantity_prefers_confirmed_original_units_over_current_quote():
    arm = SimpleNamespace(technique="options_cartel", portfolio_id="p1", state={"adoptedEntryQty": 3})
    class Session:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, model, identity): return arm if identity == "plan" else SimpleNamespace()
    service = SimpleNamespace(engine=SimpleNamespace(sf=Session))
    quantity, basis = await replay_quantity(service, "plan", None, 1000)
    assert quantity == 3 and basis["kind"] == "recorded_fill" and basis["observedAt"] == 1000


async def test_unknown_replay_funding_is_one_explicitly_hypothetical_unit():
    class Session:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, *args): return None
    service = SimpleNamespace(engine=SimpleNamespace(sf=Session))
    quantity, basis = await replay_quantity(service, "plan", None, 1000)
    assert quantity == 1 and basis["kind"] == "hypothetical"


async def test_current_funding_estimate_uses_fresh_fx_and_whole_premium_budget():
    contract = "HOOD260515C00050000"
    arm = SimpleNamespace(technique="options_cartel", portfolio_id="p1", state={},
        config={"execution": {"instrument": "options", "contract_symbol": contract,
            "budget": 500, "risk_pct": 10, "max_units": 10}})
    portfolio = SimpleNamespace(base_currency="CAD")
    class Session:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, model, identity): return arm if identity == "plan" else portfolio
    async def equity(portfolio_id): return 10000
    option = SimpleNamespace(source="opra", source_ts=1000, ts=1000, delayed=False,
        halted=False, bid=1.4, ask=1.5)
    fx_quote = SimpleNamespace(ts=1000)
    engine = SimpleNamespace(sf=Session, settings={},
        quotes=SimpleNamespace(get=lambda symbol: option if symbol == contract else fx_quote),
        positions=SimpleNamespace(equity=equity, fx=SimpleNamespace(rate=lambda *args: 1.25)))
    service = SimpleNamespace(engine=engine)
    quantity, basis = await replay_quantity(service, "plan", None, 1000)
    assert quantity == 2 and basis["kind"] == "current_funding_estimate" and basis["fxRate"] == 1.25
    option.source_ts = 1
    quantity, basis = await replay_quantity(service, "plan", None, 20000)
    assert quantity == 1 and basis["kind"] == "hypothetical"
