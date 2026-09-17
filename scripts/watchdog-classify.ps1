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
  param([string]$Root)
  $venv = (Join-Path $Root 'backend\.venv\').ToLowerInvariant()
  $procs = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
      $_.CommandLine -match 'zargar\.main' -and $_.ExecutablePath -and $_.ExecutablePath.ToLowerInvariant().StartsWith($venv) })
  return $procs.Count
}
