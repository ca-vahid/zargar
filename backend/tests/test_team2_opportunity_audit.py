"""opportunity-audit-v1: the counting rule, and what must stay visible.

The audit exists because the selection study starts at contract selection, so a candidate refused
on structure never reaches it. Its one dangerous failure mode is inflation: counting refusal rows
instead of candidates. Both desks hit that on 2026-09-21 — 37 collision rows for two setups here,
48 occupancy rows for one suppressed opportunity on the EM desk.
"""
from __future__ import annotations

from zargar.tools import team2_opportunity_audit as oa

DAY = "2026-09-21"
BOOKS = {"runC": {"symbol": "SPY", "book": "control0"}, "runS": {"symbol": "SPY", "book": "sizing00"},
         "runX": {"symbol": "SPY", "book": "c1conjun"}}


def armed():
    return [(0, "TechniquePlanArmed", {"runId": r, "symbol": v["symbol"], "portfolioId": v["book"]})
            for r, v in BOOKS.items()]


def refusal(run, setup, ts, event="skip_target_collision", reason="target is the source"):
    return (ts, "TechniquePlanTriggerSkipped",
            {"runId": run, "symbol": BOOKS[run]["symbol"], "event": event, "setup": setup, "reason": reason})


def break_note(run, setup, ts, level=767.26):
    return (ts, "TechniquePlanRead", {"runId": run, "symbol": BOOKS[run]["symbol"], "event": "pm_break",
                                      "setup": setup, "level": level})


# ---------------------------------------------------------------- the counting rule
def test_one_setup_refused_on_many_bars_in_many_books_is_one_candidate():
    """Monday's SPY shape: three books, eleven bars each. One candidate."""
    rows = armed() + [break_note("runC", "pm_break_up@09:45", 1000)]
    for run in BOOKS:
        for i in range(11):
            rows.append(refusal(run, "pm_break_up@09:45", 2000 + i * 120000))
    c = oa.fold(rows, DAY)
    assert len(c) == 1, "33 refusal rows are one physical candidate"
    only = next(iter(c.values()))
    assert only["revisions"] == 34, "every row is still counted as a revision, and none is lost"
    assert set(only["books"]) == {"control0", "sizing00", "c1conjun"}


def test_distinct_contacts_never_collide():
    rows = armed() + [refusal("runC", "pm_break_up@09:45", 1000),
                      refusal("runC", "pm_break_up@10:30", 2000),
                      refusal("runC", "scenario_1@09:30", 3000)]
    assert len(oa.fold(rows, DAY)) == 3


def test_touches_of_one_setup_are_not_separate_candidates():
    """A pullback is a touch of the same contact, not a new opportunity."""
    rows = armed() + [refusal("runC", "pm_break_up@09:45#1", 1000),
                      refusal("runC", "pm_break_up@09:45#2", 2000),
                      refusal("runC", "pm_break_up@09:45#3", 3000)]
    assert len(oa.fold(rows, DAY)) == 1


def test_the_same_setup_in_two_symbols_is_two_candidates():
    rows = armed() + [(0, "TechniquePlanArmed", {"runId": "runQ", "symbol": "QQQ", "portfolioId": "control0"}),
                      refusal("runC", "pm_break_up@09:45", 1000),
                      (2000, "TechniquePlanTriggerSkipped",
                       {"runId": "runQ", "symbol": "QQQ", "event": "skip_target_collision",
                        "setup": "pm_break_up@09:45"})]
    got = oa.fold(rows, DAY)
    assert len(got) == 2 and {c["symbol"] for c in got.values()} == {"SPY", "QQQ"}


# ---------------------------------------------------------------- what must stay visible
def test_a_refused_candidate_stays_visible_with_its_refusal_chain():
    rows = armed() + [break_note("runC", "pm_break_up@09:45", 1000),
                      refusal("runC", "pm_break_up@09:45", 2000),
                      refusal("runC", "pm_break_up@09:45", 3000, event="skip_no_trade_zone",
                              reason="inside the pre-market range")]
    c = next(iter(oa.fold(rows, DAY).values()))
    chain = [x["event"] for x in c["refusalChain"]]
    assert chain == ["skip_target_collision", "skip_no_trade_zone"], "order preserved, each reason kept once"
    assert c["refusalChain"][0]["reason"]
    s = oa.summarise({c["id"]: c})
    assert s["refusedEverywhere"] == 1 and s["firstRefusalByReason"]["skip_target_collision"] == 1


def test_a_candidate_that_was_never_priced_is_reported_as_such():
    """The whole point: no contract was ever selected, so its option outcome is unknown, not zero."""
    rows = armed() + [break_note("runC", "pm_break_up@09:45", 1000),
                      refusal("runC", "pm_break_up@09:45", 2000)]
    c = next(iter(oa.fold(rows, DAY).values()))
    assert c["priced"] is False
    assert oa.summarise({c["id"]: c})["neverPriced"] == 1


def test_a_candidate_admitted_in_one_book_and_refused_in_others_is_one_candidate_marked_admitted():
    rows = armed() + [refusal("runC", "scenario_1@09:45", 1000, event="skip_no_trade_zone"),
                      refusal("runS", "scenario_1@09:45", 1000, event="skip_no_trade_zone"),
                      (2000, "TechniquePlanTriggerFired",
                       {"runId": "runX", "symbol": "SPY", "setupId": "scenario_1@09:45",
                        "trigger": "scenario_1@09:45#1"})]
    got = oa.fold(rows, DAY)
    assert len(got) == 1
    c = next(iter(got.values()))
    assert c["books"]["c1conjun"]["admitted"] is True
    assert c["books"]["control0"]["admitted"] is False
    assert c["priced"] is True
    s = oa.summarise(got)
    assert s["admittedSomewhere"] == 1 and s["refusedEverywhere"] == 0


# ---------------------------------------------------------------- evidence integrity
def test_a_later_row_cannot_rewrite_the_first_evidence():
    """Revisions accumulate; they never overwrite what was first recorded."""
    rows = armed() + [break_note("runC", "pm_break_up@09:45", 1000, level=767.26),
                      break_note("runC", "pm_break_up@09:45", 9000, level=999.99)]
    c = next(iter(oa.fold(rows, DAY).values()))
    assert c["source"] == 767.26, "the first source stands"
    assert c["confirmedTs"] == 1000, "the first confirmation time stands"
    assert c["revisions"] == 2, "and the later row is still counted, not discarded"


def test_folding_is_pure_and_order_stable():
    rows = armed() + [break_note("runC", "pm_break_up@09:45", 1000),
                      refusal("runC", "pm_break_up@09:45", 2000)]
    assert oa.fold(list(rows), DAY) == oa.fold(list(rows), DAY)


def test_the_audit_writes_nothing():
    """Order-free means order-free: the module must hold no write, order or setting path."""
    import pathlib
    src = pathlib.Path(oa.__file__).read_text(encoding="utf-8")
    for forbidden in ("journal.append", "Journal(", "OrderIntent", "place(", "svc.set", "settings.set",
                      "INSERT", "session.add", "commit("):
        assert forbidden not in src, f"the audit must not contain {forbidden}"
