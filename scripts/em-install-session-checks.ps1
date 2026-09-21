# Install the EM session checks as RECURRING weekday scheduled tasks (2026-09-21).
#
# Why this exists: the 2026-09-19 checks were registered by hand for a single date. They ran correctly on
# 2026-09-21 and then stopped existing - the next session had no coverage at all, which is exactly the failure
# mode the checks were meant to prevent. These triggers are weekly Mon-Fri, so coverage does not depend on any
# person or chat session being alive on a given morning.
#
# Times are LOCAL (this host runs on Pacific time; the market is Eastern):
#   06:05 PT / 09:05 ET  clock        raw time validity BEFORE the open, while there is time to fix it
#   06:07 PT / 09:07 ET  preopen      both books, limits, routing (also re-checks the clock)
#   06:32 PT / 09:32 ET  postreplan   after the 09:25 ET re-plan and the open
#   07:22, 09:41, 11:52 PT           intraday operational exceptions
#   13:37 PT / 16:37 ET  close        the two-book comparison plus the exception log
#
# It changes no trading setting. Run it from an ordinary shell; -WhatIf shows what it would do.
[CmdletBinding(SupportsShouldProcess = $true)]
param(
  [string]$Repo = 'C:\Cursor\zargar\.claude\worktrees\technique-review-trade-plan-fbb9ba',
  [string]$InstallDir = 'C:\ProgramData\Zargar'
)
$ErrorActionPreference = 'Stop'
$src = Join-Path $Repo 'scripts\em-session-checks.ps1'
$dst = Join-Path $InstallDir 'em-session-checks.ps1'
if (-not (Test-Path $src)) { throw "missing $src" }
if (-not (Test-Path $InstallDir)) { New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null }
if ($PSCmdlet.ShouldProcess($dst, 'install versioned check script')) {
  Copy-Item $src $dst -Force
  Write-Output "installed $dst (from the repository, so it can be reviewed and restored)"
}

$ps = 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
$plan = @(
  @{ Name = 'ZargarEmChecksClock';      Phase = 'clock';      At = '06:05' },
  @{ Name = 'ZargarEmChecksPreopen';    Phase = 'preopen';    At = '06:07' },
  @{ Name = 'ZargarEmChecksPostReplan'; Phase = 'postreplan'; At = '06:32' },
  @{ Name = 'ZargarEmChecksExc1';       Phase = 'exceptions'; At = '07:22' },
  @{ Name = 'ZargarEmChecksExc2';       Phase = 'exceptions'; At = '09:41' },
  @{ Name = 'ZargarEmChecksExc3';       Phase = 'exceptions'; At = '11:52' },
  @{ Name = 'ZargarEmChecksClose';      Phase = 'close';      At = '13:37' }
)
foreach ($t in $plan) {
  # No -Date argument: the script defaults to TODAY. That is what makes the task reusable tomorrow.
  $action = New-ScheduledTaskAction -Execute $ps `
    -Argument ('-NoProfile -ExecutionPolicy Bypass -File "{0}" -Phase {1}' -f $dst, $t.Phase)
  $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday -At $t.At
  $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 20)
  if ($PSCmdlet.ShouldProcess($t.Name, "register weekday $($t.Phase) at $($t.At)")) {
    Register-ScheduledTask -TaskName $t.Name -Action $action -Trigger $trigger -Settings $settings `
      -Description "EM read-only $($t.Phase) check (em-experiment-v1). Changes nothing; writes research files and EM-ATTENTION.md." `
      -Force | Out-Null
    Write-Output ("registered {0,-26} {1,-11} weekdays {2}" -f $t.Name, $t.Phase, $t.At)
  }
}
Write-Output ''
Write-Output 'Verify with: Get-ScheduledTask ZargarEmChecks* | Get-ScheduledTaskInfo | Format-Table TaskName,LastRunTime,LastTaskResult,NextRunTime'
