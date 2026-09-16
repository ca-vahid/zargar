from tests.test_em_deterministic_entry_integration import rig, run_fire


def test_persisted_setup_uses_the_executed_deterministic_refusal():
    runner, ap, tracker, bar, technique = rig({
        'techniques.enhanced_market.fire_decision_mode': 'deterministic',
        'techniques.enhanced_market.critic_mode': 'advisory',
    })
    tracker.failed_breaks = 3
    run_fire(runner, ap, tracker, bar)
    assert ap.trades['b1'].decision['verdict'] == 'refuse'
    assert technique.persisted, 'The executed decision must have its setup audit record'
    assert technique.persisted[0][1] != 'setup', 'A deterministic refusal must not persist the older setup-approved analysis'
