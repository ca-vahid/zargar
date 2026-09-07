"""Collection boundaries: real provider shape, explicit date mapping, no invented facts."""
import datetime as dt

import pytest

from zargar.domain import Bar
from zargar.marketstructure.sessions import session_bounds
from zargar.techniques.options_cartel.collect import CollectInput, collect_inputs, normalize_daily

from .test_options_cartel_screen import series


def provider():
    history = series()
    at = history[-1].closes_at
    calls = []

    async def fetch(symbol, tf, start, end, *, client):
        calls.append((symbol, tf, start, end, client))
        if tf == "1d":
            return [Bar(symbol, tf, session_bounds(b.session.isoformat())[0], b.open, b.high, b.low,
                        b.close, b.volume) for b in history]
        opens, _ = session_bounds(history[-1].session.isoformat())
        return [Bar(symbol, "1m", opens, 100, 101, 99, 100, 1000)]
    return fetch, at, calls


async def test_collection_populates_prices_but_does_not_fabricate_fundamentals():
    fetch, at, calls = provider()
    research, provenance = await collect_inputs(CollectInput(symbol="test", as_of_ms=at), fetch=fetch, now_ms=at)
    assert research.facts.symbol == "TEST" and research.facts.market_cap is None
    assert len(research.history) == 80 and len(research.minute_history) == 1
    assert set(research.indices) == {"SPY", "QQQ"}
    assert provenance["warnings"] and provenance["historicalMetadataProvided"] is False
    assert all(c[-1].is_closed for c in calls)
    assert all(c[3] == at for c in calls)


async def test_collection_accepts_video_profile_and_preserves_its_relative_volume_rule():
    fetch, at, _ = provider()
    research, _ = await collect_inputs(CollectInput(symbol="TEST", profile="september_2026_video"),
                                       fetch=fetch, now_ms=at)
    assert research.rules.profile == "september_2026_video"
    assert research.rules.min_relative_volume == 1 and research.rules.min_adr_pct == 2


async def test_missing_index_and_intraday_failures_remain_visible():
    fetch, at, _ = provider()

    async def degraded(symbol, tf, start, end, *, client):
        if symbol == "QQQ" or tf == "1m":
            raise RuntimeError("test outage")
        return await fetch(symbol, tf, start, end, client=client)
    research, provenance = await collect_inputs(CollectInput(symbol="TEST"), fetch=degraded, now_ms=at)
    assert research.indices["QQQ"] == [] and research.minute_history == []
    assert len(provenance["warnings"]) == 3


async def test_symbol_daily_failure_is_not_silently_replaced_with_synthetic_bars():
    _, at, _ = provider()

    async def failed(*args, **kwargs):
        raise RuntimeError("test outage")
    with pytest.raises(ValueError, match="daily history unavailable"):
        await collect_inputs(CollectInput(symbol="TEST"), fetch=failed, now_ms=at)


async def test_future_request_and_mismatched_metadata_fail_before_io():
    fetch, at, calls = provider()
    with pytest.raises(ValueError, match="future"):
        await collect_inputs(CollectInput(symbol="TEST", as_of_ms=at+1), fetch=fetch, now_ms=at)
    with pytest.raises(ValueError, match="metadata symbol"):
        await collect_inputs(CollectInput(symbol="TEST", facts={"symbol": "OTHER", "observedAt": at,
                                                                "source": "test"}), fetch=fetch, now_ms=at)
    assert calls == []


def test_daily_mapping_rejects_ambiguous_utc_midnight_and_excludes_unfinished_session():
    day = dt.date(2026, 5, 5)
    opens, closes = session_bounds(day.isoformat())
    bar = Bar("TEST", "1d", opens, 100, 101, 99, 100, 1000)
    assert normalize_daily([bar], "TEST", closes-1) == []
    assert normalize_daily([bar], "TEST", closes)[0].session == day
    bar.ts = int(dt.datetime(2026, 5, 5, tzinfo=dt.UTC).timestamp()*1000)
    with pytest.raises(ValueError, match="timestamp"):
        normalize_daily([bar], "TEST", closes)


async def test_index_symbol_does_not_generate_duplicate_provider_requests():
    fetch, at, calls = provider()
    research, _ = await collect_inputs(CollectInput(symbol="SPY"), fetch=fetch, now_ms=at)
    assert research.history == research.indices["SPY"]
    assert [(s, tf) for s, tf, *_ in calls].count(("SPY", "1d")) == 1


async def test_image_profile_survives_collection_boundary():
    fetch, at, _ = provider()
    research, _ = await collect_inputs(CollectInput(symbol="TEST", profile="june_2026_image"), fetch=fetch, now_ms=at)
    assert research.rules.min_adr_pct == 2 and research.rules.volume_basis == "average"
    assert research.rules.volume_period == 10
