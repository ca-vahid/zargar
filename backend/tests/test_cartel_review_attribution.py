"""F1 (2026-09-21 brief): causal funnel attribution. Chronology and measured fields follow the recorded
September 21 session-review rows; the synthetic tapes only reproduce the recorded highs/lows/closes."""
import datetime as dt

from zargar.domain import Bar
from zargar.marketstructure.sessions import session_bounds
from zargar.techniques.options_cartel.data_quality import pack
from zargar.techniques.options_cartel.plans import CartelPlan, EntryPolicy
from zargar.techniques.options_cartel.review_attribution import attribute, category_from, price_touch, selection_coverage

DAY = "2026-09-21"
OPEN, CLOSE = session_bounds(DAY)
MIN = 60_000
ET = dt.timezone(dt.timedelta(hours=-4))


def at(hh, mm):
    return int(dt.datetime(2026, 9, 21, hh, mm, tzinfo=ET).timestamp()*1000)


def make_plan(symbol, trigger, invalidation, targets, tf=15):
    return CartelPlan(id=symbol.lower(), symbol=symbol, direction="long", setup="base", created_at=OPEN-MIN,
                      first_session=dt.date(2026, 9, 21), last_session=dt.date(2026, 9, 21), trigger=trigger,
                      invalidation=invalidation, targets=targets, source_refs=("2026-09-21-eod",),
                      rationale="Recorded 2026-09-21 geometry", entry=EntryPolicy(timeframe_minutes=tf),
                      baseline_as_of=OPEN-MIN, volume_baseline={i: 1000. for i in range(390//tf)})


def tape(symbol, price, minutes=390, spikes=None):
    """Flat exchange tape at `price` with optional {minute_index: (high, close)} spikes."""
    bars = {}
    for i in range(minutes):
        high, close = (spikes or {}).get(i, (price+.05, price))
        bars[str(OPEN+i*MIN)] = pack(Bar(symbol, "1m", OPEN+i*MIN, price, high, price-.05, close, 1000, source="exchange"))
    return bars


def watch_only(when, ratio, target_r, location=1.0):
    return {"at": when, "rule": "M4/M3", "decision": "watch_only", "bucketInputHash": "hash-"+str(when),
            "reason": "Breakout volume is below the snapshotted confirmation threshold." + (f" First target offers {target_r:.3f}R from confirmation; requires 0.25R." if target_r < .25 else ""),
            "measurements": {"close": 70.575, "trigger": 70.48, "volume": ratio*1000, "baselineVolume": 1000., "requiredVolumeMultiple": 1.5,
                             "volumeRatio": ratio, "closeLocation": location, "requiredCloseLocation": .7, "firstTargetR": target_r, "requiredTargetR": .25}}


def untrusted(when, missing=(), untrusted_minutes=()):
    return {"at": when, "rule": "DATA", "decision": "untrusted_confirmation", "reason": "Confirmation contains sampled or unknown bars.",
            "known": {"bucketInputHash": "k-"+str(when), "minutesPresent": 15-len(missing), "minutesMissing": list(missing),
                      "minutesUntrusted": list(untrusted_minutes), "partialHigh": 70.3, "partialLow": 70.04, "partialVolume": 45949, "slotBaseline": 51855., "lastKnownClose": 70.21}}


def test_ntnx_volume_refusal_and_later_data_warning_are_separate():
    plan = make_plan("NTNX", 70.48, 69.555, (71., 71.61, 72.42))
    state = {"minutes": tape("NTNX", 70.0, spikes={60: (70.59, 70.575)}),
             "decisionHistory": [watch_only(at(10, 30), .929, .417), untrusted(at(13, 0), untrusted_minutes=[at(12, 58)]),
                                 watch_only(at(15, 45), 1.162, .452), {"at": at(16, 0), "rule": "SESSION", "decision": "entry_window_closed", "reason": "closing bell"}]}
    result = attribute(plan, state, DAY, CLOSE, opportunity={"nativeMinutes": 378, "expectedMinutes": 390, "unresolvedMinutes": 0, "verifiedIntervals": 12})
    first = result["firstKnownBlocker"]
    assert first["at"] == at(10, 30) and first["rule"] == "volume" and first["measured"] == .929 and first["required"] == 1.5
    assert first["inputHash"] == "hash-"+str(at(10, 30)) and first["stage"] == "confirmation"
    assert result["primaryKnownCause"] == "confirmation_refused"
    assert [w["at"] for w in result["incompleteWindows"]] == [at(13, 0)]
    assert result["incompleteWindows"][0]["beforeFirstKnownBlocker"] is False and result["earlierUnknownWindows"] == 0
    assert result["incompleteWindows"][0]["evidenceAvailableAtTime"] is False
    assert [b["at"] for b in result["otherIndependentBlockers"]] == [at(15, 45)]
    # R7: a later window is a fact, not a proven counterfactual veto.
    assert result["otherIndependentBlockers"][0]["remainsIfFirstRemoved"] is None and result["otherIndependentBlockers"][0]["independence"] == "unknown"
    assert result["coverage"]["decisionTime"][0]["minutesUntrusted"] == [at(12, 58)] and result["coverage"]["final"]["nativeMinutes"] == 378
    assert result["actualOutcome"] == "no_order" and result["economics"]["actualNetRealized"] == 0
    assert result["selectionCoverage"]["status"] == "not_attempted"
    assert category_from(result, None, {"watch_only", "untrusted_confirmation"}, []) == "strategy_rejected"


def test_ulta_lists_both_independent_1000_blockers_and_keeps_target_passed_windows_separate():
    plan = make_plan("ULTA", 547.58, 544.43, (548., 560.))
    trace = [watch_only(at(10, 0), .420, .064, location=.988), untrusted(at(10, 30), missing=[at(10, 15)], untrusted_minutes=[at(10, 28)])]
    trace += [{"at": at(h, m), "rule": "M4", "decision": "target_passed", "reason": "First target is already behind the current price"} for h, m in ((10, 45), (11, 0))]
    state = {"minutes": tape("ULTA", 555.0, spikes={30: (561.47, 557.99)}), "decisionHistory": trace}
    result = attribute(plan, state, DAY, CLOSE)
    first = result["firstKnownBlocker"]
    assert first["at"] == at(10, 0) and first["rule"] == "target_room" and first["measured"] == .064
    same_window = [b for b in result["otherIndependentBlockers"] if b["sameWindowAsFirst"]]
    assert [b["rule"] for b in same_window] == ["volume"] and same_window[0]["measured"] == .420
    assert all(b["remainsIfFirstRemoved"] is True for b in same_window)   # same window, same inputs: established
    later = [b for b in result["otherIndependentBlockers"] if not b["sameWindowAsFirst"]]
    assert [b["decision"] for b in later] == ["target_passed", "target_passed"]
    assert all(b["remainsIfFirstRemoved"] is None for b in later)
    assert result["incompleteWindows"][0]["minutesMissing"] == [at(10, 15)] and result["incompleteWindows"][0]["beforeFirstKnownBlocker"] is False


def test_an_unknown_earlier_window_stays_unknown_and_a_repair_cannot_authorise():
    plan = make_plan("NTNX", 70.48, 69.555, (71., 71.61, 72.42))
    state = {"minutes": tape("NTNX", 70.0, spikes={60: (70.59, 70.575)}),
             "decisionHistory": [untrusted(at(9, 45), missing=[at(9, 40)]), watch_only(at(10, 30), .929, .417)],
             "observationRecoveries": [{"at": at(9, 47), "day": DAY, "addedMinutes": 1, "verifiedIntervalsAdded": 0}]}
    result = attribute(plan, state, DAY, CLOSE)
    assert result["firstKnownBlocker"]["at"] == at(10, 30)
    assert result["earlierUnknownWindows"] == 1 and result["incompleteWindows"][0]["beforeFirstKnownBlocker"] is True
    assert "remain unknown" in result["note"] and result["placesOrders"] is False
    assert result["funnel"]["submission"] is False and result["actualOutcome"] == "no_order"


def test_now_wick_is_not_an_eligible_missed_entry():
    plan = make_plan("NOW", 139.94, 135., (145., 150.))
    minutes = tape("NOW", 138.0, spikes={1: (140.16, 139.335)})   # 09:31 high crossed; the minute closed below the trigger
    state = {"minutes": minutes, "decisionHistory": [{"at": at(16, 0), "rule": "SESSION", "decision": "entry_window_closed", "reason": "closing bell"}]}
    touch = price_touch(plan, state, DAY, CLOSE)
    assert touch["touched"] is True and touch["wickOnly"] is True and touch["firstTouchAt"] == OPEN+MIN
    assert "every completed 15-minute candle closed at or below it" in touch["explanation"] and touch["incompleteBuckets"] == []
    result = attribute(plan, state, DAY, CLOSE, opportunity={"status": "level_reached"})
    assert result["primaryKnownCause"] == "wick_only" and result["firstKnownBlocker"] is None
    assert category_from(result, None, {"entry_window_closed"}, []) == "no_trigger"


def test_no_level_touch_names_the_distance():
    plan = make_plan("BBY", 95.85, 92., (100.,))
    state = {"minutes": tape("BBY", 93.5, spikes={120: (94.34, 94.0)}), "decisionHistory": []}
    result = attribute(plan, state, DAY, CLOSE)
    assert result["primaryKnownCause"] == "no_level_touch"
    assert result["priceTouch"]["touched"] is False and "94.34" in result["priceTouch"]["explanation"] and "1.58%" in result["priceTouch"]["explanation"]
    assert result["funnel"] == {"priceTouch": False, "confirmation": False, "contractEligibility": False, "submission": False, "fill": False}


def test_complete_no_signal_session_is_distinct_from_an_incomplete_one():
    plan = make_plan("CNH", 14.46, 13., (15.,))
    complete = attribute(plan, {"minutes": tape("CNH", 13.6), "decisionHistory": []}, DAY, CLOSE)
    assert complete["primaryKnownCause"] == "no_level_touch" and complete["incompleteWindows"] == []
    incomplete = attribute(plan, {"minutes": tape("CNH", 13.6), "decisionHistory": [untrusted(at(11, 45), untrusted_minutes=[at(11, 42)])]}, DAY, CLOSE)
    assert incomplete["primaryKnownCause"] == "data_incomplete" and incomplete["firstKnownBlocker"] is None
    assert category_from(incomplete, None, {"untrusted_confirmation"}, []) == "data_limited"


def test_contract_and_execution_stages_and_selection_coverage():
    plan = make_plan("QS", 10., 9.5, (11.,))
    signal_at = at(10, 15)
    state = {"minutes": tape("QS", 10.2), "decisionHistory": [{"at": signal_at, "rule": "M4", "decision": "triggered", "reason": "confirmed"}],
             "signal": {"at": signal_at, "id": "qs:entry"},
             "contractReselection": {"startedAt": signal_at+5000, "status": "unavailable", "selectionVersion": "diverse_liquidity_v1",
                                     "selection": {"searchComplete": False, "searchedExpiries": ["2026-10-16"], "refreshedCandidates": 6,
                                                   "structuralCandidates": 20, "incompleteReasons": ["14 refreshable candidate(s) were not refreshed"]}}}
    checks = [{"at": signal_at+3000, "passed": False, "reasons": ["spread"], "checks": [{"name": "entry_contract_spread", "reason": "Final option spread must remain within the saved 20% limit."}],
               "expression": {"symbol": "QS261016C00010000", "bid": 1.86, "ask": 2.39}}]
    result = attribute(plan, state, DAY, CLOSE, checks=checks)
    assert result["firstKnownBlocker"]["stage"] == "contract" and result["firstKnownBlocker"]["rule"] == "entry_contract_spread"
    assert result["primaryKnownCause"] == "contract_refused" and result["funnel"]["confirmation"] is True
    assert result["selectionCoverage"]["status"] == "incomplete" and result["selectionCoverage"]["selectionVersion"] == "diverse_liquidity_v1"
    assert category_from(result, None, {"triggered"}, []) == "execution_rejected"
    exhausted = selection_coverage({**state, "contractReselection": {**state["contractReselection"], "selection": {"searchComplete": True}}}, checks, CLOSE)
    assert exhausted["status"] == "exhausted"
    found = selection_coverage(state, [{"at": signal_at+9000, "passed": True, "checks": []}], CLOSE)
    assert found["status"] == "eligible_expression_found"
    assert selection_coverage({"minutes": {}}, [], CLOSE)["status"] == "not_attempted"


def test_actual_outcomes_follow_recorded_fills():
    plan = make_plan("APA", 30., 29., (32.,))
    # R6: quantities come from ORDER rows (requested/filled/status) and the fills ledger (entryFilledQty),
    # never from remaining holdings. The asset shape below is what summarize_fills produces.
    filled_order = [{"id": "buy", "qty": 2, "filledQty": 2, "status": "FILLED"}]
    held = attribute(plan, {"minutes": tape("APA", 31.), "decisionHistory": [], "orderId": "buy", "signal": {"at": at(10, 0), "id": "s"}}, DAY, CLOSE,
                     assets=[{"remainingQty": 2, "netRealized": 0., "feesPaidToday": 2.08, "entryFilledQty": 2}], entry_orders=filled_order)
    assert held["actualOutcome"] == "held" and held["economics"]["actualFees"] == 2.08 and held["funnel"]["fill"] is True
    assert held["entry"] == {"requestedQty": 2, "filledQty": 2, "orderStatuses": ["FILLED"], "terminal": True, "working": False, "entryStatus": "filled"}
    working = [{"id": "buy", "qty": 3, "filledQty": 2, "status": "PARTIALLY_FILLED"}]
    partial = attribute(plan, {"minutes": tape("APA", 31.), "decisionHistory": [], "orderId": "buy", "signal": {"at": at(10, 0), "id": "s"}}, DAY, CLOSE,
                        assets=[{"remainingQty": 2, "netRealized": 0., "feesPaidToday": 2.08, "entryFilledQty": 2}], entry_orders=working)
    assert partial["actualOutcome"] == "partially_filled" and partial["entry"]["entryStatus"] == "partially_filled"
    # The remainder was cancelled after a partial exit: holdings 1, cumulative entry fills still 2.
    cancelled = [{"id": "buy", "qty": 3, "filledQty": 2, "status": "CANCELLED"}]
    carried = attribute(plan, {"minutes": tape("APA", 31.), "decisionHistory": [], "orderId": "buy"}, DAY, CLOSE,
                        assets=[{"remainingQty": 1, "netRealized": 5., "feesPaidToday": 3.12, "entryFilledQty": 2, "exitFilledQty": 1}], entry_orders=cancelled)
    assert carried["actualOutcome"] == "held" and carried["entry"]["entryStatus"] == "partially_filled" and carried["entry"]["terminal"] is True
    closed = attribute(plan, {"minutes": tape("APA", 31.), "decisionHistory": [], "orderId": "buy"}, DAY, CLOSE,
                       assets=[{"remainingQty": 0, "netRealized": -61.13, "feesPaidToday": 2.08, "entryFilledQty": 1}], entry_orders=[{"id": "buy", "qty": 1, "filledQty": 1, "status": "FILLED"}])
    assert closed["actualOutcome"] == "closed" and closed["economics"]["actualNetRealized"] == -61.13 and closed["economics"]["modeled"] is None
    unfilled = attribute(plan, {"minutes": tape("APA", 31.), "decisionHistory": [], "orderId": "buy", "phase": "closed"}, DAY, CLOSE,
                         entry_orders=[{"id": "buy", "qty": 1, "filledQty": 0, "status": "CANCELLED"}])
    assert unfilled["actualOutcome"] == "unfilled" and category_from(unfilled, None, set(), []) == "unfilled"
    submitted = attribute(plan, {"minutes": tape("APA", 31.), "decisionHistory": [], "attemptTag": "t", "phase": "submitting"}, DAY, CLOSE)
    assert submitted["actualOutcome"] == "submitted"
    working_no_fill = attribute(plan, {"minutes": tape("APA", 31.), "decisionHistory": [], "orderId": "buy"}, DAY, CLOSE,
                                entry_orders=[{"id": "buy", "qty": 1, "filledQty": 0, "status": "ACCEPTED"}])
    assert working_no_fill["actualOutcome"] == "submitted"


def test_price_touch_completeness_rules():
    """R5: sampled bars, missing minutes and verified non-emission intervals."""
    plan = make_plan("NOW", 139.94, 135., (145., 150.), tf=5)
    complete = tape("NOW", 138.0, minutes=10, spikes={1: (140.16, 140.10), 4: (140.5, 140.2)})
    assert price_touch(plan, {"minutes": complete}, DAY, OPEN+10*MIN)["closedBucketsBeyond"] == [OPEN+5*MIN]
    missing_last = {k: v for k, v in complete.items() if int(k) != OPEN+4*MIN}
    result = price_touch(plan, {"minutes": missing_last}, DAY, OPEN+10*MIN)
    assert result["closedBucketsBeyond"] == [] and result["wickOnly"] is None and result["incompleteBuckets"] == [OPEN+5*MIN]
    sampled = dict(complete); sampled[str(OPEN+2*MIN)] = [OPEN+2*MIN, 138, 138.5, 137, 138.2, 5000, "sampled"]
    result = price_touch(plan, {"minutes": sampled}, DAY, OPEN+10*MIN)
    assert result["closedBucketsBeyond"] == [] and result["wickOnly"] is None
    verified = {k: v for k, v in complete.items() if int(k) != OPEN+2*MIN}
    proofs = {"p": {"minute": OPEN+2*MIN, "symbol": "NOW", "version": "alpaca-minute-eligibility-v1", "verifiedAt": OPEN+3*MIN}}
    from zargar.techniques.options_cartel.nonemission import minute_set
    if OPEN+2*MIN in minute_set(proofs, "NOW", OPEN+10*MIN):
        assert price_touch(plan, {"minutes": verified, "verifiedIntervals": proofs}, DAY, OPEN+10*MIN)["closedBucketsBeyond"] == [OPEN+5*MIN]
    # A bucket that has not ended by the cutoff is never judged.
    assert price_touch(plan, {"minutes": complete}, DAY, OPEN+7*MIN)["completeBuckets"] == 1
