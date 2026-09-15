"""EOD governance regression; runs only on the caller's disposable test DB."""
from zargar.techniques.tip.analyst import _run_tool

from .test_tip_knowledge import app_client  # noqa: F401


async def test_retro_cannot_promote_a_reviewed_hypothesis_to_active_policy(app_client):  # noqa: F811
    _, eng = app_client
    svc = eng.signals_service
    await eng.settings.set("techniques.tip.knowledge_apply_enabled", False, journal=False)
    await svc.add_tip_note(
        "rule", "RULE (adoption geometry): the sub-$25/high-beta 1.5% stop floor is "
        "a HYPOTHESIS under observation, not operative policy.", author="user")
    proposed = ("RULE (promotes the sub-$25/high-beta stop floor from HYPOTHESIS to "
                "operative policy): hard floor for shares is 1.5% of spot. "
                "Evidence: one historical GME stop-out.")
    await _run_tool(eng, "save_note", {"scope": "rule", "text": proposed},
                    {"ticker": "GME", "source": "neal", "run_id": "retro-proposal",
                     "stage": "retro"})
    governing = await svc.tip_notes(["rule"], limit=50)
    assert not any(n["text"] == proposed and not n.get("needsHuman") for n in governing), (
        "an LLM-authored promotion of a reviewed hypothesis must remain proposed or disputed "
        "until reviewed; it cannot become an unflagged governing rule")
