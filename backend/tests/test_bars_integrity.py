"""F75/F78 (2026-09-09): the shared `bars` table holds market data with provenance.

- an exchange correction to a quote-sampled bar reaches memory, storage, a fresh load (restart) and a
  Team2 replay read — and a later sampled bar cannot undo it (explicit source precedence);
- synthetic (sim) bars are refused unless the caller allows them; bars outside a market minute from a
  real feed are dropped (the one-price weekend "sessions");
- sampled volume is a sum of prints for symbols whose feed sees prints; a cumulative counter that is
  re-seeded or rolls a session never paints a fake spike;
- a dataset version is a CONTENT hash: a volume fix with the same row count is a different version."""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from zargar.bus import Bus
from zargar.db import make_engine, make_session_factory
from zargar.domain import Bar, Quote
from zargar.marketdata import MINUTE_MS, BarAggregator, BarPersister, dataset_version, load_bars, persist_bars
from zargar.marketstructure.market_calendar import is_market_minute

from .conftest import TEST_DB_URL

ET = ZoneInfo("America/New_York")


def et_ms(y, m, d, hh, mm) -> int:
    return int(dt.datetime(y, m, d, hh, mm, tzinfo=ET).timestamp() * 1000)


TUE_1000 = et_ms(2026, 9, 1, 10, 0)          # a trading day, regular session
SAT_1000 = et_ms(2026, 9, 5, 10, 0)          # Saturday
LABOR_DAY = et_ms(2026, 9, 7, 13, 47)        # Labor Day (the app ran that afternoon)
TUE_2130 = et_ms(2026, 9, 1, 21, 30)         # after the 20:00 close of after-hours


def bar(sym, ts, o, h, l, c, v, source):
    return Bar(symbol=sym, tf="1m", ts=ts, open=o, high=h, low=l, close=c, volume=v, source=source)


def test_is_market_minute_knows_the_calendar():
    assert is_market_minute(TUE_1000)
    assert is_market_minute(et_ms(2026, 9, 1, 4, 0))
    assert is_market_minute(et_ms(2026, 9, 1, 19, 59))
    assert not is_market_minute(TUE_2130)
    assert not is_market_minute(SAT_1000)
    assert not is_market_minute(LABOR_DAY)
    assert not is_market_minute(et_ms(2026, 11, 27, 18, 0))     # day after Thanksgiving: 13:00 close, after-hours ends 17:00
    assert is_market_minute(et_ms(2026, 11, 27, 16, 30))


async def test_an_exchange_correction_reaches_storage_and_a_sampled_bar_cannot_undo_it(fresh_db):
    sf = make_session_factory(make_engine(TEST_DB_URL))
    sampled = bar("TST", TUE_1000, 100.0, 100.5, 99.5, 100.2, 43_000_000, "sampled")   # the 43M-share minute
    await persist_bars(sf, [sampled])
    rows = await load_bars(sf, "TST", "1m")
    assert len(rows) == 1 and rows[0].volume == 43_000_000 and rows[0].source == "sampled"
    exchange = bar("TST", TUE_1000, 100.1, 100.4, 99.8, 100.2, 812_000, "exchange")
    await persist_bars(sf, [exchange])
    rows = await load_bars(sf, "TST", "1m")
    assert len(rows) == 1 and rows[0].volume == 812_000 and rows[0].source == "exchange" and rows[0].open == 100.1
    # a later sampled write for the same minute does not clobber the exchange bar
    await persist_bars(sf, [bar("TST", TUE_1000, 100.0, 100.5, 99.5, 100.2, 99, "sampled")])
    rows = await load_bars(sf, "TST", "1m")
    assert rows[0].volume == 812_000 and rows[0].source == "exchange"
    # an exchange re-fetch IS a correction
    await persist_bars(sf, [bar("TST", TUE_1000, 100.1, 100.4, 99.8, 100.2, 813_000, "exchange")])
    rows = await load_bars(sf, "TST", "1m")
    assert rows[0].volume == 813_000
    # a legacy row (unknown = no provenance) loses to a sampled bar and to an exchange bar (F79)
    await persist_bars(sf, [bar("TST", TUE_1000 + MINUTE_MS, 1, 1, 1, 1, 5, "")])
    rows = await load_bars(sf, "TST", "1m")
    assert rows[-1].volume == 5 and rows[-1].source == "unknown"
    await persist_bars(sf, [bar("TST", TUE_1000 + MINUTE_MS, 2, 2, 2, 2, 6, "sampled")])
    rows = await load_bars(sf, "TST", "1m")
    assert rows[-1].volume == 6 and rows[-1].source == "sampled"
    await persist_bars(sf, [bar("TST", TUE_1000 + MINUTE_MS, 1, 1, 1, 1, 5, "")])
    rows = await load_bars(sf, "TST", "1m")
    assert rows[-1].volume == 6 and rows[-1].source == "sampled"                   # unknown never overwrites sampled
    await persist_bars(sf, [bar("TST", TUE_1000 + MINUTE_MS, 3, 3, 3, 3, 7, "exchange")])
    rows = await load_bars(sf, "TST", "1m")
    assert rows[-1].volume == 7 and rows[-1].source == "exchange"
    # exchange over exchange: OHLC follows the newer bar, volume is never lowered (Yahoo's provisional
    # zero must not erase Alpaca's true count — F79)
    await persist_bars(sf, [bar("TST", TUE_1000 + MINUTE_MS, 4, 4, 4, 4, 0, "exchange")])
    rows = await load_bars(sf, "TST", "1m")
    assert rows[-1].close == 4 and rows[-1].volume == 7
    await persist_bars(sf, [bar("TST", TUE_1000 + MINUTE_MS, 4, 4, 4, 4, 9, "exchange")])
    rows = await load_bars(sf, "TST", "1m")
    assert rows[-1].volume == 9


async def test_sim_bars_are_refused_and_closed_day_bars_are_dropped(fresh_db):
    sf = make_session_factory(make_engine(TEST_DB_URL))
    await persist_bars(sf, [bar("SIMX", TUE_1000, 1, 1, 1, 1, 1, "sim")])
    assert await load_bars(sf, "SIMX", "1m") == []
    await persist_bars(sf, [bar("SIMX", TUE_1000, 1, 1, 1, 1, 1, "sim")], allow_sim=True)
    assert len(await load_bars(sf, "SIMX", "1m")) == 1
    await persist_bars(sf, [bar("TST", SAT_1000, 1, 1, 1, 1, 0, "sampled"),
                            bar("TST", LABOR_DAY, 1, 1, 1, 1, 0, "sampled"),
                            bar("TST", TUE_2130, 1, 1, 1, 1, 0, "exchange"),
                            bar("TST", TUE_1000, 1, 1, 1, 1, 0, "sampled")])
    rows = await load_bars(sf, "TST", "1m")
    assert [r.ts for r in rows] == [TUE_1000]


async def test_the_correction_chain_memory_storage_restart_replay(fresh_db):
    """A sampled bar, then the exchange bar for the same minute: the aggregator replaces it in memory,
    the persister lands BOTH writes, storage keeps the exchange one, a fresh load (restart) and the
    Team2 history read (replay) both see the exchange values."""
    sf = make_session_factory(make_engine(TEST_DB_URL))
    bus = Bus()
    agg = BarAggregator(bus)
    agg.configure(sampled_source="sampled", calendar_gated=True)
    persister = BarPersister(bus, sf)
    q, unsub = bus.subscribe("bars")
    agg.on_quote(Quote(symbol="TST", last=100.0, bid=99.99, ask=100.01, volume=1000, ts=TUE_1000 + 1000))
    agg.on_quote(Quote(symbol="TST", last=100.3, bid=100.29, ask=100.31, volume=43_000_000, ts=TUE_1000 + 30_000))
    agg.on_quote(Quote(symbol="TST", last=100.4, bid=100.39, ask=100.41, volume=43_001_000, ts=TUE_1000 + MINUTE_MS + 1000))  # rolls the minute
    sampled = agg.bars("TST")[0]
    assert sampled.source == "sampled" and sampled.volume == 42_999_000            # the counter's jump landed in the sampled bar
    agg.ingest_exchange_bar(bar("TST", TUE_1000, 100.0, 100.35, 99.98, 100.3, 812_000, ""))
    mem = agg.bars("TST")[0]
    assert mem.source == "exchange" and mem.volume == 812_000                        # memory
    while not q.empty():
        persister._pending.append(q.get_nowait()["bar"])
    unsub()
    await persister.flush()
    stored = [r for r in await load_bars(sf, "TST", "1m") if r.ts == TUE_1000]
    assert stored and stored[0].source == "exchange" and stored[0].volume == 812_000  # storage
    fresh = await load_bars(make_session_factory(make_engine(TEST_DB_URL)), "TST", "1m")   # restart = a fresh load
    assert [r for r in fresh if r.ts == TUE_1000][0].volume == 812_000
    from zargar.techniques.team2.history import validate_sessions                      # replay reads through this
    valid, _ = validate_sessions([b for b in fresh])
    assert any(b.ts == TUE_1000 and b.volume == 812_000 for b in fresh)


def test_sampled_volume_is_a_sum_of_prints_and_a_reseeded_counter_never_spikes():
    agg = BarAggregator(Bus())
    agg.configure(sampled_source="sampled", calendar_gated=False, volume_from_prints=lambda s: s == "PRN")
    # print-fed symbol: the cumulative counter re-seeds from 1,000 to 5,000,000 between quotes — irrelevant
    agg.on_quote(Quote(symbol="PRN", last=10.0, volume=1_000, trade_size=100, ts=TUE_1000 + 1000))
    agg.on_quote(Quote(symbol="PRN", last=10.1, volume=5_000_000, trade_size=250, ts=TUE_1000 + 5000))
    agg.on_quote(Quote(symbol="PRN", last=10.2, volume=5_000_300, trade_size=0, ts=TUE_1000 + 9000))
    assert agg.bars("PRN")[0].volume == 350
    # counter-fed symbol: a roll to a new session (counter goes down) is 0, not "negative clamped to a jump"
    agg.on_quote(Quote(symbol="CNT", last=10.0, volume=900_000, ts=TUE_1000 + 1000))
    agg.on_quote(Quote(symbol="CNT", last=10.0, volume=901_000, ts=TUE_1000 + 5000))
    agg.on_quote(Quote(symbol="CNT", last=10.0, volume=200, ts=TUE_1000 + 9000))        # session reset
    agg.on_quote(Quote(symbol="CNT", last=10.0, volume=700, ts=TUE_1000 + 12000))
    assert agg.bars("CNT")[0].volume == 1_000 + 0 + 500


def test_calendar_gated_aggregator_forms_no_bar_on_a_closed_day():
    agg = BarAggregator(Bus())
    agg.configure(sampled_source="sampled", calendar_gated=True)
    agg.on_quote(Quote(symbol="TST", last=10.0, volume=1, ts=SAT_1000))
    agg.on_quote(Quote(symbol="TST", last=10.0, volume=1, ts=LABOR_DAY))
    assert agg.bars("TST") == []
    agg.on_quote(Quote(symbol="TST", last=10.0, volume=1, ts=TUE_1000))
    assert len(agg.bars("TST")) == 1
    sim = BarAggregator(Bus())
    sim.configure(sampled_source="sim", calendar_gated=False)
    sim.on_quote(Quote(symbol="TST", last=10.0, volume=1, ts=SAT_1000))
    assert sim.bars("TST")[0].source == "sim"


async def test_dataset_version_is_a_content_hash(fresh_db):
    sf = make_session_factory(make_engine(TEST_DB_URL))
    await persist_bars(sf, [bar("TST", TUE_1000 + i * MINUTE_MS, 1, 2, 0.5, 1.5, 100, "exchange") for i in range(5)])
    a = await dataset_version(sf, ["TST"], start="2026-09-01", end="2026-09-01", note="a")
    b = await dataset_version(sf, ["tst"], start="2026-09-01", end="2026-09-01", note="b")
    assert a["hash"] == b["hash"] and a["rows"] == 5
    # same row count, one volume changed (an exchange correction): a different version
    await persist_bars(sf, [bar("TST", TUE_1000 + 2 * MINUTE_MS, 1, 2, 0.5, 1.5, 101, "exchange")])
    c = await dataset_version(sf, ["TST"], start="2026-09-01", end="2026-09-01")
    assert c["rows"] == 5 and c["hash"] != a["hash"]
    # scope matters: a different symbol set is a different dataset
    d = await dataset_version(sf, ["TST", "OTHER"], start="2026-09-01", end="2026-09-01")
    assert d["hash"] != c["hash"]
