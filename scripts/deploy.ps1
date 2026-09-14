# Run from the authorized runtime checkout. All edits/build/restart share one OS lease.
param([Parameter(Mandatory=$true)][string]$TargetCommit, [Parameter(Mandatory=$true)][string]$Expect)
$ErrorActionPreference = 'Stop'
$deployRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
. (Join-Path $PSScriptRoot 'deployment-lock.ps1')
$deployMutex = Enter-ZargarDeployment $deployRoot
try {
  Push-Location $deployRoot
  try {
    if ($TargetCommit -notmatch '^[a-fA-F0-9]{40}$') { throw 'TargetCommit must be the reviewed full commit hash.' }
    if (git status --porcelain) { throw 'Runtime has uncommitted changes; preserve and integrate them first.' }
    $readiness = Invoke-RestMethod 'http://127.0.0.1:8420/api/ops/restart-check?caller=deploy.ps1' -TimeoutSec 10
    if (-not $readiness.safe) { throw ('Runtime is busy; deployment deferred: ' + ($readiness.reasons -join '; ')) }
    $pause = Invoke-RestMethod 'http://127.0.0.1:8420/api/ops/quiesce?minutes=5' -Method Post -TimeoutSec 10
    $pausedState = Invoke-RestMethod 'http://127.0.0.1:8420/api/ops/state' -TimeoutSec 10
    if (-not $pause.quiesced -or -not $pausedState.quiesced) { throw 'Entry pause was not acknowledged and verified; runtime source unchanged.' }
    $oldCommit = (git rev-parse HEAD).Trim()
    git merge --ff-only $TargetCommit
    if ($LASTEXITCODE -ne 0) { throw 'Fast-forward refused. Integrate parallel work in a separate checkout first.' }
    $receiptPath = Join-Path $deployRoot 'logs/deployment-receipt.json'
    New-Item -ItemType Directory -Force (Split-Path $receiptPath) | Out-Null
    $receipt = @{ ownerPid=$PID; before=$oldCommit; target=$TargetCommit; expectedVersion=$Expect; startedAt=(Get-Date).ToUniversalTime().ToString('o'); phase='building' }
    $receipt | ConvertTo-Json | Set-Content -LiteralPath $receiptPath -Encoding ASCII
    Push-Location frontend
    try { & npm.cmd run build; if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed; runtime was not restarted.' } }
    finally { Pop-Location }
    if ((git rev-parse HEAD).Trim() -ne $TargetCommit -or (git status --porcelain)) { throw 'Runtime source changed during build; do not restart.' }
    $receipt.phase = 'restarting'
    $receipt.artifactSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $deployRoot 'frontend/dist/index.html')).Hash
    $receipt | ConvertTo-Json | Set-Content -LiteralPath $receiptPath -Encoding ASCII
    $handoff = @{ target=$TargetCommit; expectedVersion=$Expect; artifactSha256=$receipt.artifactSha256; expiresAt=[DateTimeOffset]::UtcNow.AddMinutes(10).ToString('o') }
    $handoff | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $deployRoot 'logs/deployment-pending.json') -Encoding ASCII
    & (Join-Path $PSScriptRoot 'restart.ps1') -Expect $Expect
    if ($LASTEXITCODE -ne 0) { throw "Guarded restart returned $LASTEXITCODE; inspect restart logs." }
    $receipt.phase = 'verified'
    $receipt.completedAt = (Get-Date).ToUniversalTime().ToString('o')
    $receipt | ConvertTo-Json | Set-Content -LiteralPath $receiptPath -Encoding ASCII
  } finally { Pop-Location }
} finally {
  try { $null = Invoke-RestMethod 'http://127.0.0.1:8420/api/ops/quiesce?release=true' -Method Post -TimeoutSec 5 } catch { }
  Exit-ZargarDeployment $deployMutex
}
