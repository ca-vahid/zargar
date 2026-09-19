"""D4 / ECON-04: the rule budget belongs to OPERATIVE policy. Pending (needs_human) proposals travel in a separate,
capped, non-operative channel and can never displace an operative rule; supply is stamped apart from reliance."""
import datetime as dt
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

from zargar.techniques.tip.analyst import PENDING_HEADER, _rules_text


def _rule(i, *, pending=False, core=False, day=1):
    return {"id": f"r{i}", "text": f"RULE {i} text", "needsHuman": pending, "core": core,
            "createdAt": f"2026-09-{day:02d}T00:00:00+00:00", "revisionNo": 1}


def _eng(rules, *, budget=3, pending_budget=2):
    svc = NS(tip_notes=AsyncMock(return_value=rules), refresh_notes_cited=AsyncMock(return_value=0))
    return NS(signals_service=svc, settings={"techniques.tip.analyst_max_rules": budget,
                                             "techniques.tip.analyst_max_pending_rules": pending_budget}), svc


async def test_pending_proposals_never_displace_operative_rules():
    # newest first, as the service returns them: four NEW pending proposals, then three OLDER operative rules
    rules = [_rule(i, pending=True, day=18) for i in (7, 6, 5, 4)] + [_rule(i, day=2) for i in (3, 2, 1)]
    eng, _svc = _eng(rules, budget=3, pending_budget=2)
    text, n, snap = await _rules_text(eng)
    operative_block, _, pending_block = text.partition(PENDING_HEADER)
    # before D4 the newest-first budget of 3 was filled by pending proposals and EVERY operative rule was dropped
    assert all(f"RULE {i} text" in operative_block for i in (1, 2, 3))
    assert "PENDING REVIEW" not in operative_block
    assert "RULE 7 text" in pending_block and "RULE 6 text" in pending_block and "RULE 5 text" not in text
    assert "+2 older pending proposal(s) not shown" in pending_block
    assert n == 5
    sel = snap["selection"]
    assert sel["omitted"] == 0 and sel["omittedIds"] == [] and sel["operative"] == 3
    assert sel["pendingSupplied"] == 2 and sel["pendingOmittedIds"] == ["r5", "r4"] and sel["budget"] == 3
    assert [r["id"] for r in snap["rules"] if r["disputed"]] == ["r6", "r7"]       # flagged in the snapshot, oldest first


async def test_the_operative_budget_still_binds_and_core_rules_come_first():
    rules = [_rule(9, pending=True, day=18), _rule(4, day=5), _rule(3, day=4), _rule(2, day=3), _rule(1, core=True, day=1)]
    eng, _svc = _eng(rules, budget=2, pending_budget=0)
    text, n, snap = await _rules_text(eng)
    assert "RULE 1 text" in text and "RULE 4 text" in text and "RULE 3 text" not in text and PENDING_HEADER not in text
    assert snap["selection"]["omittedIds"] == ["r3", "r2"] and snap["selection"]["pendingOmittedIds"] == ["r9"] and n == 2


async def test_supply_is_stamped_for_live_runs_only_and_never_as_reliance():
    rules = [_rule(2, pending=True, day=18), _rule(1, day=2)]
    eng, svc = _eng(rules)
    await _rules_text(eng)                                           # default: no stamping (pure read)
    svc.refresh_notes_cited.assert_not_awaited()
    await _rules_text(eng, stamp_supply=True)
    svc.refresh_notes_cited.assert_awaited_once()
    ids, kwargs = svc.refresh_notes_cited.await_args.args[0], svc.refresh_notes_cited.await_args.kwargs
    assert sorted(ids) == ["r1", "r2"] and kwargs == {"used_ids": []}             # supplied, not relied upon
    svc.refresh_notes_cited.reset_mock()
    await _rules_text(eng, as_of=dt.datetime(2026, 9, 1, tzinfo=dt.timezone.utc), stamp_supply=True)
    svc.refresh_notes_cited.assert_not_awaited()                     # a historical read never keeps knowledge alive
