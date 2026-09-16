"""TMR-01 (2026-09-16): verified event context - a label with provenance, never a gate.
Pure arithmetic on times and knowledge cuts; one engine case: the label rides a
card and the analyst record and places nothing."""
import datetime as dt

from zargar.techniques.tip import events as evc

ET = dt.timezone(dt.timedelta(hours=-4))
VERIFIED = {"coverageThrough": "2026-09-18", "events": [
    {"date": "2026-09-16", "time": "14:00", "kind": "fomc", "name": "FOMC statement",
     "url": "https://www.federalreserve.gov/newsevents/2026-september.htm",
     "verifiedAt": "2026-09-16T03:35:00+00:00", "verifiedBy": "tips-desk"},
    {"date": "2026-09-16", "time": "14:30", "kind": "fomc", "name": "FOMC press conference",
     "url": "https://www.federalreserve.gov/newsevents/2026-september.htm",
     "verifiedAt": "2026-09-16T03:35:00+00:00", "verifiedBy": "tips-desk"}]}


def test_event_day_label_has_time_zones_time_until_and_provenance():
    now = dt.datetime(2026, 9, 16, 11, 46, tzinfo=ET)          # 11:46 ET = 08:46 PT = 15:46 UTC
    c = evc.event_context(now=now, verified=VERIFIED)
    assert c["status"] == "event-day" and c["coverage"] == "verified" and c["session"] == "2026-09-16"
    stmt, presser = c["events"]
    assert stmt["et"] == "2026-09-16T14:00:00-04:00" and stmt["utc"] == "2026-09-16T18:00:00+00:00"
    assert stmt["secondsUntil"] == 2 * 3600 + 14 * 60 and stmt["timeUntil"] == "T-2h14m" and stmt["phase"] == "before"
    assert presser["timeUntil"] == "T-2h44m" and presser["url"].startswith("https://www.federalreserve.gov/")
    assert stmt["verifiedAt"] == "2026-09-16T03:35:00+00:00" and c["nextEvent"]["name"] == "FOMC statement"
    line = evc.header_line(c)
    assert "FOMC statement 14:00 ET (before, T-2h14m)" in line and "verified 2026-09-16T03:35:00+00:00" in line
    assert "no automatic no-trade rule" in line and c["advisory"].startswith("label only")


def test_after_the_event_the_phase_flips_and_the_next_event_is_none():
    now = dt.datetime(2026, 9, 16, 15, 5, tzinfo=ET)
    c = evc.event_context(now=now, verified=VERIFIED)
    assert [e["phase"] for e in c["events"]] == ["after", "after"] and c["nextEvent"] is None
    assert c["events"][0]["timeUntil"] == "T+1h05m"


def test_unknown_coverage_is_not_no_event():
    now = dt.datetime(2026, 9, 25, 10, 0, tzinfo=ET)          # beyond coverageThrough
    c = evc.event_context(now=now, verified=VERIFIED)
    assert c["status"] == "unknown" and c["coverage"] == "unknown" and c["events"] == []
    assert "UNKNOWN" in c["label"] and "not 'no event'" in c["label"] and "unverified" in evc.header_line(c)
    inside = evc.event_context(now=dt.datetime(2026, 9, 17, 10, 0, tzinfo=ET), verified=VERIFIED)
    assert inside["status"] == "no-scheduled-event" and inside["coverage"] == "verified"
    empty = evc.event_context(now=now, verified=None)
    assert empty["status"] == "unknown"


def test_a_fact_learned_later_never_reaches_an_earlier_decision():
    # a replay of a 2026-09-14 decision: the FOMC entry was verified on 09-15 23:35 ET -> hidden
    as_of = dt.datetime(2026, 9, 14, 13, 0, tzinfo=ET)
    replay = evc.event_context(now=dt.datetime(2026, 9, 16, 11, 0, tzinfo=ET), verified=VERIFIED, as_of=as_of)
    assert replay["events"] == [] and replay["hiddenByKnowledgeCut"] == 2 and replay["knowledgeCut"] == as_of.isoformat()
    assert replay["status"] == "no-scheduled-event", "coverage is judged on the list, the entries on the cut"
    unverified = {"coverageThrough": "2026-09-18", "events": [{"date": "2026-09-16", "time": "14:00", "kind": "fomc", "name": "x"}]}
    c = evc.event_context(now=dt.datetime(2026, 9, 16, 11, 0, tzinfo=ET), verified=unverified)
    assert c["events"] == [] and c["hiddenByKnowledgeCut"] == 1, "an entry without a verification time is never shown as verified"


def test_shared_calendar_is_reported_apart_and_never_merged():
    now = dt.datetime(2026, 9, 17, 10, 0, tzinfo=ET)
    c = evc.event_context(now=now, verified=VERIFIED, shared=[{"date": "2026-09-17", "name": "FOMC decision", "kind": "fomc", "time": "14:00"}])
    assert c["status"] == "no-scheduled-event" and c["events"] == []
    assert c["sharedCalendar"] == [{"date": "2026-09-17", "time": "14:00", "kind": "fomc", "name": "FOMC decision",
                                    "source": "shared-manual", "verifiedAt": None}]


def test_default_list_is_the_verified_fomc_pair_and_settings_can_override():
    class S:
        def __init__(self, v): self.v = v
        def get(self, k, d=None): return self.v.get(k, d)
    assert evc.load_verified(S({})) is evc.DEFAULT_VERIFIED_EVENTS
    assert evc.load_verified(S({"techniques.tip.verified_events": None})) is evc.DEFAULT_VERIFIED_EVENTS
    custom = {"coverageThrough": "2026-10-01", "events": []}
    assert evc.load_verified(S({"techniques.tip.verified_events": custom})) is custom
    assert [e["time"] for e in evc.DEFAULT_VERIFIED_EVENTS["events"]] == ["14:00", "14:30"]
    assert all(e["verifiedAt"] == "2026-09-16T03:35:00+00:00" for e in evc.DEFAULT_VERIFIED_EVENTS["events"])


async def test_label_rides_a_card_and_places_nothing(rig):
    """On the engine: a share tip card created today carries eventContext in its
    context and on the readiness plan; no order is created by labelling."""
    from zargar.approvals import readiness as rd
    from .test_tip_geometry_wiring import _quote, _tip
    eng = rig
    q = await _quote(eng, "EVTA")
    before = len((await _orders(eng)))
    row, sig = await _tip(eng, "EVTA", q.last, stop_pct=2.0)
    p = await eng.proposals.create_from_signal(row, sig, {})
    assert p, "the share tip produced no card"
    ctx = p.get("context") or {}
    assert ctx.get("eventContext") and ctx["eventContext"]["version"] == evc.CONTEXT_VERSION
    assert ctx["eventContext"]["status"] in ("event-day", "no-scheduled-event", "unknown")
    plan = rd.plan_summary(p, (ctx.get("riskPlan") or {}), limit=p.get("limitPrice"), qty=float(p.get("qty") or 1))
    assert plan["eventContext"] == ctx["eventContext"]
    assert len(await _orders(eng)) == before


async def _orders(eng):
    from sqlalchemy import select
    from zargar.models import Order
    async with eng.sf() as session:
        return list((await session.execute(select(Order))).scalars().all())


from .test_proposal_readiness import rig  # noqa: E402,F401
