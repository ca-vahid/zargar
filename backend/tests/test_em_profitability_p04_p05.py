"""P-04 (touch vs confirmed reaction) and P-05 (afternoon / event-day cohort), frozen 2026-09-16 as an addendum to
profitability-cohorts-v1. Pure: rejected opportunities and sacrificed winners are counted from the rows the report
already carries; nothing here activates a rule, changes risk, widens a chase limit or turns the friction marker into
a gate."""
from zargar.tools.em_profitability import COHORT_P01, COHORTS_ADDENDUM, EVENT_DAYS, VERSION, render, summarize


def _trade(sym, conf, window, net, *, closed=True, cohort=COHORT_P01, event=None):
    return {"symbol": sym, "trigger": "b1", "kind": "bounce", "direction": "long", "cohort": cohort, "confirmation": conf, "window": window,
            "eventDay": event, "filledQty": 1, "closed": closed, "netRealized": net if closed else None, "fees": 2.08, "roomBin": "1-3R",
            "policyVersion": "deterministic-entry-v1", "decisionId": f"d-{sym}", "runId": f"r-{sym}", "contract": None}


def _refused(sym, conf, window, proxy, *, cohort=COHORT_P01, event=None):
    return {"symbol": sym, "trigger": "b1", "kind": "bounce", "direction": "long", "cohort": cohort, "confirmation": conf, "window": window,
            "eventDay": event, "refusal": "budget", "underlyingProxy": proxy, "roomBin": "1-3R", "policyVersion": "deterministic-entry-v1",
            "decisionId": f"d-{sym}", "runId": f"r-{sym}", "contract": None}


def test_p04_counts_fills_rejections_and_sacrificed_winners_by_confirmation():
    assert VERSION == "profitability-cohorts-v1" and COHORTS_ADDENDUM == "p04-p05-2026-09-16"
    data = {"date": "2026-09-16", "cutoff": "16:00", "attempts": [],
            "trades": [_trade("CRCL", "observed_reclaim", "prime_open", -94.11), _trade("SNDK", "observed_reclaim", "prime_close", 27.16),
                       _trade("CVNA", "anticipated", "prime_open", -29.49), _trade("XYZ", "anticipated", "prime_open", 0.0, closed=False)],
            "refused": [_refused("NBIS", "anticipated", "prime_close", "tp1_first"), _refused("NOW", "observed_reclaim", "prime_open", "stop_first"),
                        _refused("BE", "anticipated", "prime_open", "unresolved: no bars")]}
    s = summarize(data)
    p04 = s["p04"]
    assert p04["confirmation=observed_reclaim"] == {"fills": 2, "net": -66.95, "open": 0, "winners": 1, "losers": 1, "rejected": 1, "sacrificedWinners": 0, "unknownProxy": 0}
    assert p04["confirmation=anticipated"] == {"fills": 2, "net": -29.49, "open": 1, "winners": 0, "losers": 1, "rejected": 2, "sacrificedWinners": 1, "unknownProxy": 1}


def test_p05_splits_afternoon_from_morning_and_event_days_from_ordinary_days():
    assert EVENT_DAYS["2026-09-16"] == "FOMC"
    data = {"date": "2026-09-16", "cutoff": "16:00", "attempts": [],
            "trades": [_trade("CRCL", "observed_reclaim", "prime_open", -94.11, event="FOMC"), _trade("SNDK", "observed_reclaim", "prime_close", 27.16, event="FOMC"),
                       _trade("OTH", "anticipated", "midday", -5.0, cohort=None)],
            "refused": [_refused("NBIS", "anticipated", "prime_close", "tp1_first", event="FOMC"), _refused("Q", "anticipated", None, "unknown")]}
    s = summarize(data)
    p05 = s["p05"]
    assert p05["morning|event:FOMC"]["fills"] == 1 and p05["morning|event:FOMC"]["net"] == -94.11
    assert p05["afternoon|event:FOMC"] == {"fills": 1, "net": 27.16, "open": 0, "winners": 1, "losers": 0, "rejected": 1, "sacrificedWinners": 1, "unknownProxy": 0}
    assert p05["afternoon|ordinary"]["fills"] == 1, "P-05 covers every EM attempt, not only the P-01 cohort"
    assert p05["unknown_window|ordinary"]["rejected"] == 1 and p05["unknown_window|ordinary"]["unknownProxy"] == 1
    md = render(data, s)
    assert "P-04 touch vs confirmed reaction" in md and "P-05 afternoon / event-day cohort" in md
    assert "gate" not in md.split("P-04")[1].split("P-05")[0].lower().replace("never a gate", "")
