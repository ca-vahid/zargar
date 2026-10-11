# Prepare a FRESH Windows 11 machine for Zargar (run this BEFORE import-machine.ps1).
# Installs WSL 2, Docker Desktop, Git, PowerShell 7, Python 3.13, Node 20, 7-Zip, GitHub CLI, Tailscale and Claude Code
# with winget, then checks each one. Safe to run again: anything already installed is skipped.
#
#   Right-click Start > "Terminal (Admin)", then:
#     Set-ExecutionPolicy -Scope Process Bypass -Force
#     & "$HOME\Downloads\prepare-new-machine.ps1"
#
# WSL needs ONE reboot. The script says when; run it again after the reboot to finish (it continues where it stopped).
# IB Gateway is not on winget - the script opens IBKR's download page at the end.
$ErrorActionPreference = "Continue"
function Step($m) { Write-Host "> $m" -ForegroundColor Cyan }
function Ok($m) { Write-Host "  ok  $m" -ForegroundColor Green }
function Warn($m) { Write-Host "  !   $m" -ForegroundColor Yellow }

$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
  [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) { Write-Host "x Run this from an ADMIN terminal (right-click Start > Terminal (Admin))." -ForegroundColor Red; exit 1 }
if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
  Write-Host "x winget is missing: install 'App Installer' from the Microsoft Store, then run this again." -ForegroundColor Red; exit 1
}

# ---- 1. WSL 2 (Docker Desktop's engine) ----------------------------------------------------------------------------
Step "WSL 2"
$needReboot = $false
$wslOk = $false
try { wsl.exe --status *> $null; $wslOk = ($LASTEXITCODE -eq 0) } catch { }
if (-not $wslOk) {
  wsl.exe --install --no-distribution
  $needReboot = $true
  Warn "WSL installed - a REBOOT is needed before Docker can start"
} else {
  wsl.exe --update *> $null
  Ok "WSL present (updated)"
}

# ---- 2. the tools ----------------------------------------------------------------------------------------------------------
$pkgs = [ordered]@{
  "Git.Git"              = "Git"
  "Microsoft.PowerShell" = "PowerShell 7"
  "Python.Python.3.13"   = "Python 3.13 (the app runs on 3.13)"
  "OpenJS.NodeJS.20"     = "Node.js 20 (the frontend is built with Node 20)"
  "Docker.DockerDesktop" = "Docker Desktop (runs the Postgres database)"
  "7zip.7zip"            = "7-Zip"
  "GitHub.cli"           = "GitHub CLI"
  "Tailscale.Tailscale"  = "Tailscale (the public https URL for your phone)"
  "Anthropic.ClaudeCode" = "Claude Code"
}
foreach ($id in $pkgs.Keys) {
  Step $pkgs[$id]
  $have = winget list --id $id --exact --accept-source-agreements 2>$null | Select-String -SimpleMatch $id
  if ($have) { Ok "already installed"; continue }
  winget install --id $id --exact --source winget --silent --accept-package-agreements --accept-source-agreements
  if ($LASTEXITCODE -eq 0) { Ok "installed" } else { Warn "winget exit $LASTEXITCODE - install $id by hand if the check below fails" }
}

# ---- 3. PATH for this window (new installs only reach NEW terminals otherwise) ----------------------------------------
$env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")

# ---- 4. checks ------------------------------------------------------------------------------------------------------------
Step "Checks"
$checks = [ordered]@{
  "git"    = { git --version }
  "pwsh"   = { pwsh -NoProfile -Command '$PSVersionTable.PSVersion.ToString()' }
  "python" = { py -3.13 --version }
  "node"   = { node --version }
  "npm"    = { npm --version }
  "gh"     = { (gh --version | Select-Object -First 1) }
  "claude" = { claude --version }
  "docker" = { docker --version }
}
$missing = @()
foreach ($k in $checks.Keys) {
  try { $v = (& $checks[$k] 2>$null | Out-String).Trim() } catch { $v = "" }
  if ($v) { Ok "$k  $v" } else { Warn "$k not found yet"; $missing += $k }
}
if (Test-Path "C:\Program Files\Tailscale\tailscale.exe") { Ok "tailscale installed (sign in later - RESTORE.md step 5)" }
if (Test-Path "C:\Program Files\7-Zip\7z.exe") { Ok "7-Zip installed" }

# ---- 5. Python on PATH as 'python' (the import script calls python) --------------------------------------------------
$py = (Get-Command py -ErrorAction SilentlyContinue)
if ($py -and -not (Get-Command python -ErrorAction SilentlyContinue | Where-Object { $_.Source -notmatch 'WindowsApps' })) {
  Warn "'python' still points at the Microsoft Store stub: Settings > Apps > Advanced app settings > App execution aliases > turn OFF python.exe and python3.exe, then open a new terminal"
}

# ---- 6. the folder + what is left ------------------------------------------------------------------------------------------
New-Item -ItemType Directory -Force -Path "C:\Cursor" | Out-Null
Ok "C:\Cursor created (the import puts the app at C:\Cursor\zargar, the same path as before)"

Write-Host ""
if ($needReboot) {
  Write-Host "REBOOT NOW, then run this script again to finish (WSL, then Docker)." -ForegroundColor Yellow
  exit 0
}
Write-Host "Next (by hand):" -ForegroundColor Cyan
Write-Host "  1. Start Docker Desktop once, accept its terms, wait until it says 'Engine running' (Settings > General: 'Start Docker Desktop when you sign in' ON)."
Write-Host "  2. Open a NEW terminal and run 'claude' to sign in to Claude Code; then 'gh auth login'."
Write-Host "  3. git config --global user.name ""Mr Vahid""   and   git config --global user.email <your email>"
Write-Host "  4. Install IB Gateway 10.50 (stable) from the page that opens now - do NOT sign in yet."
Write-Host "  5. Do NOT sign in to Tailscale yet - RESTORE.md step 5 does it after the old machine gives up the name."
Write-Host "  6. Download the package from Google Drive into C:\ZargarMove, decrypt it, then run import-machine.ps1 (RESTORE.md)."
if ($missing.Count -gt 0) { Write-Host ("Still missing: " + ($missing -join ", ") + " - open a NEW admin terminal and run this script again.") -ForegroundColor Yellow }
Start-Process "https://www.interactivebrokers.com/en/trading/ibgateway-stable.php"
