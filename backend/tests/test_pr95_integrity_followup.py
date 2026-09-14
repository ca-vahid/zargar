"""Combined PR 95 evidence-producer and release regressions; offline only."""
import datetime as dt
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

from zargar.techniques.tip import integrity as ig

from .test_premium_stop_debounce import BASE, _mgr, _pos, _q, _tick


async def test_successful_confirmation_retains_the_pair_for_exit_receipt():
    position = _pos()
    manager = _mgr(lambda _symbol: None)
    await _tick(manager, position, _q(.85, BASE), BASE + 1000)
    assert manager.close.await_count == 0
    await _tick(manager, position, _q(.83, BASE + 4000), BASE + 5000)
    assert manager.close.await_count == 1
    assert manager.close.call_args.kwargs["kind"] == "premium_stop"
    receipt = manager.close.call_args.kwargs["evidence"]
    assert receipt["confirmed"] is True and len(receipt["observations"]) == 2, receipt


async def test_unrelated_fill_cannot_release_a_missing_evidence_hold():
    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            pass

        async def get(self, _model, _ident):
            return NS(id="unrelated-fill", portfolio_id="OTHER-BOOK", symbol="OTHER",
                      side="BUY", qty=1, price=100,
                      ts=dt.datetime(2025, 1, 1, tzinfo=dt.UTC))

    incident = {"cause": "evidence_missing", "scope": {
        "portfolioId": "TIPS-PRACTICE", "symbol": "AAPL"},
        "evidence": [{"kind": "position", "id": "aapl-position", "symbol": "AAPL"},
                     {"kind": "proof", "id": "execution:unrelated-fill"}],
        "openedAt": "2026-09-14T00:00:00+00:00"}
    valid, reason = await ig._validate_release(NS(sf=Session), incident, "")
    assert not valid, reason


async def test_detection_retries_incident_after_diagnostic_commit(monkeypatch):
    seen = set()
    position = NS(id="position", portfolio_id="practice", symbol="AAPL", legs=[],
                  state={"openedMs": 100_000, "exits": [
                      {"kind": "stop", "status": "FILLED", "filledTs": 160_000}]},
                  config={"extras": {"riskPlan": {"enforced": True, "invariantOk": False}}})

    class Session:
        def __init__(self):
            self.calls = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            pass

        async def execute(self, _query):
            self.calls += 1
            values = [position] if self.calls == 1 else list(seen)
            return NS(scalars=lambda: NS(all=lambda: values))

    async def append(kind, _payload, **kwargs):
        if kind == "TipFastStopDiagnostic":
            seen.add(kwargs["aggregate_id"])

    opened = AsyncMock(side_effect=[RuntimeError("incident write failed after diagnostic commit"), {}])
    monkeypatch.setattr(ig, "open_incident", opened)
    monkeypatch.setattr(ig, "_fill_times", AsyncMock(return_value=(100_000, 160_000)))
    monkeypatch.setattr(ig, "_duplicate_executions", AsyncMock(return_value=[]))
    eng = NS(settings={"techniques.tip.default_portfolio": "practice"}, sf=Session,
             positions=NS(portfolio=lambda _pid: {"kind": "sim"}), journal=NS(append=append))
    try:
        await ig.detect_incidents(eng, strict=True)
    except RuntimeError:
        pass
    await ig.detect_incidents(eng, strict=True)
    assert opened.await_count == 2, "The diagnostic committed, but the missing incident was never retried"
