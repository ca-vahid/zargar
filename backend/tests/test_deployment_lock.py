"""Deployment ownership + reviewed-artifact hardening (`scripts/deployment-lock.ps1`; KFIN-04, 2026-09-14).

The scripts are exercised under Windows PowerShell 5.1 (`powershell.exe`) because the ZargarRestart
task runs them there. Nothing here talks to :8420 or touches the running checkout's logs: every test
works on a throw-away root under tmp_path."""
import json
import os
import subprocess
import textwrap
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / 'scripts'
LOCK = SCRIPTS / 'deployment-lock.ps1'
pytestmark = pytest.mark.skipif(os.name != 'nt', reason='Windows deployment uses a cross-session OS mutex')


def _ps(tmp_path: Path, body: str, *, env: dict | None = None, name: str = 'snippet') -> subprocess.CompletedProcess:
    """Run `body` under powershell.exe with the lock helper dot-sourced ($Lock, $Root, $Scripts preset)."""
    snippets = tmp_path.parent / f'{tmp_path.name}-snippets'   # outside the root: a snippet must not dirty the checkout
    snippets.mkdir(exist_ok=True)
    script = snippets / f'{name}.ps1'
    script.write_text(". '" + LOCK.as_posix().replace("'", "''") + "'\n"
                      + f"$Root = '{tmp_path.as_posix()}'\n$Scripts = '{SCRIPTS.as_posix()}'\n"
                      + "$ErrorActionPreference = 'Stop'\n" + textwrap.dedent(body), encoding='ascii')
    full = {**os.environ, **(env or {})}
    full.pop('ZARGAR_DEPLOY_LEASE', None)
    full.pop('ZARGAR_DEPLOY_CALLER', None)
    full.pop('PSModulePath', None)     # the scheduled task's 5.1 has its own module path, not a pwsh-7 parent's
    return subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(script)],
                          capture_output=True, text=True, timeout=90, check=False, env=full)


def _marker(tmp_path: Path) -> Path:
    return tmp_path / 'logs' / 'deploy.lock'


def _git(root: Path, *args: str) -> str:
    return subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True, check=True).stdout.strip()


def _repo(root: Path) -> str:
    """A reviewed checkout: committed backend + frontend sources, a gitignored dist with two files."""
    (root / 'backend' / 'zargar').mkdir(parents=True)
    (root / 'frontend' / 'src').mkdir(parents=True)
    (root / 'backend' / 'zargar' / 'app.py').write_text('print(1)\n')
    (root / 'frontend' / 'src' / 'main.ts').write_text('export {}\n')
    (root / 'frontend' / 'index.html').write_text('<div id=root></div>\n')
    (root / '.gitignore').write_text('frontend/dist/\n*.local.js\n__pycache__/\n/logs/\n')
    _git(root, 'init', '-q')
    _git(root, 'config', 'user.email', 't@t'); _git(root, 'config', 'user.name', 't')
    _git(root, 'add', '-A'); _git(root, 'commit', '-q', '-m', 'reviewed')
    (root / 'frontend' / 'dist' / 'assets').mkdir(parents=True)
    (root / 'frontend' / 'dist' / 'index.html').write_text('<script src=assets/app.js></script>\n')
    (root / 'frontend' / 'dist' / 'assets' / 'app.js').write_text('console.log("v1")\n')
    return _git(root, 'rev-parse', 'HEAD')


# ----------------------------------------------------------------------------- ownership

def test_competing_deploy_process_cannot_acquire_same_runtime(tmp_path):
    script=(Path(__file__).resolve().parents[2]/'scripts'/'deployment-lock.ps1').as_posix().replace("'","''")
    root=tmp_path.as_posix().replace("'","''")
    child=f". '{script}'; try {{ $m=Enter-ZargarDeployment '{root}'; Exit-ZargarDeployment $m; exit 1 }} catch {{ exit 0 }}"
    child_quoted=child.replace("'","''")
    command=f". '{script}'; $m=Enter-ZargarDeployment '{root}'; try {{ & powershell.exe -NoProfile -Command '{child_quoted}'; if ($LASTEXITCODE -ne 0) {{ throw 'Competing owner acquired lease' }}; $nested=Enter-ZargarDeployment '{root}'; Exit-ZargarDeployment $nested }} finally {{ Exit-ZargarDeployment $m }}"
    completed=subprocess.run(['powershell.exe','-NoProfile','-Command',command],capture_output=True,text=True,timeout=30,check=False)
    assert completed.returncode==0,completed.stdout+completed.stderr


def test_nested_child_shares_the_parent_lease_and_a_foreign_child_is_refused(tmp_path):
    """start.ps1 under restart.ps1 (a child process, -Nested) rides the parent's lease without owning it;
    the same child without -Nested, or one that did not inherit the lease, is a competing deployment."""
    child = tmp_path / 'child.ps1'
    child.write_text("param([switch]$Nested, [switch]$Forget)\n"
                     ". '" + LOCK.as_posix() + "'\n$ErrorActionPreference='Stop'\n"
                     "if ($Forget) { Remove-Item Env:ZARGAR_DEPLOY_LEASE -ErrorAction SilentlyContinue }\n"
                     "try { $l = Enter-ZargarDeployment $args[0] -Nested:$Nested; if ($l.Owns) { Write-Output 'OWNS'; Exit-ZargarDeployment $l; exit 3 }; Write-Output ('SHARED ' + $l.Owner); Exit-ZargarDeployment $l; exit 0 }\n"
                     "catch { Write-Output ('REFUSED ' + $_.Exception.Message); exit 7 }\n", encoding='ascii')
    out = _ps(tmp_path, f"""
        $m = Enter-ZargarDeployment $Root
        try {{
          & powershell.exe -NoProfile -ExecutionPolicy Bypass -File '{child.as_posix()}' -Nested $Root; Write-Output ("nested=" + $LASTEXITCODE)
          & powershell.exe -NoProfile -ExecutionPolicy Bypass -File '{child.as_posix()}' $Root; Write-Output ("plain=" + $LASTEXITCODE)
          & powershell.exe -NoProfile -ExecutionPolicy Bypass -File '{child.as_posix()}' -Nested -Forget $Root; Write-Output ("forgot=" + $LASTEXITCODE)
          Write-Output ("marker-during=" + (Get-Content -LiteralPath (Join-Path $Root 'logs/deploy.lock') -Raw).Trim())
          Write-Output ("owner=" + $m.Owner)
        }} finally {{ Exit-ZargarDeployment $m }}
        Write-Output ("marker-after=" + (Test-Path -LiteralPath (Join-Path $Root 'logs/deploy.lock')))
    """)
    text = out.stdout + out.stderr
    assert out.returncode == 0, text
    assert 'nested=0' in text and 'SHARED ' in text, text
    assert 'plain=7' in text and 'forgot=7' in text, text
    assert 'REFUSED Another deployment owns this runtime' in text, text
    owner = [ln for ln in text.splitlines() if ln.startswith('owner=')][0][6:]
    assert f'marker-during={owner}' in text and 'marker-after=False' in text, text


def test_dead_owner_is_recovered_and_a_hard_killed_owner_leaves_a_recoverable_marker(tmp_path):
    proc = subprocess.Popen(['cmd', '/c', 'exit 0']); proc.wait(); dead_pid = proc.pid   # a pid that is gone
    _marker(tmp_path).parent.mkdir(parents=True)
    _marker(tmp_path).write_text(f'{os.environ["COMPUTERNAME"]}:{dead_pid}:deadbeef', encoding='ascii')
    out = _ps(tmp_path, """
        $m = Enter-ZargarDeployment $Root
        Write-Output ("owns=" + $m.Owns + " marker=" + (Get-Content -LiteralPath $m.Marker -Raw).Trim())
        Exit-ZargarDeployment $m
        Write-Output ("after=" + (Test-Path -LiteralPath $m.Marker))
    """)
    assert out.returncode == 0 and 'owns=True' in out.stdout and f':{dead_pid}:' not in out.stdout, out.stdout + out.stderr
    assert 'after=False' in out.stdout
    # a process that dies WITHOUT Exit-ZargarDeployment (hard kill) leaves its marker; the mutex is
    # abandoned with it, so the next deployment recovers ownership instead of waiting forever
    killed = _ps(tmp_path, "$m = Enter-ZargarDeployment $Root; [Environment]::Exit(9)", name='killed')
    assert killed.returncode == 9 and _marker(tmp_path).exists()
    again = _ps(tmp_path, "$m = Enter-ZargarDeployment $Root; Write-Output ('owns=' + $m.Owns); Exit-ZargarDeployment $m", name='again')
    assert again.returncode == 0 and 'owns=True' in again.stdout, again.stdout + again.stderr
    # an unidentified marker (another host, or garbage) is never removed silently
    _marker(tmp_path).parent.mkdir(exist_ok=True)
    _marker(tmp_path).write_text('OTHER-HOST:4242:cafe', encoding='ascii')
    foreign = _ps(tmp_path, "try { $m = Enter-ZargarDeployment $Root; Exit-ZargarDeployment $m; exit 1 } catch { Write-Output $_.Exception.Message; exit 0 }", name='foreign')
    assert foreign.returncode == 0 and 'unidentified deployment marker' in foreign.stdout, foreign.stdout + foreign.stderr
    assert _marker(tmp_path).read_text() == 'OTHER-HOST:4242:cafe'


def test_pending_handoff_blocks_new_deployments_until_it_expires_but_not_the_restart(tmp_path):
    (tmp_path / 'logs').mkdir()
    pending = tmp_path / 'logs' / 'deployment-pending.json'
    body = """
        try { $m = Enter-ZargarDeployment $Root; Exit-ZargarDeployment $m; Write-Output 'plain=ok' } catch { Write-Output ('plain=' + $_.Exception.Message) }
        try { $m = Enter-ZargarDeployment $Root -Restart; Exit-ZargarDeployment $m; Write-Output 'restart=ok' } catch { Write-Output ('restart=' + $_.Exception.Message) }
    """
    pending.write_text(json.dumps({'target': 'x', 'expiresAt': '2099-01-01T00:00:00+00:00'}))
    live = _ps(tmp_path, body, name='live')
    assert 'plain=A reviewed deployment is awaiting its elevated restart' in live.stdout and 'restart=ok' in live.stdout, live.stdout + live.stderr
    pending.write_text(json.dumps({'target': 'x', 'expiresAt': '2020-01-01T00:00:00+00:00'}))
    expired = _ps(tmp_path, body, name='expired')
    assert 'plain=ok' in expired.stdout and 'restart=ok' in expired.stdout, expired.stdout + expired.stderr


def test_an_exception_inside_the_lease_releases_ownership_for_the_next_process(tmp_path):
    crashed = _ps(tmp_path, """
        $m = Enter-ZargarDeployment $Root
        try { throw 'build blew up' } finally { Exit-ZargarDeployment $m }
    """, name='crashed')
    assert crashed.returncode != 0 and 'build blew up' in (crashed.stdout + crashed.stderr)
    assert not _marker(tmp_path).exists(), 'the marker must not outlive a failed deployment'
    nxt = _ps(tmp_path, "$m = Enter-ZargarDeployment $Root; Write-Output ('owns=' + $m.Owns); Exit-ZargarDeployment $m", name='next')
    assert nxt.returncode == 0 and 'owns=True' in nxt.stdout, nxt.stdout + nxt.stderr
    # the env var is restored to what it was before the lease (nothing) — a later child is not fooled
    env = _ps(tmp_path, "$m = Enter-ZargarDeployment $Root; Exit-ZargarDeployment $m; Write-Output ('lease=[' + $env:ZARGAR_DEPLOY_LEASE + ']')", name='env')
    assert 'lease=[]' in env.stdout


def test_duplicate_request_in_one_process_neither_owns_nor_releases(tmp_path):
    out = _ps(tmp_path, """
        $first = Enter-ZargarDeployment $Root
        $dup = Enter-ZargarDeployment $Root
        Write-Output ("dup-owns=" + $dup.Owns + " same-owner=" + ($dup.Owner -eq $first.Owner))
        Exit-ZargarDeployment $dup
        Write-Output ("marker-after-dup-exit=" + (Test-Path -LiteralPath $first.Marker))
        Exit-ZargarDeployment $first
        Write-Output ("marker-after-first-exit=" + (Test-Path -LiteralPath $first.Marker))
    """)
    assert out.returncode == 0, out.stdout + out.stderr
    assert 'dup-owns=False same-owner=True' in out.stdout
    assert 'marker-after-dup-exit=True' in out.stdout and 'marker-after-first-exit=False' in out.stdout


# ----------------------------------------------------------------------------- reviewed artifact

def test_artifact_manifest_covers_every_dist_file_and_refuses_modified_assets(tmp_path):
    head = _repo(tmp_path)
    show = """
        $m = Get-ZargarArtifactManifest $Root
        Write-Output ("count=" + $m.FileCount + " sha=" + $m.ManifestSha256 + " files=" + (($m.Files.Keys | Sort-Object) -join ','))
    """
    one = _ps(tmp_path, show, name='m1')
    assert one.returncode == 0 and 'count=2 ' in one.stdout and 'files=assets/app.js,index.html' in one.stdout, one.stdout + one.stderr
    sha1 = one.stdout.split('sha=')[1].split()[0]
    # a handoff issued for this artifact passes with the very same files...
    handoff = tmp_path / 'logs' / 'deployment-pending.json'
    handoff.parent.mkdir(exist_ok=True)
    def write_handoff(sha, *, target=head, expires='2099-01-01T00:00:00+00:00'):
        files = {'assets/app.js': 'x', 'index.html': 'y'}
        handoff.write_text(json.dumps({'target': target, 'expectedVersion': '0.7.78', 'artifactManifestSha256': sha,
                                       'files': files, 'expiresAt': expires}))
    check = """
        $h = Get-Content -LiteralPath (Join-Path $Root 'logs/deployment-pending.json') -Raw | ConvertFrom-Json
        try { $m = Assert-ZargarHandoff $Root $h '0.7.78'; Write-Output ('PASS ' + $m.ManifestSha256) } catch { Write-Output ('REFUSED ' + $_.Exception.Message) }
    """
    write_handoff(sha1)
    assert 'PASS ' + sha1 in _ps(tmp_path, check, name='c1').stdout
    # ...and refuses when a gitignored dist asset changed even though dist/index.html did not
    (tmp_path / 'frontend' / 'dist' / 'assets' / 'app.js').write_text('console.log("v2 hotpatch")\n')
    two = _ps(tmp_path, check, name='c2').stdout
    assert 'REFUSED Deployment artifact changed after handoff' in two and 'modified assets/app.js' in two, two
    (tmp_path / 'frontend' / 'dist' / 'assets' / 'app.js').write_text('console.log("v1")\n')
    assert 'PASS ' + sha1 in _ps(tmp_path, check, name='c3').stdout
    # a dirty backend file is not reviewed source
    (tmp_path / 'backend' / 'zargar' / 'app.py').write_text('print(2)  # local edit\n')
    dirty = _ps(tmp_path, check, name='c4').stdout
    assert 'REFUSED Deployment source is not the reviewed target' in dirty and 'uncommitted:' in dirty and 'backend/zargar/app.py' in dirty, dirty
    (tmp_path / 'backend' / 'zargar' / 'app.py').write_text('print(1)\n')
    # an IGNORED source file inside a shipped tree is unreviewed code the runtime would still load
    (tmp_path / 'frontend' / 'src' / 'patch.local.js').write_text('window.x = 1\n')
    ignored = _ps(tmp_path, check, name='c5').stdout
    assert 'REFUSED' in ignored and 'ignored source file present: frontend/src/patch.local.js' in ignored, ignored
    (tmp_path / 'frontend' / 'src' / 'patch.local.js').unlink()
    # HEAD that is not the reviewed target, and an expired handoff
    write_handoff(sha1, target='0' * 40)
    assert 'is not the reviewed target' in _ps(tmp_path, check, name='c6').stdout
    write_handoff(sha1, expires='2020-01-01T00:00:00+00:00')
    assert 'REFUSED Deployment handoff expired' in _ps(tmp_path, check, name='c7').stdout
    # a legacy handoff with only dist/index.html's hash is not enough evidence any more
    handoff.write_text(json.dumps({'target': head, 'expectedVersion': '0.7.78', 'artifactSha256': 'abc', 'expiresAt': '2099-01-01T00:00:00+00:00'}))
    assert 'carries no artifact manifest' in _ps(tmp_path, check, name='c8').stdout


def test_runtime_identity_and_receipt_are_shared_by_every_door(tmp_path):
    head = _repo(tmp_path)
    (tmp_path / 'scripts').mkdir()
    for s in ('deployment-lock.ps1', 'deploy.ps1', 'restart.ps1', 'start.ps1', 'watchdog.ps1'):
        (tmp_path / 'scripts' / s).write_bytes((SCRIPTS / s).read_bytes())
    _git(tmp_path, 'add', '-A'); _git(tmp_path, 'commit', '-q', '-m', 'scripts')
    head = _git(tmp_path, 'rev-parse', 'HEAD')
    out = _ps(tmp_path, """
        $i = Write-ZargarRuntimeIdentity $Root 'watchdog'
        $m = Get-ZargarArtifactManifest $Root
        Write-Output ("head=" + $i.head + " clean=" + $i.clean + " caller=" + $i.caller + " same=" + ($i.artifactManifestSha256 -eq $m.ManifestSha256) + " scripts=" + $i.scripts.Keys.Count)
        $env:ZARGAR_DEPLOY_CALLER = 'restart.ps1'
        $j = Get-ZargarRuntimeIdentity $Root
        Write-Output ("caller2=" + $j.caller + " same2=" + ($j.artifactManifestSha256 -eq $i.artifactManifestSha256))
        $file = Get-Content -LiteralPath (Join-Path $Root 'logs/runtime-identity.json') -Raw | ConvertFrom-Json
        Write-Output ("file-head=" + $file.head + " file-caller=" + $file.caller)
    """)
    assert out.returncode == 0, out.stdout + out.stderr
    assert f'head={head} clean=True caller=watchdog same=True scripts=5' in out.stdout, out.stdout
    assert 'caller2=restart.ps1 same2=True' in out.stdout and f'file-head={head} file-caller=watchdog' in out.stdout
    # every door dot-sources the ONE helper and goes through the ONE identity/receipt path
    restart, start, watchdog, deploy = [(SCRIPTS / s).read_text(encoding='utf-8') for s in ('restart.ps1', 'start.ps1', 'watchdog.ps1', 'deploy.ps1')]
    for text in (restart, start, watchdog, deploy):
        assert "deployment-lock.ps1'" in text
    assert 'Write-ZargarRuntimeIdentity $Root' in start, 'start.ps1 (the door under every path) stamps the identity before launching'
    assert 'Assert-ZargarHandoff' in restart and 'runtime-identity.json' in restart and 'Set-ZargarReceiptPhase' in restart
    assert 'ZARGAR_DEPLOY_CALLER' in watchdog and 'runtime-identity.json' in watchdog
    assert 'Get-ZargarArtifactManifest' in deploy and 'Set-ZargarReceiptPhase' in deploy and "'deferred'" in deploy
    assert 'Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $Root \'frontend/dist/index.html\')' not in restart, \
        'the restart handoff check must use the complete-artifact manifest, not dist/index.html alone'


def test_receipt_phases_are_terminal_never_left_building(tmp_path):
    (tmp_path / 'logs').mkdir()
    receipt = tmp_path / 'logs' / 'deployment-receipt.json'
    receipt.write_text(json.dumps({'ownerPid': 1, 'target': 'abc', 'expectedVersion': '0.7.78', 'phase': 'building', 'startedAt': 't0'}))
    out = _ps(tmp_path, """
        $r = Set-ZargarReceiptPhase $Root 'failed' 'Frontend build failed; runtime was not restarted.' 'deploy.ps1'
        Write-Output ("phase=" + $r.phase + " target=" + $r.target + " by=" + $r.completedBy + " detail=" + $r.detail + " has-completed=" + [bool]$r.completedAt)
        $r2 = Set-ZargarReceiptPhase $Root 'deferred' 'in flight: 1 analyst run' 'restart.ps1'
        Write-Output ("phase2=" + $r2.phase + " started=" + $r2.startedAt)
    """)
    assert out.returncode == 0, out.stdout + out.stderr
    assert 'phase=failed target=abc by=deploy.ps1 detail=Frontend build failed; runtime was not restarted. has-completed=True' in out.stdout
    assert 'phase2=deferred started=t0' in out.stdout
    saved = json.loads(receipt.read_text())
    assert saved['phase'] == 'deferred' and saved['expectedVersion'] == '0.7.78' and saved['completedAt']
    # no receipt yet: the terminal phase still lands (a deploy that failed before its build)
    receipt.unlink()
    fresh = _ps(tmp_path, "$r = Set-ZargarReceiptPhase $Root 'failed' 'TargetCommit must be the reviewed full commit hash.' 'deploy.ps1'; Write-Output ('phase=' + $r.phase)", name='fresh')
    assert 'phase=failed' in fresh.stdout and json.loads(receipt.read_text())['phase'] == 'failed'
