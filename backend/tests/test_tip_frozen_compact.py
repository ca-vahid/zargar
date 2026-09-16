"""PROF-05 (2026-09-15): the frozen `compact` variant - core rules, relevant
notes, trimmed history - on the SAME evidence and time as the full variant;
pure, no provider, no mutation."""
from zargar.techniques.tip import frozen


def _bundle():
    rules = [{"id": "r1", "text": "RULE (geometry): never chase", "core": True, "createdAt": "2026-09-10"},
             {"id": "r2", "text": "RULE (sizing): one lotto per session", "core": False, "createdAt": "2026-09-11"},
             {"id": "r3", "text": "RULE (time): re-evaluate at half runway", "core": False, "createdAt": "2026-09-12"}]
    notes = [{"id": "n1", "scope": "ticker:AAPL", "text": "AAPL gaps fill fast", "createdAt": "2026-09-12", "author": "analyst"},
             {"id": "n2", "scope": "source:Src", "text": "Src posts opens as OPEN:", "createdAt": "2026-09-12", "author": "analyst"},
             {"id": "n3", "scope": "general", "text": "market chop", "createdAt": "2026-09-12", "author": "analyst"},
             {"id": "n4", "scope": "daily:2026-09-12", "text": "digest", "createdAt": "2026-09-12", "author": "digest"},
             {"id": "n5", "scope": "ticker:MSFT", "text": "unrelated", "createdAt": "2026-09-12", "author": "analyst", "core": True}]
    history = "\n".join(f"- line {i}" for i in range(1, 31))
    header = ("Today (ET): 2026-09-15 10:00\nPer-tip budget: $2,000\nTIP: {}\nVERIFICATION: {} failed checks: []\n"
              + frozen._RULES_MARK + frozen.format_rules(rules) + frozen._NOTES_MARK + frozen.format_notes(notes)
              + "\nTHIS SOURCE'S LAST ~3 DAYS (their channel, mirrored, newest first - the backstory):\n" + history)
    man = {"version": frozen.BUNDLE_VERSION, "exact": True, "header": header, "headerSha": frozen._sha(header),
           "system": "SYS", "systemSha": frozen._sha("SYS"), "todayLine": "Today (ET): 2026-09-15 10:00",
           "rulesText": frozen.format_rules(rules), "notesText": frozen.format_notes(notes), "historyText": history,
           "tip": {"ticker": "AAPL", "source": "Src"}}
    return {"id": "fb-test", "run": {"tip": {"ticker": "AAPL", "source": "Src"}, "opinion": {"verdict": "take"}},
            "manifest": man, "knowledge": {"rules": rules, "notes": notes, "rulesHash": "x"},
            "toolOutputs": [{"tool": "get_quote", "args": {"symbol": "AAPL"}, "result": {"last": 100}}], "gaps": []}


def test_compact_keeps_core_rules_relevant_notes_and_the_same_evidence():
    b = _bundle()
    full = frozen.variant_knowledge(b, "current")
    compact = frozen.variant_knowledge(b, "compact")
    assert compact["available"] and compact["ruleIds"] == ["r1"] and sorted(compact["noteIds"]) == ["n1", "n2", "n5"]
    assert compact["dropped"] == 2 + 2 and compact["historyLines"] == frozen.COMPACT_HISTORY_LINES
    h_full, _ = frozen._rebuild_header(b["manifest"], rules_text=full["rulesText"], notes_text=full["notesText"])
    h_compact, gaps = frozen._rebuild_header(b["manifest"], rules_text=compact["rulesText"], notes_text=compact["notesText"],
                                             history_lines=compact["historyLines"])
    assert not gaps and h_full == b["manifest"]["header"], "the full variant rebuilds the header verbatim"
    # same evidence and time: identical head (today line, tip, verification), same tool outputs available
    assert h_compact.split("\n")[0] == h_full.split("\n")[0] and "TIP: {}" in h_compact
    assert "- line 12" in h_compact and "- line 13" not in h_compact and "- line 30" in h_full
    assert "RULE (sizing)" not in h_compact and "RULE (geometry)" in h_compact
    assert "unrelated" in h_compact and "market chop" not in h_compact and "digest" not in h_compact
    assert len(h_compact) < len(h_full)
    served = frozen._Served(b)
    assert served.call("get_quote", {"symbol": "AAPL"}) == {"last": 100}
    assert "error" in served.call("get_chain", {"symbol": "AAPL", "expiry": "2026-10-16"})


def test_compact_is_unavailable_without_core_flags_and_no_mutation_paths_exist():
    b = _bundle()
    for r in b["knowledge"]["rules"]:
        r.pop("core", None)
    assert frozen.variant_knowledge(b, "compact")["available"] is False
    served = frozen._Served(_bundle())
    out = served.call("save_note", {"scope": "rule", "text": "x"})
    assert out.get("frozen") and served.proposed_notes and "not written" in out["note"]



def test_compare_reads_the_emitted_gap_fields_and_keeps_reasons_apart():
    # R147-02: an uncapturable image is a capture-time gap emitted as `bundleGaps`
    base = {"bundleId": "case", "variant": "current", "verdict": "skip", "noVerdict": False,
            "bundleGaps": [], "manifestGaps": [], "toolCalls": {"served": 1, "missing": 0}}
    complete = frozen.compare([base, {**base, "variant": "compact"}])
    assert complete["coverageLimited"] is False and complete["coverage"] == {
        "missingToolCalls": 0, "imageGap": False, "bundleGaps": [], "manifestGaps": []}
    image = frozen.compare([{**base, "bundleGaps": ["view_image output is not capturable"]}, {**base, "variant": "compact"}])
    assert image["coverageLimited"] is True and image["coverage"]["imageGap"] is True \
        and image["coverage"]["missingToolCalls"] == 0 and "uncapturable image output" in image["coverageNote"]
    manifest_only = frozen.compare([{**base, "manifestGaps": ["source history block missing (not persisted at run time)"]},
                                    {**base, "variant": "compact"}])
    assert manifest_only["coverageLimited"] is True and manifest_only["coverage"]["imageGap"] is False \
        and manifest_only["coverage"]["manifestGaps"] == ["source history block missing (not persisted at run time)"]
    both = frozen.compare([{**base, "bundleGaps": ["view_image output is not capturable"],
                            "toolCalls": {"served": 0, "missing": 2}}, {**base, "variant": "compact"}])
    assert both["coverage"]["missingToolCalls"] == 2 and both["coverage"]["imageGap"] is True, "one reason never masks another"
    legacy = frozen.compare([{**base, "gaps": ["image output not captured"]}])
    assert legacy["coverageLimited"] is True and legacy["coverage"]["imageGap"] is True
