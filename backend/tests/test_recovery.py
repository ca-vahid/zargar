"""Intake recovery (POST-SOAK Phase 4): cold-quote parks re-verify when the
feed warms, error content retries exactly once, typo tickers normalize."""
import datetime as dt

import pytest

from zargar.domain import Quote, new_id
from zargar.engine import Engine
from zargar.models import RawContent, Signal
from zargar.signals.schemas import ExtractionResult, TradeSignal
from zargar.signals.service import attach_signal_layer

from .conftest import make_test_config


class _FakeExtractor:
    available = True
    model = "fake"

    def __init__(self, result):
        self.result = result
        self.calls = 0

    async def extract(self, text, **kw):
        self.calls += 1
        return self.result


def _tip(**kw):
    base = dict(ticker="AAPL", direction="long", action="open",
                entry_price=231.5, target_price=260.0, stop_price=220.0,
                entry_type="limit", timeframe="swing", thesis_summary="x",
                evidence_quotes=["Entry at $231.50, stop loss $220, target $260"],
                confidence="explicit_call", is_actionable=True)
    base.update(kw)
    return TradeSignal(**base)


@pytest.fixture
async def rig(fresh_db):
    eng = Engine(make_test_config())
    await eng.start()
    await attach_signal_layer(eng)
    yield eng
    await eng.stop()


def test_typo_ticker_normalizes():
    assert _tip(ticker="APPL").ticker == "AAPL"
    assert _tip(ticker=" appl ").ticker == "AAPL"
    assert _tip(ticker="PLTR").ticker == "PLTR"     # unknown names untouched


async def test_cold_park_reverifies_when_feed_warms(rig, monkeypatch):
    import zargar.brokers.sim as simmod

    from .conftest import wait_for
    eng = rig
    svc = eng.signals_service
    # the sim feed does not know COLDX yet — the sweep's nudge (ensure_symbol)
    # is what warms it, at the price the tip claims
    monkeypatch.setitem(simmod.KNOWN_PRICES, "COLDX", 231.8)
    sig = _tip(ticker="COLDX")
    row_id = new_id()
    async with eng.sf() as session:
        session.add(Signal(
            id=row_id, source_name="ColdSrc", ticker="COLDX", direction="long",
            action="open", entry_type="limit", timeframe="swing",
            confidence="explicit_call", is_actionable=True, status="parked",
            entry_price=231.5, target_price=260.0, stop_price=220.0,
            extraction={"signal": sig.model_dump()},
            verification={"passed": False, "park": True, "shadow_only": False,
                          "checks": [{"name": "ticker_resolves", "passed": False,
                                      "fatal": False,
                                      "detail": "no market data yet"}]},
            created_at=dt.datetime.now(dt.timezone.utc), seen_count=1))
        await session.commit()

    # cold: the sweep nudges the feed (ensure_symbol) but promotes nothing yet
    out1 = await svc.recovery_sweep()
    assert out1["promoted"] == 0
    async with eng.sf() as session:
        assert (await session.get(Signal, row_id)).status == "parked"

    # the nudge warms the feed near the claimed entry → re-verifies + promotes
    await wait_for(lambda: (q := eng.quotes.get("COLDX")) is not None
                   and bool(q.last and q.last > 0))
    out2 = await svc.recovery_sweep()
    assert out2["reverified"] == 1 and out2["promoted"] == 1, out2
    async with eng.sf() as session:
        promoted = await session.get(Signal, row_id)
    assert promoted.status == "proposed"      # verified → proposal minted
    # a proposal was minted but NEVER self-approved from the sweep
    pending = await eng.proposals.list_pending()
    assert any(p["signalId"] == row_id and p["status"] == "pending" for p in pending)


async def test_error_content_retries_exactly_once(rig):
    eng = rig
    svc = eng.signals_service
    svc.extractor = _FakeExtractor(ExtractionResult(signals=[], source_type="commentary"))
    fresh_id, stale_id = new_id(), new_id()
    now = dt.datetime.now(dt.timezone.utc)
    async with eng.sf() as session:
        session.add(RawContent(id=fresh_id, source_type="manual", source_name="S",
                               subject="x", body_text="hello", status="error",
                               received_at=now))
        session.add(RawContent(id=stale_id, source_type="manual", source_name="S",
                               subject="x", body_text="old", status="error",
                               received_at=now - dt.timedelta(hours=30)))
        await session.commit()
    out = await svc.recovery_sweep()
    assert out["retried"] == 1                      # the stale one is left alone
    assert svc.extractor.calls == 1
    async with eng.sf() as session:
        fresh = await session.get(RawContent, fresh_id)
        assert (fresh.meta or {}).get("recoveryRetried")
        assert fresh.status != "error"
    # second sweep: marked — never retried again
    out2 = await svc.recovery_sweep()
    assert out2["retried"] == 0 and svc.extractor.calls == 1


