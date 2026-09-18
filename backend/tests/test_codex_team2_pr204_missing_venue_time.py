"""Provider-boundary probes: receipt time must not become venue time."""
import datetime as dt
from types import SimpleNamespace
import pytest
from zargar.brokers.alpaca import AlpacaQuoteFeed
from .test_codex_team2_data_eod import rig, ms


@pytest.mark.parametrize('kind', ['t', 'q'])
@pytest.mark.parametrize('timestamp_present', [False, True])
def test_missing_venue_time_stays_unknown_through_adapter(monkeypatch, kind, timestamp_present):
    import zargar.brokers.alpaca as feed_module
    import zargar.techniques.team2.runner as runner_module
    now = ms(13, 10)
    monkeypatch.setattr(feed_module, 'now_ms', lambda: now)
    monkeypatch.setattr(runner_module.time, 'time', lambda: now / 1000)
    runner, ap = rig()
    emitted = []
    feed = AlpacaQuoteFeed(emitted.append, '', '')
    message = {'T': kind, 'S': ap.symbol, 'p': 101.1, 's': 100,
               'bp': 101.1, 'ap': 101.12, 'bs': 1, 'as': 1}
    if timestamp_present:
        message['t'] = dt.datetime.fromtimestamp(now / 1000, dt.timezone.utc).isoformat()
    feed.handle(message)
    runner.engine.quotes = SimpleNamespace(get=lambda _: emitted[-1] if emitted else None)
    px, _ = runner._fresh_underlying(ap)
    if timestamp_present:
        assert px is not None
    else:
        assert px is None, 'adapter substituted receipt time for missing venue time'
