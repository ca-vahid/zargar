"""Synthetic source-age probes; no network, runtime DB or orders."""
from types import SimpleNamespace
import datetime as dt
import pytest
from zargar.brokers.alpaca import AlpacaQuoteFeed
from .test_codex_team2_data_eod import rig, ms


@pytest.mark.parametrize('age_ms', [0, 600_000])
def test_new_quote_does_not_reconfirm_old_last(monkeypatch, age_ms):
    import zargar.brokers.alpaca as feed_module
    import zargar.techniques.team2.runner as runner_module
    runner, ap = rig()
    now = ms(13, 10)
    clock = [now - age_ms]
    monkeypatch.setattr(feed_module, 'now_ms', lambda: clock[0])
    monkeypatch.setattr(runner_module.time, 'time', lambda: now / 1000)
    emitted = []
    feed = AlpacaQuoteFeed(emitted.append, '', '')
    iso = dt.datetime.fromtimestamp(clock[0] / 1000, dt.timezone.utc).isoformat()
    feed.handle({'T': 't', 'S': ap.symbol, 'p': 100.4, 's': 100, 't': iso})
    clock[0] = now
    feed.handle({'T': 'q', 'S': ap.symbol, 'bp': 101.1, 'ap': 101.12,
                 'bs': 1, 'as': 1, 't': dt.datetime.fromtimestamp(now / 1000, dt.timezone.utc).isoformat()})
    runner.engine.quotes = SimpleNamespace(get=lambda _: emitted[-1])
    px, reason = runner._fresh_underlying(ap)
    if age_ms:
        assert px != 100.4, 'bid/ask update refreshed receipt time but never reconfirmed the ten-minute-old last'
    else:
        assert px == 100.4


def test_missing_price_time_is_not_fresh(monkeypatch):
    import zargar.techniques.team2.runner as module
    runner, ap = rig()
    monkeypatch.setattr(module.time, 'time', lambda: ms(13, 10) / 1000)
    runner.engine.quotes = SimpleNamespace(get=lambda _: SimpleNamespace(last=100.4, ts=0))
    assert runner._fresh_underlying(ap)[0] is None
