# One deployment ownership protocol: OS mutex plus deploy.lock compatibility marker.
# ASCII ONLY (Windows PowerShell 5.1 reads a BOM-less file as ANSI). Every deploy door
# (deploy.ps1, restart.ps1, start.ps1, watchdog.ps1 - the ZargarRestart task calls
# restart.ps1) dot-sources this file: ONE lease, ONE reviewed-artifact check, ONE
# runtime identity and ONE receipt format (KFIN-04, 2026-09-14).
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

# --- reviewed artifact + source (KFIN-04) ------------------------------------------------------
# .NET hashing on purpose: Get-FileHash is a module function that Windows PowerShell 5.1 cannot find
# when it inherits a PowerShell 7 PSModulePath (an assistant shell driving a 5.1 child).
function Get-ZargarFileSha256([string]$Path) {
  $sha = [Security.Cryptography.SHA256]::Create()
  $stream = [IO.File]::Open($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite)
  try { return [BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-','') }
  finally { $stream.Dispose(); $sha.Dispose() }
}
# The built artifact is ALL of frontend/dist (a modified dist/assets/*.js is a different runtime even
# when dist/index.html is unchanged): every file hashed, the manifest hash is over the sorted list.
function Get-ZargarArtifactManifest([string]$Root, [switch]$AllowMissing) {
  $dist = Join-Path $Root 'frontend/dist'
  if (-not (Test-Path -LiteralPath $dist)) {
    if ($AllowMissing) { return [pscustomobject]@{ ManifestSha256=$null; FileCount=0; Files=@{} } }
    throw 'Built artifact missing: frontend/dist does not exist.'
  }
  $dist = (Resolve-Path -LiteralPath $dist).Path.TrimEnd('\','/')
  $rels = @(Get-ChildItem -LiteralPath $dist -Recurse -File | ForEach-Object { $_.FullName.Substring($dist.Length).TrimStart('\','/').Replace('\','/') })
  if ($rels.Count -eq 0) {
    if ($AllowMissing) { return [pscustomobject]@{ ManifestSha256=$null; FileCount=0; Files=@{} } }
    throw 'Built artifact is empty: frontend/dist has no files.'
  }
  [Array]::Sort($rels, [StringComparer]::Ordinal)
  $files = [ordered]@{}
  $sb = New-Object Text.StringBuilder
  foreach ($rel in $rels) {
    $h = Get-ZargarFileSha256 (Join-Path $dist $rel)
    $files[$rel] = $h
    [void]$sb.Append($rel).Append('=').Append($h).Append("`n")
  }
  $sha = [Security.Cryptography.SHA256]::Create()
  try { $manifest = [BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($sb.ToString()))).Replace('-','') }
  finally { $sha.Dispose() }
  return [pscustomobject]@{ ManifestSha256=$manifest; FileCount=$rels.Count; Files=$files }
}
function Compare-ZargarArtifactManifest($Expected, $Actual) {
  # $Expected.files may be a PSCustomObject (read back from JSON); $Actual.Files an ordered hashtable
  $exp = @{}
  if ($Expected -and $Expected.PSObject.Properties['files'] -and $Expected.files) {
    foreach ($p in $Expected.files.PSObject.Properties) { $exp[$p.Name] = [string]$p.Value }
  }
  $act = @{}
  foreach ($k in $Actual.Files.Keys) { $act[$k] = [string]$Actual.Files[$k] }
  $diff = @()
  foreach ($k in $act.Keys) {
    if (-not $exp.ContainsKey($k)) { $diff += ('added ' + $k) }
    elseif ($exp[$k] -ne $act[$k]) { $diff += ('modified ' + $k) }
  }
  foreach ($k in $exp.Keys) { if (-not $act.ContainsKey($k)) { $diff += ('removed ' + $k) } }
  return @($diff | Sort-Object)
}
# Clean reviewed source = HEAD is the reviewed target, nothing modified or untracked, and no
# IGNORED source-like file (.py/.js/.ts/.css ...) inside the shipped trees - a gitignored file
# under backend/zargar or frontend/src is unreviewed code the runtime would still load.
function Test-ZargarReviewedSource([string]$Root, [string]$Target) {
  $problems = @()
  $head = & git -C $Root rev-parse HEAD 2>$null
  if ($LASTEXITCODE -ne 0 -or -not $head) { return @('not a git checkout: ' + $Root) }
  $head = ([string]$head).Trim()
  if ($Target -and $head -ne $Target) { $problems += ('HEAD ' + $head + ' is not the reviewed target ' + $Target) }
  $status = @(& git -C $Root status --porcelain --untracked-files=all 2>$null)
  foreach ($line in $status) { if ($line) { $problems += ('uncommitted: ' + ([string]$line).Trim()) } }
  $ignored = @(& git -C $Root status --porcelain --ignored=matching --untracked-files=all -- backend/zargar frontend/src frontend/public frontend/index.html 2>$null)
  foreach ($line in $ignored) {
    $line = [string]$line
    if (-not $line.StartsWith('!! ')) { continue }
    $path = $line.Substring(3).Trim()
    if ($path -match '(^|/)__pycache__/' -or $path -match '\.pyc$') { continue }
    if ($path -match '\.(py|js|mjs|cjs|ts|tsx|css|html)$') { $problems += ('ignored source file present: ' + $path) }
  }
  return @($problems)
}
function Assert-ZargarHandoff([string]$Root, $Handoff, [string]$Expect) {
  if ($null -eq $Handoff) { throw 'No deployment handoff to verify.' }
  if ([DateTimeOffset]::Parse($Handoff.expiresAt) -le [DateTimeOffset]::UtcNow) { throw 'Deployment handoff expired; revalidate source and artifact before restart.' }
  $problems = @(Test-ZargarReviewedSource $Root $Handoff.target)
  if ($problems.Count -gt 0) { throw ('Deployment source is not the reviewed target; restart refused: ' + (($problems | Select-Object -First 6) -join '; ')) }
  $manifest = Get-ZargarArtifactManifest $Root
  $expectedManifest = $null
  if ($Handoff.PSObject.Properties['artifactManifestSha256']) { $expectedManifest = $Handoff.artifactManifestSha256 }
  if (-not $expectedManifest) { throw 'Deployment handoff carries no artifact manifest; rebuild under deploy.ps1.' }
  if ($manifest.ManifestSha256 -ne $expectedManifest) {
    $diff = @(Compare-ZargarArtifactManifest $Handoff $manifest)
    throw ('Deployment artifact changed after handoff; restart refused (' + $(if ($diff.Count) { ($diff | Select-Object -First 6) -join ', ' } else { 'manifest mismatch' }) + ').')
  }
  if ($Expect -and $Expect -ne $Handoff.expectedVersion) { throw 'Expected version disagrees with deployment handoff.' }
  return $manifest
}

# --- runtime identity + receipt (shared by every door) ---------------------------------------------
function Get-ZargarRuntimeIdentity([string]$Root, [string]$Caller) {
  $Root = [IO.Path]::GetFullPath($Root).TrimEnd([IO.Path]::DirectorySeparatorChar)
  $head = $null
  try { $head = ([string](& git -C $Root rev-parse HEAD 2>$null)).Trim() } catch { $head = $null }
  $dirty = @(Test-ZargarReviewedSource $Root $head)
  $manifest = Get-ZargarArtifactManifest $Root -AllowMissing
  $scripts = [ordered]@{}
  foreach ($s in @('deployment-lock.ps1','deploy.ps1','restart.ps1','start.ps1','watchdog.ps1')) {
    $p = Join-Path $Root ('scripts/' + $s)
    if (Test-Path -LiteralPath $p) { $scripts[$s] = Get-ZargarFileSha256 $p }
  }
  if (-not $Caller) { $Caller = $env:ZARGAR_DEPLOY_CALLER }
  if (-not $Caller) { $Caller = 'manual' }
  return [pscustomobject]@{
    root=$Root; head=$head; clean=($dirty.Count -eq 0); problems=@($dirty | Select-Object -First 10)
    artifactManifestSha256=$manifest.ManifestSha256; artifactFileCount=$manifest.FileCount
    scripts=$scripts; caller=$Caller; host=$env:COMPUTERNAME; ownerPid=$PID
    lease=$env:ZARGAR_DEPLOY_LEASE; at=[DateTimeOffset]::UtcNow.ToString('o') }
}
function Write-ZargarRuntimeIdentity([string]$Root, [string]$Caller) {
  $identity = Get-ZargarRuntimeIdentity $Root $Caller
  $path = Join-Path $Root 'logs/runtime-identity.json'
  New-Item -ItemType Directory -Force (Split-Path $path) | Out-Null
  $identity | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $path -Encoding ASCII
  return $identity
}
function Read-ZargarReceipt([string]$Root) {
  $path = Join-Path $Root 'logs/deployment-receipt.json'
  if (-not (Test-Path -LiteralPath $path)) { return $null }
  return (Get-Content -LiteralPath $path -Raw | ConvertFrom-Json)
}
function Write-ZargarReceipt([string]$Root, $Receipt) {
  $path = Join-Path $Root 'logs/deployment-receipt.json'
  New-Item -ItemType Directory -Force (Split-Path $path) | Out-Null
  $Receipt | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $path -Encoding ASCII
}
# A deployment never ends in 'building' / 'restarting': the terminal phase (verified | failed |
# deferred) and why are written on every exit path.
function Set-ZargarReceiptPhase([string]$Root, [string]$Phase, [string]$Detail, [string]$Caller) {
  $receipt = Read-ZargarReceipt $Root
  if ($null -eq $receipt) { $receipt = [pscustomobject]@{} }
  $set = @{ phase=$Phase; completedAt=[DateTimeOffset]::UtcNow.ToString('o'); ownerPid=$PID }
  if ($Detail) { $set['detail'] = $Detail }
  if ($Caller) { $set['completedBy'] = $Caller }
  foreach ($k in $set.Keys) {
    if ($receipt.PSObject.Properties[$k]) { $receipt.$k = $set[$k] }
    else { $receipt | Add-Member -NotePropertyName $k -NotePropertyValue $set[$k] }
  }
  Write-ZargarReceipt $Root $receipt
  return $receipt
}
