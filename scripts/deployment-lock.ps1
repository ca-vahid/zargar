# OS-owned, cross-process lease. A dead owner cannot leave a permanent lock.
function Enter-ZargarDeployment([string]$Root, [switch]$Restart) {
  $Root = [IO.Path]::GetFullPath($Root).TrimEnd([IO.Path]::DirectorySeparatorChar)
  $sha = [Security.Cryptography.SHA256]::Create()
  try { $hash = [BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($Root.ToLowerInvariant()))).Replace('-', '') }
  finally { $sha.Dispose() }
  $mutex = New-Object Threading.Mutex($false, ('Global\ZargarDeploy-' + $hash.Substring(0,24)))
  $acquired = $false
  try { $acquired = $mutex.WaitOne(0) }
  catch [Threading.AbandonedMutexException] { $acquired = $true }
  if (-not $acquired) { $mutex.Dispose(); throw 'Another deployment owns this runtime. Wait for its receipt before retrying.' }
  try {
    $pendingPath = Join-Path $Root 'logs/deployment-pending.json'
    if (-not $Restart -and (Test-Path -LiteralPath $pendingPath)) {
      $pending = Get-Content -LiteralPath $pendingPath -Raw | ConvertFrom-Json
      if ([DateTimeOffset]::Parse($pending.expiresAt) -gt [DateTimeOffset]::UtcNow) {
        throw 'A reviewed deployment is awaiting its elevated restart. Wait for its receipt.'
      }
    }
  } catch { $mutex.ReleaseMutex(); $mutex.Dispose(); throw }
  return $mutex
}
function Exit-ZargarDeployment($Mutex) {
  if ($null -ne $Mutex) { $Mutex.ReleaseMutex(); $Mutex.Dispose() }
}
