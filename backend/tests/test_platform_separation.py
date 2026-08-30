"""Separation guard (KNOWLEDGE plan §E, user requirement 2026-08-30):

technique knowledge stores are PER-TECHNIQUE. `tip_notes` (TipNote) belongs to
the tips desk only; EM's rulebook/method modules belong to EM only. Changing one
analyst's knowledge must never affect the other, so a cross-read anywhere in the
code fails the suite here — before it can fail a trader.

Static source scan on purpose: an import guard at runtime can be dodged by a
lazy import inside a function; a text scan catches those too.
"""
from __future__ import annotations

import re
from pathlib import Path

import zargar

PKG = Path(zargar.__file__).resolve().parent
EM_DIR = PKG / "technique"                 # EnhancedMarket method + its knowledge
TIP_DIR = PKG / "techniques" / "tip"       # the tips desk

# EM modules that carry METHOD KNOWLEDGE (rulebook, prompts, chart reads,
# reviews). Tips code may share mechanics (llm client, plan dataclasses,
# option picking) but never these.
EM_KNOWLEDGE_MODULES = (
    "rulebook", "vision", "analysis", "review", "setups", "chat",
    "backtest", "walkforward", "arming", "grounding",
)


def _py_files(root: Path) -> list[Path]:
    files = sorted(root.rglob("*.py"))
    assert files, f"no python files under {root} — did the layout move?"
    return files


def test_em_never_touches_tip_knowledge():
    pat = re.compile(r"\btip_notes?\b|\bTipNote\b")
    hits = [f"{p.relative_to(PKG)}: {m.group(0)}"
            for p in _py_files(EM_DIR)
            for m in [pat.search(p.read_text(encoding="utf-8"))] if m]
    assert not hits, (
        "EM code must never read/write the tips knowledge store (tip_notes): "
        + "; ".join(hits))


def test_tip_never_reads_em_method():
    pat = re.compile(
        r"technique\s*\.\s*(" + "|".join(EM_KNOWLEDGE_MODULES) + r")\b"
        r"|technique\s+import\s+(" + "|".join(EM_KNOWLEDGE_MODULES) + r")\b"
        r"|TRADING-RULES\.md")
    hits = [f"{p.relative_to(PKG)}: {m.group(0)}"
            for p in _py_files(TIP_DIR)
            for m in [pat.search(p.read_text(encoding="utf-8"))] if m]
    assert not hits, (
        "tips code must never read EM's method knowledge (rulebook/prompts/"
        "chart-read modules): " + "; ".join(hits))


def test_tip_analyst_prompt_disclaims_em():
    # the charter line is load-bearing: the analyst is told, in its own prompt,
    # that EM's book does not apply to it
    text = (TIP_DIR / "analyst.py").read_text(encoding="utf-8")
    assert "NOT bound by any other technique's method" in text
