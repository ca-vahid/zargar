# Focused acceptance for scripts\watchdog-classify.ps1 (PFU-01 re-review): the pure classifier AND the caller decision
# with mocked probe / process / filesystem / alert actions. No real probe, no restart, no file writes.
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\tests\watchdog-classify.tests.ps1
$ErrorActionPreference = 'Stop'
. (Join-Path (Split-Path -Parent $PSScriptRoot) 'watchdog-classify.ps1')
$now = Get-Date '2026-09-17 09:00:00'
$fails = 0
function Check($name, $cond) { if ($cond) { "PASS $name" } else { "FAIL $name"; $script:fails++ } }

# ---------------------------------------------------------------- classifier
$r = Get-EngineClassification -Probe1 $true -Probe2 $false -BoundProcesses 2 -LogAgeS 5 -MarkerAt $now.AddSeconds(-400) -Now $now
Check 'classifier: healthy on the first probe clears an old marker' ($r.class -eq 'healthy' -and $r.markerAction -eq 'clear')
$r = Get-EngineClassification -Probe1 $false -Probe2 $false -BoundProcesses 1 -LogAgeS 181 -MarkerAt $null -Now $now
Check 'classifier: LIVE process with a STALE log is live-unhealthy, never absent (re-review blocker)' ($r.class -eq 'live-unhealthy' -and $r.markerAction -eq 'set')
$r = Get-EngineClassification -Probe1 $false -Probe2 $false -BoundProcesses 1 -LogAgeS 999999 -MarkerAt $null -Now $now
Check 'classifier: live process with NO log is still live-unhealthy' ($r.class -eq 'live-unhealthy')
$r = Get-EngineClassification -Probe1 $false -Probe2 $false -BoundProcesses -1 -LogAgeS 5 -MarkerAt $null -Now $now
Check 'classifier: discovery failure is uncertain, not absent' ($r.class -eq 'uncertain' -and $r.markerAction -eq 'set')
$r = Get-EngineClassification -Probe1 $false -Probe2 $false -BoundProcesses 0 -LogAgeS 5 -MarkerAt $now.AddSeconds(-100) -Now $now
Check 'classifier: zero bound processes is absent and clears the marker' ($r.class -eq 'absent' -and $r.markerAction -eq 'clear')
$r = Get-EngineClassification -Probe1 $false -Probe2 $false -BoundProcesses 2 -LogAgeS 20 -MarkerAt $now.AddSeconds(-2000) -Now $now
Check 'classifier: stale marker restarts the clock (unrelated stalls never chain)' ($r.class -eq 'live-unhealthy' -and -not $r.persisted -and $r.markerAction -eq 'set')
$r = Get-EngineClassification -Probe1 $false -Probe2 $false -BoundProcesses 2 -LogAgeS 20 -MarkerAt $now.AddSeconds(-40) -Now $now
Check 'classifier: 40 s old marker is not persistent' (-not $r.persisted -and $r.markerAction -eq 'none')
$r = Get-EngineClassification -Probe1 $false -Probe2 $false -BoundProcesses 2 -LogAgeS 20 -MarkerAt $now.AddSeconds(-240) -Now $now
Check 'classifier: 240 s stall is persistent and still live-unhealthy' ($r.persisted -and $r.class -eq 'live-unhealthy')
$ro = Get-EngineClassification -Probe1 $false -Probe2 $false -BoundProcesses 2 -LogAgeS 5 -MarkerAt $now.AddSeconds(-2000) -Now $now -ReadOnly
Check 'classifier: read-only never returns a marker action' ($ro.markerAction -eq 'none')

# ---------------------------------------------------------------- caller decision with mocks
function New-Mock([bool[]]$probes, [hashtable]$live, $marker) {
  $state = @{ probes = [System.Collections.ArrayList]@($probes); marker = $marker; sets = 0; clears = 0; logs = [System.Collections.ArrayList]@(); alerts = 0; sleeps = 0 }
  $actions = @{
    Probe       = { param($t) if ($state.probes.Count -gt 0) { $v = $state.probes[0]; $state.probes.RemoveAt(0); return $v } else { return $false } }.GetNewClosure()
    Sleep       = { param($s) $state.sleeps++ }.GetNewClosure()
    Liveness    = { return $live }.GetNewClosure()
    ReadMarker  = { return $state.marker }.GetNewClosure()
    SetMarker   = { $state.sets++; $state.marker = $now }.GetNewClosure()
    ClearMarker = { $state.clears++; $state.marker = $null }.GetNewClosure()
    Log         = { param($m) [void]$state.logs.Add($m) }.GetNewClosure()
    Alert       = { param($t) $state.alerts++; return $true }.GetNewClosure()
    Now         = { return $now }.GetNewClosure()
  }
  return @{ actions = $actions; state = $state }
}

# 1. live process + stale log, no switches -> refuse (exit 2), alerted, marker set, NOT proceed
$m = New-Mock @($false, $false, $false) @{ bound = 1; logAgeS = 900; identity = 'engine.pid 123' } $null
$d = Invoke-WatchdogDecision -Force $false -Override $false -ProbeOnly $false -Actions $m.actions
Check 'caller: live process + stale log refuses (exit 2) and alerts once' ($d.action -eq 'refuse' -and $d.exitCode -eq 2 -and $m.state.alerts -eq 1 -and $m.state.sets -eq 1)
Check 'caller: the refusal names the human next step' (($m.state.logs -join ' ') -match 'ZargarRestartOverride')

# 2. -Force alone with health down and a live engine -> refuse; no proceed
$m = New-Mock @($false, $false, $false) @{ bound = 2; logAgeS = 3; identity = 'engine.pid 123' } $null
$d = Invoke-WatchdogDecision -Force $true -Override $false -ProbeOnly $false -Actions $m.actions
Check 'caller: -Force alone never bypasses an unavailable readiness (refuse)' ($d.action -eq 'refuse' -and $d.exitCode -eq 2 -and (($m.state.logs -join ' ') -match '-Force without -Override'))

# 3. -Force -Override with health down -> proceed-override, recorded as OVERRIDE
$m = New-Mock @($false, $false, $false) @{ bound = 2; logAgeS = 3; identity = 'engine.pid 123' } $null
$d = Invoke-WatchdogDecision -Force $true -Override $true -ProbeOnly $false -Actions $m.actions
Check 'caller: -Force -Override proceeds and is recorded as OVERRIDE' ($d.action -eq 'proceed-override' -and $d.exitCode -eq 0 -and (($m.state.logs -join ' ') -match '^OVERRIDE|OVERRIDE:'))

# 4. first-probe recovery clears the old marker and alert state, exits healthy
$m = New-Mock @($true) @{ bound = 2; logAgeS = 3; identity = 'x' } $now.AddSeconds(-400)
$d = Invoke-WatchdogDecision -Force $false -Override $false -ProbeOnly $false -Actions $m.actions
Check 'caller: first-probe recovery clears marker/alert state and exits healthy' ($d.action -eq 'exit-healthy' -and $m.state.clears -eq 1 -and $m.state.sleeps -eq 0)

# 5. discovery error (-1) does not establish absence -> refuse
$m = New-Mock @($false, $false, $false) @{ bound = -1; logAgeS = 999999; identity = 'discovery failed: CIM' } $null
$d = Invoke-WatchdogDecision -Force $false -Override $false -ProbeOnly $false -Actions $m.actions
Check 'caller: process discovery failure is uncertain -> refuse, never proceed-down' ($d.action -eq 'refuse' -and $d.class -eq 'uncertain')

# 6. ProbeOnly causes no recovery-state mutation in any branch, and no log writes
foreach ($case in @(@{ p = @($true); live = @{ bound = 2; logAgeS = 1; identity = 'x' }; mk = $now.AddSeconds(-400) },
                    @{ p = @($false, $false, $false); live = @{ bound = 1; logAgeS = 900; identity = 'x' }; mk = $null },
                    @{ p = @($false, $false, $false); live = @{ bound = 0; logAgeS = 999999; identity = 'x' }; mk = $now.AddSeconds(-100) })) {
  $m = New-Mock $case.p $case.live $case.mk
  $d = Invoke-WatchdogDecision -Force $false -Override $false -ProbeOnly $true -Actions $m.actions
  Check ("caller: ProbeOnly mutates nothing (class " + $d.class + ")") ($d.action -eq 'probe-only' -and $m.state.sets -eq 0 -and $m.state.clears -eq 0 -and $m.state.alerts -eq 0 -and $m.state.logs.Count -eq 0)
}

# 7. absent (discovery worked, zero bound processes) -> proceed-down with up=false, marker cleared
$m = New-Mock @($false, $false, $false) @{ bound = 0; logAgeS = 999999; identity = 'venv-path fallback (0 proc)' } $now.AddSeconds(-100)
$d = Invoke-WatchdogDecision -Force $false -Override $false -ProbeOnly $false -Actions $m.actions
Check 'caller: absent proceeds down the existing DOWN path and clears the marker' ($d.action -eq 'proceed-down' -and $d.up -eq $false -and $m.state.clears -eq 1)

# 8. late second probe -> healthy; with -Force it proceeds with readiness available (up=true)
$m = New-Mock @($false, $true) @{ bound = 2; logAgeS = 3; identity = 'x' } $now.AddSeconds(-50)
$d = Invoke-WatchdogDecision -Force $true -Override $false -ProbeOnly $false -Actions $m.actions
Check 'caller: late probe ok + -Force -> proceed-force with readiness available' ($d.action -eq 'proceed-force' -and $d.up -eq $true -and $m.state.clears -eq 1)

"result: $fails failure(s)"
exit $fails
