"""The Codex review's independent regressions against a3885a9 (2026-09-09; findings R1-R10 in
docs/techniques/team2/notes/research/2026-09-09-pr33-45-review.md), adopted verbatim into the suite so the
contracts they pin stay closed. No runtime/network access (the provider test uses httpx.MockTransport)."""
import datetime as dt
from types import SimpleNamespace
from unittest.mock import AsyncMock

from zargar.bus import Bus
from zargar.db import make_engine, make_session_factory
from zargar.domain import Bar
from zargar.marketdata import BarAggregator, load_bars, persist_bars
from zargar.ops import compare_states, readiness_from_state, restart_state
from zargar.techniques.team2.rules import Team2Rules
from zargar.techniques.team2.service import Team2Service
from .conftest import TEST_DB_URL
from .test_bars_integrity import TUE_1000, MINUTE_MS, bar
from .test_team2_history import _session, wave


def test_recovery_inserts_a_missing_minute_between_existing_bars():
    agg = BarAggregator(Bus())
    mk = lambda ts: bar("SPY", ts, 100, 101, 99, 100, 100, "exchange")
    agg.seed("SPY", [mk(TUE_1000), mk(TUE_1000 + 2 * MINUTE_MS)])
    agg.ingest_exchange_bar(mk(TUE_1000 + MINUTE_MS))
    got = [b.ts for b in agg.bars("SPY", include_forming=False)]
    assert got == [TUE_1000 + i * MINUTE_MS for i in range(3)], got


async def test_exchange_volume_does_not_depend_on_flush_grouping(fresh_db):
    eng = make_engine(TEST_DB_URL)
    sf = make_session_factory(eng)
    try:
        mk = lambda sym, v: bar(sym, TUE_1000, 100, 101, 99, 100, v, "exchange")
        await persist_bars(sf, [mk("BATCH", 100), mk("BATCH", 0)])
        await persist_bars(sf, [mk("SEPARATE", 100)])
        await persist_bars(sf, [mk("SEPARATE", 0)])
        a = (await load_bars(sf, "BATCH"))[0].volume
        b = (await load_bars(sf, "SEPARATE"))[0].volume
        assert a == b == 100, {"same_flush": a, "separate_flushes": b}
    finally:
        await eng.dispose()


async def test_exchange_memory_and_database_agree_after_lesser_refetch(fresh_db):
    eng = make_engine(TEST_DB_URL)
    sf = make_session_factory(eng)
    agg = BarAggregator(Bus())
    try:
        for volume in (100, 0):
            b = bar("SPY", TUE_1000, 100, 101, 99, 100, volume, "exchange")
            agg.ingest_exchange_bar(b)
            await persist_bars(sf, [b])
        memory = agg.bars("SPY", include_forming=False)[0].volume
        stored = (await load_bars(sf, "SPY"))[0].volume
        assert memory == stored, {"memory": memory, "stored": stored}
    finally:
        await eng.dispose()


async def test_sweep_validates_warmup_not_only_scored_dates(monkeypatch):
    import zargar.marketdata as md
    import zargar.techniques.team2.service as module
    source = _session(dt.date(2026, 9, 4), wave(100, 2))
    source += _session(dt.date(2026, 9, 5), None, flat=101)
    source += _session(dt.date(2026, 9, 8), wave(100, 2))
    service = Team2Service(SimpleNamespace(settings={}, sf=None), None)
    service.bars_1m = AsyncMock(return_value=source)
    monkeypatch.setattr(md, "dataset_version", AsyncMock(return_value={"hash": "review-fixture", "rows": len(source)}))
    captured = []
    def simulate(plan, today, rules, **kwargs):
        captured.extend(kwargs["warmup_1m"])
        return SimpleNamespace(to_dict=lambda: {"trades": [], "summary": {}, "bias": {}, "setups": []})
    monkeypatch.setattr(module, "simulate_session", simulate)
    await service.sweep("2026-09-08", "2026-09-08", symbols=["SPY"], sigma=0.2)
    from zargar.marketstructure.sessions import session_date
    used = {session_date(b.ts) for b in captured}
    assert used == {"2026-09-04"}, used


async def test_empty_history_returns_no_plan_instead_of_crashing():
    service = Team2Service(SimpleNamespace(settings={}), None)
    service._history_provenance = AsyncMock(return_value={})
    result = await service.mint_plan_run("SPY", "2026-09-09", rules=Team2Rules(), fifteen=[])
    assert result is None


async def test_restart_refuses_when_order_inventory_is_unavailable():
    engine = SimpleNamespace(plan_runners={}, orders=SimpleNamespace(list_orders=AsyncMock(side_effect=RuntimeError("DB unavailable"))))
    state = await restart_state(engine)
    result = readiness_from_state(state)
    assert result["safe"] is False, result


async def test_restart_refuses_a_fire_awaiting_contract_selection():
    trade = SimpleNamespace(status="fired", trigger_id="first", pending_exit_qty=0)
    plan = SimpleNamespace(status="armed", run_id="run1", symbol="SPY", config=SimpleNamespace(mode="auto"),
                           trades={"first": trade}, fire_tasks={"first": object()})
    engine = SimpleNamespace(plan_runners={"team2": SimpleNamespace(_armed={"run1": plan})})
    result = readiness_from_state(await restart_state(engine))
    assert result["safe"] is False, result


def test_restore_detects_missing_managed_position():
    result = compare_states({"managedOpen": 1}, {"managedOpen": 0})
    assert result["ok"] is False, result


async def test_quarantine_does_not_delete_a_row_corrected_after_selection(fresh_db):
    from sqlalchemy import select
    from zargar.models import BarRow, BarQuarantineRow
    from zargar.tools.bars_repair import select_quarantine, apply_quarantine
    eng = make_engine(TEST_DB_URL)
    sf = make_session_factory(eng)
    try:
        await persist_bars(sf, [bar("SPY", TUE_1000, 100, 101, 99, 100, 100, "sampled")])
        selected = await select_quarantine(sf, reason="sim_feed", symbols=["SPY"],
                                           date_from="2026-09-01", date_to="2026-09-01")
        # Deterministic interleaving: a venue correction arrives after selection, before deletion.
        await persist_bars(sf, [bar("SPY", TUE_1000, 101, 102, 100, 101, 250, "exchange")])
        await apply_quarantine(sf, selected, reason="sim_feed")
        async with sf() as session:
            live = list((await session.execute(select(BarRow))).scalars())
            archived = list((await session.execute(select(BarQuarantineRow))).scalars())
        assert any(r.volume == 250 and r.close == 101 for r in live + archived), {
            "live": [(r.close, r.volume) for r in live],
            "quarantine": [(r.close, r.volume) for r in archived],
        }
    finally:
        await eng.dispose()


async def test_backfill_does_not_zero_history_after_alpaca_falls_back(fresh_db, monkeypatch):
    import httpx
    import zargar.marketstructure.history as history
    import zargar.tools.bars_repair as repair
    eng = make_engine(TEST_DB_URL)
    sf = make_session_factory(eng)
    requested = []
    def serve(request):
        requested.append(request.url.host)
        if request.url.host == "data.alpaca.markets":
            return httpx.Response(503, json={"error": "temporary provider failure"})
        return httpx.Response(200, json={"chart": {"result": [{
            "timestamp": [TUE_1000 // 1000, (TUE_1000 + 2 * MINUTE_MS) // 1000],
            "indicators": {"quote": [{"open": [100, 100], "high": [101, 101],
                                       "low": [99, 99], "close": [100, 100], "volume": [None, None]}]},
        }]}})
    client = httpx.AsyncClient(transport=httpx.MockTransport(serve))
    monkeypatch.setattr(history, "_client_shared", lambda: client)
    monkeypatch.setattr(history, "_ALPACA", {"key": "", "secret": ""})
    monkeypatch.setattr(history, "_cache", {})
    monkeypatch.setattr(repair, "get_config", lambda: SimpleNamespace(alpaca_key_id="fixture", alpaca_secret="fixture"))
    try:
        await persist_bars(sf, [bar("SPY", TUE_1000 + MINUTE_MS, 100, 101, 99, 100, 500, "sampled")])
        result = await repair.cmd_backfill(sf, symbols=["SPY"], all_symbols=False,
                                          date_from="2026-09-01", date_to="2026-09-01", pace=0)
        assert "data.alpaca.markets" in requested and len(requested) > 1, requested
        stored = await load_bars(sf, "SPY")
        middle = next(r for r in stored if r.ts == TUE_1000 + MINUTE_MS)
        assert middle.volume == 500, {"middle_volume": middle.volume, "result": result}
    finally:
        await client.aclose()
        await eng.dispose()


def test_seeded_yahoo_counter_does_not_become_one_minute_volume():
    from zargar.domain import Quote
    agg = BarAggregator(Bus())
    agg.configure(sampled_source="sampled", calendar_gated=True)
    agg.seed("SPY", [bar("SPY", TUE_1000 - MINUTE_MS, 100, 101, 99, 100, 1000, "exchange")])
    agg.on_quote(Quote(symbol="SPY", ts=TUE_1000, last=100, volume=10_000_000))
    assert agg.bars("SPY")[-1].volume == 0, agg.bars("SPY")[-1].volume


async def test_sweep_hash_identifies_the_bars_actually_consumed(fresh_db, monkeypatch):
    import zargar.techniques.team2.service as module
    from zargar.marketdata import dataset_version
    eng = make_engine(TEST_DB_URL)
    sf = make_session_factory(eng)
    rows = _session(dt.date(2026, 9, 4), wave(100, 2)) + _session(dt.date(2026, 9, 8), wave(100, 2))
    for b in rows:
        b.symbol, b.source = "SPY", "exchange"
    try:
        await persist_bars(sf, rows)
        service = Team2Service(SimpleNamespace(settings={}, sf=sf), None)
        async def load_after_correction(symbol, **kwargs):
            # A venue correction arrives between hash collection and the sweep's independent read.
            old = rows[0]
            await persist_bars(sf, [Bar(symbol="SPY", tf="1m", ts=old.ts, open=old.open, high=old.high,
                                        low=old.low, close=old.close, volume=old.volume + 1, source="exchange")])
            return await load_bars(sf, symbol, limit=60000)
        service.bars_1m = load_after_correction
        monkeypatch.setattr(module, "simulate_session", lambda *a, **kw: SimpleNamespace(
            to_dict=lambda: {"trades": [], "summary": {}, "bias": {}, "setups": []}))
        result = await service.sweep("2026-09-08", "2026-09-08", symbols=["SPY"], sigma=0.2)
        actual = await dataset_version(sf, ["SPY"], start=None, end="2026-09-08", record=False)
        assert result["datasetVersion"] == actual["hash"], {
            "claimed": result["datasetVersion"], "consumed": actual["hash"],
        }
    finally:
        await eng.dispose()
