"""TMR-03 (scenario prototype) + TMR-05 (experiment register), 2026-09-16: pure
arithmetic, explicit unknowns, and every report carrying its experiment identity.
Nothing here touches the risk estimator, a gate or an order."""
import math
import re
from pathlib import Path

from zargar.techniques.tip import experiments_register as xr
from zargar.techniques.tip import scenarios as sc


def test_local_model_matches_put_call_parity_and_the_venue_delta():
    c = sc.price_and_greeks(spot=100, strike=100, dte_days=365, iv=0.2, kind="call")
    p = sc.price_and_greeks(spot=100, strike=100, dte_days=365, iv=0.2, kind="put")
    assert round(c["value"] - p["value"], 4) == round(100 - 100 * math.exp(-0.04), 4), "put-call parity"
    assert 0 < c["delta"] < 1 and -1 < p["delta"] < 0 and c["theta"] < 0 and c["vega"] > 0 and c["gamma"] > 0
    # the worked example: SLV Nov-20 65C on the 2026-09-15 CBOE snapshot (iv 0.4665, venue delta 0.3144), spot 57.55, 65 DTE
    g = sc.price_and_greeks(spot=57.55, strike=65.0, dte_days=65, iv=0.4665, kind="call")
    assert abs(g["delta"] - 0.3144) < 0.001 and abs(g["value"] - 2.085) < 0.02
    assert g["model"] == "bsm-local-v1"
    expired = sc.price_and_greeks(spot=70, strike=65, dte_days=0, iv=0.4, kind="call")
    assert expired["expired"] and expired["value"] == 5.0 and expired["delta"] == 1.0


def test_scenario_grid_reports_dollars_time_and_iv_and_declares_its_limits():
    grid = sc.scenario_grid(spot=57.55, strike=65.0, dte_days=65, iv=0.4665, kind="call", premium_paid=2.085, target=61.8)
    assert grid["status"] == "known" and grid["today"]["thetaPerDayDollars"] == -3.27 and grid["today"]["vegaPerIvPointDollars"] == 8.62
    assert grid["today"]["modelMinusPaid"] == -0.0074, "the model's mispricing of TODAY is shown, not hidden"
    rows = {(r["scenario"], r["holdDays"], r["ivShift"]): r for r in grid["grid"]}
    assert rows[("flat", 10.0, 0.0)]["pnlDollars"] == -34.16 and rows[("flat", 1.0, 0.05)]["pnlDollars"] == 39.32
    assert rows[("target-soon", 1.0, 0.0)]["pnlDollars"] == 157.82 and rows[("target-later", 32.5, 0.0)]["pnlDollars"] == 13.94
    assert rows[("target-later", 32.5, -0.05)]["pnlDollars"] < 0, "the same target reached late with lower IV loses money"
    assert any("not a calibrated forecast" in x for x in grid["limits"]) and any("no stop hit is modelled" in x for x in grid["limits"])
    assert grid["rate"] == 0.04 and grid["inputs"]["premiumPaid"] == 2.085


def test_missing_inputs_stay_unknown():
    g = sc.scenario_grid(spot=57.55, strike=65.0, dte_days=65, iv=None, kind="call", premium_paid=2.085)
    assert g["status"] == "unknown" and g["unknown"] == ["iv"] and "grid" not in g
    g2 = sc.scenario_grid(spot=None, strike=65.0, dte_days=None, iv=0.4, kind="call", premium_paid=None)
    assert g2["unknown"] == ["spot", "dteDays", "premiumPaid"]
    bad = sc.scenario_grid(spot=57.55, strike=65.0, dte_days=65, iv=-0.1, kind="call", premium_paid=2.0)
    assert bad["status"] == "unknown" and "positive" in bad["unknown"][0]


def test_register_and_its_markdown_mirror_list_the_same_experiments():
    doc = Path(__file__).resolve().parents[2] / "docs" / "techniques" / "tip" / "research" / "EXPERIMENT-REGISTER.md"
    text = doc.read_text(encoding="utf-8")
    ids_in_doc = set(re.findall(r"^## `([a-z0-9-]+)`", text, flags=re.M))
    assert ids_in_doc == set(xr.EXPERIMENTS), (ids_in_doc ^ set(xr.EXPERIMENTS))
    for eid, e in xr.EXPERIMENTS.items():
        for k in ("hypothesis", "variants", "eligibleSetup", "unit", "episodeIdentity", "primaryMetric", "costs", "regime",
                  "alternativesTried", "evaluationWindow", "status"):
            assert k in e, (eid, k)
        assert e["evaluationWindow"].get("closes") and e["evaluationWindow"].get("decisionRule")


def test_identity_block_and_reports_carry_it():
    ident = xr.identity("overnight-hold", build="abc1234")
    assert ident["registered"] and ident["regime"]["build"] == "abc1234" and ident["unit"].startswith("one position-session")
    assert "not independent observations" in ident["caveat"] and "no sample count is called proof" in ident["caveat"]
    assert xr.identity("nope")["registered"] is False
    from zargar.techniques.tip import frozen, holdstudy
    assert holdstudy.aggregate([])["experiment"]["experimentId"] == "overnight-hold"
    assert frozen.compare([])["experiment"]["experimentId"] == "frozen-context"
