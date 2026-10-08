"""Scout P1 on real Postgres: idempotent EDGAR ingest (fake transport serving saved
filings - no network), the daily job's candidates + gates + journal, toggles, and the
read-only API."""
from __future__ import annotations

import datetime as dt
import zipfile
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select

from zargar import events as ev
from zargar.api.app import create_app
from zargar.domain import Bar, new_id
from zargar.models import Event, ScoutCandidate, ScoutFiling, ScoutInsiderTrade, Signal
from zargar.techniques.scout import ingest as ing
from zargar.techniques.scout.form4 import ET
from zargar.techniques.scout.service import ScoutService

from .conftest import make_test_config

FIX = Path(__file__).parent / "fixtures" / "scout"

INDEX = (
    "Description:           Daily Index of EDGAR Dissemination Feed by Form Type\n\n"
    "Form Type   Company Name                                                  CIK         Date Filed  File Name\n"
    "-----------------------------------------------------------------------------------------------------------\n"
    "4                AFLAC INC                                                     4977        20261006    edgar/data/4977/0001104659-26-113911.txt\n"
    "4                Japan Post Holdings Co., Ltd.                                 1783464     20261006    edgar/data/1783464/0001104659-26-113911.txt\n"
    "4                Borr Drilling Ltd                                             1715497     20261006    edgar/data/1715497/0001628280-26-065174.txt\n"
    "8-K              SOME CO                                                       55555       20261006    edgar/data/55555/0001575872-26-000675.txt\n")


class FakeEdgar:
    def __init__(self):
        self.requests = 0
        self.paths: list[str] = []

    async def daily_index(self, day):
        self.requests += 1
        return INDEX if day == dt.date(2026, 10, 6) else None

    async def submission_text(self, path):
        self.requests += 1
        self.paths.append(path)
        name = {"0001104659-26-113911": "form4_sale_tenpct.txt",
                "0001628280-26-065174": "form4_purchase_2.txt"}[path.rsplit("/", 1)[-1][:-4]]
        return (FIX / name).read_text(encoding="utf-8")

    async def header(self, cik, acc):
        self.requests += 1
        self.paths.append(acc)
        return (FIX / "8k_202.hdr.sgml").read_text(encoding="utf-8")

    async def dataset_zip(self, name, dest):
        self.requests += 1
        with zipfile.ZipFile(dest, "w") as z:
            z.writestr("SUBMISSION.tsv", "ACCESSION_NUMBER\tFILING_DATE\tDOCUMENT_TYPE\tISSUERCIK\tISSUERTRADINGSYMBOL\n"
                       "0000000009-26-000001\t02-JUL-2026\t4\t0000001234\tXYZ\n"
                       "0001628280-26-065174\t06-OCT-2026\t4\t0001715497\tBORR\n")
            z.writestr("REPORTINGOWNER.tsv", "ACCESSION_NUMBER\tRPTOWNERCIK\tRPTOWNERNAME\tRPTOWNER_RELATIONSHIP\tRPTOWNER_TITLE\n"
                       "0000000009-26-000001\t0000000777\tDOE\tDirector\t\n"
                       "0001628280-26-065174\t0000000888\tX\tDirector\t\n")
            z.writestr("NONDERIV_TRANS.tsv", "ACCESSION_NUMBER\tNONDERIV_TRANS_SK\tTRANS_DATE\tTRANS_CODE\tTRANS_SHARES\t"
                       "TRANS_PRICEPERSHARE\tTRANS_ACQUIRED_DISP_CD\n"
                       "0000000009-26-000001\t1\t01-JUL-2026\tP\t100\t10\tA\n"
                       "0001628280-26-065174\t2\t02-OCT-2026\tP\t100\t10\tA\n")
        return dest

    async def get(self, url, **kw):
        raise AssertionError("no network in tests")

    async def aclose(self):
        pass


async def test_ingest_daily_is_idempotent(engine, tmp_path):
    fake = FakeEdgar()
    st = await ing.ingest_daily(engine.sf, fake, dt.date(2026, 10, 6),
                                ticker_for_cik=lambda cik: _async("SOME"))
    assert st["form4"] == 2 and st["form4New"] == 2 and st["eightK"] == 1 and st["earnings"] == 1
    async with engine.sf() as s:
        trades = (await s.execute(select(ScoutInsiderTrade))).scalars().all()
        eightk = await s.get(ScoutFiling, "0001575872-26-000675")
    assert {t.trans_code for t in trades} == {"S", "P"} and len(trades) == 2 + 1   # AFL 2 sales, BORR 1 buy
    borr = [t for t in trades if t.ticker == "BORR"][0]
    assert borr.is_director and borr.acceptance_ts == dt.datetime(2026, 10, 6, 7, 29, 54, tzinfo=ET)
    assert eightk.items and "2.02" in eightk.items and eightk.ticker == "SOME"
    before = fake.requests
    st2 = await ing.ingest_daily(engine.sf, fake, dt.date(2026, 10, 6))
    assert st2["form4New"] == 0 and st2["eightKNew"] == 0 and fake.requests == before + 1   # index only
    assert (await ing.get_state(engine.sf, "daily_days"))["2026-10-06"]["form4"] == 2
    # the quarterly data set never duplicates a filing the daily index already parsed
    q = await ing.ingest_dataset_quarter(engine.sf, fake, 2026, 3, workdir=tmp_path)
    assert q["filings"] == 1 and q["skippedKnown"] == 1 and q["trades"] == 1
    assert ing.coverage_start(await ing.get_state(engine.sf, "datasets"), {}) == "2026-07-01"


async def _async(v):
    return v


def test_coverage_start_needs_contiguous_quarters():
    done = {"2025q4": {"published": True}, "2026q1": {"published": True}, "2026q3": {"published": True},
            "2026q2": {"published": True}, "2024q1": {"published": True}}
    assert ing.coverage_start(done, {}) == "2025-10-01"


# --------------------------------------------------------------------------- daily job
def bars_for(sym: str, end: dt.date, *, close=50.0, vol=1_000_000, n=40, react=None) -> list[Bar]:
    import zargar.marketstructure.market_calendar as mcal
    days = []
    d = end
    while len(days) < n:
        if mcal.is_trading_day(d):
            days.append(d)
        d -= dt.timedelta(days=1)
    days.reverse()
    out = []
    for i, d in enumerate(days):
        c, v = close, vol
        if react and d.isoformat() in react:
            c, v = react[d.isoformat()]
        ts = int(dt.datetime.combine(d, dt.time(9, 30), ET).timestamp() * 1000)
        out.append(Bar(sym, "1d", ts, c, c, c, c, int(v)))
    return out


def trade(cik, date, code, value=80_000.0, *, issuer="100", ticker="ABC", accepted=None, acc=None):
    acc = acc or f"{cik}-{date}-{code}"
    return ScoutInsiderTrade(
        accession=acc, row_key=f"{acc}:0", form_type="4", issuer_cik=issuer, ticker=ticker, insider_cik=cik,
        insider_name=f"Insider {cik}", is_director=True, is_officer=False, is_ten_pct=False, is_other=False,
        trans_date=date, trans_code=code, acq_disp="A" if code == "P" else "D", shares=value / 10, price=10.0,
        value=value, filed_date=date, acceptance_ts=accepted, source="test")


@pytest.fixture
async def scout(engine):
    svc = ScoutService(engine)
    now = dt.datetime(2026, 10, 7, 7, 0, tzinfo=ET)

    async def bars(sym, start, end):
        if sym == "SPY":
            return bars_for("SPY", end, close=400.0)
        if sym == "ERN":
            # release accepted Sunday 10-04 -> day 0 = Mon 10-05 (3x volume), day +1 = 10-06: +10% vs flat SPY
            return bars_for("ERN", end, react={"2026-10-05": (53.0, 3_000_000), "2026-10-06": (55.0, 1_500_000)})
        if sym == "PENNY":
            return bars_for("PENNY", end, close=2.0)
        return bars_for(sym, end)

    async def spread(sym, entry_date, now_):
        return None, f"pending: entry session {entry_date} not reached"

    async def mcap(cik, close, as_of):
        return (None, "no shares fact") if cik == "300" else (2e9, "test")

    async def corp(sym, start, end):
        return []

    async def earnings(sym, cik, as_of):
        return ["2026-12-15"], "test"

    async def tick(cik):
        return {"500": "ERN"}.get(str(cik))

    svc.daily_bars, svc.entry_spread_pct, svc.market_cap = bars, spread, mcap
    svc.corporate_actions, svc.earnings_dates, svc.ticker_for_cik = corp, earnings, tick
    # three years of history: insiders 1 and 2 opportunistic, 3 routine (March every year)
    rows = []
    for y, (m1, m2) in zip((2023, 2024, 2025), ((2, 5), (6, 8), (11, 1))):
        rows += [trade("1", f"{y}-{m1:02d}-10", "S", acc=f"h1{y}"), trade("2", f"{y}-{m2:02d}-11", "S", acc=f"h2{y}"),
                 trade("3", f"{y}-03-12", "S", acc=f"h3{y}")]
    acc = lambda d, h: dt.datetime.fromisoformat(f"{d}T{h}").replace(tzinfo=ET)
    rows += [trade("1", "2026-10-01", "P", 70_000, accepted=acc("2026-10-01", "17:10:00")),
             trade("2", "2026-10-05", "P", 60_000, accepted=acc("2026-10-06", "18:07:46")),
             trade("3", "2026-10-05", "P", 900_000, accepted=acc("2026-10-06", "18:00:00")),     # routine: never counts
             # issuer 300: opportunistic pair but cheap stock + no market-cap fact
             trade("1", "2026-10-05", "P", 70_000, issuer="300", ticker="PENNY", accepted=acc("2026-10-06", "09:00:00")),
             trade("2", "2026-10-06", "P", 70_000, issuer="300", ticker="PENNY", accepted=acc("2026-10-06", "19:00:00"))]
    async with engine.sf() as s:
        s.add_all(rows)
        s.add(ScoutFiling(accession="E1", form_type="8-K", issuer_cik="500", ticker=None, filed_date="2026-10-04",
                          acceptance_ts=acc("2026-10-04", "16:05:00"), items="2.02,9.01", source="test",
                          status="header"))
        s.add(Signal(id=new_id(), source_name="discord-alpha", ticker="ABC", direction="long", action="open",
                     created_at=dt.datetime(2026, 10, 4, 12, 0, tzinfo=ET)))
        await s.commit()
    await ing.put_state(engine.sf, "datasets", {"2023q1": {"published": True}, "2023q2": {"published": True},
                                                "2023q3": {"published": True}, "2023q4": {"published": True},
                                                **{f"{y}q{q}": {"published": True} for y in (2024, 2025)
                                                   for q in (1, 2, 3, 4)},
                                                **{f"2026q{q}": {"published": True} for q in (1, 2, 3)}})
    engine.scout_service = svc
    return svc, now


async def test_daily_job_writes_candidates_gates_and_journal(scout, engine):
    svc, now = scout
    out = await svc.run_daily(now=now, ingest=False)
    assert out["s1"]["coverageStart"] == "2023-01-01"
    async with engine.sf() as s:
        cands = {c.ticker: c for c in (await s.execute(select(ScoutCandidate))).scalars().all()}
    abc = cands["ABC"]
    assert abc.kind == "s1_insider" and abc.entry_date == "2026-10-07"
    assert {i["insiderCik"] for i in abc.evidence["insiders"]} == {"1", "2"}       # routine #3 excluded
    assert abc.evidence["totalValue"] == 130_000
    assert abc.gates["spread"]["status"] == "unknown" and abc.gates["tipsMention"]["status"] == "fail"
    assert abc.gates["earningsInHold"]["status"] == "pass" and abc.gates["price"]["status"] == "pass"
    assert abc.status == "fail"                                                      # Tips mention
    penny = cands["PENNY"]
    assert penny.gates["price"]["status"] == "fail" and penny.gates["marketCap"]["status"] == "unknown"
    ern = cands["ERN"]
    assert ern.kind == "s2_earnings" and ern.evidence["day0"] == "2026-10-05" and ern.entry_date == "2026-10-07"
    assert ern.evidence["volumeRatio"] == 3.0 and "earningsInHold" not in ern.gates
    assert ern.status == "unknown"                                                   # spread pending at entry
    async with engine.sf() as s:
        kinds = (await s.execute(select(Event.type, func.count()).where(Event.type.like("Scout%"))
                                 .group_by(Event.type))).all()
    kinds = dict(kinds)
    assert kinds[ev.SCOUT_CANDIDATE_FOUND] == 3 and kinds[ev.SCOUT_GATE_RESULT] == 3 and kinds[ev.SCOUT_DAILY_RUN] == 1
    # idempotent: a second run adds nothing
    again = await svc.run_daily(now=now, ingest=False)
    assert again["s1"]["new"] == 0 and again["s2"]["new"] == 0


async def test_spread_recheck_after_entry(scout, engine):
    svc, now = scout
    await svc.run_daily(now=now, ingest=False)

    async def spread(sym, entry_date, now_):
        return 0.2, "test quotes"

    svc.entry_spread_pct = spread
    later = dt.datetime(2026, 10, 7, 10, 0, tzinfo=ET)
    res = await svc.recheck_spreads(later)
    assert res["updated"] == 3
    async with engine.sf() as s:
        ern = (await s.execute(select(ScoutCandidate).where(ScoutCandidate.ticker == "ERN"))).scalar_one()
    assert ern.gates["spread"]["status"] == "pass" and ern.status == "pass"


async def test_toggles_fully_disable_screens(scout, engine):
    svc, now = scout
    await engine.settings.set("techniques.scout.s1_insider_enabled", False)
    await engine.settings.set("techniques.scout.s2_earnings_enabled", False)
    out = await svc.run_daily(now=now)            # ingest=True but both screens off -> no EDGAR at all
    assert out["s1"] is None and out["s2"] is None and out["ingest"] == []
    async with engine.sf() as s:
        assert (await s.execute(select(func.count()).select_from(ScoutCandidate))).scalar_one() == 0
    await engine.settings.set("techniques.scout.s2_earnings_enabled", True)
    out = await svc.run_daily(now=now, ingest=False)
    assert out["s1"] is None and out["s2"]["new"] == 1


async def test_api_is_read_only(scout, engine):
    svc, now = scout
    await svc.run_daily(now=now, ingest=False)
    app = create_app(make_test_config(), engine)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/scout/candidates", params={"days": 3650})
        assert r.status_code == 200 and {x["ticker"] for x in r.json()} == {"ABC", "PENNY", "ERN"}
        assert all("gates" in x and "evidence" in x for x in r.json())
        st = (await c.get("/api/scout/status")).json()
        assert st["researchOnly"] and st["ingest"]["coverageStart"] == "2023-01-01"
        assert st["lastRun"]["s1"]["new"] == 2
        assert (await c.post("/api/scout/candidates")).status_code == 405
