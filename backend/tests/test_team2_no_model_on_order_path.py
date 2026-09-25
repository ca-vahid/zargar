"""Guard (2026-09-24 review): Team2's live decision path is deterministic — no model may reach it.

A model call on the order path would make a fill depend on a paid, non-reproducible answer. This pins the
three places that would have to change for one to creep in: the runner's reviewer hook, the plan's frozen
`useCritic`, and any model client import in the Team2 package.
"""
from __future__ import annotations

import pathlib

from zargar.techniques.team2.runner import Team2Runner

PKG = pathlib.Path(__file__).resolve().parents[1] / "zargar" / "techniques" / "team2"


def test_the_runner_has_no_reviewer():
    r = object.__new__(Team2Runner)
    assert r.reviewer_available() is False


def test_plans_are_minted_without_a_critic():
    src = (PKG / "service.py").read_text(encoding="utf-8")
    assert '"useCritic": False' in src and "usage={}, llm={}" in src


def test_no_team2_module_imports_a_model_client():
    for f in PKG.glob("*.py"):
        src = f.read_text(encoding="utf-8")
        for forbidden in ("import anthropic", "from anthropic", "technique.llm", "technique import llm", "stream_message(",
                          "messages.create(", "Extractor("):
            assert forbidden not in src, f"{f.name} reaches a model ({forbidden})"
