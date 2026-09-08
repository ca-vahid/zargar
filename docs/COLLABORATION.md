# Claude / Codex collaboration

Shared instructions live in [AGENTS.md](../AGENTS.md); [CLAUDE.md](../CLAUDE.md)
retains project context and trading rules. Both agents read both files.

Current release checkpoint: [Options Cartel handoff](techniques/options-cartel/RELEASE-HANDOFF.md).
The dated PID and test observations below are historical; use the current pid file
and verify the process command line before operating the isolated preview.

## Current status (2026-09-06, after permission update)

2026-09-07 execution-desk verification: only the owned Codex preview was refreshed
for the money-mode runtime and UI. Latest launcher PID observed: 55344; recheck
the pid file and command line before operating. Synthetic plans for 2026-09-08
were used to verify auto/proposal arming, pause/resume and shared Armed display.
Every fixture was disarmed; no preview orders or positions were created. Practice
workspace and blank integration credentials were preserved. The source fixture
records are explicitly labeled synthetic and are not performance evidence.

2026-09-07 prior-mark recovery verification: owned preview launcher PID 85100
(recheck ownership before operating). Only the Codex preview was refreshed after
confirming isolated sim configuration, blank integration credentials and zero
execution state. It remains in Practice with zero orders, managed positions and
armed plans. Build, focused mark tests and the ten-case mobile audit passed.

2026-09-07: the owned preview was refreshed for the Cartel daily-risk report/card
after verifying zero orders, managed positions and armed plans, and unchanged
sim/loopback configuration with blank integration credentials. Latest launcher
PID observed: 79820; recheck `.cache/cartel-preview.pid` and process ownership
before operating. The preview remains in Practice. A workspace confirmation was
cancelled during UI verification; no live routing or trading was activated.

Latest owned preview refresh loaded residual recovery and the September video
scanner profile. Launcher PID: 147448 (historical observation; recheck ownership
before operating). Only the verified Codex port-8421 process was restarted.
Browser collection of MU with the video profile succeeded; `zargar_dev_codex`
still had zero orders, managed positions and armed plans afterward. Integration
credentials were checked blank and effective config remained sim/loopback8421.

Later UI verification provisioned `zargar_dev_codex` on the Codex PostgreSQL
container and started an isolated sim preview at `http://127.0.0.1:8421`.
Launcher PID was 170272, listener PID 46572 at verification (recheck before
operating on a process; PID values are historical evidence, not permanent ids).
The owned preview was subsequently restarted to load the scanner-image profile;
the new launcher PID was 53700. Only the verified port-8421 child of the prior
Codex launcher was stopped, after confirming zero order rows in this preview DB.
`.cache/cartel-preview.pid`, `.cache/cartel-preview.stdout.log` and
`.cache/cartel-preview.stderr.log` identify this task's preview. Database/broker/
port and blank integration credentials were asserted before launch. This is the
only app process started by Codex; no existing runtime/worktree was altered.
The preview database contains explicitly labeled synthetic UI test records plus
a real read-only MU analysis; it had zero order rows after UI verification.
The following initial setup notes describe the earlier state before this preview.

The earlier permission blockers below are historical: after the session's
permissions changed, WSL enumeration, Python temporary-directory writes, and
Node child-process pipes all passed without code or ACL changes. Docker Desktop
and its WSL backend were started successfully. The separate Codex test container
is healthy, and `zargar_test_codex` was created and verified on loopback 5433.

Backend `pip install -e './backend[dev]'`, `pip check`, frontend `npm ci`, and
`npm run build` passed. Vite reported non-fatal mixed-import and large-chunk
warnings. The Codex Vite configuration was loaded and verified: strict port
5174, API and WebSocket proxies to 8421. Local runtime configuration was checked
for the reserved `zargar_dev_codex` database, sim broker/quotes, port 8421, and
blank integration credentials. No interactive trading runtime was launched.

The full backend suite ran sequentially via `test-codex.ps1`: **664 passed,
47 failed, 4 warnings in 601.36 seconds**. Most failures exposed an undeclared
runtime dependency: `technique/render.py` imports matplotlib, but pyproject.toml
did not include it. Matplotlib is now declared and installed; `pip check` passes.
Rerunning all 47 failures with `--lf -q --tb=short` produced **44 passed,
3 failed in 184.09 seconds**. Thus 708 distinct tests have passed across the
two runs; this is not a claim of a subsequent all-green full-suite run.

Remaining failures, outside the collaboration/dependency setup:

- `tests/test_daily_loss.py::test_traded_portfolio_still_halts`: expects the
  global `engine.halt.engaged`, whereas the current default
  `risk.daily_loss_halt_scope` is `portfolio`.
- `tests/test_platform_phase3.py::test_every_journaled_kind_has_a_contract`:
  `TechniqueLossHalt` is journaled but missing from `research/events_contract.py`.
- `tests/test_technique_api.py::test_chart_png_endpoint_on_sim_symbol`:
  `RuntimeError: Event loop is closed` in the HTTPX/AnyIO connection cleanup
  reached through the Yahoo history/chart path. Reproduced in both test runs.

Logs: `.cache/backend-tests.log` (full run), `.cache/backend-tests-retry.log`
(failed-test rerun), and `.cache/backend-install-matplotlib.log` (dependency fix).
Reproduce remaining failures: `scripts/test-codex.ps1 --lf -v --tb=short`.
Use verbose output for visible per-test progress when redirecting logs.
No terminal intervention remains necessary for setup. Runtime trading code,
the npm lockfile, and existing Claude checkouts are unchanged. Docker and the
healthy test-only PostgreSQL container remain running; no app was started.

## Ownership and ports

| Resource | Existing Claude / user setup | Codex setup |
|---|---|---|
| Checkout | `C:\Cursor\zargar` and its `.claude/worktrees/*` | `C:\Cursor\zargar-codex` |
| Branch | Preserve each existing branch / detached checkout | `codex/zargar-development`, based on `origin/main` |
| API / engine | `8420` reserved | `8421` reserved, not started |
| Vite UI | `5173` reserved | `5174`, strict port, proxies only to `8421` |
| Runtime DB | Existing `zargar`, never use for Codex | `zargar_dev_codex` reserved, not provisioned |
| Disposable tests | Existing `zargar_test*` databases, preserve | `127.0.0.1:5433/zargar_test_codex` |

Port reservations apply even when no listener is visible. Recheck before launch;
never stop an unknown owner to free a port. A separate API port does not isolate
a trading engine from persisted positions/settings. Do not run the generic
`setup.ps1`, `start.ps1`, or `stop.ps1` in this worktree.

## Setup (PowerShell, from the Codex root)

```powershell
# With Docker Desktop running; creates a separate test-only container if 5433 is free.
.\scripts\setup-codex.ps1 -StartTestPostgres

# If the shared PostgreSQL test server already exists on 5433:
.\scripts\setup-codex.ps1

# Sequential tests; the wrapper sets the database override in the process environment.
.\scripts\test-codex.ps1 tests/test_engine_flow.py tests/test_api_and_pipeline.py -q
# Full suite, when needed:
.\scripts\test-codex.ps1 -q
```

The DB helper creates only `zargar_test_codex` if absent, then verifies a connection
to that database. It never drops a database or starts an engine. The optional
Compose file has its own project, container (`zargar-codex-test-db`), and volume;
it is never layered over the runtime Compose file. If 5433 is occupied, setup
uses the existing server and fails on connection/authentication errors instead
of replacing it. Local development credentials are `zargar` / `zargar`.

`backend/tests/conftest.py` reads `ZARGAR_TEST_DATABASE_URL` from the actual
environment, not `.env`. Always use the wrapper; its fixtures drop and recreate
tables. Run only one suite at a time per database. The wrapper restores the
caller's environment afterward. Keep `backend/.env` free of integration keys.

Dependencies belong in `backend/.venv` and `frontend/node_modules` in this
checkout. No dependency or Git checkout changes belong in Claude's folders.
If a partial venv is missing pip, `uv pip install --python
backend/.venv/Scripts/python.exe --cache-dir .cache/uv pip` can bootstrap it.

For future UI development against an independently provisioned sim runtime:

```powershell
cd frontend
npm run dev -- --config vite.codex.config.ts
```

This starts only Vite; its API will be unavailable until the separate backend
exists. The ignored local `backend/.env` selects `zargar_dev_codex`, sim broker
and quotes, loopback `8421`, and CORS for `5174`. It deliberately points to an
unprovisioned runtime database so ordinary backend commands cannot silently
attach to the existing runtime or the disposable test database. A future
runtime must have its own empty database, no inherited integration credentials,
and checked effective `AppConfig`; never copy the existing runtime DB or `.env`.

## Initial assessment (2026-09-06)

- GitHub HEAD resolves to `refs/heads/main` at
  `75016774b14c66eb7c839df215da8fe5e4be3853`, matching this checkout and its
  `origin/main` tracking ref. All six pre-existing Claude checkouts were preserved.
- Git requires a command-scoped `safe.directory` here because the checkout is
  owned by Administrators. HTTPS verification worked with command-scoped
  `-c http.sslBackend=openssl`; default Schannel failed acquiring credentials.
  No global Git configuration was changed.
- No listeners were visible on 5432, 5433, 8420, 8421, 5173, or 5174 via
  `netstat`. `Get-NetTCPConnection` was access denied. Neither configured Docker
  endpoint was available, including after requesting a hidden Docker Desktop
  launch. Existing runtime availability therefore could not be verified.
- See the setup verification report below for checks and outstanding blockers.

## Setup verification (2026-09-06)

Passed: Git branch/default-branch checks; PowerShell and Python helper syntax;
isolated Compose configuration validation; frontend TypeScript check, including
the separate Codex Vite config; `git diff --check`. The npm lockfile is unchanged.
The local `.env` exists and is ignored. No trading engine was launched and no
existing worktree or database was modified.

Incomplete due to this session's environment:

- `backend/.venv` exists with pip, setuptools, wheel, packaging, and asyncpg.
  Full `.[dev]` installation failed with Windows permission errors in temporary
  build directories (both pip and uv attempted). Backend tests could not run.
- Frontend packages installed with lifecycle scripts disabled after normal
  `npm ci` hit `spawn EPERM`. TypeScript passes, but the Vite build hits the same
  error starting esbuild. Re-run normal `npm ci` and the build in a shell with
  the required process permissions.
- `zargar_test_codex` has **not been created**: the explicit isolated Compose
  startup could not reach Docker Desktop, and a direct asyncpg connection to
  `127.0.0.1:5433` was refused. The runtime DB reservation is also unprovisioned.

Remaining: make Docker Desktop's Linux engine available and use a shell with
working temporary-directory and child-process permissions. Then run
`scripts/setup-codex.ps1 -StartTestPostgres` and the targeted test command above.
These commands install/provision/verify the test environment without starting
the trading app. UI/browser and live-runtime verification remain unperformed.

## Follow-up permission diagnosis (2026-09-06)

The user confirmed Docker/WSL had been manually stopped to free memory and
authorized starting them again. A hidden Docker Desktop launch from the agent
was attempted, but the process did not remain running and no engine pipe appeared.

Observed independently of application code:

| Check | Result |
|---|---|
| Windows `WslService` | Running; service is installed |
| `wsl --list --verbose` | `Wsl/EnumerateDistros/Service/E_ACCESSDENIED` |
| `com.docker.service` | Installed, stopped, Manual start; this alone does not diagnose the WSL backend |
| `docker desktop status` | Cannot create logs under `%LOCALAPPDATA%\Docker\log\host`: access denied |
| Python ordinary workspace subfolder | Write succeeds |
| Python 3.13 `tempfile.mkdtemp` inside the same workspace | Folder created but writing inside it is denied |
| Node child process with inherited stdio | Succeeds |
| Same Node child process with piped stdio | `spawn EPERM` |
| Backend install retry | Permission denied in pip's temporary build tracker |
| Build retry | TypeScript passes; esbuild child-process pipes fail with `EPERM` |
| Targeted test retry | Stops before collection: `No module named pytest` |

This establishes both a stopped Docker engine and permission failures in the
restricted agent session. The temp-folder/pipe failures strongly implicate the
sandbox/token boundary rather than Zargar dependencies; confirmation outside
the sandbox requires the user's terminal. Python's installed `tempfile.py`
creates these directories with mode `0o700`. No ACLs, sandbox policies, service
configuration, runtime processes, or Claude checkouts were changed.
OpenAI documents restricted Windows tokens and ACL boundaries in its
[Windows sandbox guide](https://learn.chatgpt.com/docs/windows/windows-sandbox).
The active session does not permit elevation requests.

Run these in the user's own PowerShell terminal (ordinary user session first):

```powershell
Set-Location 'C:\Cursor\zargar-codex'
Start-Process -FilePath 'C:\Program Files\Docker\Docker\Docker Desktop.exe' -WindowStyle Hidden

# Wait at most 3 minutes for Docker's Linux engine. Do not restart/stop anything.
$dockerReady = $false
for ($attempt = 0; $attempt -lt 36; $attempt++) {
    docker --context desktop-linux info *> $null
    if ($LASTEXITCODE -eq 0) { $dockerReady = $true; break }
    Start-Sleep -Seconds 5
}
if (-not $dockerReady) { throw 'Docker Desktop did not become ready; inspect its startup error.' }

powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup-codex.ps1 -StartTestPostgres
if ($LASTEXITCODE -ne 0) { throw 'Setup failed; keep the error output for diagnosis.' }
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\test-codex.ps1 -q
if ($LASTEXITCODE -ne 0) { throw 'Backend tests failed; keep the failure summary for diagnosis.' }
```

Setup installs backend/frontend dependencies, creates/verifies only
`zargar_test_codex`, and runs the frontend production build. The final command
runs the full backend suite sequentially in that database. It does not start an
interactive trading app. No global permission changes or Administrator shell
are prescribed; if these fail in the normal terminal too, investigate those
specific host errors before changing system security.
