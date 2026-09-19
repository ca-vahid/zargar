# Run from the authorized runtime checkout. All edits/build/restart share one OS lease.
# ASCII ONLY. The receipt (logs/deployment-receipt.json) never ends in 'building' or 'restarting':
# every exit path records a terminal phase - verified | failed | deferred - with the reason (KFIN-04).
param([Parameter(Mandatory=$true)][string]$TargetCommit, [Parameter(Mandatory=$true)][string]$Expect)
$ErrorActionPreference = 'Stop'
$deployRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
. (Join-Path $PSScriptRoot 'deployment-lock.ps1')
$deployMutex = Enter-ZargarDeployment $deployRoot
$pausedByDeploy = $false
$deferred = $false
$receiptStarted = $false
try {
  Push-Location $deployRoot
  try {
    if ($TargetCommit -notmatch '^[a-fA-F0-9]{40}$') { throw 'TargetCommit must be the reviewed full commit hash.' }
    $sourceProblems = @(Test-ZargarReviewedSource $deployRoot)
    if ($sourceProblems.Count -gt 0) { throw ('Runtime has unreviewed changes; preserve and integrate them first: ' + (($sourceProblems | Select-Object -First 6) -join '; ')) }
    $readiness = Invoke-RestMethod 'http://127.0.0.1:8420/api/ops/restart-check?caller=deploy.ps1' -TimeoutSec 10
    if (-not $readiness.safe) { $deferred = $true; throw ('Runtime is busy; deployment deferred: ' + ($readiness.reasons -join '; ')) }
    $pause = Invoke-RestMethod 'http://127.0.0.1:8420/api/ops/quiesce?minutes=5' -Method Post -TimeoutSec 10
    $pausedByDeploy = [bool]$pause.quiesced
    $pausedState = Invoke-RestMethod 'http://127.0.0.1:8420/api/ops/state' -TimeoutSec 10
    if (-not $pause.quiesced -or -not $pausedState.quiesced) { $deferred = $true; throw 'Entry pause was not acknowledged and verified; runtime source unchanged.' }
    $oldCommit = (git rev-parse HEAD).Trim()
    git merge --ff-only $TargetCommit
    if ($LASTEXITCODE -ne 0) { throw 'Fast-forward refused. Integrate parallel work in a separate checkout first.' }
    $receipt = [pscustomobject]@{ ownerPid=$PID; caller='deploy.ps1'; before=$oldCommit; target=$TargetCommit; expectedVersion=$Expect; startedAt=(Get-Date).ToUniversalTime().ToString('o'); phase='building' }
    Write-ZargarReceipt $deployRoot $receipt
    $receiptStarted = $true
    Push-Location frontend
    try { & npm.cmd run build; if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed; runtime was not restarted.' } }
    finally { Pop-Location }
    $sourceProblems = @(Test-ZargarReviewedSource $deployRoot $TargetCommit)
    if ($sourceProblems.Count -gt 0) { throw ('Runtime source changed during build; do not restart: ' + (($sourceProblems | Select-Object -First 6) -join '; ')) }
    $manifest = Get-ZargarArtifactManifest $deployRoot
    $receipt.phase = 'restarting'
    $receipt | Add-Member -NotePropertyName artifactManifestSha256 -NotePropertyValue $manifest.ManifestSha256
    $receipt | Add-Member -NotePropertyName artifactFileCount -NotePropertyValue $manifest.FileCount
    $receipt | Add-Member -NotePropertyName artifactSha256 -NotePropertyValue $manifest.Files['index.html']   # compatibility field
    Write-ZargarReceipt $deployRoot $receipt
    $handoff = [ordered]@{ target=$TargetCommit; expectedVersion=$Expect; artifactManifestSha256=$manifest.ManifestSha256
                           artifactFileCount=$manifest.FileCount; artifactSha256=$manifest.Files['index.html']; files=$manifest.Files
                           issuedBy=('deploy.ps1:' + $PID); expiresAt=[DateTimeOffset]::UtcNow.AddMinutes(10).ToString('o') }
    $handoff | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $deployRoot 'logs/deployment-pending.json') -Encoding ASCII
    $env:ZARGAR_DEPLOY_CALLER = 'deploy.ps1'
    if (Get-ZargarElevation) {
      # 2026-09-19: an elevated shell must never stop the engine it cannot restart. The handoff above is written;
      # release the lease (the task's restart.ps1 takes it, and would otherwise wait on us) and let the
      # Limited ZargarRestart task consume the handoff, then wait for THIS target's terminal receipt.
      Write-Host '> Elevated shell: handing the restart to the ZargarRestart task (it verifies the handoff and restarts)'
      Exit-ZargarDeployment $deployMutex
      Start-ScheduledTask -TaskName 'ZargarRestart'
      $final = Wait-ZargarReceipt $deployRoot $TargetCommit 480
      if ($null -eq $final) { throw 'The ZargarRestart task did not report a terminal receipt within 8 minutes; check logs/restart-*.log and /api/health now.' }
      if ($final.phase -ne 'verified') { throw ('The ZargarRestart task ended ' + $final.phase + ': ' + $final.detail) }
    } else {
      & (Join-Path $PSScriptRoot 'restart.ps1') -Expect $Expect
      if ($LASTEXITCODE -ne 0) { throw "Guarded restart returned $LASTEXITCODE; inspect restart logs." }
      $final = Read-ZargarReceipt $deployRoot
      if ($null -eq $final -or $final.phase -ne 'verified') { throw 'Restart returned 0 but the receipt is not verified; inspect restart logs.' }
    }
  } finally { Pop-Location }
} catch {
  # terminal phase on the record, then the failure propagates (exit code stays non-zero)
  $phase = $(if ($deferred) { 'deferred' } else { 'failed' })
  $detail = $_.Exception.Message
  try {
    if ($receiptStarted -or (Read-ZargarReceipt $deployRoot)) { $null = Set-ZargarReceiptPhase $deployRoot $phase $detail 'deploy.ps1' }
    else { Write-ZargarReceipt $deployRoot ([pscustomobject]@{ ownerPid=$PID; caller='deploy.ps1'; target=$TargetCommit; expectedVersion=$Expect; phase=$phase; detail=$detail; completedAt=[DateTimeOffset]::UtcNow.ToString('o') }) }
  } catch { Write-Host ('receipt not written: ' + $_.Exception.Message) -ForegroundColor Yellow }
  throw
} finally {
  if ($pausedByDeploy) { try { $null = Invoke-RestMethod 'http://127.0.0.1:8420/api/ops/quiesce?release=true' -Method Post -TimeoutSec 5 } catch { } }
  Exit-ZargarDeployment $deployMutex
}
