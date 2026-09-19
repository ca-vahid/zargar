# Tips five-session observation checkpoint (2026-09-19). Read-only: runs the existing report tools against the runtime
# database and writes their raw outputs OUTSIDE the checkout (a dirty runtime checkout blocks deploys).
# Owner + procedure: docs/techniques/tip/research/FIVE-SESSION-CHECKPOINT.md. Registered as the Windows task
# "ZargarTipsFiveSession" (daily 02:00 local from 2026-09-26; idempotent - each run overwrites its outputs).
param(
    [string]$Since = "2026-09-21",
    [string]$OutDir = "C:\ProgramData\Zargar\tips-five-session",
    [string]$Backend = "C:\Cursor\zargar\backend",
    [int]$Need = 5
)
$ErrorActionPreference = "Continue"
$env:PYTHONIOENCODING = "utf-8"
New-Item -ItemType Directory -Force $OutDir | Out-Null
$py = Join-Path $Backend ".venv\Scripts\python.exe"
Push-Location $Backend
try {
    # an OBSERVED session = an accounting day (04:00 ET anchor) on which the relevance filter actually journaled decisions
    $sql = "select count(distinct ((ts at time zone 'America/New_York') - interval '4 hours')::date) from events where type='TipReviewGate' and ts >= '$Since 04:00-04' and extract(isodow from ((ts at time zone 'America/New_York') - interval '4 hours')) < 6"
    $observed = [int]((docker exec zargar-db psql -U zargar -d zargar -Atc $sql) | Select-Object -First 1)
    # the fifth session's mark is its 03:59 ET point the NEXT morning, so only completed accounting days are reported
    $until = (docker exec zargar-db psql -U zargar -d zargar -Atc "select (((now() at time zone 'America/New_York') - interval '4 hours')::date - 1)::text") | Select-Object -First 1
    & $py -m zargar.tools.tip_review_gate_eval --since $Since --prospective *> (Join-Path $OutDir "review-gate-prospective.md")
    & $py -m zargar.tools.tip_scorecard --since $Since --until $until *> (Join-Path $OutDir "scorecard.md")
    & $py -m zargar.tools.tip_outcomes --dispositions --since $Since *> (Join-Path $OutDir "opportunity-dispositions.md")
    & $py -m zargar.tools.tip_review_gate_eval --since $Since --model-plan *> (Join-Path $OutDir "review-model-cases.md")
    $state = if ($observed -ge $Need) { "READY" } else { "NOT-YET" }
    [ordered]@{ state = $state; observedSessions = $observed; need = $Need; since = $Since; until = $until
                generatedAt = (Get-Date).ToUniversalTime().ToString("o")
                next = "Tips desk writes ONE report from these files (FIVE-SESSION-CHECKPOINT.md). No enforcement, no paid run." } |
        ConvertTo-Json | Set-Content -Encoding utf8 (Join-Path $OutDir "STATUS.json")
    Write-Output "tips five-session: $state ($observed of $Need observed sessions, through $until) -> $OutDir"
} finally { Pop-Location }
