# Focused acceptance for scripts\watchdog-classify.ps1 (PFU-01). Plain PowerShell, no Pester, no probes, no restarts.
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\tests\watchdog-classify.tests.ps1
$ErrorActionPreference = 'Stop'
. (Join-Path (Split-Path -Parent $PSScriptRoot) 'watchdog-classify.ps1')
$now = Get-Date '2026-09-17 09:00:00'
$fails = 0
function Check($name, $cond) { if ($cond) { "PASS $name" } else { "FAIL $name"; $script:fails++ } }

# 1. first-probe recovery clears an old marker and never advances recovery
$r = Get-EngineClassification -Probe1 $true -Probe2 $false -BoundProcesses 2 -LogAgeS 5 -MarkerAt $now.AddSeconds(-400) -Now $now
Check 'healthy on the first probe clears an old marker' ($r.class -eq 'healthy' -and $r.markerAction -eq 'clear' -and -not $r.persisted)

# 2. second-probe recovery is healthy too
$r = Get-EngineClassification -Probe1 $false -Probe2 $true -BoundProcesses 2 -LogAgeS 5 -MarkerAt $null -Now $now
Check 'healthy on the second probe (transient stall)' ($r.class -eq 'healthy' -and $r.markerAction -eq 'none')

# 3. two unrelated stalls do not become consecutive: a marker older than MaxStallS restarts the clock
$r = Get-EngineClassification -Probe1 $false -Probe2 $false -BoundProcesses 2 -LogAgeS 20 -MarkerAt $now.AddSeconds(-2000) -Now $now
Check 'stale marker is replaced, not treated as persistence' ($r.class -eq 'live-unhealthy' -and -not $r.persisted -and $r.markerAction -eq 'set')

# 4. rapid invocations do not satisfy the duration threshold
$r = Get-EngineClassification -Probe1 $false -Probe2 $false -BoundProcesses 2 -LogAgeS 20 -MarkerAt $now.AddSeconds(-40) -Now $now
Check 'a 40 s old marker is not persistent (MinStallS 180)' ($r.class -eq 'live-unhealthy' -and -not $r.persisted -and $r.markerAction -eq 'none')

# 5. a stall that lasted long enough is persistent - and STILL live-unhealthy, never a licence to skip readiness
$r = Get-EngineClassification -Probe1 $false -Probe2 $false -BoundProcesses 2 -LogAgeS 20 -MarkerAt $now.AddSeconds(-240) -Now $now
Check 'persistent stall stays live-unhealthy (readiness unavailable -> refuse ordinary recovery)' ($r.class -eq 'live-unhealthy' -and $r.persisted)

# 6. live process with an OLD log is absent (not alive); readiness unavailable does not authorise anything here either
$r = Get-EngineClassification -Probe1 $false -Probe2 $false -BoundProcesses 2 -LogAgeS 900 -MarkerAt $null -Now $now
Check 'process with a stale log classifies as absent' ($r.class -eq 'absent')

# 7. an unrelated zargar.main process (not bound to this runtime) cannot satisfy liveness: BoundProcesses is 0
$r = Get-EngineClassification -Probe1 $false -Probe2 $false -BoundProcesses 0 -LogAgeS 5 -MarkerAt $null -Now $now
Check 'unbound process count 0 -> absent even with a fresh log' ($r.class -eq 'absent')

# 8. ProbeOnly (ReadOnly) never changes the recovery marker in any branch
$a = Get-EngineClassification -Probe1 $true  -Probe2 $false -BoundProcesses 2 -LogAgeS 5  -MarkerAt $now.AddSeconds(-400) -Now $now -ReadOnly
$b = Get-EngineClassification -Probe1 $false -Probe2 $false -BoundProcesses 2 -LogAgeS 5  -MarkerAt $null -Now $now -ReadOnly
$c = Get-EngineClassification -Probe1 $false -Probe2 $false -BoundProcesses 2 -LogAgeS 5  -MarkerAt $now.AddSeconds(-2000) -Now $now -ReadOnly
$d = Get-EngineClassification -Probe1 $false -Probe2 $false -BoundProcesses 0 -LogAgeS 999999 -MarkerAt $now.AddSeconds(-100) -Now $now -ReadOnly
Check 'read-only classification returns markerAction none everywhere' (($a.markerAction -eq 'none') -and ($b.markerAction -eq 'none') -and ($c.markerAction -eq 'none') -and ($d.markerAction -eq 'none'))

"result: $fails failure(s)"
exit $fails
