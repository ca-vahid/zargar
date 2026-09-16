# Cartel profitability research

Decision recorded September 15, 2026. This implements the prospective studies from
the [September 15 review](PROFITABILITY-REVIEW-2026-09-15.md). It is a Practice
research program, not a change to the executable Cartel method.

## Using it

Open **Options Cartel → Settings** and leave profitability research enabled. Run
a fresh **Prepare now** before the next session, or let scheduled preparation run.
Keep the app running through that session. **Validation → Profitability research**
shows the selected session's observation pool, ranking comparisons and experimental
results. The ordinary **Daily review** remains the report of actual orders, costs
and account P&L.

Fresh preparation freezes the candidate inputs and research policy. Turning the
study on after the market has opened does not manufacture earlier observations.
Historical scans that predate this feature do not acquire a prospective research
record retroactively. Missing observations remain missing.

The collection setting is `techniques.options_cartel.profitability_research`.
Its candidate cap defaults to 50; the bearish research switch defaults on.
These settings do not alter the preparation shortlist size, the 10% risk ceiling,
the premium budget, Live permissions, or existing campaigns. Research records
cannot be armed. There is no automatic promotion of a winning experiment.

## Questions and fixed comparisons

| Question | Comparison | Interpretation boundary |
|---|---|---|
| Are we watching the best opportunities? | Current structural-target-R ranking against a theme/leader-first research ranking, using the same frozen candidate pool | Industry is a theme proxy, not a verified catalyst. Keep the full denominator, including non-entries and losers. |
| Does target one describe the funded campaign? | Saved nearest target against the first static target with a nonzero whole-unit allocation | Preserve every resistance level. A moving-average exit has no known static target price. Unknown quantity or target importance remains unknown. |
| Is there a downside opportunity when long entries are blocked? | Separate pre-session bearish cohort, followed only after sustained bearish index evidence | This does not flip a long plan into a put or authorize automatic short trading. |
| Can we contain failed breaks? | Saved campaign versus a completed-candle failed-break exit and a separate 60-minute exit | Use identical entries and initial risk; report winners cut early as well as losses reduced. |
| Should weak conditions prompt an earlier trim? | Separate weak-environment half trim at a completed-bar gain of 0.5 initial R | Whole units only; one unit cannot be halved. Weak context must be known by entry. |
| Is skipping an unaffordable option best? | Conditional ordinary unlevered shares study at the same cash cap | Only when affordability alone blocks an otherwise eligible option setup. Different leverage and stop risk must remain visible. |

The exit challengers are fixed engineering hypotheses: `failed_break_v1`,
`time_60m_v1`, and `weak_strength_v1`. The failed-break variant closes remaining
units when a complete post-entry candle closes back through the original trigger,
before the first target trim has filled. The time variant closes remaining units
after 60 completed regular-session minutes. The weak-strength variant trims
`floor(original quantity / 2)` once after a completed candle reaches +0.5 initial
R; it does not silently move the stop to breakeven. Protective baseline exits
retain priority. Versions must change when these definitions change.

## Direction and source fidelity

The long study preserves the selected Strict/Moderate research alignment rule.
The initial bearish cohort is explicitly a versioned **structural-short proxy**:
it re-evaluates frozen daily inputs in the short direction under the saved
structural rules. It does not claim the author's full March scanner, whose
relative-volume, negative-change and exact listing thresholds differ. This
difference travels with the cohort and must be preserved in comparisons.
The bearish branch requires both indices below their frozen prior-session daily
8/21/50 EMA references, with consecutive completed index observations. Entries
must be subsequent fresh confirmations; an earlier crossing is not recovered as
a hypothetical fill after permission evidence arrives.

Sean's [market-to-leader framework](https://x.com/SRxTrades/status/2099241717983486243),
[bearish framework](https://x.com/SRxTrades/status/1906420174246510756), and
[adaptive-management discussion](https://x.com/SRxTrades/status/2099641849212293453)
motivate these questions. They do not specify our numerical challengers, the
two-observation rule, or an automatic trading override. The source variant and
engineering differences belong in each cohort's protocol.

## How to read results

Stock confirmations, next-open stock paths, and stock R are research observations.
They are not purchased options or option P&L. An open mark is not a realized gain.
Option eligibility needs contemporaneous contract evidence; net option returns
need the selected contract's recorded executable quotes, quantities and costs.
An absent quote or fee is unknown, never a zero-cost profitable fill.

Use source-qualified complete candles, actual entry-time stops, the same entry
cohort, integer quantities, and stated slippage. A missing expected fill minute
must not be bridged to a convenient later price. Keep source and availability
timestamps distinct. Intraday references remain **daily** EMAs, not EMAs computed
on 15-minute candles. Target importance is unknown unless pre-entry evidence
establishes it; do not relabel the nearest resistance as minor after a stock rallies.

The default stock-path slippage assumption is two basis points per fill. A modeled
entry cannot precede the actual signal/contract observation: it uses the next
expected whole minute and refuses a stale signal. Option quantities are estimates
from the observed ask, displayed size, current cash/equity limits and frozen Practice
fee settings. They reserve no money and do not prove that simultaneous positions
would pass the account's aggregate exposure checks. Quote-based option valuation
uses modeled fees separately from the stock proxy. Unknown fees do not become zero.

## Review and promotion

The first checkpoint is 20 observed sessions, not 20 correlated variants of a
single session. Compare candidate coverage, usable entries, refusals, no-fills,
fees, concentration, premature exits and net outcomes against the same capital
limit and the cash baseline. Show separate aligned, mixed and bearish cohorts.
Repeat the comparison without the largest winner and over a later holdout period.

No setting is automatically optimized. A proposed executable change needs its
own review, meaningful sample, net option evidence where options would trade,
and an explicit acceptance decision. September 15's DT/GH rallies are motivation
for the experiment, not an acceptance sample used to choose thresholds.

## Implementation status

This chapter describes the new research release. Deployment and validation
evidence are recorded in its release handoff; merging the chapter alone does not
start collection. Old execution plans keep their original policies.

## Baseline queue fairness — September 16 correction

Due candidates with no prior baseline attempt run first. Remaining due retries run
in ascending persisted attempt count, then oldest retry time. The two-attempt
per-pass budget and five-minute cooldown remain unchanged. Ready candidates are
skipped. This ordering survives restart and does not reorder the frozen candidate
rankings, weaken coverage requirements or create retrospective entries. Existing
saved study contexts benefit without rerunning preparation.
