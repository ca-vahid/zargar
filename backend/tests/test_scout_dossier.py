"""Scout dossier: XBRL fundamentals (quarters from cumulative filings, restatements, stale data), the fact
sheet, grounding of the note, its own budget, and the API - NO model call and no network here."""
from __future__ import annotations

import datetime as dt
import json

import httpx
import pytest
from sqlalchemy import func, select

from zargar import events as ev
from zargar.api.app import create_app
from zargar.models import Event, Order, ScoutDossier
from zargar.techniques.scout import dossier as ds
from zargar.techniques.scout import fundamentals as fu
from zargar.techniques.scout.form4 import ET
from zargar.techniques.scout.service import ScoutService

from .conftest import make_test_config
from .test_scout_p3 import FakeClaude, daily


def row(start, end, val, filed="2026-01-01", **kw):
    return {"start": start, "end": end, "val": val, "filed": filed, **kw}


def inst(end, val, filed="2026-01-01"):
    return {"end": end, "val": val, "filed": filed}


def facts_doc(tags: dict, ns: str = "us-gaap") -> dict:
    return {"facts": {ns: {t: {"units": u} for t, u in tags.items()}}}


# FY2025 = calendar year; 10-Qs file Q1..Q3 as 3-month periods, the 10-K only the year
REV = [row("2024-01-01", "2024-03-31", 90), row("2024-04-01", "2024-06-30", 95), row("2024-07-01", "2024-09-30", 100),
       row("2024-01-01", "2024-12-31", 395),
       row("2025-01-01", "2025-03-31", 100), row("2025-04-01", "2025-06-30", 110), row("2025-07-01", "2025-09-30", 120),
       row("2025-01-01", "2025-12-31", 460),
       row("2026-01-01", "2026-03-31", 130), row("2026-04-01", "2026-06-30", 143)]
# cash flow is filed year-to-date
OCF = [row("2025-01-01", "2025-03-31", 10), row("2025-01-01", "2025-06-30", 25), row("2025-01-01", "2025-09-30", 45),
       row("2025-01-01", "2025-12-31", 70), row("2026-01-01", "2026-03-31", 12), row("2026-01-01", "2026-06-30", 30)]


# =========================================================================== fundamentals (pure)
def test_quarters_from_reported_cumulative_and_fiscal_year():
    q = fu.quarters_from(fu.duration_periods(REV))
    assert q["2025-12-31"] == {"value": 130.0, "start": "2025-09-30", "derived": True}      # FY - Q1..Q3
    assert q["2024-12-31"]["value"] == 110.0 and not q["2025-06-30"]["derived"]
    c = fu.quarters_from(fu.duration_periods(OCF))
    assert [c[e]["value"] for e in sorted(c)] == [10, 15, 20, 25, 12, 18]                    # YTD differences
    assert c["2025-03-31"]["derived"] is False and c["2025-06-30"]["derived"] is True


def test_latest_filed_statement_wins_and_ttm_basis():
    rows = REV + [row("2025-07-01", "2025-09-30", 121, filed="2026-06-01")]                  # restated later
    s = fu.duration_series(facts_doc({"Revenues": {"USD": rows}})["facts"], "revenue", ("Revenues",))
    assert s.quarters["2025-09-30"]["value"] == 121
    assert s.ttm() == (121 + 129 + 130 + 143, "four quarters to 2026-06-30")                # Q4 = 460 - 100 - 110 - 121
    assert s.yoy("2026-06-30") == pytest.approx(143 / 110 - 1)
    # a gap in the quarters -> the last fiscal year, and the basis says so
    gappy = [r for r in REV if r["end"] != "2026-03-31"]
    g = fu.duration_series(facts_doc({"Revenues": {"USD": gappy}})["facts"], "revenue", ("Revenues",))
    assert g.ttm() == (460.0, "fiscal year to 2025-12-31")
    assert fu.Series("x").ttm() == (None, "not reported")


def test_tag_fallback_never_mixes_currencies_and_shares_are_not_differenced():
    doc = facts_doc({"RevenueFromContractWithCustomerExcludingAssessedTax": {"USD": REV[4:]},
                     "Revenues": {"USD": REV[:4], "EUR": [row("2023-01-01", "2023-12-31", 1)]},
                     "NetIncomeLoss": {"USD": [row("2025-01-01", "2025-12-31", 40)]},
                     "WeightedAverageNumberOfDilutedSharesOutstanding": {"shares": [
                         row("2025-01-01", "2025-03-31", 1000), row("2025-01-01", "2025-06-30", 1010),
                         row("2025-04-01", "2025-06-30", 1020)]},
                     "Assets": {"USD": [inst("2026-06-30", 900), inst("2026-06-30", 950, filed="2026-08-01")]}})
    s = fu.build(doc)
    assert s["revenue"].tag.startswith("RevenueFromContract") and "2024-12-31" in s["revenue"].annuals   # older tag fills in
    assert fu.currency(s) == "USD"
    assert sorted(s["dilutedShares"].quarters) == ["2025-03-31", "2025-06-30"]
    assert s["dilutedShares"].quarters["2025-06-30"]["value"] == 1020                       # reported, never 6M - 3M
    assert s["assets"].latest_point() == ("2026-06-30", 950.0)
    assert s["capex"].tag is None and s["capex"].ttm()[0] is None


# =========================================================================== price + sheet (pure)
def test_price_stats_and_chart():
    end = dt.date(2026, 10, 9)
    bars = daily("ABC", end, close=100.0, n=300)
    for i, b in enumerate(bars):                                 # a steady climb to 129.9
        b.close = 100.0 + i * 0.1
        b.high, b.low = b.close * 1.01, b.close * 0.99
    px = ds.price_stats(bars, daily("SPY", end, close=500.0, n=300))
    assert px["last"] == pytest.approx(129.9) and px["lastDate"] == "2026-10-09"
    assert px["ret"]["1m"] == pytest.approx(129.9 / 127.8 - 1) and px["bench"]["12m"] == pytest.approx(0.0)
    assert px["sma200"] is not None and px["maxDrawdown"] == 0.0 and px["atrPct"] > 0
    assert ds.price_stats(bars[:1]) == {} and ds.price_stats(bars[:30])["ret"]["3m"] is None
    pts = ds.price_chart(bars, daily("SPY", end, close=500.0, n=300))["points"]
    assert len(pts) == 252 and pts[0]["ma200"] is None and pts[-1]["ma200"] is not None
    assert pts[-1]["bench"] == pytest.approx(pts[0]["c"])        # flat benchmark, rebased to the first close


def sheet_for(doc, *, sic="3570", mcap=1000.0, today="2026-08-15"):
    return ds.build_sheet(ticker="ABC", profile={"name": "Abc Corp", "sic": sic, "sicDescription": "Widgets"},
                          series=fu.build(doc), px={}, market_cap=mcap, market_cap_why="test",
                          insiders=ds.insider_summary([], today), today=today)


def by_label(sheet, part):
    return next((f for f in sheet.facts if part in f.label), None)


def test_sheet_numbers_and_what_it_refuses_to_show():
    doc = facts_doc({"Revenues": {"USD": REV}, "NetCashProvidedByUsedInOperatingActivities": {"USD": OCF},
                     "NetIncomeLoss": {"USD": [row("2025-01-01", "2025-12-31", -40)]},
                     "CashAndCashEquivalentsAtCarryingValue": {"USD": [inst("2026-06-30", 50)]},
                     "LongTermDebt": {"USD": [inst("2019-12-31", 999)]},                     # stale -> not used
                     "Liabilities": {"USD": [inst("2026-06-30", 300)]}, "Assets": {"USD": [inst("2026-06-30", 600)]}})
    sh, charts = sheet_for(doc)
    assert by_label(sh, "Revenue, latest quarter").value.startswith("$143.00; +30.0%")
    assert by_label(sh, "Revenue, trailing").value == "$523.00 (four quarters to 2026-06-30)"
    assert by_label(sh, "Cash from operations").value.startswith("$75.00")                   # 20 + 25 + 12 + 18
    assert by_label(sh, "Long-term debt").value == "not reported under the standard tags"
    assert by_label(sh, "Long-term debt minus cash") is None
    assert by_label(sh, "Price to earnings").value.startswith("not meaningful")
    assert by_label(sh, "Price to sales").value == "1.9x"
    assert by_label(sh, "Liabilities as a share").value == "50.0%"
    assert by_label(sh, "Free cash flow") is None                                            # no capital spending tag
    assert by_label(sh, "last 90 days").value == "no open-market buying; no open-market selling"
    assert [q["end"] for q in charts["quarters"]][-1] == "2026-06-30" and len(charts["quarters"]) == 8
    assert [f.id for f in sh.facts] == [f"F{i + 1}" for i in range(len(sh.facts))]
    # a financial company: no cash-flow or debt measures at all
    fin, _ = sheet_for(doc, sic="6021")
    assert by_label(fin, "Cash flow").value.startswith("not shown") and by_label(fin, "Long-term debt") is None
    # statements that stopped long ago are flagged, a foreign-currency reporter gets no valuation ratios
    old, _ = sheet_for(doc, today="2027-06-01")
    assert by_label(old, "Data warning").tone == "bad"
    eur, _ = sheet_for(facts_doc({"Revenues": {"EUR": REV}}))
    assert by_label(eur, "Reporting currency") and by_label(eur, "Price to sales") is None
    none, _ = ds.build_sheet(ticker="X", profile={}, series=None, px={}, market_cap=None)
    assert by_label(none, "Financial statements").value.startswith("none on file")


def test_insider_summary_dedupes_joint_filings():
    rows = [{"row_key": "a:1", "insider_cik": "1", "trans_code": "P", "trans_date": "2026-08-01", "value": 100.0},
            {"row_key": "a:1", "insider_cik": "2", "trans_code": "P", "trans_date": "2026-08-01", "value": 100.0},
            {"row_key": "b:1", "insider_cik": "3", "trans_code": "S", "trans_date": "2026-01-10", "value": 40.0}]
    s = ds.insider_summary(rows, "2026-08-15")
    assert s["d90"]["buys"] == {"n": 1, "value": 100.0, "insiders": 2} and s["d90"]["sells"]["n"] == 0
    assert s["d365"]["sells"] == {"n": 1, "value": 40.0, "insiders": 1}


# =========================================================================== grounding (pure)
def test_grounding_keeps_only_cited_points():
    sh = ds.Sheet()
    sh.add("growth", "Revenue", "$1.00B")
    sh.add("profit", "Margin", "10.0%")
    release = "Sales volume grew for the seventh consecutive quarter."
    reply = {"lean": "Neutral", "confidence": 9, "summary": "s", "background": "makes widgets",
             "leanWhy": {"text": "balanced", "facts": ["F1"]},
             "strengths": [{"text": "growing", "facts": ["[F1]", "F99"]},                    # brackets ok, F99 removed
                           {"text": "volume", "quote": "sales volume  GREW for the seventh"},    # ws/case-insensitive quote
                           {"text": "invented", "quote": "record profit this quarter"},           # not in the release
                           {"text": "uncited"}],
             "concerns": [{"text": "thin", "facts": ["F2"], "quote": "made up words here"}],      # bad quote, good fact
             "valuation": "not a list", "watch": [],
             "questions": ["q1", "", "q3", "q4", "q5", "q6"]}
    g = ds.ground(reply, sh, release)
    n = g["note"]
    assert n["lean"] == "neutral" and n["confidence"] == 5 and n["leanWhy"]["facts"] == ["F1"]
    assert [p["text"] for p in n["strengths"]] == ["growing", "volume"] and n["strengths"][0]["facts"] == ["F1"]
    assert n["strengths"][1]["quote"].startswith("sales volume") and n["concerns"][0] == {
        "text": "thin", "facts": ["F2"], "quote": None}
    assert {d["point"]["text"] for d in g["dropped"]} == {"invented", "uncited"}
    assert n["valuation"] == [] and n["questions"] == ["q1", "q3", "q4", "q5"]
    with pytest.raises(ValueError):
        ds.ground({"lean": "buy"}, sh, release)
    with pytest.raises(ValueError):                              # nothing grounded is not a note
        ds.ground({"lean": "cautious", "strengths": [{"text": "x", "facts": ["F77"]}]}, sh, None)
    assert "does not exist" in ds.render(sh, None, today="2026-08-15") and "[F2] Margin: 10.0%" in ds.render(sh, None, today="x")


# =========================================================================== integration (fake model, no network)
NOTE = {"lean": "constructive", "confidence": 4, "summary": "Growing.", "background": "Makes widgets.",
        "leanWhy": {"text": "growth", "facts": ["F1"]},
        "strengths": [{"text": "listed company", "facts": ["F1"]}, {"text": "from the release", "quote": "Revenue rose 30 percent"},
                      {"text": "invented", "facts": ["F999"]}],
        "concerns": [], "valuation": [], "watch": [], "questions": ["What next?"]}


@pytest.fixture
async def rig(engine):
    svc = ScoutService(engine)
    engine.scout_service = svc
    today = dt.datetime.now(ET).date()

    async def bars(sym, start, end):
        return daily(sym, end, close=50.0, n=300)

    async def mcap(cik, close, as_of):
        return 2e9, "test"

    async def earnings(sym, cik, as_of):
        return [(today + dt.timedelta(days=20)).isoformat()], "test"

    async def subs(cik):
        return {"name": "Abc Corp", "sic": "3570", "sicDescription": "Widgets", "exchanges": ["Nasdaq"],
                "filings": {"recent": {"form": ["8-K", "10-Q"], "filingDate": ["2026-08-01", "2026-08-02"],
                                       "items": ["2.02,9.01", ""], "accessionNumber": ["0001-26-000001", "0001-26-000002"]}}}

    async def text(cik, acc):
        return "Abc Corp today reported results. Revenue rose 30 percent.", []

    async def cik_of(t):
        return ("1234", "ABC CORP") if t == "ABC" else None

    async def cfacts(cik):
        return facts_doc({"Revenues": {"USD": REV}, "NetIncomeLoss": {"USD": [row("2025-01-01", "2025-12-31", 40)]}})

    svc.daily_bars, svc.market_cap, svc.earnings_dates, svc._submissions = bars, mcap, earnings, subs
    svc.desk.filing_text = text
    svc.dossier.cik_for_ticker, svc.dossier.company_facts = cik_of, cfacts
    return svc


async def count(engine, model, *where):
    async with engine.sf() as s:
        return (await s.execute(select(func.count()).select_from(model).where(*where))).scalar()


async def test_dossier_run_grounds_the_note_and_places_no_order(rig, engine):
    svc = rig
    svc.desk.claude_client = fake = FakeClaude(NOTE, usage=(6000, 3000))
    d = await svc.dossier.request("abc", wait=True)
    assert d["status"] == "ok" and d["ticker"] == "ABC" and d["name"] == "Abc Corp" and d["lean"] == "constructive"
    assert [p["text"] for p in d["note"]["strengths"]] == ["listed company", "from the release"]
    assert d["dropped"][0]["point"]["text"] == "invented" and d["costUsd"] == pytest.approx(6000 * 4e-6 + 3000 * 20e-6)
    labels = {f["label"] for f in d["facts"]}
    assert {"Last close", "Revenue, latest quarter", "Market value", "Next results date"} <= labels
    assert len(d["charts"]["price"]) == 252 and d["sources"]["release"]["accession"] == "0001-26-000001"
    assert "releaseText" not in d["sources"]
    sent = fake.calls[0]
    assert sent["model"] == "claude-opus-5-5" and "SOURCE R1" in sent["messages"][0]["content"]
    assert "Revenue rose 30 percent" in sent["messages"][0]["content"] and "[F1] Company: Abc Corp (ABC)" in sent["messages"][0]["content"]
    assert await count(engine, Event, Event.type == ev.SCOUT_DOSSIER) == 1 and await count(engine, Order) == 0
    # the same ticker the same day is reused (no second call); refresh makes a new one
    again = await svc.dossier.request("ABC", wait=True)
    assert again["id"] == d["id"] and len(fake.calls) == 1
    fresh = await svc.dossier.request("ABC", refresh=True, wait=True)
    assert fresh["id"] != d["id"] and len(fake.calls) == 2


async def test_dossier_degrades_to_facts_only_and_has_its_own_budget(rig, engine):
    svc = rig
    svc.desk.claude_client = fake = FakeClaude("I cannot answer in JSON")
    d = await svc.dossier.request("ABC", wait=True)
    assert d["status"] == "facts_only" and d["note"] is None and len(d["facts"]) > 10 and "not usable" in d["reason"]
    await engine.settings.set("techniques.scout.dossier_budget_usd_day", 0.01)
    b = await svc.dossier.request("ABC", refresh=True, wait=True)
    assert b["status"] == "facts_only" and "dossier_budget_usd_day" in b["reason"] and len(fake.calls) == 1
    bad = await svc.dossier.request("ZZZZ", wait=True)
    assert bad["status"] == "error" and "not in the SEC's company list" in bad["reason"]
    with pytest.raises(ValueError):
        await svc.dossier.request("  ", wait=True)
    assert (await svc.desk.spent_today(dt.datetime.now(ET).date().isoformat()))["total"] == 0   # lanes' budget untouched


async def test_dossier_api(rig, engine):
    svc = rig
    svc.desk.claude_client = FakeClaude(NOTE)
    app = create_app(make_test_config(), engine)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as h:
        r = await h.post("/api/scout/dossiers", json={"ticker": "ABC"})
        assert r.status_code == 200 and r.json()["status"] in ("running", "ok")
        did = r.json()["id"]
        for t in list(svc.dossier._tasks):
            await t
        full = (await h.get(f"/api/scout/dossiers/{did}")).json()
        assert full["status"] == "ok" and full["note"]["summary"] == "Growing."
        rows = (await h.get("/api/scout/dossiers", params={"ticker": "abc"})).json()
        assert [x["id"] for x in rows] == [did] and "facts" not in rows[0] and rows[0]["lean"] == "constructive"
        assert (await h.get("/api/scout/dossiers/nope")).status_code == 404
        assert (await h.post("/api/scout/dossiers", json={"ticker": "!!"})).status_code == 400
        assert "api_key" not in json.dumps(full).lower()
    assert await count(engine, ScoutDossier) == 1
