# September 18: selection, opportunity and actual economics

## Verdict

No active selection or risk rule is promoted. A nearer level increased observed
touches in this small retrospective comparison, but no additional executable,
after-cost option profit is established. September 16-18 have pre-open research
populations. Earlier sessions have incomplete candidate denominators and minute
tapes. Missing evidence is not a zero-touch result, a win, or a loss.

## Actual account results

Book `0b48ed48de2f4030b49942b52858356d`, Options Cartel Practice. Across nine
exchange sessions September 8-18, one completed APA campaign on September 14:
gross -$59.05, recorded fees $2.08, net -$61.13. No open instruments at September
18 close. The two APA fills lack newer fill-evidence receipts; accounting is
recorded but execution realism is unverified. QS generated a journaled signal
September 16 and failed final spread admission. Final arm state alone loses that
history; journaled signals remain authoritative. September 18: no orders or fills.

## Frozen selection comparison

Each list contains five names from the same pre-open cohort. Primary was SHORT
on September 16 and 17, LONG on September 18. The September 18 bearish pool is
information-only and remains separate. Rankings were defined after the sample;
these are exploratory results, not held-out validation. Counts below are observed
price touches, not completed confirmations, fills, or profits. Incomplete tapes
make untouched cases inconclusive.

| Session | Cohort | Candidate count | Quality list touches | Nearest list touches | Liquidity list touches |
|---|---|---:|---:|---:|---:|
| Sep 16 | Primary short | 29 | 2/5 | 3/5 | 2/5 |
| Sep 17 | Primary short | 13 | 2/5 | 2/5 | 1/5 |
| Sep 18 | Primary long | 13 | 0/5 | 1/5 | 0/5 |
| Sep 18 | Bearish research only | 20 | 2/5 | 3/5 | 2/5 |

Quality is the ordering before execution admission, not the final armed list.
Every symbol, distance, selected list and source context ID is in `evidence.json`.

## September 18 candidates

Distance is directional trigger distance from the last completed daily close,
known before the session. Dispositions are dated pre-open preparation attempts.

| Symbol | Distance | Armed | Pre-open disposition | Level observed |
|---|---:|---|---|---|
| CRCT | 0.35% | no | Baseline coverage blocked | no |
| KODK | 0.41% | no | Baseline coverage blocked | yes |
| STLD | 0.71% | no | Baseline coverage blocked | no |
| NTNX | 0.73% | yes | Armed | no |
| BOX | 1.24% | no | Awaiting contract | no |
| BBY | 1.36% | yes | Armed | no |
| ASC | 1.95% | no | Baseline coverage blocked | no |
| IDYA | 2.23% | no | Baseline coverage blocked | no |
| CLF | 2.74% | yes | Armed | no |
| DE | 2.95% | no | Awaiting contract | no |
| DAR | 3.25% | yes | Armed | no |
| ALT | 3.40% | no | Awaiting contract | no |
| CNH | 6.72% | yes | Armed | no |

KODK touched its level, but its research record has only one usable pre-close
volume-confirmation window and fails the unchanged opening-and-broad gate.
Therefore this is not a demonstrated nearer executable winner displaced by the
five arms. CRCT and STLD were also closer but failed coverage admission. None of
the actual five reached its buy level in retained exchange prices.

## Causal limits and prospective collection

- Recovered provider prices are separate from retained arm/research observations.
  Neither alone establishes that a fresh quote and valid confirmation coexisted.
- No `profit_quote` runs exist in the inspected database. Alternative option net
  outcomes remain null: no stock-return substitution, invented delta or fees.
- Older arms do not supply the full universe. September 8-11 have missing retained
  minute tapes; their trigger frequency cannot be established from those tapes.
- Frozen daily geometry/ranking fields define selection. Mutable context baseline
  fields are not retrospectively treated as pre-open knowledge; append-only
  preparation attempts provide dated readiness evidence.
- New pre-open research contexts save nearest-unbroken and liquidity-first lists
  alongside quality and leader-first. Their candidates participate only in the
  bounded research sample. Existing contexts are not rewritten.
- Validation > Profitability research > Compare research shortlists displays
  new lists when a new context contains them. Unknown distance/liquidity is not
  invented to fill a list. Actual automatic selection is unchanged.
- Before promoting any ranking: compare the same eligible population over future
  sessions, preserve confirmations/quotes/exits/fees, and establish quote coverage
  before claiming option returns. This sample supplies no profitability approval.

## Reliability fixes

Enabled verified-interval Practice repair retries at most once/minute, five
plans/pass, eight intervals/plan, retaining the existing timeout. Newly recovered
native bars do not consume verification probes. Positive complete SIP evidence
and the two-minute post-close evidence maturity remain unchanged.

Repair/correction excludes every already-closed confirmation bucket, but permits
the current bucket's future close to be assessed. Existing arm/restart/pause
cutoffs never move backward. A new closed candle and all current admission gates
remain required. Live/default repair behavior stays strict. No backdated order.

Daily review separates trigger/high/low, unresolved coverage, and historical data
refusals. Complete no-touch coverage is no-trigger even after a prior refusal;
partial no-touch evidence is explicitly inconclusive. Armed no longer presents a
cleared historical data refusal as a current hold.

The proof maturity still means a suppressed latest minute may not be verifiable
within the entry-age limit. Such a candle can remain untradeable. This release
does not authorize late entry to hide that limitation.

## Reproduction and checks

Set `CARTEL_AUDIT_DATABASE_URL` locally, then from backend:

```text
python -m zargar.tools.cartel_opportunity_audit --start 2026-09-08 --end 2026-09-18 --portfolio 0b48ed48de2f4030b49942b52858356d --output evidence.json
```

The tool uses one read-only repeatable-read transaction, with no provider calls or
runtime mutations. `accounting.json` contains authenticated daily-review results
for all nine sessions. `manifest.json` hashes both evidence files.

Focused runs passed: 40 interval/recovery/observer/opportunity tests; 30 report/
runtime tests; 43 research/workspace tests; 14 report tests after query refinement;
one retry-pacing regression. Sets overlap and are not a summed unique count.
Production frontend build, release consistency, Ruff F and diff checks pass.
