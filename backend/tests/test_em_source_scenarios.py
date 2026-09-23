"""source-scenarios-v1 (integrated plan A, 2026-09-18) on the REAL 09-18 notes (fixture = the immutable revision text,
the transcript artifact, the persisted extraction artifact and the saved ingest plans, captured read-only):
author note ae7cfbc9... (video) and EvaPanda note c2846661... (text post). Acceptance rows "Source identity" and
"Source fidelity". Pure + one Postgres case for the append-only artifact. Zero model calls, nothing arms."""
import copy
import json
import os

import pytest

from zargar.technique import source_scenarios as ss

FX = json.load(open(os.path.join(os.path.dirname(__file__), "fixtures", "em_source_notes_2026_09_18.json"), encoding="utf-8"))
AUTHOR, EVA = "ae7cfbc9010e4254bcdb714b821f7c79", "c2846661a72f4e588435538473f4f483"
UNIVERSE = {"SPY", "QQQ", "AAPL", "META", "AMD", "SPCX", "NVDA", "MRNA", "AMZN", "TSLA", "APP", "MU", "ARM", "SPX", "INTC", "AVGO", "GOOGL", "MSFT", "IWM", "NFLX"}


def _build(nid):
    return ss.build_scenarios(copy.deepcopy(FX[nid]), known_symbols=UNIVERSE)


def _of(p, sym, direction=None):
    rows = [s for s in p["scenarios"] if s["authorSupplied"]["symbolAsExtracted"] == sym and (direction is None or s["authorSupplied"]["direction"] == direction)]
    assert rows, sym
    return rows[0]


# ------------------------------------------------------------------------------------------------ source identity
def test_mu_stays_mu_the_tsla_attribution_is_a_conflict_and_is_held():
    s = _of(_build(AUTHOR), "TSLA")
    assert s["symbol"] == {"status": "conflict", "resolved": None, "evidenceSymbol": "MU", "derivation": "evidence-verified-ticker-v1"}
    assert s["disposition"] == "held_for_resolution" and "evidence_names_MU_not_TSLA" in s["flags"]
    assert any("M you" in e["quote"] for e in s["evidence"]) and s["evidence"][0]["artifact"] == "transcript" and s["evidence"][0]["offsetSeconds"] is not None


def test_ambiguous_mbgo_stays_unresolved_and_avgo_is_only_a_hypothesis():
    s = _of(_build(AUTHOR), "MBGO")
    assert s["symbol"]["status"] == "unresolved" and s["symbol"]["resolved"] is None and s["disposition"] == "held_for_resolution"
    assert "symbol_not_in_universe" in s["flags"]
    no_universe = ss.build_scenarios(copy.deepcopy(FX[AUTHOR]))
    m = _of(no_universe, "MBGO")
    assert m["symbol"]["status"] == "unresolved" and m["symbol"]["resolved"] is None, "a fuzzy transcript never yields a tradable symbol"
    assert not any(x["symbol"]["resolved"] == "AVGO" for x in no_universe["scenarios"])


def test_author_and_evapanda_are_separate_identities_with_their_own_usable_times():
    a, e = _build(AUTHOR), _build(EVA)
    assert a["author"]["displayName"].startswith("EnhancedMarket") and e["author"]["displayName"].startswith("EvaPanda")
    assert a["note"]["id"] == AUTHOR and e["note"]["id"] == EVA and a["revision"]["id"] != e["revision"]["id"]
    assert a["inputs"]["evidenceKind"] == "transcript" and e["inputs"]["evidenceKind"] == "text"
    assert a["authorResult"]["status"] == "unknown", "platform P&L never stands in for the author's result"


def test_a_call_strike_is_not_an_underlying_target():
    meta = _of(_build(EVA), "META")
    assert meta["appDerived"]["underlyingTargets"] == [] and meta["authorSupplied"]["optionMentions"] == [{"strike": 700.0, "right": "C", "raw": "700C"}]
    assert "target_was_option_strike:700" in meta["flags"] and meta["appDerived"]["level"] == 687.0 and meta["appDerived"]["family"] == "bounce"
    mu = _of(_build(EVA), "MU")
    assert mu["appDerived"]["underlyingTargets"] == [1000.0], "`test 1000` is an underlying target even though 1000C is also mentioned"
    amzn = _of(_build(EVA), "AMZN")
    assert amzn["appDerived"]["underlyingTargets"] == [260.0] and amzn["authorSupplied"]["optionMentions"][0]["strike"] == 257.5
    assert all(s["authorSupplied"]["stop"] is None for s in _build(EVA)["scenarios"]), "a missing author stop stays unknown"


def test_the_literal_1155_beside_160c_165c_is_flagged_and_never_corrected_to_155():
    s = _of(_build(EVA), "SPCX")
    assert s["appDerived"]["level"] == 1155.0 and any(f.startswith("level_conflict:1155_vs_strikes_160/165") for f in s["flags"])
    assert s["disposition"] == "held_for_resolution" and s["symbol"]["status"] == "resolved"


def test_an_edited_revision_makes_a_new_artifact_and_never_rewrites_the_prior_one():
    before = _build(EVA)
    edited = copy.deepcopy(FX[EVA])
    edited["revision"] = {**edited["revision"], "id": "rev-edit-2", "revision": 9, "kind": "edit", "text": edited["revision"]["text"].replace("1155", "155")}
    after = ss.build_scenarios(edited, known_symbols=UNIVERSE)
    assert after["inputHash"] != before["inputHash"] and after["revision"]["id"] == "rev-edit-2"
    assert _of(before, "SPCX")["appDerived"]["level"] == 1155.0, "the earlier decision's evidence is untouched"
    assert {s["scenarioId"] for s in before["scenarios"]}.isdisjoint({s["scenarioId"] for s in after["scenarios"]})
    deleted = copy.deepcopy(FX[EVA]); deleted["revision"]["deleted"] = True
    assert ss.build_scenarios(deleted)["scenarios"] == []


def test_corrections_are_append_only_and_usable_only_from_their_own_time():
    base = _build(AUTHOR)
    snapshot = json.dumps(base, sort_keys=True, default=str)
    fixed = ss.apply_corrections(base, [{"match": {"symbolAsExtracted": "TSLA"}, "set": {"resolvedSymbol": "MU"}, "reason": "transcript 5:38 says `M you`",
                                         "evidence": "review 2026-09-18"}], corrected_at="2026-09-19T01:00:00+00:00", corrected_by="em-desk")
    assert json.dumps(base, sort_keys=True, default=str) == snapshot, "the original payload is never edited"
    s = _of(fixed, "TSLA")
    assert s["symbol"]["resolved"] == "MU" and s["disposition"] == "candidate_source" and s["correction"]["before"]["symbol"]["status"] == "conflict"
    assert ss.usable_at(s, fixed) == "2026-09-19T01:00:00+00:00" and ss.usable_at(_of(fixed, "NVDA"), fixed) == base["times"]["usableAt"]
    assert fixed["configHash"] != base["configHash"] and fixed["correctionOf"]["inputHash"] == base["inputHash"]


# ------------------------------------------------------------------------------------------------ source fidelity
def test_both_branches_are_represented_with_a_shared_pair_id():
    p = _build(AUTHOR)
    app = [s for s in p["scenarios"] if s["authorSupplied"]["symbolAsExtracted"] == "APP"]
    assert [s["branch"] for s in app] == ["long", "short"] and app[0]["pairId"] == app[1]["pairId"] and app[0]["pairId"]
    assert app[0]["scenarioId"] != app[1]["scenarioId"] and app[1]["appDerived"]["family"] == "reject"
    spx = [s for s in _build(EVA)["scenarios"] if s["authorSupplied"]["symbolAsExtracted"] == "SPX"]
    assert [(s["authorSupplied"]["direction"], s["appDerived"]["level"]) for s in spx] == [("long", 7650.0), ("short", 7620.0)]


def test_spcx_long_is_never_matched_by_the_short_reject_at_the_same_number():
    p = _build(AUTHOR)
    spcx = _of(p, "SPCX")
    plan = FX["plans"]["b9953dd07e234bd99ef03919db7b1fc3"]
    m = ss.match_plan(spcx, p, plan["plan"], plan_built_at=plan["createdAt"], plan_origin=plan["trigger"])
    rows = {r["trigger"]: r for r in m["triggers"]}
    assert rows["r2"]["verdict"] == "opposite_direction_same_level" and rows["r2"]["valid"] is True
    assert rows["k2"]["verdict"] == "aligned" and rows["k2"]["valid"] is False
    assert m["overall"] == "aligned_trigger_rejected_by_our_gates" and m["oppositeValidAtSameLevel"] == ["r2"]
    assert m["overall"] != "aligned", "the armed trigger was the SHORT reject - that is not source alignment"


def test_nvda_keeps_the_full_trigger_set_not_the_board_representative():
    p = _build(AUTHOR)
    plan = FX["plans"]["3ed6d5cd95e042c69636de5acde77a16"]
    m = ss.match_plan(_of(p, "NVDA"), p, plan["plan"], plan_built_at=plan["createdAt"], plan_origin=plan["trigger"])
    assert [r["trigger"] for r in m["triggers"]] == ["b1", "k1", "k2", "r1", "r2", "d1", "d2"]
    assert {r["trigger"] for r in m["triggers"] if r["direction"] == "long" and r["valid"]} == {"k1", "k2"}
    assert m["overall"] == "same_direction_not_aligned", "the author gave no numeric level: same-direction triggers exist but the region is unknown - never 'aligned'"
    assert {r["verdict"] for r in m["triggers"] if r["trigger"] in ("k1", "k2")} == {"same_direction_level_unknown"}
    assert _of(p, "NVDA")["stance"] == "preferred" and _of(p, "NVDA")["appDerived"]["underlyingTargets"] == [222.0]


def test_a_late_transcript_is_unavailable_to_an_earlier_decision():
    p = _build(AUTHOR)
    assert p["times"]["sourcePostedAt"].startswith("2026-09-18") and p["times"]["usableAt"] > p["times"]["receivedAt"]
    assert p["times"]["usableAt"].startswith("2026-09-18 13:20:4") or p["times"]["usableAt"].startswith("2026-09-18T13:20:4")
    overnight = FX["plans"]["5f5a64f0d4284df6916a8cd352cd9535"]                       # SPY promoted the evening before
    m = ss.match_plan(_of(p, "SPY"), p, overnight["plan"], plan_built_at=overnight["createdAt"], plan_origin=overnight["trigger"])
    assert m["causal"] is False and m["overall"] != "aligned", "a plan built before the source was usable was not informed by it"
    late = copy.deepcopy(FX[AUTHOR]); late["transcript"]["completedAt"] = None
    assert ss.build_scenarios(late)["times"]["usableAt"] is None, "an unknown completion time is unknown, never the message timestamp"


def test_mu_volume_skip_and_amd_r2_rejection_stay_named_baseline_outcomes():
    e = _build(EVA)
    plan = FX["plans"]["ae478636" + next(k for k in FX["plans"] if k.startswith("ae478636"))[8:]]
    m = ss.match_plan(_of(e, "MU"), e, plan["plan"], plan_built_at=plan["createdAt"], plan_origin=plan["trigger"])
    assert m["overall"] == "same_direction_not_aligned", "EvaPanda said HOLD 980; the armed trigger was a breakout of 986.20 - same side, not her condition"
    assert any(ev["type"] == "TechniquePlanTriggerSkipped" and "volume" in (ev.get("reason") or "") for ev in plan["events"])
    amd = FX["plans"][next(k for k in FX["plans"] if k.startswith("17df157e"))]
    k1 = next(t for t in amd["plan"]["triggers"] if t["id"] == "k1")
    assert k1["valid"] is False and k1["levelPrice"] == 551.42 and any("2.97" in r for r in k1["noTradeReasons"])
    a = _build(AUTHOR)
    ma = ss.match_plan(_of(a, "AMD"), a, amd["plan"], plan_built_at=amd["createdAt"], plan_origin=amd["trigger"])
    assert ma["overall"] == "aligned_trigger_rejected_by_our_gates" and ma["alignedTrigger"] == "k1"


def test_the_gopogl_no_chase_is_an_avoid_row_not_a_candidate():
    a = _build(AUTHOR)
    assert {"symbol": "GOOGL", "status": "no_chase"} in [{k: v[k] for k in ("symbol", "status")} for v in a["avoid"]]
    assert not any(s["authorSupplied"]["symbolAsExtracted"] == "GOOGL" for s in a["scenarios"])


def test_parsing_helpers():
    assert ss.speech_numbers("below 759 96 and 551 42") == "below 759.96 and 551.42"
    assert ss.underlying_numbers("test 1000 - i like 1000C lottos") == [1000.0]
    assert ss.derive_level("break previous resistance from April 17")[0] is None, "a date is not a level"
    assert [m["symbol"] for m in ss.symbol_mentions("M you also like. How about meta and Tesla", {"MU", "META", "TSLA"})] == ["MU", "META", "TSLA"]
    assert ss.symbol_mentions("Apple looks good", {"APP"}) == []


# ------------------------------------------------------------------------------------- append-only artifact (Postgres)
@pytest.mark.usefixtures("fresh_db")
async def test_scenarios_are_stored_append_only_and_idempotently():
    from sqlalchemy import select
    from tests.conftest import TEST_DB_URL
    from zargar.db import make_engine, make_session_factory
    from zargar.models import TechniqueSourceArtifact
    eng = make_engine(TEST_DB_URL); sf = make_session_factory(eng)
    base = _build(AUTHOR)
    fixed = ss.apply_corrections(base, [{"match": {"symbolAsExtracted": "TSLA"}, "set": {"resolvedSymbol": "MU"}, "reason": "5:38"}], corrected_at="2026-09-19T01:00:00+00:00", corrected_by="em-desk")
    async with sf() as s:
        _, r1 = await ss.store_scenarios(s, note_id=AUTHOR, revision_id=base["revision"]["id"], payload=base)
        await s.commit()
    async with sf() as s:
        _, r2 = await ss.store_scenarios(s, note_id=AUTHOR, revision_id=base["revision"]["id"], payload=base)
        _, r3 = await ss.store_scenarios(s, note_id=AUTHOR, revision_id=base["revision"]["id"], payload=fixed)
        await s.commit()
        rows = (await s.execute(select(TechniqueSourceArtifact).where(TechniqueSourceArtifact.kind == "scenarios"))).scalars().all()
    assert (r1, r2, r3) == (False, True, False) and len(rows) == 2, "same inputs reuse the row; a correction is a NEW row beside the original"
    assert sorted(bool(r.payload.get("correctionOf")) for r in rows) == [False, True]
    await eng.dispose()
