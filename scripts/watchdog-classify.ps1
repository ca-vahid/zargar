# Watchdog engine classification (EM desk proposal 2026-09-17, PFU-01) - PURE: no probes, no process kills, no files.
# Dot-source it and call Get-EngineClassification with the observed facts; the caller decides what to do.
#
#   healthy         a probe answered ok            -> nothing to do; clear any stall marker
#   live-unhealthy  no probe answered, but THIS runtime's engine process exists and its log is fresh
#                   -> a stall. Never permission to skip readiness: ordinary recovery is REFUSED; the emergency
#                      override is the only path to a replacement while the engine is alive.
#   absent          no bound engine process, or its log is stale -> the existing DOWN path (nothing to quiesce)
#
# Stall persistence is a fact about time, not about ticks: a stall "persists" only when the marker was set at least
# MinStallS ago and no more than MaxStallS ago. A marker older than MaxStallS is stale and is replaced (two unrelated
# stalls never become one). Any successful probe clears the marker. A diagnostic call (ProbeOnly) must pass
# -ReadOnly and then no marker action is returned.

function Get-EngineClassification {
  param(
    [bool]$Probe1,
    [bool]$Probe2,
    [int]$BoundProcesses,          # engine processes whose executable lives under THIS runtime's backend\.venv
    [int]$LogAgeS,                 # seconds since the engine log was last written (999999 = no log)
    [Nullable[datetime]]$MarkerAt, # when the stall marker was written, or $null
    [datetime]$Now,
    [int]$LogFreshS = 180,
    [int]$MinStallS = 180,
    [int]$MaxStallS = 600,
    [switch]$ReadOnly
  )
  $result = @{ class = ''; persisted = $false; markerAction = 'none'; stallAgeS = $null; reason = '' }
  if ($Probe1 -or $Probe2) {
    $result.class = 'healthy'
    $result.reason = $(if ($Probe1) { 'first probe ok' } else { 'second probe ok (transient stall)' })
    if (-not $ReadOnly -and $MarkerAt -ne $null) { $result.markerAction = 'clear' }
    return $result
  }
  $alive = ($BoundProcesses -gt 0) -and ($LogAgeS -lt $LogFreshS)
  if (-not $alive) {
    $result.class = 'absent'
    $result.reason = "no bound engine process or stale log (processes=$BoundProcesses, logAge=${LogAgeS}s)"
    if (-not $ReadOnly -and $MarkerAt -ne $null) { $result.markerAction = 'clear' }
    return $result
  }
  $result.class = 'live-unhealthy'
  if ($MarkerAt -eq $null) {
    $result.reason = 'first sighting of a live engine that does not answer health'
    if (-not $ReadOnly) { $result.markerAction = 'set' }
    return $result
  }
  $age = [int]($Now - $MarkerAt).TotalSeconds
  $result.stallAgeS = $age
  if ($age -gt $MaxStallS) {
    $result.reason = "previous stall marker is stale (${age}s > ${MaxStallS}s) - unrelated stall, restarting the clock"
    if (-not $ReadOnly) { $result.markerAction = 'set' }
    return $result
  }
  if ($age -lt $MinStallS) {
    $result.reason = "stall observed for ${age}s (< ${MinStallS}s) - not yet persistent"
    return $result
  }
  $result.persisted = $true
  $result.reason = "stall persisted ${age}s (>= ${MinStallS}s) with the engine alive - readiness unavailable"
  return $result
}

function Get-BoundEngineProcessCount {
  # Identity, strongest first: (1) the pid the engine stamped itself in logs\engine.pid (alive AND a zargar.main
  # command line); (2) fallback: zargar.main processes whose executable lives under THIS runtime's backend\.venv.
  # A second engine started by hand from the same venv is only counted under the fallback, and the caller logs which
  # identity was used.
  param([string]$Root)
  $pidFile = Join-Path $Root 'logs\engine.pid'
  if (Test-Path $pidFile) {
    $stamped = 0
    try { $stamped = [int](Get-Content $pidFile -Raw).Trim() } catch { $stamped = 0 }
    if ($stamped -gt 0) {
      $p = Get-CimInstance Win32_Process -Filter "ProcessId=$stamped" -ErrorAction SilentlyContinue
      if ($p -and $p.CommandLine -match 'zargar\.main') { $script:WatchdogIdentity = "engine.pid $stamped"; return 1 }
      $script:WatchdogIdentity = "engine.pid $stamped not alive"; return 0
    }
  }
  $venv = (Join-Path $Root 'backend\.venv\').ToLowerInvariant()
  $procs = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
      $_.CommandLine -match 'zargar\.main' -and $_.ExecutablePath -and $_.ExecutablePath.ToLowerInvariant().StartsWith($venv) })
  $script:WatchdogIdentity = "venv-path fallback (" + $procs.Count + " proc)"
  return $procs.Count
}

function Send-WatchdogAlert {
  # Once per stall marker: Telegram (token/chat from backend\.env, never logged) + the log line the caller writes.
  param([string]$Root, [string]$Text, [string]$OnceFile)
  if ($OnceFile -and (Test-Path $OnceFile)) { return $false }
  $envPath = Join-Path $Root 'backend\.env'
  if (-not (Test-Path $envPath)) { return $false }
  $tok = $null; $chat = $null
  foreach ($line in Get-Content $envPath) {
    if ($line -match '^ZARGAR_TELEGRAM_BOT_TOKEN=(.+)$') { $tok = $Matches[1].Trim().Trim('"') }
    if ($line -match '^ZARGAR_TELEGRAM_CHAT_ID=(.+)$') { $chat = $Matches[1].Trim().Trim('"') }
  }
  if (-not $tok -or -not $chat) { return $false }
  try {
    Invoke-RestMethod -Uri ("https://api.telegram.org/bot" + $tok + "/sendMessage") -Method Post -TimeoutSec 10 -Body @{ chat_id = $chat; text = $Text } | Out-Null
    if ($OnceFile) { Set-Content -Path $OnceFile -Value (Get-Date -Format "yyyy-MM-dd HH:mm:ss") }
    return $true
  } catch { return $false }
}
