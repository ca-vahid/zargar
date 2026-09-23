# Watchdog engine classification + decision (EM desk, PFU-01 re-review 2026-09-17) - PURE: no probes, no kills, no files.
# Dot-source it. Get-EngineClassification turns observed facts into a class; Invoke-WatchdogDecision turns the class
# and the switches into ONE action, calling only the injected action scriptblocks, so the caller paths are testable
# with mocks (scripts\tests\watchdog-classify.tests.ps1) and watchdog.ps1 only supplies real implementations.
#
#   healthy          a probe answered ok                                  -> nothing to do; clear any stall marker
#   live-unhealthy   no probe answered, THIS runtime's engine process exists -> a stall. Log inactivity proves nothing:
#                    a live process with a quiet log is still live. Readiness is unavailable, so ordinary recovery -
#                    with or without -Force - is REFUSED; only the explicit -Override replaces a living engine.
#   uncertain        process discovery failed or identity is ambiguous  -> treated exactly like live-unhealthy
#   absent           process discovery worked and found no bound engine -> the existing DOWN path (nothing to quiesce)
#
# Stall persistence is time-based: the marker persists only when set >= MinStallS and <= MaxStallS ago; older = an
# unrelated stall, the clock restarts. ANY successful probe clears the marker and the alert companion. A read-only
# call (ProbeOnly) returns markerAction 'none' in every branch and the decision never mutates anything.

function Get-EngineClassification {
  param(
    [bool]$Probe1,
    [bool]$Probe2,
    [int]$BoundProcesses,          # >0 bound engine processes; 0 none; -1 discovery failed / identity ambiguous
    [int]$LogAgeS,                 # seconds since the engine log was last written (999999 = no log) - a NOTE, never proof of absence
    [Nullable[datetime]]$MarkerAt, # when the stall marker was written, or $null
    [datetime]$Now,
    [int]$MinStallS = 180,
    [int]$MaxStallS = 600,
    [switch]$ReadOnly
  )
  $result = @{ class = ''; persisted = $false; markerAction = 'none'; stallAgeS = $null; reason = ''; logAgeS = $LogAgeS }
  if ($Probe1 -or $Probe2) {
    $result.class = 'healthy'
    $result.reason = $(if ($Probe1) { 'first probe ok' } else { 'second/third probe ok (transient stall)' })
    if (-not $ReadOnly -and $MarkerAt -ne $null) { $result.markerAction = 'clear' }
    return $result
  }
  if ($BoundProcesses -lt 0) {
    $result.class = 'uncertain'
    $result.reason = 'process discovery failed or identity ambiguous - absence is not established'
  } elseif ($BoundProcesses -eq 0) {
    $result.class = 'absent'
    $result.reason = "no bound engine process (log age ${LogAgeS}s)"
    if (-not $ReadOnly -and $MarkerAt -ne $null) { $result.markerAction = 'clear' }
    return $result
  } else {
    $result.class = 'live-unhealthy'
    $result.reason = "engine process alive ($BoundProcesses bound) but health unanswered; log age ${LogAgeS}s" + $(if ($LogAgeS -ge 180) { ' (quiet log - still not proof of absence)' } else { '' })
  }
  # live-unhealthy / uncertain share the stall clock
  if ($MarkerAt -eq $null) {
    $result.reason += '; first sighting'
    if (-not $ReadOnly) { $result.markerAction = 'set' }
    return $result
  }
  $age = [int]($Now - $MarkerAt).TotalSeconds
  $result.stallAgeS = $age
  if ($age -gt $MaxStallS) {
    $result.reason += "; previous marker stale (${age}s > ${MaxStallS}s) - unrelated stall, clock restarted"
    if (-not $ReadOnly) { $result.markerAction = 'set' }
    return $result
  }
  if ($age -lt $MinStallS) {
    $result.reason += "; stall observed for ${age}s (< ${MinStallS}s) - not yet persistent"
    return $result
  }
  $result.persisted = $true
  $result.reason += "; stall persisted ${age}s (>= ${MinStallS}s) - readiness unavailable"
  return $result
}

function Invoke-WatchdogDecision {
  # Every side effect goes through $Actions: Probe(timeoutSec)->bool, Sleep(sec), Liveness()->@{bound;logAgeS;identity},
  # ReadMarker()->datetime|$null, SetMarker(), ClearMarker(), Log(msg), Alert(text)->bool, Now()->datetime.
  # Returns @{ action; exitCode; class; reason; up } where action is one of:
  #   exit-healthy | probe-only | refuse | proceed-force | proceed-override | proceed-down
  # proceed-force  : health answered and -Force asked - the caller runs readiness/quiesce/inventory (up = $true)
  # proceed-override: explicit -Override over a live/uncertain engine - recorded as OVERRIDE (up = $false, readiness unavailable)
  # proceed-down   : discovery found NO bound process - the existing DOWN path (up = $false)
  param([bool]$Force, [bool]$Override, [bool]$ProbeOnly, [hashtable]$Actions, [int]$MinStallS = 180, [int]$MaxStallS = 600)
  $up1 = [bool](& $Actions.Probe 4)
  if ($up1) {
    if ($ProbeOnly) { return @{ action = 'probe-only'; exitCode = 0; class = 'healthy'; reason = 'first probe ok'; up = $true } }
    $marker = & $Actions.ReadMarker
    if ($marker -ne $null) { & $Actions.ClearMarker; & $Actions.Log 'engine healthy on the first probe - stall marker and alert state cleared' }
    if ($Force) { return @{ action = 'proceed-force'; exitCode = 0; class = 'healthy'; reason = 'restart requested with health answering'; up = $true } }
    return @{ action = 'exit-healthy'; exitCode = 0; class = 'healthy'; reason = 'first probe ok'; up = $true }
  }
  # 2-of-3 probes with 12 s timeouts before anything is called unhealthy
  & $Actions.Sleep 15
  $up2 = [bool](& $Actions.Probe 12)
  if (-not $up2) { & $Actions.Sleep 10; $up2 = [bool](& $Actions.Probe 12) }
  $live = & $Actions.Liveness
  $marker = & $Actions.ReadMarker
  $cls = Get-EngineClassification -Probe1 $false -Probe2 $up2 -BoundProcesses ([int]$live.bound) -LogAgeS ([int]$live.logAgeS) -MarkerAt $marker -Now (& $Actions.Now) -MinStallS $MinStallS -MaxStallS $MaxStallS -ReadOnly:$ProbeOnly
  if ($ProbeOnly) { return @{ action = 'probe-only'; exitCode = 0; class = $cls.class; reason = $cls.reason; up = $up2; identity = $live.identity } }
  switch ($cls.markerAction) { 'set' { & $Actions.SetMarker } 'clear' { & $Actions.ClearMarker } }
  if ($cls.class -eq 'healthy') {
    & $Actions.Log ("health answered late (" + $cls.reason + ")")
    if ($Force) { return @{ action = 'proceed-force'; exitCode = 0; class = 'healthy'; reason = $cls.reason; up = $true } }
    return @{ action = 'exit-healthy'; exitCode = 0; class = 'healthy'; reason = $cls.reason; up = $true }
  }
  if ($cls.class -eq 'absent') {
    & $Actions.Log ("DOWN confirmed: " + $cls.reason + " (identity " + $live.identity + ")")
    return @{ action = 'proceed-down'; exitCode = 0; class = 'absent'; reason = $cls.reason; up = $false }
  }
  # live-unhealthy or uncertain: readiness is unavailable. -Force alone never bypasses this; only -Override does.
  if ($Override) {
    & $Actions.Log ("OVERRIDE: " + $cls.class + " engine (" + $cls.reason + "; identity " + $live.identity + ") - replacing it on explicit override; readiness was unavailable")
    return @{ action = 'proceed-override'; exitCode = 0; class = $cls.class; reason = $cls.reason; up = $false }
  }
  $msg = ("REFUSED restart" + $(if ($Force) { ' (-Force without -Override)' } else { '' }) + ": " + $cls.class + " engine (" + $cls.reason + "; identity " + $live.identity + "). " +
          "Readiness is unavailable so ordinary recovery is refused. HUMAN NEXT STEP: check the engine (scripts\logs.ps1, /api/health); " +
          "if positions are held and it stays stalled, run the scheduled task ZargarRestartOverride (or watchdog.ps1 -Force -Override) - the only path that replaces a live engine.")
  & $Actions.Log $msg
  $sent = [bool](& $Actions.Alert ("Zargar watchdog: " + $msg))
  & $Actions.Log ("escalation " + $(if ($sent) { 'sent (once per stall marker)' } else { 'not sent (no Telegram config, already alerted for this marker, or send failed)' }))
  return @{ action = 'refuse'; exitCode = 2; class = $cls.class; reason = $cls.reason; up = $false }
}

function Get-BoundEngineProcessCount {
  # Identity, strongest first: (1) the pid the engine stamped itself in logs\engine.pid (alive AND a zargar.main
  # command line); (2) fallback: zargar.main processes whose executable lives under THIS runtime's backend\.venv.
  # Returns -1 when discovery itself fails (CIM error) - the caller treats that as `uncertain`, never as absence.
  param([string]$Root)
  try {
    $pidFile = Join-Path $Root 'logs\engine.pid'
    if (Test-Path $pidFile) {
      $stamped = 0
      try { $stamped = [int](Get-Content $pidFile -Raw).Trim() } catch { $stamped = 0 }
      if ($stamped -gt 0) {
        $p = Get-CimInstance Win32_Process -Filter "ProcessId=$stamped" -ErrorAction Stop
        if ($p -and $p.CommandLine -match 'zargar\.main') { $script:WatchdogIdentity = "engine.pid $stamped"; return 1 }
        $script:WatchdogIdentity = "engine.pid $stamped not alive"
      }
    }
    $venv = (Join-Path $Root 'backend\.venv\').ToLowerInvariant()
    $procs = @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
        $_.CommandLine -match 'zargar\.main' -and $_.ExecutablePath -and $_.ExecutablePath.ToLowerInvariant().StartsWith($venv) })
    $script:WatchdogIdentity = "venv-path fallback (" + $procs.Count + " proc)"
    return $procs.Count
  } catch {
    $script:WatchdogIdentity = "discovery failed: " + $_.Exception.Message
    return -1
  }
}

function Send-WatchdogAlert {
  # Once per stall marker: Telegram (token/chat from backend\.env, never logged). Returns $true only when sent.
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
