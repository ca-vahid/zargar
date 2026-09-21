"""The 2026-09-21 AMD/MRNA hold: a topic switch the transcriber spelled wrong.

The source row `sc1-6db4626f03216c0a2f42` was held as `evidence_names_AMD_not_MRNA`. The passage is
about Moderna - its numbers are Moderna's, and AMD's only number (584) is six lines earlier - but
the ASR wrote "maderna", which matched neither the ticker pattern nor the alias table. The locator's
rule that a speaker stays on a chart until he names the next one then carried AMD's label across the
whole passage.

The span selection was RIGHT and is left alone. What was wrong was the label on it. These fixtures
are the real transcript lines, kept verbatim, so the fix cannot be undone without failing here.
"""
import pytest

from zargar.technique.source_scenarios import ALIASES, locate_evidence, symbol_mentions

# Verbatim from artifact 51fb65d560c6f323348ced5573e6a1f3 (note f42af4852d3d446d9ca8b193b7adede3).
TRANSCRIPT = """[4:20] Um amd is up three and a half percent here at the open or at pre market
[4:24] We are approaching this
[4:27] All-time high 584 pre market pretty awesome
[4:31] Bobby how happy are you?
[4:33] um
[4:35] so
[4:37] There's really no good spot for an entry at the open. It's just it's gabbing up. That's really all we can do
[4:43] um, maderna
[4:44] We had a great move last week on thursday, and then we ended up just selling off
[4:50] Um, we could watch it though if we start to break through that high
[4:54] Now we created 160 196 or so
[4:58] Right around this zone there
[5:00] meta
[5:02] Is a little iffy nothing really there that i'm interested in apple."""

BOARD_LINE = {"symbol": "MRNA", "direction": "long",
              "trigger": "break through last week's high around 196",
              "targets": [], "note": "'not the best name to trade', he doesn't like trading it"}
UNIVERSE = ["AMD", "MRNA", "META", "AAPL", "NVDA", "TSLA"]


def test_the_transcriber_wrote_maderna_and_that_spelling_is_now_recognised():
    assert "maderna" in ALIASES["MRNA"] and "moderna" in ALIASES["MRNA"]
    mentions = symbol_mentions(TRANSCRIPT, set(UNIVERSE) | set(ALIASES))
    named = [m["symbol"] for m in mentions]
    assert "MRNA" in named, "the passage names Moderna, however the transcriber spelled it"
    assert "AMD" in named and "META" in named, "the neighbouring topics still resolve"


def test_the_passage_resolves_to_moderna_and_no_longer_conflicts_with_amd():
    out = locate_evidence(BOARD_LINE, TRANSCRIPT, "transcript", UNIVERSE)
    assert out["located"] is True
    assert out["evidenceSymbol"] == "MRNA", "this is the demonstrated 2026-09-21 boundary error"
    assert out["symbolSeen"] is True, "the ticker is now verifiable from the evidence itself"


def test_the_span_that_was_already_correct_is_unchanged():
    out = locate_evidence(BOARD_LINE, TRANSCRIPT, "transcript", UNIVERSE)
    text = " ".join(sp.get("quote", "") for sp in out["spans"])
    assert "196" in text, "the span still carries the sentence with the level"
    assert "584" not in text, "AMD's own number was never in the window and must not enter it now"
    assert "meta" not in text.lower(), "the window stops before the next topic"


def test_amds_own_passage_still_belongs_to_amd():
    amd_line = {"symbol": "AMD", "direction": "long", "trigger": "all-time high 584 pre market",
                "targets": [], "note": "gapping up, no good spot at the open"}
    out = locate_evidence(amd_line, TRANSCRIPT, "transcript", UNIVERSE)
    assert out["evidenceSymbol"] == "AMD" and out["symbolSeen"] is True
    assert "584" in " ".join(sp.get("quote", "") for sp in out["spans"])


def test_a_ticker_the_evidence_never_names_is_still_refused():
    """The rule that produced the hold is correct and stays: no alias, no resolution, no invention."""
    ghost = {"symbol": "PLTR", "direction": "long", "trigger": "break through that high",
             "targets": [], "note": ""}
    out = locate_evidence(ghost, TRANSCRIPT, "transcript", UNIVERSE + ["PLTR"])
    assert out["symbolSeen"] is False, "Palantir is never spoken here and must never be inferred"
    assert out["evidenceSymbol"] != "PLTR"


@pytest.mark.parametrize("spelling", ["moderna", "maderna"])
def test_both_spellings_reach_the_same_ticker(spelling):
    text = TRANSCRIPT.replace("maderna", spelling)
    out = locate_evidence(BOARD_LINE, text, "transcript", UNIVERSE)
    assert out["evidenceSymbol"] == "MRNA" and out["symbolSeen"] is True
