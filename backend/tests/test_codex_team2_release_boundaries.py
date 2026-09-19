"""Final release boundaries. Synthetic study data; CLI uses only fresh Codex test DB."""
import copy
import os
import subprocess
import sys
from .test_team2_selection_lifecycle import FULL, opp, life, close_of
from zargar.techniques.team2 import selection_study as ss, selection_study_analysis as an, selection_study_lifecycle as lc


def test_later_out_of_window_rows_do_not_change_frozen_manifest():
    rows = [r for d in FULL[:60] for r in opp(d, 0)]
    _, original = lc.final_sample(life(rows, now=close_of(FULL[59])), rows)
    later = rows + opp(FULL[60], 0)
    _, repeated = lc.final_sample(life(later, now=close_of(FULL[60])), later)
    assert lc.sha(original) == lc.sha(repeated), 'outside-window diagnostic counts changed the frozen manifest'


def test_final_sample_preserves_first_journaled_close():
    rows = [r for d in FULL[:60] for r in opp(d, 0)]
    duplicate = copy.deepcopy(rows[1])
    duplicate['observations']['30']['bid'] = .01
    rows.append(duplicate)
    original = an.population(rows)['primary'][0]
    inc, _ = lc.final_sample(life(rows, now=close_of(FULL[59])), rows)
    final = an.population(inc)['primary'][0]
    assert ss.outcome(original, 1.04)['primary'] == ss.outcome(final, 1.04)['primary'], 'value sorting replaced first journal close'


async def test_actual_activation_cli_completes_with_one_database_engine(fresh_db):
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    result = subprocess.run([sys.executable, '-X', 'utf8', '-m', 'zargar.tools.team2_selection_study',
                             'activate', '--build', 'isolated-test-build', '--confirm', ss.REGISTRATION_HASH],
                            env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
