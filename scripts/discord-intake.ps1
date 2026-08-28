# Zargar experimental Discord intake — runs the gateway DM listener in its own
# window. Launched by scripts\start.ps1 (unless -NoDiscord), or on its own:
#
#   scripts\discord-intake.ps1                 monitor the sources you picked in the app
#                                              (Tips > Sources > Discord); nothing else
#   scripts\discord-intake.ps1 -AllDms         ignore the watchlist, ingest every DM
#   scripts\discord-intake.ps1 -IncludeSelf    also ingest DMs you send yourself (self-test)
#   scripts\discord-intake.ps1 -NoWait         start listening immediately
#   scripts\discord-intake.ps1 -DumpOnly       log DMs to JSONL, ingest nothing
#
# ⚠️  This uses your Discord USER token (auto-grabbed from the desktop app) —
# not ToS-sanctioned; the risk is to your account. Read-only listener. See
# docs\techniques\tip\INTAKE-PLAN.md. Close this window to stop the intake.

param(
  [switch]$AllDms,       # ignore the watchlist, ingest every DM (testing)
  [switch]$NoWait,       # do not wait for the API first
  [switch]$DumpOnly,     # capture to JSONL, never ingest
  [switch]$IncludeSelf,  # also ingest DMs you send yourself (end-to-end test)
  [string]$Api = "http://127.0.0.1:8420"
)
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Backend = Join-Path $Root "backend"
$py = Join-Path $Backend ".venv\Scripts\python.exe"
$Host.UI.RawUI.WindowTitle = "Zargar · Discord intake"

function Step($m) { Write-Host "> $m" -ForegroundColor Cyan }
function Warn($m) { Write-Host "! $m" -ForegroundColor Yellow }

if (-not (Test-Path $py)) { Warn "backend\.venv not found"; Read-Host "Enter to close"; exit 1 }
Set-Location $Backend

Write-Host "Zargar Discord intake (experimental, read-only)" -ForegroundColor Magenta
Write-Host "Uses your Discord user token from the desktop app. Close this window to stop." -ForegroundColor DarkGray

# --- wait for the API so the first alert can ingest ---------------------------
if (-not $NoWait) {
  Step "Waiting for Zargar API on $Api ..."
  $ok = $false
  foreach ($i in 1..40) {
    try { Invoke-RestMethod -Uri "$Api/api/health" -TimeoutSec 2 | Out-Null; $ok = $true; break }
    catch { Start-Sleep -Seconds 1 }
  }
  if ($ok) { Step "API is up." } else { Warn "API not answering yet — listening anyway (ingest will retry)." }
}

# --- mint a long session so ingest passes auth (best-effort) ------------------
# The app gates /api/ingest/manual behind sign-in. Mint a long-lived local
# session; if minting can't (auth off, or no allow-listed email), carry on —
# with auth off ingest works tokenless, with auth on the gateway logs the 401
# and the JSONL capture still records every alert.
if (-not $DumpOnly) {
  try {
    $tok = & $py -m zargar.tools.mint_session --hours 720 2>$null
    if ($tok -and $tok.Trim() -match '^[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.') {
      $env:ZARGAR_SESSION = $tok.Trim()
      Step "Session minted (30-day local token)."
    } else {
      Warn "Could not mint a session (auth may be off). Proceeding without one."
    }
  } catch { Warn "mint_session failed: $($_.Exception.Message). Proceeding without a session." }
}

# --- run the listener (foreground in THIS window) ----------------------------
$gwArgs = @("-m", "zargar.tools.discord_gateway")
if ($DumpOnly) { $gwArgs += "--dump" }
else {
  $gwArgs += "--ingest"                 # default: watchlist governs (allowlist)
  if ($AllDms) { $gwArgs += "--all-dms" }
}
if ($IncludeSelf) { $gwArgs += "--include-self" }
Step ("Starting listener: python " + ($gwArgs -join " "))
& $py @gwArgs
$code = $LASTEXITCODE
Warn "Listener exited (code $code)."
Read-Host "Press Enter to close this window"
