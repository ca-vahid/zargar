"""I175-01..04 (2026-09-16): route boundaries, partial-copy labels from the executed
sequence, hold cap apart from expiry, and REPLAY PARITY - the frozen `recap_candidate`
variant assembles exactly what the production compact route assembles (unpaid)."""
from types import SimpleNamespace as NS

from zargar.techniques.tip import frozen, payoff, recap

FEE = 0.99 + 0.05


def _s(ticker, instrument="call", action="open", premium=None, entry=None, strike=None, actionable=True):
    return NS(ticker=ticker, direction="long", action=action, instrument=instrument, strike=strike, expiry=None,
              premium=premium, entry_price=entry, is_actionable=actionable)


def test_route_boundaries_fresh_entry_management_old_averages_and_clean_map():
    clean_map = [_s("SPX", "call", strike=6600), _s("SPX", "put", strike=6500), _s("TSLA", "call"), _s("TSLA", "put"), _s("AAPL", "call")]
    assert recap.classify(clean_map, "FOMC morning map - levels above and below", fan_in_min=3)["route"] == "compact"
    # a recap that re-lists OLD averages (non-actionable priced opens) is still a recap
    holdings = [_s("APLD", "shares", entry=12.5, actionable=False), _s("RDDT", "call", premium=3.1, actionable=False),
                _s("GOOGL", "call", premium=1.9, actionable=False), _s("AMZN", "shares", entry=250.0, actionable=False)]
    r = recap.classify(holdings, "Mass position update - unrealized only: swing trades", fan_in_min=3)
    assert r["category"] == "recap" and r["route"] == "compact" and r["features"]["oldAverages"] == 4 and r["features"]["freshPricedEntries"] == 0
    # the same map with ONE fresh priced BTO is mixed and full - before any scoring
    with_entry = clean_map + [_s("NVDA", "call", premium=1.0)]
    m = recap.classify(with_entry, "Morning map and levels. BTO NVDA calls at 1.00.", fan_in_min=3)
    assert m["category"] == "mixed" and m["route"] == "full" and m["features"]["freshPricedEntries"] == 1
    # entry cues on actionable content, even unpriced, stay full
    cues = recap.classify(clean_map, "map for today; sending it on TSLA calls", fan_in_min=3)
    assert cues["route"] == "full"
    # management stays full
    mg = recap.classify([_s("SLV", "call", action="trim"), _s("MRNA", "shares", action="update_stop"), _s("T", "call", action="close")],
                        "trimming SLV, stop MRNA 138, closing T", fan_in_min=3)
    assert mg["category"] == "management" and mg["route"] == "full"


def test_partial_copy_labels_follow_the_executed_units():
    r = payoff.payoff_preview(qty=3, fractions=[0.8, 0.1, 0.1], gains=[10, 20, 30], unit_loss=5)
    assert r["ladder"]["units"] == [2, 1, 0] and r["singleLot"]["canCopyPartials"] is False
    assert r["singleLot"]["uncoveredRungs"] == [3] and r["singleLot"]["executedUnits"] == [2, 1, 0]
    assert "rung(s) [3] receive no unit" in r["singleLot"]["note"]
    balanced = payoff.payoff_preview(qty=3, fractions=[0.4, 0.3, 0.3], gains=[10, 20, 30], unit_loss=5)
    assert balanced["singleLot"]["canCopyPartials"] is True and balanced["singleLot"]["reproducesWeights"] is False
    exact = payoff.payoff_preview(qty=10, fractions=[0.5, 0.3, 0.2], gains=[10, 20, 30], unit_loss=5)
    assert exact["singleLot"]["canCopyPartials"] is True and exact["singleLot"]["reproducesWeights"] is True
    one = payoff.payoff_preview(qty=1, fractions=[0.4, 0.3, 0.3], gains=[10, 20, 30], unit_loss=5, fee_per_unit=FEE)
    assert one["singleLot"]["canCopyPartials"] is False and one["oneLot"]["policy"] == "single exit at the first target"
    assert one["oneLot"]["net"] == round(10 - 2 * FEE, 2), "the one-contract first-target behaviour is unchanged"


def test_hold_cap_expiry_and_exit_assumption_are_three_things():
    import datetime as dt
    # a 5-session cap on a 2-DTE contract: NOT an expiry exit
    r = payoff.payoff_preview(qty=1, fractions=[1], gains=[10], unit_loss=5, strike=350, premium=2.19, option_type="call",
                              dte=2, hold_sessions=5, expiry_date="2026-09-18", as_of=dt.date(2026, 9, 16))
    h = r["horizon"]
    assert h["exitAssumption"].startswith("before expiry") and h["maxHoldSessions"] == 5 and h["expiryDate"] == "2026-09-18"
    assert h["holdCapEndsOn"] == "2026-09-23" and h["holdCapReachesExpiry"] is True and "expiryScenario" not in r
    # an EXPLICIT held-to-expiry exit uses intrinsic value - only then
    e = payoff.payoff_preview(qty=1, fractions=[1], gains=[10], unit_loss=5, strike=350, premium=2.19, option_type="call",
                              dte=2, hold_sessions=2, expiry_date="2026-09-18", as_of=dt.date(2026, 9, 16), fee_per_unit=FEE,
                              exit_at_expiry=True, underlying_targets=[349.0, 355.0])
    assert e["horizon"]["exitAssumption"] == "declared: held to expiry"
    per = {x["underlying"]: x for x in e["expiryScenario"]["perTarget"]}
    assert per[349.0]["intrinsic"] == 0.0 and per[349.0]["net"] == round(-219.0 - 2 * FEE, 2)
    assert per[355.0]["intrinsic"] == 5.0 and per[355.0]["net"] == round((5.0 - 2.19) * 100 - 2 * FEE, 2)
    # a weekend-spanning cap converts on the exchange calendar: Fri 09-18 + 2 sessions = Tue 09-22
    w = payoff.horizon_block(dte=30, hold_sessions=2, expiry_date="2026-10-16", as_of=dt.date(2026, 9, 18))
    assert w["holdCapEndsOn"] == "2026-09-22" and w["holdCapReachesExpiry"] is False
    # unknown stays unknown
    u = payoff.horizon_block(dte=None, hold_sessions=None)
    assert u["exitAssumption"] == "unknown" and u["holdCapEndsOn"] is None
    # the verified early-sale example and its cost basis are untouched
    sale = payoff.premium_exit(entry_premium=2.19, exit_premium=2.50, qty=1, fee_per_unit=FEE, evidence="synthetic")
    assert sale["net"] == 28.92 and sale["fees"] == 2.08


def _bundle(rules, notes, history, ticker="SPX", source="eva", conf=0.85):
    header = ("Today (ET): 2026-09-16 09:21\nPer-tip budget: $2,000\nTIP: {}\nVERIFICATION: {} failed checks: []\n"
              + frozen._RULES_MARK + frozen.format_rules(rules) + frozen._NOTES_MARK + frozen.format_notes(notes)
              + "\nTHIS SOURCE'S LAST ~3 DAYS (their channel, mirrored, newest first - the backstory):\n" + history)
    man = {"version": frozen.BUNDLE_VERSION, "exact": True, "header": header, "headerSha": frozen._sha(header),
           "system": "SYS-CAPTURED", "systemSha": frozen._sha("SYS-CAPTURED"), "todayLine": "Today (ET): 2026-09-16 09:21",
           "rulesText": frozen.format_rules(rules), "notesText": frozen.format_notes(notes), "historyText": history,
           "tip": {"ticker": ticker, "source": source}}
    return {"id": "fb-parity", "run": {"tip": {"ticker": ticker, "source": source}, "opinion": {"verdict": "skip"},
                                       "recapRead": {"category": "recap", "confidence": conf, "route": "compact"}},
            "manifest": man, "knowledge": {"rules": rules, "notes": notes, "rulesHash": "x"}, "toolOutputs": [], "gaps": []}


def test_replay_recap_candidate_matches_the_production_route_unpaid():
    rules = [{"id": "r1", "text": "RULE (geometry): never chase", "core": True, "createdAt": "2026-09-10"},
             {"id": "r2", "text": "RULE (sizing): one lotto", "core": False, "createdAt": "2026-09-11"},
             {"id": "r3", "text": "RULE (time): half runway", "core": False, "createdAt": "2026-09-12"}]
    notes = [{"id": "n1", "scope": "ticker:SPX", "text": "SPX pins 6600", "createdAt": "2026-09-15", "author": "analyst"},
             {"id": "n2", "scope": "source:eva", "text": "eva maps mornings", "createdAt": "2026-09-15", "author": "analyst"},
             {"id": "n3", "scope": "ticker:MSFT", "text": "unrelated", "createdAt": "2026-09-15", "author": "analyst"},
             {"id": "n4", "scope": "general", "text": "core note", "createdAt": "2026-09-15", "author": "analyst", "core": True}]
    history = "\n".join(f"- [Tue 09:{20 - i:02d}] eva: line {i}" for i in range(30))
    b = _bundle(rules, notes, history)
    # what production assembles for this message (the same builder the compact route uses)
    prod = recap.build_candidate_context(rules=rules, notes=notes, history_text=history, ticker="SPX", source="eva", confidence=0.85)
    # what the isolated replay assembles from the bundle
    kv = frozen.variant_knowledge(b, "recap_candidate")
    assert kv["available"] and kv["candidate"] == recap.CANDIDATE["version"] == "recap-candidate-v1"
    assert kv["ruleIds"] == prod["ruleIds"] == ["r1"]
    assert sorted(kv["noteIds"]) == sorted(prod["noteIds"]) == ["n1", "n2", "n4"]
    assert kv["rulesText"] == frozen.format_rules(prod["rules"]) and kv["notesText"] == frozen.format_notes(prod["notes"])
    assert kv["historyLines"] == prod["historyLines"] == 12 and kv["maxTools"] == prod["maxTools"] == 2
    assert kv["prefix"] == prod["prefix"] == recap.candidate_prefix(0.85) and "confidence 0.85" in kv["prefix"]
    header, gaps = frozen._rebuild_header(b["manifest"], rules_text=kv["rulesText"], notes_text=kv["notesText"],
                                          history_lines=kv["historyLines"], prefix=kv["prefix"])
    assert header.startswith(recap.candidate_prefix(0.85) + "\n\n")
    assert "- [Tue 09:09] eva: line 11" in header and "line 12" not in header, "the newest 12 captured lines, no more"
    assert header.split("\n\n", 1)[1].split("\n")[0] == "Today (ET): 2026-09-16 09:21", "same evidence time"
    assert "RULE (sizing)" not in header and "unrelated" not in header and "core note" in header
    assert prod["historyText"] == "\n".join(history.split("\n")[:12])
    # the gaps are DECLARED: the 24 h bound is not verifiable on captured lines; the captured prompt is kept
    assert any("24-hour bound" in g for g in kv["gaps"]) and any("captured system prompt" in g for g in kv["gaps"])
    assert not gaps, "an exact manifest rebuilds without header gaps"
    # the full variant is untouched by the candidate machinery
    full = frozen.variant_knowledge(b, "current")
    h_full, _ = frozen._rebuild_header(b["manifest"], rules_text=full["rulesText"], notes_text=full["notesText"])
    assert h_full == b["manifest"]["header"]
    # missing history stays missing: no bundle history -> the candidate carries none, never today's
    b2 = _bundle(rules, notes, "")
    b2["manifest"]["historyText"] = ""
    kv2 = frozen.variant_knowledge(b2, "recap_candidate")
    assert kv2["available"] and kv2["ruleIds"] == ["r1"]
    assert recap.build_candidate_context(rules=rules, notes=notes, history_text=None, ticker="SPX", source="eva", confidence=0.85)["historyText"] == ""
