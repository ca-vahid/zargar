"""PROF-01/02 on the real analyst path (scripted client, no provider): a TAKE
gets its expression checked against the approved risk budget and its exit
plan previewed in integer units; `analyst_feasibility_gate` annotate keeps
the verdict, downgrade turns an unfittable take into watch with the thesis
verdict kept."""
from .test_tip_kfin09_experiments import _Scripted, _opinion, _run, _text, canned, rig  # noqa: F401


async def _take_opinion(eng, *, stop_frac: float, qty: int = 5):
    q = eng.quotes.get("AAPL")
    px = float(q.last)
    return _opinion("take", instrument="shares", contract=None, limit_price=round(px, 2), quantity=qty,
                    underlying_stop=round(px * stop_frac, 2), exit_targets=[round(px * 1.03, 2), round(px * 1.06, 2)],
                    exit_fractions=[0.5, 0.5], max_hold_sessions=5, exit_rationale="scripted")


async def test_take_is_annotated_with_feasibility_and_payoff(rig):  # noqa: F811
    eng = rig
    pid = next(p["id"] for p in eng.positions.portfolios() if p["kind"] == "sim")
    await eng.settings.set("techniques.tip.default_portfolio", pid, journal=False)
    await eng.settings.set("techniques.tip.risk_budget_per_tip", 200.0, journal=False)   # a fixed, known budget
    eng.signals_service._analyst_client = _Scripted([_text(await _take_opinion(eng, stop_frac=0.98))])
    out = await _run(eng, canned(), source="ExprSrc")
    sig = out[0]["signal"]
    an = (sig.get("extraction") or {}).get("analyst") or {}
    assert an.get("verdict") == "take" and an.get("thesisVerdict") == "take" and an.get("expressionGate") == "annotated"
    ex = an.get("expression") or {}
    assert ex.get("unitRiskBasis") == "stop-distance" and ex.get("riskBudget") == 200.0
    assert ex.get("feasible") is True and ex.get("qty") >= 1
    po = an.get("payoff") or {}
    assert po.get("ladder", {}).get("units") and po.get("scenarios", {}).get("tp1ThenStop") is not None


async def test_downgrade_mode_turns_an_unfittable_take_into_watch(rig):  # noqa: F811
    eng = rig
    pid = next(p["id"] for p in eng.positions.portfolios() if p["kind"] == "sim")
    await eng.settings.set("techniques.tip.default_portfolio", pid, journal=False)
    await eng.settings.set("techniques.tip.risk_budget_per_tip", 1.0, journal=False)     # nothing fits at a 2% stop of a $200+ share
    await eng.settings.set("techniques.tip.analyst_feasibility_gate", "downgrade", journal=False)
    eng.signals_service._analyst_client = _Scripted([_text(await _take_opinion(eng, stop_frac=0.98))])
    out = await _run(eng, canned(), source="ExprSrc2")
    sig = out[0]["signal"]
    an = (sig.get("extraction") or {}).get("analyst") or {}
    assert an.get("verdict") == "watch" and an.get("thesisVerdict") == "take" and an.get("expressionGate") == "downgraded"
    assert an["expression"]["feasible"] is False and an["expression"]["qty"] == 0
    assert "does not fit" in an.get("rationale", "")
    # the card (if any) is an analyst WATCH like any other: never self-approved,
    # and it carries the thesis verdict and the expression check for the person
    from sqlalchemy import select
    from zargar.models import Proposal
    async with eng.sf() as session:
        rows = (await session.execute(select(Proposal).where(Proposal.signal_id == sig["id"]))).scalars().all()
    for r in rows:
        assert r.status in ("pending", "rejected", "expired") and r.decided_via != "auto", (r.status, r.decided_via)
        assert (r.context.get("analyst") or {}).get("verdict") == "watch"
