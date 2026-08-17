"""Quote-grounding validation for extracted signals (pure functions, no API)."""
from zargar.signals.extraction import ground_signal, quote_in_source
from zargar.signals.schemas import TradeSignal

SOURCE = """
ALERT: We are buying NVDA today. Entry at $128.50, stop loss $122, target $145.
NVIDIA remains our top semiconductor pick going into earnings.
"""


def sig(**kw):
    base = dict(
        ticker="NVDA", direction="long", action="open",
        entry_price=128.50, target_price=145.0, stop_price=122.0,
        entry_type="limit", timeframe="swing",
        thesis_summary="Top semi pick into earnings.",
        evidence_quotes=["We are buying NVDA today", "Entry at $128.50, stop loss $122, target $145"],
        confidence="explicit_call", is_actionable=True,
    )
    base.update(kw)
    return TradeSignal(**base)


def test_quote_in_source_whitespace_insensitive():
    assert quote_in_source("we are buying   NVDA today", SOURCE)
    assert not quote_in_source("we are selling NVDA", SOURCE)
    assert not quote_in_source("", SOURCE)


def test_grounded_signal_passes():
    result = ground_signal(sig(), SOURCE)
    assert result["passed"], result


def test_fabricated_quote_fails():
    result = ground_signal(sig(evidence_quotes=["We are buying NVDA at any price"]), SOURCE)
    assert not result["passed"]
    assert result["failedQuotes"]


def test_hallucinated_price_fails():
    # price not present in any evidence quote
    result = ground_signal(sig(entry_price=131.0), SOURCE)
    assert not result["passed"]
    assert not result["checks"]["entry_evidenced"]


def test_ticker_must_be_evidenced():
    source = "The market looks strong. Semis are leading."
    result = ground_signal(sig(evidence_quotes=["Semis are leading"],
                               entry_price=None, target_price=None, stop_price=None), source)
    assert not result["checks"]["ticker_evidenced"]
    assert not result["passed"]


def test_no_quotes_fails():
    result = ground_signal(sig(evidence_quotes=[]), SOURCE)
    assert not result["passed"]
