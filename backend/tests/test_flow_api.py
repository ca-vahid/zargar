"""Flow UI backend (UI-PLAN F1): day summaries, the symbol story with journaled
context deliveries, and the server-composed brief. Reads are seeded directly —
no chain fetches, no LLM."""
from __future__ import annotations

import pytest

from zargar.domain import new_id
from zargar.engine import Engine
from zargar.models import Event, FlowRead
from zargar.techniques.flow.service import FlowService

from .conftest import make_test_config

DAYS = ["2026-09-02", "2026-09-03", "2026-09-04"]


def flag(contract="COIN260912C00300000", opt="call", prem=4_200_000.0, vol=9850, oi=7410,
         dte=8, strong=True, vol_oi=5.7):
    return {"contract": contract, "expiry": "2026-09-12", "optionType": opt, "strike": 300.0,
            "volume": vol, "openInterest": oi, "volOi": vol_oi, "mid": 4.2, "premium": prem,
            "otmPct": 4.0, "dte": dte, "strong": strong, "iv": 0.62}


def read_row(day, symbol, score, lean, flags, confirmed=(), repeats=None):
    return FlowRead(id=new_id(), day=day, symbol=symbol, score=float(score), lean=lean,
                    read={"flags": list(flags), "confirmed": list(confirmed),
                          "repeatHits": dict(repeats or {}),
                          "reasons": [f"{symbol} reason"], "aggregates": {}})


@pytest.fixture
async def flow_rig(fresh_db):
    eng = Engine(make_test_config(anthropic_api_key=""))
    await eng.start()
    eng.flow_service = FlowService(eng)
    rows = [
        # day 1: COIN + TSLA flagged
        read_row(DAYS[0], "COIN", 4, "bull", [flag(prem=1_800_000, vol=4200, oi=2300, vol_oi=1.8)]),
        read_row(DAYS[0], "TSLA", 3, "bear",
                 [flag(contract="TSLA260905P00320000", opt="put", prem=2_000_000, dte=3)]),
        read_row(DAYS[0], "KO", 0, "none", []),
        # day 2: COIN confirmed + repeat; TSLA quiet (streak breaks day 3)
        read_row(DAYS[1], "COIN", 6, "bull", [flag(prem=2_900_000, vol=7240, oi=4120, vol_oi=1.8)],
                 confirmed=[{**flag(), "oiDelta": 2470, "oiConfirmed": True}],
                 repeats={"COIN260912C00300000": 3}),
        read_row(DAYS[1], "NVDA", 3, "bull",
                 [flag(contract="NVDA260919C00190000", prem=3_200_000, dte=16)]),
        read_row(DAYS[1], "KO", 0, "none", []),
        # day 3: the big day — COIN 9 with confirm + repeat, NVDA confirmed, TSLA dying flag
        read_row(DAYS[2], "COIN", 9, "bull", [flag()],
                 confirmed=[{**flag(vol=7240, oi=4120), "oiDelta": 6140, "oiConfirmed": True}],
                 repeats={"COIN260912C00300000": 4}),
        read_row(DAYS[2], "NVDA", 7, "bull",
                 [flag(contract="NVDA260919C00190000", prem=8_400_000, vol=48213, oi=9870, dte=15, vol_oi=4.9)],
                 confirmed=[{"contract": "NVDA260919C00190000", "expiry": "2026-09-19",
                             "optionType": "call", "strike": 190.0, "volume": 18410,
                             "openInterest": 6230, "oiDelta": 9480, "oiConfirmed": True}]),
        read_row(DAYS[2], "TSLA", 5, "bear",
                 [flag(contract="TSLA260905P00320000", opt="put", prem=3_100_000, dte=1)]),
        read_row(DAYS[2], "KO", 0, "none", []),
    ]
    async with eng.sf() as session:
        session.add_all(rows)
        await session.commit()
    yield eng
    await eng.stop()


async def test_days_summary_math(flow_rig):
    eng = flow_rig
    days = await eng.flow_service.days(limit=5)
    assert [d["day"] for d in days] == [DAYS[2], DAYS[1], DAYS[0]]
    today = days[0]
    assert today["scanned"] == 4 and today["flagged"] == 3
    assert today["callPremium"] == 4_200_000 + 8_400_000
    assert today["putPremium"] == 3_100_000
    assert today["confirmed"] == 2
    # yesterday's NVDA + COIN flags both confirmed today -> churn 0
    assert today["churn"] == 0
    assert today["repeatStreaks"][0] == {"symbol": "COIN", "contract": "COIN260912C00300000", "days": 4}
    # day 2: only COIN's day-1 flag confirmed; TSLA's day-1 flag was not -> churn 1
    assert days[1]["churn"] == 1


async def test_story_reads_deliveries_and_universe(flow_rig):
    eng = flow_rig
    # a tip consumes the context -> the delivery is journaled and joins the story
    line = await eng.flow_service.context_for("COIN", consumer="tip", ref_id="sig-123")
    assert line and "COIN" in line
    story = await eng.flow_service.story("COIN")
    assert [r["day"] for r in story["reads"]] == DAYS          # oldest -> newest
    assert story["reads"][-1]["score"] == 9
    [d] = story["deliveries"]
    assert d["consumer"] == "tip" and d["refId"] == "sig-123" and d["line"] == line
    assert story["universe"]["inUniverse"] in (True, False)    # shape, not membership
    # the journal row is queryable by symbol (aggregate_id)
    from sqlalchemy import select
    async with eng.sf() as session:
        evs = (await session.execute(select(Event).where(
            Event.type == "FlowContextServed", Event.aggregate_id == "COIN"))).scalars().all()
    assert len(evs) == 1


async def test_context_without_consumer_never_journals(flow_rig):
    eng = flow_rig
    assert await eng.flow_service.context_for("COIN") is not None
    story = await eng.flow_service.story("COIN")
    assert story["deliveries"] == []


async def test_brief_sections(flow_rig):
    eng = flow_rig
    brief = await eng.flow_service.brief()
    assert brief["day"] == DAYS[2] and brief["prevDay"] == DAYS[1]
    s = brief["sections"]
    assert {c["symbol"] for c in s["confirmedOvernight"]} == {"COIN", "NVDA"}
    coin = next(c for c in s["confirmedOvernight"] if c["symbol"] == "COIN")
    assert coin["oiDelta"] == 6140 and coin["volume"] == 7240
    assert s["churn"] == []                                    # everything confirmed
    assert s["accumulation"][0]["symbol"] == "COIN" and s["accumulation"][0]["days"] == 4
    # TSLA's put wasn't flagged yesterday -> new today; and it dies tomorrow
    assert any(n["symbol"] == "TSLA" for n in s["newToday"])
    dying = {(d["symbol"], d["reason"].split(" ")[0]) for d in s["dying"]}
    assert ("TSLA", "expires") in dying
    assert len(s["contextLines"]) >= 2 and all(x["line"] for x in s["contextLines"])
    # an explicit earlier day works too
    brief2 = await eng.flow_service.brief(day=DAYS[1])
    assert brief2["day"] == DAYS[1] and brief2["prevDay"] == DAYS[0]


async def test_flow_read_becomes_a_tip(flow_rig):
    """'Send to Tips': the latest read enters the normal tip pipeline under the
    source 'flow-scan' — grounded, deduped, both books, armable like any tip."""
    from zargar.signals.service import attach_signal_layer

    from .conftest import wait_for

    eng = flow_rig
    await attach_signal_layer(eng)
    await eng.ensure_symbol("COIN")
    await wait_for(lambda: eng.quotes.get("COIN") is not None)

    out = await eng.flow_service.to_tip("COIN")     # bull; top call flag: 300C 2026-09-12, dte 8
    sig = out["signal"]
    assert sig["sourceName"] == "flow-scan"
    assert sig["direction"] == "long" and sig["instrument"] == "call"
    assert sig["strike"] == 300.0 and sig["expiry"] == "2026-09-12"
    assert sig["status"] in ("verified", "parked"), sig["verification"]
    # the delivery is journaled into the symbol's story
    story = await eng.flow_service.story("COIN")
    assert any(d["consumer"] == "tip" and d["refId"] == sig["id"] for d in story["deliveries"])
    # sending it again dedupes (a repeat mention, not a second tip)
    out2 = await eng.flow_service.to_tip("COIN")
    assert out2.get("duplicateOf") == sig["id"]
    # TSLA's latest flagged put expires in 1 day -> refused as expiry noise
    with pytest.raises(ValueError, match="expire within a day"):
        await eng.flow_service.to_tip("TSLA")
    # quiet symbols have nothing to send
    with pytest.raises(ValueError, match="no flagged"):
        await eng.flow_service.to_tip("KO")


def snap(day, sym, occ_sym, opt, strike, *, vol=5000, oi=1000, bid=2.0, ask=2.2,
         expiry="2026-09-18"):
    from zargar.models import OptionChainSnapshot
    return OptionChainSnapshot(date=day, occ=occ_sym, underlying=sym, expiry=expiry,
                               strike=strike, option_type=opt, volume=vol,
                               open_interest=oi, iv=0.4, bid=bid, ask=ask,
                               mid=(bid + ask) / 2, last=(bid + ask) / 2)


async def test_degraded_scan_never_overwrites(flow_rig):
    """The 2026-08-28 wipe: a cold-boot re-scan with no spot must keep the
    existing scored read, not replace it with a flag-less one. A symbol with
    no prior read still gets its (degraded) read — better than nothing."""
    eng = flow_rig
    eng.options = None    # offline: no live CBOE fallback in tests
    day = DAYS[2]
    async with eng.sf() as session:
        # COIN already has a good day-3 read (score 9). Calls-only snapshots:
        # parity has no put side -> spot stays 0 -> degraded path.
        session.add_all([
            snap(day, "COIN", "COIN260918C00300000", "call", 300.0),
            snap(day, "ZETA", "ZETA260918C00030000", "call", 30.0),
        ])
        await session.commit()
    out = await eng.flow_service.scan(day=day, symbols=["COIN", "ZETA"])
    assert out["noSpot"] == 2 and out["keptExisting"] == 1
    story = await eng.flow_service.story("COIN")
    kept = story["reads"][-1]
    assert kept["score"] == 9 and kept["flags"], "good read was overwritten"
    zeta = await eng.flow_service._read_row_for("ZETA", day)
    assert zeta is not None                       # no prior read -> persisted


async def test_scan_uses_parity_spot_when_quotes_cold(flow_rig):
    """With no quote at all, spot comes from put-call parity on the snapshot
    chain — the scan still flags (the 08-28 failure never recurs silently)."""
    eng = flow_rig
    eng.options = None    # offline: no live CBOE fallback in tests
    day = DAYS[2]
    async with eng.sf() as session:
        session.add_all([
            snap(day, "ZETA", "ZETA260918C00031000", "call", 31.0, vol=9000, oi=1500,
                 bid=1.9, ask=2.1),
            snap(day, "ZETA", "ZETA260918P00031000", "put", 31.0, vol=100, oi=500,
                 bid=3.9, ask=4.1),   # parity: spot ≈ 31 + 2.0 − 4.0 = 29
        ])
        await session.commit()
    assert eng.quotes.get("ZETA") is None
    out = await eng.flow_service.scan(day=day, symbols=["ZETA"])
    assert out["noSpot"] == 0
    read = await eng.flow_service._read_row_for("ZETA", day)
    assert read.read["spot"] == 29.0
    [flag] = read.read["flags"]                   # 31C is ~6.9% OTM of 29 -> flagged
    assert flag["contract"] == "ZETA260918C00031000"


async def test_repair_rescans_degraded_day(flow_rig):
    """Boot self-healing: a latest day whose reads carry the degraded signature
    (scores from OI confirms, zero flags, no spot) is re-scanned when its
    snapshots hold volume."""
    from zargar.models import FlowRead
    from zargar.domain import new_id
    eng = flow_rig
    eng.options = None    # offline: no live CBOE fallback in tests
    day = "2026-09-08"                             # newer than the fixture days
    async with eng.sf() as session:
        session.add(FlowRead(id=new_id(), day=day, symbol="ZETA", score=4.0, lean="none",
                             read={"flags": [], "confirmed": [{"contract": "X"}],
                                   "repeatHits": {}, "reasons": ["confirm only"],
                                   "aggregates": {}, "spot": None}))
        session.add_all([
            snap(day, "ZETA", "ZETA260918C00031000", "call", 31.0, vol=9000, oi=1500,
                 bid=1.9, ask=2.1, expiry="2026-09-18"),
            snap(day, "ZETA", "ZETA260918P00031000", "put", 31.0, vol=100, oi=500,
                 bid=3.9, ask=4.1, expiry="2026-09-18"),
        ])
        await session.commit()
    await eng.flow_service._repair_last_scan(delay=0)
    read = await eng.flow_service._read_row_for("ZETA", day)
    assert read.read["flags"], "repair did not rebuild the degraded day"
    assert read.read["spot"] == 29.0


async def test_scheduler_once_per_day_survives_restart(flow_rig):
    """Job hydration: a ScheduledJobRan journaled today (by the process that
    just exited) stops the rebooted scheduler from re-running the job."""
    import zargar.scheduler as sch
    eng = flow_rig
    ran = []

    async def job():
        ran.append(1)

    await eng.journal.append(sch.SCHEDULED_JOB_RAN, {
        "job": "t_hydrate", "date": __import__("datetime").datetime.now(sch.ET).strftime("%Y-%m-%d"),
        "seconds": 1.0})
    eng.scheduler.register("t_hydrate", "00:00", job, weekdays_only=False)
    await eng.scheduler._tick()
    assert ran == []                               # journal says it already ran today
    # a job with no history still runs
    eng.scheduler.register("t_fresh", "00:00", job, weekdays_only=False)
    await eng.scheduler._tick()
    assert ran == [1]


async def test_universe_flow_layer(flow_rig):
    """score >= 5 on 2 of the last 3 scan days joins the universe as 'flow'."""
    eng = flow_rig
    layer = await eng.flow_service.universe_layer()
    assert layer == ["COIN"]                     # 6 and 9; NVDA/TSLA hit 5+ only once
    from zargar.technique.universe import resolve
    r = resolve(core=["SPY"], extra=[], exclude=[], auto=[], flow=layer)
    assert r["provenance"]["COIN"] == "flow" and r["counts"]["flow"] == 1
    # exclusion still wins over the flow layer
    r2 = resolve(core=["SPY"], extra=[], exclude=["COIN"], auto=[], flow=layer)
    assert "COIN" not in r2["symbols"]


async def test_em_analyze_carries_flow_context(flow_rig, monkeypatch):
    """analyze() stamps the flow line into run provenance + journals the delivery
    (plan mode without vision: fully deterministic, no LLM)."""
    eng = flow_rig
    import zargar.technique.service as service_mod
    from zargar.technique.service import attach_technique_layer

    from .test_technique_walkforward import continuous_market, weekdays

    market = continuous_market(weekdays(6), lo=100.0, hi=104.0)

    async def fake_gather(req_):
        out = {tf: [b for b in (market.get(tf) or []) if req_.as_of_ms is None or b.ts <= req_.as_of_ms]
               for tf in req_.timeframes}
        return {k: v for k, v in out.items() if v}, ["synthetic bars"]

    monkeypatch.setattr(service_mod, "gather_bars", fake_gather)
    await attach_technique_layer(eng)
    # seed a COIN read is already there; run a deterministic plan build for COIN
    from zargar.technique.rulebook import session_bounds
    close_ts = session_bounds(weekdays(6)[3].isoformat())[1]
    # market fixture symbols are TEST-agnostic; analyze COIN with synthetic bars
    run = await eng.technique.analyze("COIN", as_of_ms=close_ts, wait=True, with_vision=False)
    assert run["status"] == "done", run.get("error")
    assert "flow" in (run["config"].get("flowContext") or "").lower() or \
        (run["config"].get("flowContext") or "").startswith("Options flow")
    story = await eng.flow_service.story("COIN")
    em = [d for d in story["deliveries"] if d["consumer"] == "em"]
    assert em and em[0]["refId"] == run["id"]
    await eng.technique.stop()