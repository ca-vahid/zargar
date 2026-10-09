# Moving Zargar to another Windows machine

Written 2026-10-08. Applies to the whole app: engine + API, the Postgres database, the Discord intake, the IBKR paper
link, the public URL and the Claude Code history of this project. The package is built by
`scripts\export-machine.ps1` and restored by `scripts\import-machine.ps1`; this file travels in the package as
`RESTORE.md`.

**Claude on the new machine: read this whole file first, then do the steps in order. Never start the app on the new
machine while it can still run on the old one** (two engines = duplicate orders at IBKR and duplicate Discord intake).

## What moves, and how

| Piece | How it moves | Notes |
|---|---|---|
| Code, every branch | `repo\zargar.bundle` (git bundle `--all`) | origin is reset to GitHub after the clone |
| Uncommitted work in worktrees | `repo\worktrees\*.patch` (+ `-untracked.zip`) | dirty worktrees, and the ones a Claude session lives in, are recreated at the same path |
| Database (all books, orders, events, settings, tips knowledge, Scout data, bars) | `db\zargar.dump` (`pg_dump -Fc`) | row counts of 14 tables are checked after the restore |
| Secrets and runtime files | `files\` (`backend\.env`, `docker-compose.override.yml`, gateway ledger, `discord_media`, logs) | `.env` holds every API key - see "Secrets" below |
| Claude Code chat history and memory | `claude\projects\C--Cursor-zargar*` (11 folders, about 1 GB) | `claude --resume` lists the old sessions; the memory folder loads automatically |
| Claude prompt history, settings, skills | `claude\history.jsonl`, `settings*.json`, `skills\`, `plans\` | `~/.claude.json` comes as `claude.json.reference` and is merged by hand |
| Scheduled tasks (watchdog, restart doors, WSL cache drop, EM checks, Tips verify) | `machine\tasks\*.xml` | registered DISABLED; enabled in step 7 |
| `C:\ProgramData\Zargar` (task scripts, settings snapshots) | `machine\ProgramData-Zargar` | |
| IB Gateway configuration | `machine\ibgateway\*.ini` | reference only - the gateway is reinstalled and you sign in |
| Tailscale public URL | `machine\tailscale-*.json` | reference - the new machine joins the tailnet and takes the old name |
| Python/Node versions | `machine\pip-freeze-*.txt`, `manifest.json` | the venvs are rebuilt with the exact versions |

**What does not move:** the Claude Code login (`.credentials.json` - sign in again), the GitHub CLI login, Windows
credentials and browser sessions, other projects' Docker containers, the throwaway test databases (`zargar_test_*`,
the tests recreate them), `node_modules` and the venvs (rebuilt). Cloud and Remote Control Claude sessions belong to
your account and appear on any machine.

## Secrets

The package contains `backend\.env` (Anthropic, OpenAI, SnapTrade, Alpaca, Discord bot, Google sign-in, Telegram) and
the database (VAPID push keys and the settings). Install 7-Zip on the old machine: the export then writes one AES-256
`.7z` with hidden file names and asks for a password. Without 7-Zip it is a plain folder. Either way:
- move it on a USB drive you control (BitLocker To Go) or over your own network - never through a cloud sync folder,
  email or chat;
- delete it from the drive and the new machine once the restore checks pass.

## Step 1 - prepare the new machine (any time before the move)

Install, matching the old machine where it matters:
- Git, PowerShell 7, **Python 3.13** (the old machine runs 3.13.7; tick "Add to PATH"), **Node 20** (20.19.5),
  Docker Desktop (WSL 2 backend), 7-Zip
- Claude Code (then `claude` and sign in), GitHub CLI (`gh auth login`), and
  `git config --global user.name "Mr Vahid"` plus your email
- Tailscale (do NOT sign in yet - step 5)
- IB Gateway **10.50** (stable), installed to `C:\Jts` (do NOT sign in yet - step 5)
- Use the same folder: **`C:\Cursor\zargar`**. Claude's history is keyed by the folder path; another path works (the
  import renames the history folders and fixes the task paths) but the same path is simplest.

## Step 2 - optional rehearsal on the old machine

From the elevated terminal that owns the app: `scripts\export-machine.ps1 -Dest E:\zargar-move`. The app keeps
running. This tells you the size (about 8-10 GB with Discord media; `-SkipMedia` leaves out ~4 GB of attachments)
and how long the dump takes. A rehearsal package can be imported on the new machine to test everything EXCEPT going
live - but delete it afterwards and use the final export for the real move.

## Step 3 - cutover on the old machine (after 16:15 ET or on a weekend)

1. Check that every position has its stop: IBKR paper holds share positions with GTC stops resting AT IBKR, so they
   stay protected while the app is off. Practice positions are simulated and simply wait.
2. Elevated terminal: `scripts\export-machine.ps1 -Dest E:\zargar-move -Final`. It refuses during market hours,
   **disables every Zargar scheduled task** (so the watchdog cannot bring the app back), stops the app and its helper
   windows, then exports.
3. IB Gateway: **log out** on the old machine (IBKR allows one session per username).
4. Tailscale admin console (https://login.tailscale.com/admin/machines): rename the old machine away from
   `zargar-desk` (or remove it), so the new machine can take that name. The public URL
   `https://zargar-desk.tail97d481.ts.net` then moves with the name, and Google sign-in and the phones' push
   subscriptions keep working unchanged.
5. Leave the old machine off, or at least never start Zargar on it again.

## Step 4 - import on the new machine

Copy the package, unpack the `.7z` if you made one, then from an **elevated** PowerShell with Docker Desktop running:

    powershell -ExecutionPolicy Bypass -File <package>\import-machine.ps1 -From <package>

It verifies every checksum, clones the repo from the bundle (all branches, origin = GitHub), recreates the dirty and
Claude-session worktrees, restores the runtime files, starts Postgres (host port 5433, from the override file),
restores the database and **checks the row counts** against the old machine, rebuilds both Python venvs with the
exact versions, runs `npm ci` + the frontend build, restores the Claude history/memory/skills, copies
`C:\ProgramData\Zargar`, and registers the scheduled tasks **disabled**. Nothing trades and the app is not started.

## Step 5 - sign-ins and external access (you)

1. **Tailscale**: sign in with the personal tailnet account (visper@gmail.com). Rename this machine to `zargar-desk`
   in the admin console. Then re-create the public URL (check `machine\tailscale-serve.json` for the exact old setup):

       & "C:\Program Files\Tailscale\tailscale.exe" serve --bg 8420
       & "C:\Program Files\Tailscale\tailscale.exe" funnel --bg 8420

   Funnel DNS can take about 15 minutes. `tailscale.exe` is not on PATH - use the full path.
2. **Google sign-in**: nothing to do if the URL is the same. If the name changed, add the new
   `https://<name>.tail97d481.ts.net` origin to the OAuth client in Google Cloud project `zargar-sso-jmgibv`.
3. **IB Gateway**: sign in to the PAPER account. Configure > API > Settings: socket port **4002**, "Allow connections
   from localhost only" on, trusted IP `127.0.0.1`, "Read-Only API" OFF (the app places paper orders; client id 17 is
   the app). Compare with `machine\ibgateway\*.ini`.
4. Keep `ZARGAR_IBKR_QUOTES` unset (as before).

## Step 6 - first start and checks (Claude can do this part)

1. Start the app once: `scripts\start.ps1 -Detach` from an elevated terminal.
2. Check, and do not go on until every item passes:
   - `http://127.0.0.1:8420/api/health`: `ok`, the version in `manifest.json`, the armed plans restored
     (`start.ps1` runs the restore check itself);
   - `cd backend; .venv\Scripts\python.exe -m zargar.tools.ibkr_check`: connected to the paper account;
   - the app's IBKR paper positions and cash match IBKR, and every held quantity has its GTC stop at IBKR;
   - Discord intake live: `GET /api/tip/intake/liveness` (start `scripts\discord-intake.ps1` if `start.ps1` did not);
   - the public URL loads and Google sign-in works from your phone; a test push arrives;
   - the Tips page, the Scout page and the Ledger show the same numbers as before the move.

## Step 7 - turn the automation back on

Enable the tasks once step 6 passed: `ZargarWatchdog`, `ZargarRestart`, `ZargarRestartOverride`,
`ZargarUnelevatedStart`, `ZargarWslCacheDrop`, `ZargarTipsVerify`, and the EM desk's `ZargarEm*` tasks:

    Get-ScheduledTask -TaskName "Zargar*" | Enable-ScheduledTask

Check `ZargarWatchdog` runs (Task Scheduler history) and that `C:\ProgramData\Zargar` paths in the task actions
exist.

## Step 8 - Claude Code

- Open Claude Code in `C:\Cursor\zargar`; `claude --resume` lists this project's old sessions, and the memory index
  (`MEMORY.md`) loads by itself.
- Compare `claude.json.reference` with the new `~/.claude.json` and copy over the project entries you want (trusted
  folders, allowed tools, MCP servers) - never overwrite the whole file (it holds the new machine's account state).
- Session cron jobs (the market-hours checks) do not move - ask the Tips session to schedule them again.

## Afterwards

- Delete the package from the USB drive and the new machine.
- After a week on the new machine without problems, wipe the old machine's `backend\.env` and the Docker volume
  `zargar_zargar_pgdata`, so two copies of the keys and the books do not linger.

## If something fails

- Checksum mismatch: copy the package again.
- Row counts differ: run the import again with the database step only (drop the `zargar` database, or recreate the
  container volume, first) - the dump is not modified by a failed restore.
- A worktree patch does not apply: the branch is still in the bundle; the patch is in `repo\worktrees\` to apply by hand.
- A scheduled task does not register (another user/SID): register it from its XML in Task Scheduler, Import Task.
