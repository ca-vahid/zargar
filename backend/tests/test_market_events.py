"""W4.1-W4.5 (2026-10-03): the shared, append-only market event store - parsers, revisions, coverage, exposure."""
import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from zargar.engine import Engine
from zargar.research import market_events as me

from .conftest import make_test_config

ET = ZoneInfo("America/New_York")

FOMC_HTML = """
<h4>2026 FOMC Meetings</h4>
<div class="fomc-meeting__month"><strong>September</strong></div><div class="fomc-meeting__date">15-16*</div>
<div class="fomc-meeting__month"><strong>October</strong></div><div class="fomc-meeting__date">27-28</div>
<h4>2027 FOMC Meetings</h4>
<div class="fomc-meeting__month"><strong>January</strong></div><div class="fomc-meeting__date">26-27</div>
"""

BEA_ICS = "\r\n".join([
    "BEGIN:VCALENDAR",
    "BEGIN:VEVENT", "DTSTART;VALUE=DATE-TIME:20260930T123000Z",
    "SUMMARY:Personal Income and Outlays\\, August 2026", "END:VEVENT",
    "BEGIN:VEVENT", "DTSTART;VALUE=DATE-TIME:20261029T123000Z",
    "SUMMARY:GDP (Advance Estimate)\\, 3rd Quarter 2026", "END:VEVENT",
    "BEGIN:VEVENT", "DTSTART;VALUE=DATE-TIME:20261202T133000Z",
    "SUMMARY:GDP by County and Personal Income by County\\, 2025", "END:VEVENT",
    "BEGIN:VEVENT", "DTSTART;VALUE=DATE-TIME:20261103T133000Z",
    "SUMMARY:U.S. International Trade in Goods and Services\\, Sept", "END:VEVENT",
    "END:VCALENDAR"])


def test_parsers():
    evs, cov = me.parse_fomc(FOMC_HTML)
    st = [e for e in evs if e["kind"] == "fomc_statement"]
    assert [(e["date"], e["time"]) for e in st] == [("2026-09-16", "14:00"), ("2026-10-28", "14:00"),
                                                    ("2027-01-27", "14:00")]
    assert st[0]["extra"]["sep"] is True and "projections" in st[0]["name"]
    assert cov == ("2026-01-01", "2027-12-31")
    bea, bcov = me.parse_bea_ics(BEA_ICS)
    assert [(e["kind"], e["date"], e["time"]) for e in bea] == [("pce", "2026-09-30", "08:30"),
                                                                 ("gdp", "2026-10-29", "08:30")]
    assert bcov == ("2026-09-30", "2026-12-02")
    bls = me.bls_events()
    assert ("cpi", "2026-09-11") in {(e["kind"], e["date"]) for e in bls}, "the CPI the app never had"
    assert ("nfp", "2026-10-02") in {(e["kind"], e["date"]) for e in bls}
    assert all(e["tier"] == 2 for e in bls if e["kind"] in ("ppi", "jolts"))
    rows = me.parse_nasdaq_earnings({"data": {"rows": [{"symbol": "ORCL", "time": "time-after-hours"},
                                                       {"symbol": "XYZ", "time": "time-pre-market"}]}},
                                    "2026-10-06", {"ORCL"})
    assert len(rows) == 1 and rows[0]["extra"]["timing"] == "AMC" and rows[0]["scope"] == "symbol"


def test_policy_shadow_rules():
    now = dt.datetime(2026, 10, 28, 13, 30, tzinfo=ET)
    expo = {"events": [{"name": "FOMC statement", "kind": "fomc_statement", "tier": 1, "date": "2026-10-28",
                        "time": "14:00"}], "earnings": None}
    opt = {w["rule"] for w in me.policy_shadow(expo, now=now, sec_type="OPT", dte=2)}
    assert opt == {"E1", "E2", "E3"}
    shares = {w["rule"] for w in me.policy_shadow(expo, now=now, sec_type="STK", dte=None)}
    assert shares == {"E2"}, "shares are only held 15 minutes either side"
    assert me.policy_shadow({"events": []}, now=now, sec_type="OPT", dte=1) == []


@pytest.fixture
async def eng(fresh_db):
    e = Engine(make_test_config())
    await e.start()
    yield e
    await e.stop()


async def test_store_is_append_only_with_coverage_and_tombstones(eng):
    store = eng.market_events
    assert store is not None and store.loaded and store.macro_coverage_through() is None, "no coverage = unknown"
    t0 = dt.datetime(2026, 10, 1, 12, 0, tzinfo=dt.timezone.utc)
    evs, cov = me.parse_fomc(FOMC_HTML)
    r = await store.write(evs, source="fed", coverage=cov, now=t0)
    assert r["added"] == 6 and r["changed"] == 0
    assert (await store.write(evs, source="fed", coverage=cov, now=t0 + dt.timedelta(hours=1)))["added"] == 0
    # the October meeting moves a day; the January one disappears from the page
    moved = [dict(e) for e in evs if not e["date"].startswith("2027")]
    t2 = t0 + dt.timedelta(days=1)
    for e in moved:
        if e["date"] == "2026-10-28":
            e["name"] = e["name"] + " (rescheduled)"
    r2 = await store.write(moved, source="fed", coverage=cov, now=t2)
    assert r2["changed"] == 2 and r2["removed"] == 2
    before = await store.as_of(t0 + dt.timedelta(hours=2))
    assert any(e["date"] == "2027-01-27" for e in before), "an earlier decision still sees what was known then"
    assert not any("rescheduled" in e["name"] for e in before)
    now_view = store.between("2026-01-01", "2027-12-31")
    assert not any(e["date"] == "2027-01-27" for e in now_view)
    # coverage needs every tier-1 macro source
    assert store.macro_coverage_through() is None
    await store.write(me.bls_events(), source="bls", coverage=me.BLS_COVERAGE, now=t2)
    bea, bcov = me.parse_bea_ics(BEA_ICS)
    await store.write(bea, source="bea", coverage=bcov, now=t2)
    assert store.macro_coverage_through() == "2026-12-02"
    v = store.as_verified()
    assert v["coverageThrough"] == "2026-12-02" and all(e["tier"] <= 2 for e in v["events"])
    # exposure: a position held across the FOMC window
    expo = me.exposure(store, now=dt.datetime(2026, 10, 26, 10, 0, tzinfo=ET), hold_until=dt.date(2026, 10, 30),
                       symbol="ORCL")
    names = [e["name"] for e in expo["events"]]
    assert expo["coverage"] == "covered" and any("FOMC" in n for n in names) and any(n == "GDP" for n in names)
    assert expo["nextTier1"]["date"] == "2026-10-28"


async def test_tips_header_reads_the_store_and_looks_ahead(eng):
    from zargar.techniques.tip import events as evc
    store = eng.market_events
    t0 = dt.datetime(2026, 10, 1, 12, 0, tzinfo=dt.timezone.utc)
    await store.write(me.bls_events(), source="bls", coverage=me.BLS_COVERAGE, now=t0)
    evs, cov = me.parse_fomc(FOMC_HTML)
    await store.write(evs, source="fed", coverage=cov, now=t0)
    bea, bcov = me.parse_bea_ics(BEA_ICS)
    await store.write(bea, source="bea", coverage=bcov, now=t0)
    ctx = evc.context_for(eng, now=dt.datetime(2026, 10, 9, 14, 0, tzinfo=dt.timezone.utc))
    assert ctx["store"] == "market_events" and ctx["status"] == "no-scheduled-event"
    assert [u["date"] for u in ctx["upcoming"]][:1] == ["2026-10-14"], "CPI next week is on the header"
    line = evc.header_line(ctx)
    assert "next tier-1" in line and "Consumer Price Index" in line
    # PPI (tier 2) on its day labels the day; a Treasury auction never would (not stored)
    ppi = evc.context_for(eng, now=dt.datetime(2026, 10, 15, 13, 0, tzinfo=dt.timezone.utc))
    assert ppi["status"] == "event-day" and any("Producer" in e["name"] for e in ppi["events"])
