# ONE step on the new machine: put this file in the folder with the downloaded package parts
# (zargar-package-*.zenc.000 ... + package_crypt.py + import-machine.ps1), right-click it > "Run with PowerShell".
#
# It asks for the package password once (typed, never shown, never saved), then: installs the decryption library,
# decrypts the package next to the parts, starts Docker Desktop and waits for it, runs import-machine.ps1 into
# -RepoPath (default C:\DevSpace\Zargar), and writes everything to restore.log in this folder.
# Safe to run again: a finished decrypt is reused and the import skips what is already in place.
param([string]$RepoPath = "C:\DevSpace\Zargar")
$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path

# ---- admin (scheduled tasks + ProgramData need it) -------------------------------------------------------------
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
  [Security.Principal.WindowsBuiltInRole]::Administrator)
$pwsh = Get-Command pwsh -ErrorAction SilentlyContinue
if (-not $pwsh) { $p7 = "C:\Program Files\PowerShell\7\pwsh.exe"; if (Test-Path $p7) { $pwsh = $p7 } }
# PowerShell 7 + admin; "Run with PowerShell" starts the old Windows PowerShell 5.1, whose handling of git's stderr breaks the import
if (-not $admin -or ($PSVersionTable.PSVersion.Major -lt 7 -and $pwsh)) {
  $shell = if ($pwsh) { "$pwsh" } else { "powershell" }
  Start-Process $shell -Verb RunAs -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-File", "`"$($MyInvocation.MyCommand.Path)`"", "-RepoPath", "`"$RepoPath`""
  exit 0
}
Start-Transcript -Path (Join-Path $Here "restore.log") -Append | Out-Null
function Step($m) { Write-Host "`n> $m" -ForegroundColor Cyan }
function Fail($m) { Write-Host "`nx $m" -ForegroundColor Red; Stop-Transcript | Out-Null; Read-Host "Press Enter to close"; exit 1 }
$env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")

# ---- 1. decrypt (skipped when already done) ------------------------------------------------------------------------
$first = Get-ChildItem $Here -Filter "zargar-package-*.zenc.000" | Select-Object -First 1
if (-not $first) { Fail "no zargar-package-*.zenc.000 in $Here - put this script next to the downloaded parts" }
$stem = $first.Name -replace '\.zenc\.000$', ''
$pkg = Join-Path $Here $stem
if (-not (Test-Path (Join-Path $pkg "manifest.json"))) {
  Step "Checking the package parts"
  $parts = @(Get-ChildItem $Here -Filter "$stem.zenc.*" | Sort-Object Name)
  Write-Host ("  {0} parts, {1:N1} GB" -f $parts.Count, (($parts | Measure-Object Length -Sum).Sum / 1GB))
  if ($parts.Count -lt 6) { Fail "expected 6 parts (.000 to .005) - a download is missing" }
  $free = (Get-PSDrive ($Here.Substring(0, 1))).Free / 1GB
  if ($free -lt 25) { Fail ("only {0:N0} GB free on this drive - the restore needs about 25 GB" -f $free) }

  Step "Python decryption library"
  & py -3.13 -m pip install --quiet --disable-pip-version-check cryptography
  if ($LASTEXITCODE -ne 0) { Fail "could not install 'cryptography' (is Python 3.13 installed? run prepare-new-machine.ps1)" }

  # the password file sent from the old machine (ZARGAR-PACKAGE-PASSWORD.txt next to this script) is used first;
  # otherwise the password is typed or PASTED (right-click / Ctrl+V pastes into the hidden prompt)
  $given = Get-ChildItem $Here -Filter "ZARGAR-PACKAGE-PASSWORD*.txt" -ErrorAction SilentlyContinue | Select-Object -First 1
  $tries = 0
  while ($true) {
    if ($given -and $tries -eq 0) {
      Write-Host "  using the password file $($given.Name)"
      $plain = (Get-Content $given.FullName | Where-Object { $_.Trim() } | Select-Object -Last 1)
    } else {
      $sec = Read-Host "Package password (paste with right-click or Ctrl+V)" -AsSecureString
      $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec))
    }
    if (-not $plain -or -not $plain.Trim()) { Write-Host "  empty - try again" -ForegroundColor Yellow; $tries++; if ($tries -ge 4) { Fail "no password given" }; continue }
    Write-Host ("  password has {0} characters (the right one has 32)" -f $plain.Trim().Length)
    $pwFile = Join-Path $env:TEMP ("zpw-" + [guid]::NewGuid().ToString("N") + ".txt")
    Set-Content -Path $pwFile -Value $plain.Trim() -Encoding utf8 -NoNewline
    $plain = $null
    Step "Decrypting (a few minutes)"
    try {
      & py -3.13 (Join-Path $Here "package_crypt.py") decrypt $first.FullName $Here --password-file $pwFile
      $ok = ($LASTEXITCODE -eq 0)
    } finally { Remove-Item $pwFile -Force -ErrorAction SilentlyContinue }
    if ($ok -and (Test-Path (Join-Path $pkg "manifest.json"))) { break }
    $tries++
    if (Test-Path $pkg) { Remove-Item $pkg -Recurse -Force -ErrorAction SilentlyContinue }
    if ($tries -ge 3) { Fail "decryption failed 3 times - check the password, or download the parts again" }
    Write-Host "  wrong password or a damaged part - try again" -ForegroundColor Yellow
  }
} else {
  Step "Already decrypted: $pkg"
}

# ---- 2. Docker Desktop ---------------------------------------------------------------------------------------------------
Step "Docker"
docker info *> $null
if ($LASTEXITCODE -ne 0) {
  $dd = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
  if (-not (Test-Path $dd)) { Fail "Docker Desktop is not installed - run prepare-new-machine.ps1 first" }
  Start-Process $dd
  Write-Host "  starting Docker Desktop (accept its terms if a window asks) ..."
  $up = $false
  foreach ($i in 1..90) { Start-Sleep 4; docker info *> $null; if ($LASTEXITCODE -eq 0) { $up = $true; break } }
  if (-not $up) { Fail "Docker did not start within 6 minutes - open Docker Desktop, wait for 'Engine running', run this again" }
}
Write-Host "  Docker engine running"

# ---- 3. the import (always the copy next to this script: it is newer than the one inside the package) -------------------
Step "Importing into $RepoPath (database restore + package installs take a while)"
$imp = Join-Path $Here "import-machine.ps1"
if (-not (Test-Path $imp)) { $imp = Join-Path $pkg "import-machine.ps1" }
& $imp -From $pkg -RepoPath $RepoPath
if ($LASTEXITCODE -ne 0) { Fail "the import stopped (see the lines above, and restore.log)" }

# ---- 4. what is left ---------------------------------------------------------------------------------------------------------
Write-Host "`nRESTORE COMPLETE - nothing is running yet and every Zargar task is disabled." -ForegroundColor Green
Write-Host "Left for you (MIGRATION.md step 5 onward):"
Write-Host "  1. Old machine: log out of IB Gateway. New machine: install IB Gateway 10.50, sign in to the PAPER account,"
Write-Host "     API settings: port 4002, localhost only, trusted 127.0.0.1, Read-Only API OFF."
Write-Host "  2. Tailscale admin console: rename the old machine, rename this one to zargar-desk, then run:"
Write-Host "       & 'C:\Program Files\Tailscale\tailscale.exe' serve --bg 8420"
Write-Host "       & 'C:\Program Files\Tailscale\tailscale.exe' funnel --bg 8420"
Write-Host "  3. Open Claude Code in $RepoPath and ask it to finish the move: first start, checks, enable the tasks."
Write-Host "  4. After it all works: delete $pkg and the .zenc parts (they hold your keys), here and on Google Drive."
Stop-Transcript | Out-Null
Read-Host "Press Enter to close"
