# EM desk: deploy a reviewed commit OFF-HOURS, once the evening batch has finished and the engine says it is safe.
# ASCII only (Windows PowerShell 5.1). Versioned 2026-09-22 (replaces the one-off C:\ProgramData\Zargar\deploy-when-safe.ps1).
#
# Order of conditions, all required, re-checked every 2 minutes:
#   1. the EM evening batch is no longer running (its paid reads are not interrupted);
#   2. /api/ops/restart-check says safe (no open technique trade, no paid run in flight, ...);
#   3. it is still before -NotAfter (local time). Past it the deploy is ABANDONED and a keyed 'deploy' notice is
#      raised - a restart close to the open would collide with the clock and pre-open checks.
# The deploy itself is ONLY scripts\deploy.ps1 in the runtime checkout (fast-forward to the full reviewed SHA, build,
# guarded restart, verified receipt). This script never stops a process and never edits the runtime source.
param(
  [Parameter(Mandatory = $true)][string]$TargetCommit,
  [Parameter(Mandatory = $true)][string]$Expect,
  [string]$NotAfter = '05:40',
  [string]$BatchMatch = 'em-evening-batch',
  [string]$Runtime = 'C:\Cursor\zargar'
)
$ErrorActionPreference = 'Continue'
$logDir = 'C:\ProgramData\Zargar\logs'
$log = Join-Path $logDir ("em-deploy-{0}.log" -f (Get-Date).ToString('yyyy-MM-dd'))
$attention = 'C:\ProgramData\Zargar\EM-ATTENTION.md'
function Say($m) {
  $line = "$((Get-Date).ToString('yyyy-MM-dd HH:mm:ss')) [em-deploy] $m"
  Write-Host $line
  $line | Out-File -FilePath $log -Append -Encoding utf8
}
function Raise($title, $body) {
  @("# EM needs attention - $title", "", "Key: deploy", "Raised $((Get-Date).ToString('yyyy-MM-dd HH:mm:ss')) by em-deploy-when-safe.",
    "Owner: EM desk", "", $body, "", "No trading setting was changed and no process was stopped.") -join "`r`n" |
    Out-File -FilePath $attention -Encoding utf8
  Say "ATTENTION RAISED [deploy]: $title"
}
if ($TargetCommit -notmatch '^[a-fA-F0-9]{40}$') { Say 'TargetCommit must be a full 40-character SHA - abort'; exit 2 }
$hh, $mm = $NotAfter.Split(':')
$deadline = (Get-Date).Date.AddHours([int]$hh).AddMinutes([int]$mm)
if ($deadline -lt (Get-Date)) { $deadline = $deadline.AddDays(1) }
Say "target $TargetCommit expect $Expect; deadline $deadline"
$tokLine = (Get-Content -LiteralPath (Join-Path $Runtime 'backend\.env') | Where-Object { $_ -like 'ZARGAR_AUTH_TOKEN=*' } | Select-Object -First 1)
$H = @{ Authorization = ('Bearer ' + (($tokLine -replace '^ZARGAR_AUTH_TOKEN=', '').Trim())) }

$ready = $false
while ((Get-Date) -lt $deadline) {
  # one venv python instance is a PROCESS PAIR, so presence is "count > 0"
  $n = (Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -like "*$BatchMatch*" } | Measure-Object).Count
  if ($n -gt 0) { Say 'evening batch still running - waiting'; Start-Sleep -Seconds 120; continue }
  try {
    $r = Invoke-RestMethod -Uri 'http://127.0.0.1:8420/api/ops/restart-check?caller=em-deploy-when-safe' -Headers $H -TimeoutSec 10
    if ($r.safe) { $ready = $true; break }
    Say ('not safe: ' + ($r.reasons -join '; '))
  } catch { Say ('restart-check failed: ' + $_.Exception.Message) }
  Start-Sleep -Seconds 120
}
if (-not $ready) {
  Raise "deploy of $Expect abandoned at the deadline" ("Target $TargetCommit was not deployed: the batch or the engine was not ready before $NotAfter.`r`n" +
    "The running build is unchanged. Deploy in the next off-hours window with:`r`n" +
    "    cd $Runtime ; powershell -File scripts\deploy.ps1 -TargetCommit $TargetCommit -Expect $Expect")
  exit 1
}
$before = $null
try { $before = Invoke-RestMethod -Uri 'http://127.0.0.1:8420/api/health' -TimeoutSec 5 } catch {}
Say ("before: version {0} build {1} armed {2}" -f $before.version, $before.build, $before.local.armed)
Push-Location $Runtime
try {
  $out = & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Runtime 'scripts\deploy.ps1') -TargetCommit $TargetCommit -Expect $Expect 2>&1
  $code = $LASTEXITCODE
  $out | ForEach-Object { $_.ToString() | Out-File -FilePath $log -Append -Encoding utf8 }
} finally { Pop-Location }
$after = $null
for ($i = 0; $i -lt 30; $i++) {
  try { $after = Invoke-RestMethod -Uri 'http://127.0.0.1:8420/api/health' -TimeoutSec 5; if ($after.started) { break } } catch {}
  Start-Sleep -Seconds 10
}
Say ("deploy.ps1 exit {0}; after: version {1} build {2} armed {3}" -f $code, $after.version, $after.build, $after.local.armed)
if ($code -ne 0 -or $after.version -ne $Expect -or $after.build -ne $TargetCommit) {
  Raise "deploy of $Expect did not verify" ("deploy.ps1 exit $code; health version $($after.version) build $($after.build) (expected $Expect / $TargetCommit).`r`n" +
    "Armed before $($before.local.armed), after $($after.local.armed). Read $log and $Runtime\logs\deployment-receipt.json.")
  exit 1
}
if ([int]$after.local.armed -lt [int]$before.local.armed) {
  Raise 'fewer plans armed after the deploy' ("Armed before $($before.local.armed), after $($after.local.armed). Restore may still be running; check /api/technique/armed.")
}
Say 'verified'
