# Monday action: turn justified opportunities into executable trades

September 19, 2026. User instruction: document the lack of trading impact honestly,
keep working, and prioritize actionable profitability improvements for Monday.

## Accountability correction

PR231 completed an offline historical study. It did not change automatic trading
behavior, create additional executable opportunities, or establish a profit edge.
Calling the implementation goal complete overstated progress toward the user's
business objective. Software/research delivery is complete for that packet;
**the profitability problem is not solved**. Future sessions are not required
before investigating and implementing a justified change. Do not use a new
research layer as a substitute for tracing and addressing an actual missed trade.

Every next handback must say separately: what trading behavior changed, which
observed failure it addresses, how it was verified, what is deployed/enabled, and
whether any after-cost result is actual, modeled, or unknown. No guarantee of
Monday profit and no target trade count.

## Concrete evidence, checked September 19

Monday preparation `5ba695862bbb425d98090a3da877debe` preserved BBY, CNH and NOW.
Saved policy: $500 budget, maximum option ask $5, risk 10%, focus capacity five.
The following otherwise-eligible option asks fail premium affordability:

| Candidate | Plan | Lowest eligible ask except premium | Share trigger | Whole shares within $500 at trigger, before fees |
|---|---|---:|---:|---:|
| NTNX | 1744928cfdc86044fa82f031ef00d748 | $11.00 / $1,100 contract | $70.48 | 7 ($493.36) |
| NVT | ab30bb8aba324bd1aeac39f23acb9647 | $9.90 / $990 contract | $163.75 | 3 ($491.25) |
| ULTA | d1f1440782913758fec1a7800de150e3 | $10.50 / $1,050 contract | $547.58 | 0 |

These are saved preparation observations, not fresh execution quotes. Entry
quantity must be recalculated using the current ask, fees, cash and risk checks.
Do not fill at the trigger merely because it appears in this table.

Historical OKTA, September 14: preparation `98bd007f09694c778c1fe53e84b9fb5a`
created plan `6c7410ced2523428506de9a0d6279c22`, awaiting_contract. The audit
identified `OKTA261016C00180000` at $6.35 rejected solely for premium.
The saved stock trigger was $179.44. The historical share model produced an
open positive mark, not a proved profitable option trade or a closed winner.
This establishes an affordability mismatch worth fixing; it does not prove an edge.

VG September 9 was armed (`85617c164471325bbcddcf15820c3398`) with an affordable
contract; its extra 5m retrospective confirmation is a different issue. BOX
September 15 was under a mixed-market read. Neither is evidence that lifting
premium affordability alone would have admitted those trades.

## Priority implementation: affordability-only shares fallback

**Proposal, not implemented or enabled by this document.** Keep options preferred;
allow explicitly configured Practice-only long-share fallback when a complete
chain audit contains at least one otherwise-eligible contract rejected solely
for premium and no affordable eligible contract exists. Provider errors, missing
chain data, bad spread, bad Greeks or unknown identity alone must never trigger
fallback. Preserve the option audit and record why the share expression was chosen.

This is a concrete production integration gap: `runtime.py` and `execution.py`
already support long shares, but `preparation.py::prepared_execution` hard-codes
instrument=options. Implement the same decision in initial preparation and
`activate_pending`, rather than a one-off manual arm that the scheduler will undo.

Keep the current $500 maximum purchase budget, existing risk limits, five-slot
capacity, cash requirement, market alignment, closed-bar confirmation, baseline
and provenance gates, stop/exit management and fresh native stock quote checks.
No short-share fallback. No Live behavior change. Existing options arms remain
unchanged. One symbol cannot receive both an option and share entry for the same
plan. Restart/retry must retain the selected expression and prevent duplicate arms.

Fresh stock size is in shares, not option contracts or obsolete SIP lots. Set a
separate share-unit bound rather than reusing max_contracts=10 as a stock policy.
Use whole shares, include fees, and reject zero affordable units. Reuse the
existing campaign/partial-exit allocator with quantities appropriate to shares.
Protective exits remain active if fallback is disabled.

### Acceptance before Monday activation

1. Complete premium-only planning refusal can choose shares; an eligible option
   still wins. Incomplete chain/provider failure/spread-only refusal cannot.
2. Long Practice only; Live and bearish paths unchanged. Risk/account gates remain.
3. NTNX/NVT-sized examples fit $500 at a fresh quote; ULTA-sized example refuses
   one whole share. Price changes and fees resize down or refuse, never overspend.
4. Initial preparation, pending activation, retry and restart cannot duplicate
   or replace an existing arm/position. Five-slot capacity remains atomic.
5. Stock quotes require native provenance, fresh timestamps and proper share-size
   units. A stock touch alone never places an order.
6. Integer exits, protective stops and restoration work on the share instrument.
7. UI clearly shows shares versus options, quantity/budget and fallback reason.
8. Deployment/activation verdict explicitly states this changes execution access,
   not proven profitability. Verify Monday state after any safe guarded release.

## Other decisions

- Do not blanket-raise the premium cap to $1,000 to manufacture activity. NVT would
  nearly consume the approved 10% full-debit risk allowance; ULTA/NTNX still may
  fail it. A higher budget also increases size on other entries.
- Do not switch the whole strategy to 5m or nearest-level ranking from the small
  retrospective sample. Keep any targeted timing comparison separately versioned.
- Do not weaken missing-data, spread or risk checks to get a trade.
- First measure this specific expression-access change: valid confirmations,
  entered shares, actual fees/exits and net dollar P&L. Report failed attempts with
  their independent blockers; a no-trade day can remain correct.
