# Rebuild Zargar on a NEW Windows machine from a package made by scripts\export-machine.ps1.
# Full runbook (what this does, what stays manual, how to verify): RESTORE.md in the package (= docs\MIGRATION.md).
#
#   powershell -ExecutionPolicy Bypass -File <package>\import-machine.ps1 -From <package> [-RepoPath C:\Cursor\zargar]
#   -SkipDb       do not restore the database (e.g. a re-run after the restore already succeeded)
#   -SkipTasks    do not register the scheduled tasks
#
# Safe by construction: nothing trades - every Zargar scheduled task is registered DISABLED and the app is NOT started.
# Run from an ELEVATED PowerShell (scheduled tasks + ProgramData need it). Prerequisites: git, Python 3.13, Node 20,
# Docker Desktop (running).
param(
  [Parameter(Mandatory = $true)][string]$From,
  [string]$RepoPath = "",
  [switch]$SkipDb,
  [switch]$SkipTasks
)
$ErrorActionPreference = "Stop"
function Step($m) { Write-Host "> $m" -ForegroundColor Cyan }
function Warn($m) { Write-Host "! $m" -ForegroundColor Yellow }
function Fail($m) { Write-Host "x $m" -ForegroundColor Red; exit 1 }
$Pkg = (Resolve-Path $From).Path
$man = Get-Content (Join-Path $Pkg "manifest.json") -Raw | ConvertFrom-Json
if (-not $RepoPath) { $RepoPath = $man.repoPath }
$OldRoot = $man.repoPath
$ClaudeDir = Join-Path $env:USERPROFILE ".claude"
function Enc($p) { ($p -replace '[^A-Za-z0-9-]', '-') }        # Claude Code's project-folder name for a path

# ---- 0. prerequisites --------------------------------------------------------------------------------------------
foreach ($c in "git", "node", "npm", "docker") {
  if (-not (Get-Command $c -ErrorAction SilentlyContinue)) { Fail "$c not found - install it first (prepare-new-machine.ps1)" }
}
# the real Python 3.13 (the py launcher first: a fresh Windows 'python' can be the Microsoft Store stub)
$Python = $null
if (Get-Command py -ErrorAction SilentlyContinue) { $Python = (py -3.13 -c "import sys; print(sys.executable)" 2>$null) }
if (-not $Python) { $Python = (python -c "import sys; print(sys.executable)" 2>$null) }
if (-not $Python -or -not (Test-Path $Python)) { Fail "Python 3.13 not found - run prepare-new-machine.ps1" }
docker info *> $null; if ($LASTEXITCODE -ne 0) { Fail "Docker Desktop is not running" }
if (Get-NetTCPConnection -LocalPort 8420 -State Listen -ErrorAction SilentlyContinue) { Fail "something already listens on :8420" }

# ---- 1. integrity --------------------------------------------------------------------------------------------------
Step "Verifying the package checksums"
$bad = 0
foreach ($line in Get-Content (Join-Path $Pkg "SHA256SUMS.txt")) {
  if (-not $line.Trim()) { continue }
  $hash, $rel = $line -split '  ', 2
  $p = Join-Path $Pkg $rel
  if (-not (Test-Path $p) -or (Get-FileHash $p -Algorithm SHA256).Hash -ne $hash) { $bad++; Warn "checksum mismatch: $rel" }
}
if ($bad -gt 0) { Fail "$bad file(s) failed the checksum - copy the package again" }

# ---- 2. code -----------------------------------------------------------------------------------------------------------
Step "Repository -> $RepoPath"
$bundle = Join-Path $Pkg "repo\zargar.bundle"
if (-not (Test-Path (Join-Path $RepoPath ".git"))) {
  git clone $bundle $RepoPath
  if ($LASTEXITCODE -ne 0) { Fail "git clone from the bundle failed" }
}
Push-Location $RepoPath
git fetch $bundle "+refs/heads/*:refs/heads/*" --update-head-ok 2>&1 | Out-Null      # every local branch of the old machine
git remote set-url origin $man.parts.repo.remote
git checkout $man.parts.repo.branch
git reset --hard $man.parts.repo.head
Pop-Location
# worktrees: the dirty ones (uncommitted work) and the ones a Claude session lives in are recreated at the same place
$wts = Get-Content (Join-Path $Pkg "repo\worktrees.json") -Raw | ConvertFrom-Json
$claudeDirs = @(Get-ChildItem (Join-Path $Pkg "claude\projects") -Directory | ForEach-Object { $_.Name })
foreach ($w in $wts) {
  $newPath = $w.path -replace [regex]::Escape(($OldRoot -replace '\\', '/')), ($RepoPath -replace '\\', '/')
  $newPath = $newPath -replace [regex]::Escape($OldRoot), $RepoPath
  $isMain = (($w.path -replace '/', '\').TrimEnd('\') -eq $OldRoot.TrimEnd('\'))
  $wanted = $w.dirty -or ($claudeDirs -contains (Enc ($w.path -replace '/', '\')))
  if ($isMain) {
    if ($w.dirty) { git -C $RepoPath apply --binary --whitespace=nowarn (Join-Path $Pkg "repo\worktrees\$($w.patch)") }
    continue
  }
  if (-not $wanted -or -not $w.branch -or (Test-Path $newPath)) { continue }
  git -C $RepoPath worktree add $newPath $w.branch 2>&1 | Out-Null
  if ($LASTEXITCODE -ne 0) { Warn "worktree $newPath ($($w.branch)) not recreated"; continue }
  if ($w.dirty) {
    git -C $newPath apply --binary --whitespace=nowarn (Join-Path $Pkg "repo\worktrees\$($w.patch)")
    $zip = Join-Path $Pkg ("repo\worktrees\" + ($w.patch -replace '\.patch$', '-untracked.zip'))
    if (Test-Path $zip) { Expand-Archive $zip -DestinationPath $newPath -Force }
  }
}

# ---- 3. untracked runtime files ----------------------------------------------------------------------------------------
Step "Runtime files (.env, gateway ledger, media, logs)"
robocopy (Join-Path $Pkg "files") $RepoPath /E /R:1 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { Fail "copying the runtime files failed" }
$envFile = Join-Path $RepoPath "backend\.env"
if ((Test-Path $envFile) -and $RepoPath -ne $OldRoot) {
  $dist = (Join-Path $RepoPath "frontend\dist") -replace '\\', '/'
  (Get-Content $envFile) -replace '^ZARGAR_FRONTEND_DIST=.*', "ZARGAR_FRONTEND_DIST=$dist" | Set-Content $envFile -Encoding utf8
}

# ---- 4. database -------------------------------------------------------------------------------------------------------
if (-not $SkipDb) {
  Step "Postgres container + restore (several minutes for a multi-GB dump)"
  Push-Location $RepoPath; docker compose up -d; Pop-Location
  foreach ($i in 1..60) { docker exec zargar-db pg_isready -U zargar *> $null; if ($LASTEXITCODE -eq 0) { break }; Start-Sleep 2 }
  docker cp (Join-Path $Pkg "db\zargar.dump") zargar-db:/tmp/zargar.dump | Out-Null
  docker exec zargar-db sh -c "pg_restore -U zargar -d zargar --clean --if-exists --no-owner -j 4 /tmp/zargar.dump"
  if ($LASTEXITCODE -ne 0) { Warn "pg_restore reported errors - check the row counts below before going on" }
  docker exec zargar-db rm -f /tmp/zargar.dump | Out-Null
  $mism = 0
  foreach ($p in $man.parts.db.rowCounts.PSObject.Properties) {
    $n = [int64]("$(docker exec zargar-db psql -U zargar -d zargar -tAc "select count(*) from $($p.Name)")".Trim())
    if ($n -ne [int64]$p.Value) { $mism++; Warn ("{0}: {1} rows, the old machine had {2}" -f $p.Name, $n, $p.Value) }
  }
  if ($mism -eq 0) { Step "Row counts match the old machine for every checked table" } else { Fail "$mism table(s) differ" }
}

# ---- 5. Python + Node -------------------------------------------------------------------------------------------------
Step "Backend virtualenv (the exact package versions of the old machine)"
Push-Location (Join-Path $RepoPath "backend")
if (-not (Test-Path ".venv")) { & $Python -m venv .venv }
$freeze = Get-Content (Join-Path $Pkg "machine\pip-freeze-venv.txt") | Where-Object { $_ -and $_ -notmatch '^-e |zargar' }
$freeze | Set-Content "$env:TEMP\zargar-req.txt" -Encoding utf8
& .venv\Scripts\python.exe -m pip install --quiet --upgrade pip
& .venv\Scripts\python.exe -m pip install --quiet -r "$env:TEMP\zargar-req.txt"
& .venv\Scripts\python.exe -m pip install --quiet -e ".[dev]" --no-deps
if ($LASTEXITCODE -ne 0) { Fail "backend install failed" }
$fi = Join-Path $Pkg "machine\pip-freeze-venv-ingest.txt"
if (Test-Path $fi) {
  if (-not (Test-Path ".venv-ingest")) { & $Python -m venv .venv-ingest }
  Get-Content $fi | Where-Object { $_ -and $_ -notmatch '^-e |zargar' } | Set-Content "$env:TEMP\zargar-ingest-req.txt" -Encoding utf8
  & .venv-ingest\Scripts\python.exe -m pip install --quiet -r "$env:TEMP\zargar-ingest-req.txt"
  if ($LASTEXITCODE -ne 0) { Warn "the EM ingestion venv did not install cleanly (only the EM video worker needs it)" }
}
& .venv\Scripts\python.exe -c "import zargar.api.app; print('backend imports OK')"
Pop-Location
Step "Frontend (npm ci + build)"
Push-Location (Join-Path $RepoPath "frontend"); npm ci --no-fund --no-audit; npm run build; Pop-Location

# ---- 6. Claude Code history + memory -------------------------------------------------------------------------------------
Step "Claude Code: sessions, memory, prompt history, skills"
New-Item -ItemType Directory -Force -Path (Join-Path $ClaudeDir "projects") | Out-Null
foreach ($d in Get-ChildItem (Join-Path $Pkg "claude\projects") -Directory) {
  $name = $d.Name
  if ($RepoPath -ne $OldRoot) { $name = $name.Replace((Enc $OldRoot), (Enc $RepoPath)) }
  robocopy $d.FullName (Join-Path $ClaudeDir "projects\$name") /E /XO /R:1 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null
}
$hist = Join-Path $ClaudeDir "history.jsonl"
$oldHist = Join-Path $Pkg "claude\history.jsonl"
if (Test-Path $oldHist) {
  if (Test-Path $hist) { Get-Content $oldHist | Add-Content $hist } else { Copy-Item $oldHist $hist }
}
foreach ($f in "settings.json", "settings.local.json", "statusline-command.sh") {
  $src = Join-Path $Pkg "claude\$f"
  if (-not (Test-Path $src)) { continue }
  $dst = Join-Path $ClaudeDir $f
  if (Test-Path $dst) { Copy-Item $src "$dst.from-old-machine" -Force; Warn "$f exists here - the old one is saved as $f.from-old-machine" }
  else { Copy-Item $src $dst }
}
foreach ($d in "skills", "plans") {
  $src = Join-Path $Pkg "claude\$d"
  if (Test-Path $src) { robocopy $src (Join-Path $ClaudeDir $d) /E /XO /R:1 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null }
}

# ---- 7. machine pieces ------------------------------------------------------------------------------------------------------
Step "C:\ProgramData\Zargar"
$pd = Join-Path $Pkg "machine\ProgramData-Zargar"
if (Test-Path $pd) { robocopy $pd "C:\ProgramData\Zargar" /E /R:1 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null }
# a different folder on this machine: the task helper scripts name the repo by its full path - point them at the new one
function Repath([string]$text) {
  $t = [regex]::Replace($text, [regex]::Escape($OldRoot), $RepoPath.Replace('$', '$$'), 'IgnoreCase')
  return [regex]::Replace($t, [regex]::Escape($OldRoot.Replace('\', '/')), $RepoPath.Replace('\', '/').Replace('$', '$$'), 'IgnoreCase')
}
if ($RepoPath -ne $OldRoot -and (Test-Path "C:\ProgramData\Zargar")) {
  Get-ChildItem "C:\ProgramData\Zargar" -Recurse -File -Include *.ps1, *.py, *.vbs, *.cmd, *.bat, *.json |
    Where-Object { $_.FullName -notmatch '\\(logs|archive)\\' } | ForEach-Object {
      $raw = Get-Content $_.FullName -Raw -Encoding utf8
      $new = Repath $raw
      if ($new -ne $raw) { Set-Content $_.FullName $new -Encoding utf8 -NoNewline; Step "  repointed $($_.Name) to $RepoPath" }
    }
}
if (-not $SkipTasks) {
  Step "Scheduled tasks (registered DISABLED - RESTORE.md enables them after the checks)"
  $me = "$env:USERDOMAIN\$env:USERNAME"
  foreach ($x in Get-ChildItem (Join-Path $Pkg "machine\tasks") -Filter *.xml) {
    $xml = Get-Content $x.FullName -Raw
    $xml = $xml -replace '<UserId>[^<]*</UserId>', "<UserId>$me</UserId>"
    if ($RepoPath -ne $OldRoot) { $xml = Repath $xml }
    $xml = $xml -replace '<Enabled>true</Enabled>(\s*<Hidden>|\s*</Settings>)', '<Enabled>false</Enabled>$1'
    try {
      Register-ScheduledTask -TaskName $x.BaseName -Xml $xml -Force | Out-Null
      Disable-ScheduledTask -TaskName $x.BaseName | Out-Null
    } catch { Warn "task $($x.BaseName): $($_.Exception.Message) - register it by hand from $($x.FullName)" }
  }
}
Step "Done. Nothing is running yet. Continue with RESTORE.md step 5 (sign-ins, Tailscale, IB Gateway, first start)."
