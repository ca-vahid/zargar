import asyncio
from unittest.mock import AsyncMock, patch

from tests.test_policy_migration_reporting import _ReportConnection
from zargar.tools import em_profitability as report


def test_prior_veto_counts_as_refused_after_a_later_deterministic_fill():
    conn = _ReportConnection()
    with patch('asyncpg.connect', new=AsyncMock(return_value=conn)), \
         patch.object(report, 'LEDGER', '__deliberately_absent_ledger__'):
        data = asyncio.run(report.build('2026-09-16'))
    result = report.summarize(data)['byPolicy']
    assert result['deterministic-entry-v1']['fills'] == 1
    assert result['deterministic-entry-v1']['net'] == 97.92
    assert result['legacy-critic:momentum_only']['attempts'] == 1
    assert result['legacy-critic:momentum_only']['refused'] == 1, 'The retained earlier veto must remain in the refusal total'
