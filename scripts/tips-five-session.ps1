# Tips five-session observation checkpoint (rev 2, 2026-09-21 review S21-02).
# The decision and the publication live in `zargar.tools.tip_checkpoint_status` (testable): observed sessions are
# COMPLETED accounting days with observe decisions, ONE cutoff drives the count and every report, each report's exit
# code is checked, and STATUS.json is written atomically with READY / NOT-YET / INCOMPLETE / FAILED / INVALID.
# This wrapper only launches it and surfaces ITS exit code. Registered as the Windows task "ZargarTipsFiveSession".
param(
    [string]$Since = "2026-09-21",
    [string]$OutDir = "C:\ProgramData\Zargar\tips-five-session",
    [string]$Backend = "C:\Cursor\zargar\backend",
    [int]$Need = 5
)
$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"
$py = Join-Path $Backend ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { Write-Error "runtime venv not found at $py"; exit 3 }
New-Item -ItemType Directory -Force $OutDir | Out-Null
Push-Location $Backend
try {
    & $py -m zargar.tools.tip_checkpoint_status --since $Since --need $Need --out $OutDir --python $py
    $code = $LASTEXITCODE
} finally { Pop-Location }
if ($code -ne 0) {
    Write-Error "tips five-session checkpoint reported state FAILED/INVALID (exit $code); see $OutDir\STATUS.json"
}
exit $code
