"""Elevated assistant shells never leave the app dark (2026-09-19, the 0.8.23 deploy was dark ~4 minutes).

restart.ps1 refuses BEFORE the lease and BEFORE any stop when the shell is elevated; deploy.ps1 hands an elevated
restart to the Limited ZargarRestart task after releasing its lease, then waits for THIS target's terminal receipt.
These tests never run restart.ps1 or deploy.ps1 (their stop step is machine-wide): the pure helpers are exercised
under Windows PowerShell 5.1 on a throw-away root, and the script ORDER is asserted from source."""
import json
import os
import subprocess
import textwrap
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / 'scripts'
LOCK = SCRIPTS / 'deployment-lock.ps1'
pytestmark = pytest.mark.skipif(os.name != 'nt', reason='Windows deployment scripts')


def _ps(tmp_path: Path, body: str) -> subprocess.CompletedProcess:
    snippets = tmp_path.parent / f'{tmp_path.name}-snippets'
    snippets.mkdir(exist_ok=True)
    script = snippets / 'elev.ps1'
    script.write_text(". '" + LOCK.as_posix().replace("'", "''") + "'\n" + f"$Root = '{tmp_path.as_posix()}'\n"
                      + "$ErrorActionPreference = 'Stop'\n" + textwrap.dedent(body), encoding='ascii')
    env = {k: v for k, v in os.environ.items() if k not in ('ZARGAR_DEPLOY_LEASE', 'ZARGAR_DEPLOY_CALLER', 'PSModulePath')}
    return subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(script)],
                          capture_output=True, text=True, timeout=90, check=False, env=env)


def test_elevated_door_is_refused_and_a_limited_or_deliberate_door_proceeds(tmp_path):
    r = _ps(tmp_path, """
        $a = Test-ZargarDoorElevation $true $false
        $b = Test-ZargarDoorElevation $false $false
        $c = Test-ZargarDoorElevation $true $true
        Write-Output ("A=" + [bool]$a + "|B=" + ($null -eq $b) + "|C=" + ($null -eq $c))
        Write-Output $a
    """)
    assert r.returncode == 0, r.stderr
    assert "A=True|B=True|C=True" in r.stdout
    assert "nothing was stopped" in r.stdout and "ZargarRestart" in r.stdout


def test_receipt_wait_returns_only_this_targets_terminal_phase(tmp_path):
    logs = tmp_path / 'logs'
    logs.mkdir()
    (logs / 'deployment-receipt.json').write_text(json.dumps({"target": "OTHER", "phase": "verified"}), encoding='ascii')
    r = _ps(tmp_path, """
        $x = Wait-ZargarReceipt $Root 'abc' 2 1
        Write-Output ("other-target=" + ($null -eq $x))
        Write-ZargarReceipt $Root ([pscustomobject]@{ target='abc'; phase='restarting' })
        $y = Wait-ZargarReceipt $Root 'abc' 2 1
        Write-Output ("still-restarting=" + ($null -eq $y))
        Write-ZargarReceipt $Root ([pscustomobject]@{ target='abc'; phase='failed'; detail='start.ps1 exited 1' })
        $z = Wait-ZargarReceipt $Root 'abc' 5 1
        Write-Output ("terminal=" + $z.phase)
    """)
    assert r.returncode == 0, r.stderr
    assert "other-target=True" in r.stdout and "still-restarting=True" in r.stdout and "terminal=failed" in r.stdout


def test_restart_refuses_before_the_lease_and_before_any_stop():
    src = (SCRIPTS / 'restart.ps1').read_text(encoding='ascii')
    pre = src.index("Test-ZargarDoorElevation (Get-ZargarElevation)")
    assert pre < src.index("Enter-ZargarDeployment $Root -Restart")
    assert pre < src.index("Stop-Process -Id $_.ProcessId")
    assert "exit 8" in src[pre:pre + 400]
    assert "$args2.AllowElevated = $true" in src                 # a deliberate override reaches start.ps1


def test_elevated_deploy_releases_the_lease_before_starting_the_task_and_never_runs_restart_itself():
    src = (SCRIPTS / 'deploy.ps1').read_text(encoding='ascii')
    branch = src[src.index("if (Get-ZargarElevation) {"):src.index("} else {", src.index("if (Get-ZargarElevation) {"))]
    assert branch.index("Exit-ZargarDeployment $deployMutex") < branch.index("Start-ScheduledTask -TaskName 'ZargarRestart'")
    assert "& (Join-Path $PSScriptRoot 'restart.ps1')" not in branch      # never invoked from the elevated shell
    assert "Wait-ZargarReceipt $deployRoot $TargetCommit" in branch
    # the handoff is written BEFORE the branch (the task consumes it)
    assert src.index("deployment-pending.json") < src.index("if (Get-ZargarElevation) {")


def test_scripts_stay_ascii_for_windows_powershell_51():
    for name in ('restart.ps1', 'deploy.ps1', 'deployment-lock.ps1'):
        (SCRIPTS / name).read_bytes().decode('ascii')
