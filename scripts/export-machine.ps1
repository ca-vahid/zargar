# Export EVERYTHING Zargar needs to run on another Windows machine - one folder (optionally one encrypted .7z).
# The restore side is scripts\import-machine.ps1 + docs\MIGRATION.md (copied into the package as RESTORE.md).
#
#   scripts\export-machine.ps1 -Dest E:\zargar-move                  rehearsal: the app keeps running (DB dump is a
#                                                                      consistent snapshot, but later changes are not in it)
#   scripts\export-machine.ps1 -Dest E:\zargar-move -Final           CUTOVER: refuses during market hours, disables every
#                                                                      Zargar scheduled task (so the watchdog cannot restart
#                                                                      it), stops the app + helpers, THEN exports
#   -SkipMedia     leave backend\discord_media (~4 GB of Discord attachments) out
#   -NoArchive     do not build the .7z even when 7-Zip is installed
#
# Run it from the ELEVATED terminal that owns the app (stop.ps1's rule). The package holds SECRETS (backend\.env API
# keys, the database's settings) - keep it on a drive you control, delete it after the import.
param(
  [Parameter(Mandatory = $true)][string]$Dest,
  [switch]$Final,
  [switch]$SkipMedia,
  [switch]$NoArchive
)
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ClaudeDir = Join-Path $env:USERPROFILE ".claude"
function Step($m) { Write-Host "> $m" -ForegroundColor Cyan }
function Warn($m) { Write-Host "! $m" -ForegroundColor Yellow }
function Fail($m) { Write-Host "x $m" -ForegroundColor Red; exit 1 }

$stamp = Get-Date -Format "yyyyMMdd-HHmm"
$Pkg = Join-Path $Dest "zargar-package-$stamp"
New-Item -ItemType Directory -Force -Path $Pkg | Out-Null
$manifest = [ordered]@{ createdAt = (Get-Date).ToString("o"); machine = $env:COMPUTERNAME; user = $env:USERNAME
                        repoPath = $Root; final = [bool]$Final; parts = [ordered]@{} }

# ---- 0. cutover: nothing may change after the dump --------------------------------------------------------------
if ($Final) {
  $et = [System.TimeZoneInfo]::ConvertTimeBySystemTimeZoneId([DateTime]::UtcNow, "Eastern Standard Time")
  $mins = $et.Hour * 60 + $et.Minute
  if ($et.DayOfWeek -notin "Saturday", "Sunday" -and $mins -ge 9 * 60 + 15 -and $mins -le 16 * 60 + 15) {
    Fail "market hours (ET $($et.ToString('HH:mm'))): run -Final after 16:15 ET or on a weekend"
  }
  Step "Disabling every Zargar scheduled task (the watchdog would restart the app)"
  $tasks = @(Get-ScheduledTask | Where-Object { $_.TaskName -like "Zargar*" })
  foreach ($t in $tasks) { Disable-ScheduledTask -TaskName $t.TaskName -TaskPath $t.TaskPath | Out-Null }
  $manifest.disabledTasks = @($tasks | ForEach-Object { $_.TaskName })
  Step "Stopping the app and its helper windows"
  & powershell -ExecutionPolicy Bypass -File (Join-Path $Root "scripts\stop.ps1") -Force
  if ($LASTEXITCODE -ne 0) { Fail "stop.ps1 failed (exit $LASTEXITCODE) - the app must be stopped for a final export" }
}

# ---- 1. code: every branch + every local change ------------------------------------------------------------------
Step "Git: bundle of every branch, plus the uncommitted changes of each worktree"
$repoOut = Join-Path $Pkg "repo"; New-Item -ItemType Directory -Force -Path $repoOut | Out-Null
git -C $Root bundle create (Join-Path $repoOut "zargar.bundle") --all 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { Fail "git bundle failed" }
$wtOut = Join-Path $repoOut "worktrees"; New-Item -ItemType Directory -Force -Path $wtOut | Out-Null
$wts = @(); $cur = $null
foreach ($line in (git -C $Root worktree list --porcelain)) {
  if ($line -like "worktree *") { $cur = [ordered]@{ path = $line.Substring(9) }; $wts += $cur }
  elseif ($line -like "HEAD *" -and $cur) { $cur.head = $line.Substring(5) }
  elseif ($line -like "branch *" -and $cur) { $cur.branch = $line.Substring(7) -replace '^refs/heads/', '' }
}
$dirty = 0
foreach ($w in $wts) {
  if (-not (Test-Path $w.path)) { $w.missing = $true; continue }
  $st = git -C $w.path status --porcelain 2>$null
  if (-not $st) { continue }
  $dirty++
  $name = ($w.path -replace '[:\\/ ]', '_').Trim('_')
  git -C $w.path diff HEAD --binary > (Join-Path $wtOut "$name.patch")
  $untracked = @(git -C $w.path ls-files --others --exclude-standard)
  if ($untracked.Count -gt 0) {
    $zip = Join-Path $wtOut "$name-untracked.zip"
    Push-Location $w.path
    try { Compress-Archive -Path $untracked -DestinationPath $zip -Force } catch { Warn "untracked files of $($w.path): $($_.Exception.Message)" }
    Pop-Location
  }
  $w.dirty = $true; $w.patch = "$name.patch"
}
$wts | ConvertTo-Json -Depth 4 | Set-Content (Join-Path $repoOut "worktrees.json") -Encoding utf8
$manifest.parts.repo = @{ head = (git -C $Root rev-parse HEAD); branch = (git -C $Root branch --show-current)
                          worktrees = $wts.Count; dirtyWorktrees = $dirty; remote = (git -C $Root remote get-url origin) }

# ---- 2. files git does not track (secrets, Discord ledger, media, logs) -------------------------------------------
Step "Untracked runtime files (backend\.env, gateway ledger, media, logs)"
$filesOut = Join-Path $Pkg "files"
$keep = @("backend\.env", "docker-compose.override.yml", "backend\gateway_cursors.json", "backend\gateway_spool.jsonl",
          "backend\gateway_status.json", "backend\discord_dms.jsonl", "backend\finpages.txt", "backend\em_ingest_media",
          "backend\logs", "logs", "technique-reviews", "frontend\art-src",
          "docs\techniques\team2\notes\research\week37-author-charts")
if (-not $SkipMedia) { $keep += "backend\discord_media" }
$copied = @()
foreach ($rel in $keep) {
  $src = Join-Path $Root $rel
  if (-not (Test-Path $src)) { continue }
  $dst = Join-Path $filesOut $rel
  if ((Get-Item $src).PSIsContainer) {
    robocopy $src $dst /E /R:1 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { Fail "robocopy $rel failed ($LASTEXITCODE)" }
  } else {
    New-Item -ItemType Directory -Force -Path (Split-Path $dst) | Out-Null
    Copy-Item $src $dst -Force
  }
  $copied += $rel
}
# the zargar log files next to the package (zargar-8420.log*) - evidence, small
Get-ChildItem (Join-Path $Root "backend") -Filter "zargar-84*.log*" -ErrorAction SilentlyContinue | ForEach-Object {
  New-Item -ItemType Directory -Force -Path (Join-Path $filesOut "backend") | Out-Null
  Copy-Item $_.FullName (Join-Path $filesOut "backend\$($_.Name)") -Force
}
$envKeys = @()
if (Test-Path (Join-Path $Root "backend\.env")) {
  $envKeys = @(Get-Content (Join-Path $Root "backend\.env") | Where-Object { $_ -match '^\s*[A-Z_][A-Z0-9_]*=' } |
               ForEach-Object { ($_ -split '=', 2)[0].Trim() })
}
$manifest.parts.files = @{ copied = $copied; skippedMedia = [bool]$SkipMedia; envKeyNames = $envKeys }

# ---- 3. the database ------------------------------------------------------------------------------------------------
Step "Database: pg_dump of 'zargar' (custom format, compressed) - this takes a while"
$dbOut = Join-Path $Pkg "db"; New-Item -ItemType Directory -Force -Path $dbOut | Out-Null
docker exec zargar-db sh -c "pg_dump -U zargar -d zargar -Fc -Z 6 -f /tmp/zargar.dump" 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { Fail "pg_dump failed" }
docker cp zargar-db:/tmp/zargar.dump (Join-Path $dbOut "zargar.dump") | Out-Null       # docker cp: never a PS pipe (binary)
docker exec zargar-db rm -f /tmp/zargar.dump | Out-Null
$counts = [ordered]@{}
foreach ($t in "events", "orders", "executions", "portfolios", "positions", "managed_positions", "proposals", "signals",
               "settings", "tip_notes", "technique_runs", "bars", "chat_messages", "scout_filings") {
  $n = docker exec zargar-db psql -U zargar -d zargar -tAc "select count(*) from $t" 2>$null
  if ($LASTEXITCODE -eq 0) { $counts[$t] = [int64]("$n".Trim()) }
}
$manifest.parts.db = @{ file = "db\zargar.dump"; image = (docker inspect zargar-db --format "{{.Config.Image}}")
                        sizeOnDisk = (docker exec zargar-db psql -U zargar -d zargar -tAc "select pg_size_pretty(pg_database_size('zargar'))").Trim()
                        rowCounts = $counts }

# ---- 4. Claude Code: chat history, memory, settings, skills -------------------------------------------------------
Step "Claude Code: this project's sessions + memory, prompt history, settings, skills"
$cOut = Join-Path $Pkg "claude"; New-Item -ItemType Directory -Force -Path (Join-Path $cOut "projects") | Out-Null
$projDirs = @(Get-ChildItem (Join-Path $ClaudeDir "projects") -Directory | Where-Object { $_.Name -like "*zargar*" })
foreach ($d in $projDirs) {
  robocopy $d.FullName (Join-Path $cOut "projects\$($d.Name)") /E /R:1 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null
}
foreach ($f in "history.jsonl", "settings.json", "settings.local.json", "statusline-command.sh") {
  $p = Join-Path $ClaudeDir $f
  if (Test-Path $p) { Copy-Item $p (Join-Path $cOut $f) -Force }
}
foreach ($d in "skills", "plans") {
  $p = Join-Path $ClaudeDir $d
  if (Test-Path $p) { robocopy $p (Join-Path $cOut $d) /E /R:1 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null }
}
$pl = Join-Path $ClaudeDir "plugins"
if (Test-Path $pl) {
  New-Item -ItemType Directory -Force -Path (Join-Path $cOut "plugins") | Out-Null
  Get-ChildItem $pl -Filter *.json | ForEach-Object { Copy-Item $_.FullName (Join-Path $cOut "plugins\$($_.Name)") -Force }
}
$cj = Join-Path $env:USERPROFILE ".claude.json"
if (Test-Path $cj) { Copy-Item $cj (Join-Path $cOut "claude.json.reference") -Force }   # merged by hand, never overwritten
$manifest.parts.claude = @{ projectDirs = @($projDirs | ForEach-Object { $_.Name })
                            note = ".credentials.json is NOT exported - sign in to Claude Code on the new machine" }

# ---- 5. machine-level pieces: ProgramData, scheduled tasks, IB Gateway config, Tailscale -----------------------------
Step "Machine pieces: C:\ProgramData\Zargar, scheduled tasks, IB Gateway config, Tailscale config"
$mOut = Join-Path $Pkg "machine"; New-Item -ItemType Directory -Force -Path $mOut | Out-Null
if (Test-Path "C:\ProgramData\Zargar") {
  robocopy "C:\ProgramData\Zargar" (Join-Path $mOut "ProgramData-Zargar") /E /R:1 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null
}
$tOut = Join-Path $mOut "tasks"; New-Item -ItemType Directory -Force -Path $tOut | Out-Null
foreach ($t in @(Get-ScheduledTask | Where-Object { $_.TaskName -like "Zargar*" })) {
  Export-ScheduledTask -TaskName $t.TaskName -TaskPath $t.TaskPath | Set-Content (Join-Path $tOut "$($t.TaskName).xml") -Encoding unicode
}
$iOut = Join-Path $mOut "ibgateway"; New-Item -ItemType Directory -Force -Path $iOut | Out-Null
Get-ChildItem "C:\Jts" -Recurse -Include *.ini, *.vmoptions -ErrorAction SilentlyContinue |
  ForEach-Object { Copy-Item $_.FullName (Join-Path $iOut (($_.FullName.Substring(7)) -replace '[\\/]', '__')) -Force }
$ts = "C:\Program Files\Tailscale\tailscale.exe"
if (Test-Path $ts) {
  & $ts status --json 2>$null | Set-Content (Join-Path $mOut "tailscale-status.json") -Encoding utf8
  & $ts serve status --json 2>$null | Set-Content (Join-Path $mOut "tailscale-serve.json") -Encoding utf8
  & $ts funnel status 2>$null | Set-Content (Join-Path $mOut "tailscale-funnel.txt") -Encoding utf8
}
$venv = Join-Path $Root "backend\.venv\Scripts\python.exe"
$tool = [ordered]@{ os = (Get-CimInstance Win32_OperatingSystem).Caption; python = (& $venv --version 2>&1) -join ""
                    node = (node --version 2>$null); npm = (npm --version 2>$null); docker = (docker --version 2>$null)
                    git = (git --version) }
& $venv -m pip freeze 2>$null | Set-Content (Join-Path $mOut "pip-freeze-venv.txt") -Encoding utf8
$vi = Join-Path $Root "backend\.venv-ingest\Scripts\python.exe"
if (Test-Path $vi) { & $vi -m pip freeze 2>$null | Set-Content (Join-Path $mOut "pip-freeze-venv-ingest.txt") -Encoding utf8 }
$manifest.parts.machine = $tool
try { $manifest.appVersion = (Invoke-RestMethod http://127.0.0.1:8420/api/health -TimeoutSec 3).version } catch {
  $manifest.appVersion = ((Get-Content (Join-Path $Root "backend\zargar\__init__.py") | Select-String '__version__') -replace '.*"(.*)".*', '$1')
}

# ---- 6. the runbook + checksums ----------------------------------------------------------------------------------------
Copy-Item (Join-Path $Root "docs\MIGRATION.md") (Join-Path $Pkg "RESTORE.md") -Force
Copy-Item (Join-Path $Root "scripts\import-machine.ps1") (Join-Path $Pkg "import-machine.ps1") -Force
$manifest | ConvertTo-Json -Depth 6 | Set-Content (Join-Path $Pkg "manifest.json") -Encoding utf8
Step "Checksums (SHA256 of every file)"
$base = (Resolve-Path $Pkg).Path
Get-ChildItem $Pkg -Recurse -File | Where-Object { $_.Name -ne "SHA256SUMS.txt" } | ForEach-Object {
  "{0}  {1}" -f (Get-FileHash $_.FullName -Algorithm SHA256).Hash, $_.FullName.Substring($base.Length + 1)
} | Set-Content (Join-Path $Pkg "SHA256SUMS.txt") -Encoding utf8
$size = (Get-ChildItem $Pkg -Recurse -File | Measure-Object Length -Sum).Sum / 1GB

# ---- 7. optional encrypted archive -------------------------------------------------------------------------------------
$7z = "C:\Program Files\7-Zip\7z.exe"
if (-not $NoArchive -and (Test-Path $7z)) {
  Step "Encrypting into one .7z (AES-256, file names hidden) - 7-Zip asks for a password"
  & $7z a -t7z -mhe=on -p (Join-Path $Dest "zargar-package-$stamp.7z") $Pkg
  if ($LASTEXITCODE -eq 0) { Warn "Encrypted archive written. Delete the plain folder after checking it: $Pkg" }
} elseif (-not $NoArchive) {
  Warn "7-Zip is not installed: the package is a PLAIN folder that contains secrets (.env keys, database settings)."
  Warn "Keep it on a drive you control (BitLocker To Go on a USB drive works), and delete it after the import."
}
Step ("Package ready: {0} ({1:N1} GB)" -f $Pkg, $size)
if ($Final) { Warn "This machine's Zargar tasks are DISABLED and the app is stopped. Do not start it here again." }
