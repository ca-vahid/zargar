# One deployment ownership protocol: OS mutex plus deploy.lock compatibility marker.
function Enter-ZargarDeployment([string]$Root, [switch]$Restart, [switch]$Nested) {
  $Root = [IO.Path]::GetFullPath($Root).TrimEnd([IO.Path]::DirectorySeparatorChar)
  $marker = Join-Path $Root 'logs/deploy.lock'
  $inherited = $env:ZARGAR_DEPLOY_LEASE
  if ($inherited -and (Test-Path -LiteralPath $marker) -and (Get-Content -LiteralPath $marker -Raw).Trim() -eq $inherited) {
    $parts = $inherited.Split(':')
    $ownerPid = 0
    if ($parts.Length -ge 3 -and $parts[0] -eq $env:COMPUTERNAME -and [int]::TryParse($parts[1], [ref]$ownerPid)) {
      $probe = $PID
      for ($depth=0; $depth -lt 8 -and $probe -gt 0; $depth++) {
        if ($probe -eq $ownerPid -and ($probe -eq $PID -or $Nested)) {
          return [pscustomobject]@{ Mutex=$null; Marker=$marker; Owner=$inherited; Owns=$false; Previous=$inherited }
        }
        if (-not $Nested) { break }
        $process = Get-CimInstance Win32_Process -Filter "ProcessId = $probe" -ErrorAction Stop
        $probe = [int]$process.ParentProcessId
      }
    }
  }
  $sha = [Security.Cryptography.SHA256]::Create()
  try { $hash = [BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($Root.ToLowerInvariant()))).Replace('-', '') }
  finally { $sha.Dispose() }
  $mutex = New-Object Threading.Mutex($false, ('Global\ZargarDeploy-' + $hash.Substring(0,24)))
  $acquired = $false
  try { $acquired = $mutex.WaitOne(0) }
  catch [Threading.AbandonedMutexException] { $acquired = $true }
  if (-not $acquired) { $mutex.Dispose(); throw 'Another deployment owns this runtime. Wait for its receipt.' }
  try {
    $pendingPath = Join-Path $Root 'logs/deployment-pending.json'
    if (-not $Restart -and (Test-Path -LiteralPath $pendingPath)) {
      $pending = Get-Content -LiteralPath $pendingPath -Raw | ConvertFrom-Json
      if ([DateTimeOffset]::Parse($pending.expiresAt) -gt [DateTimeOffset]::UtcNow) {
        throw 'A reviewed deployment is awaiting its elevated restart. Wait for its receipt.'
      }
    }
    if (Test-Path -LiteralPath $marker) {
      $old = (Get-Content -LiteralPath $marker -Raw).Trim().Split(':')
      $oldPid = 0
      if ($old.Length -lt 3 -or $old[0] -ne $env:COMPUTERNAME -or -not [int]::TryParse($old[1], [ref]$oldPid)) {
        throw 'An unidentified deployment marker exists; inspect its owner before proceeding.'
      }
      if (Get-Process -Id $oldPid -ErrorAction SilentlyContinue) { throw 'The existing deployment marker owner is still alive.' }
      Remove-Item -LiteralPath $marker
    }
    New-Item -ItemType Directory -Force (Split-Path $marker) | Out-Null
    $owner = '{0}:{1}:{2}' -f $env:COMPUTERNAME,$PID,[Guid]::NewGuid().ToString('N')
    $stream = [IO.File]::Open($marker,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::Read)
    try { $bytes=[Text.Encoding]::ASCII.GetBytes($owner);$stream.Write($bytes,0,$bytes.Length) }
    finally { $stream.Dispose() }
    $env:ZARGAR_DEPLOY_LEASE = $owner
    return [pscustomobject]@{ Mutex=$mutex; Marker=$marker; Owner=$owner; Owns=$true; Previous=$inherited }
  } catch { $mutex.ReleaseMutex(); $mutex.Dispose(); throw }
}
function Exit-ZargarDeployment($Lease) {
  if ($null -eq $Lease -or -not $Lease.Owns) { return }
  try {
    if ((Test-Path -LiteralPath $Lease.Marker) -and (Get-Content -LiteralPath $Lease.Marker -Raw).Trim() -eq $Lease.Owner) {
      Remove-Item -LiteralPath $Lease.Marker
    }
    if ($Lease.Previous) { $env:ZARGAR_DEPLOY_LEASE=$Lease.Previous }
    else { Remove-Item Env:ZARGAR_DEPLOY_LEASE -ErrorAction SilentlyContinue }
  } finally { $Lease.Mutex.ReleaseMutex(); $Lease.Mutex.Dispose(); $Lease.Owns=$false }
}
