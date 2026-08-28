# Attach to the running Zargar server's log - anytime, no restart needed.
#
#   scripts\logs.ps1               follow live (Ctrl+C detaches; server unaffected)
#   scripts\logs.ps1 -Tail 200     start with the last 200 lines
#   scripts\logs.ps1 -Errors       only WARNING / ERROR (and their tracebacks)
#   scripts\logs.ps1 -Match INTU   only lines matching a regex
#   scripts\logs.ps1 -NoFollow     print the tail and exit (no streaming)
#
# Colors (the file itself is plain text - color is applied here, by level):
#   red = ERROR/CRITICAL + traceback lines · yellow = WARNING · dark gray =
#   httpx request noise and DEBUG · green = trading events (fired/armed/order/
#   fill/halt) · default = everything else

param(
  [int]$Tail = 40,
  [switch]$Errors,
  [string]$Match,
  [switch]$NoFollow
)
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$log = Join-Path $Root "backend\zargar-8420.log"
if (-not (Test-Path $log)) {
  Write-Host "x $log not found - has the server ever started?" -ForegroundColor Red
  exit 1
}
if (-not $NoFollow) {
  Write-Host "> Following $log - Ctrl+C detaches (the server keeps running)" -ForegroundColor Cyan
}

# Lines are "YYYY-MM-DD HH:MM:SS,mmm LEVEL logger message". Unstamped lines
# (tracebacks, wrapped messages) belong to the previous record and inherit
# its color, so a multi-line ERROR stays red all the way down.
$script:carry = $null
$paint = {
  process {
    $line = $_
    if ($Match -and $line -notmatch $Match) { return }
    if ($line -match '^\d{4}-\d{2}-\d{2} ') {
      if     ($line -match ' ERROR | CRITICAL ') { $script:carry = 'Red' }
      elseif ($line -match ' WARNING ')          { $script:carry = 'Yellow' }
      elseif ($line -match ' DEBUG ')            { $script:carry = 'DarkGray' }
      else                                       { $script:carry = $null }
    }
    $color = $script:carry
    if ($Errors -and $color -notin @('Red', 'Yellow')) { return }
    if (-not $color) {
      if     ($line -match 'httpx')                                  { $color = 'DarkGray' }
      elseif ($line -match 'trigger|fired|armed|disarm|order|fill|halt|kill|proposal|exit') { $color = 'Green' }
    }
    if ($color) { Write-Host $line -ForegroundColor $color } else { Write-Host $line }
  }
}

if ($NoFollow) {
  Get-Content $log -Tail $Tail | & $paint
} else {
  Get-Content $log -Tail $Tail -Wait | & $paint
}
