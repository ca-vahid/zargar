# Verified provider intervals — Practice data repair

September 18, 2026. The morning DAR, BBY and NTNX refusals included 13 sampled
minutes. Direct SIP queries found trades in every queried interval, no emitted
one-minute bar, zero price-eligible trades and no unknown conditions. Repeating
bar downloads cannot produce a bar that the provider intentionally suppresses.

## Data contract

`techniques.options_cartel.verified_intervals` defaults **off**. When explicitly
enabled it applies only to simulated Practice accounts, never Live or broker-paper
accounts. Existing plan prices, baselines, volume ratios, quote/contract requirements,
account risk limits and protective exits remain unchanged.

The background repair worker can certify an interval only when both SIP responses
are complete, the bar endpoint has no bar for exactly that minute, and the trade
endpoint contains positive observed trades but **none** can set open/close or high/low
under the frozen `alpaca-minute-eligibility-v1` matrix. Empty responses, unknown
conditions, partial pagination, HTTP failures and price-eligible trades remain
unverified. Timestamps use half-open boundaries; the interval must have closed at
least two minutes before verification. Evidence records observation time, condition
groups/counts/shares, protocol/rules versions, response hashes and an integrity hash.

[Alpaca's aggregation specification](https://docs.alpaca.markets/us/docs/market-data-faq#how-are-bars-aggregated)
distinguishes price eligibility from volume eligibility. An odd-lot-only minute can
contain volume yet emit no OHLCV bar. Multi-minute provider candles aggregate the
**emitted** minute bars. Accordingly:

- No one-minute candle, OHLC value, carry-forward price, or zero-volume candle is invented.
- Sampled prices for a certified interval are excluded from entry calculations.
- Bucket OHLC and volume come from actual emitted price bars. Suppressed eligible
  shares remain audit evidence, not an addition to provider-bar volume.
- A wholly suppressed confirmation bucket has no candle and cannot trigger.
- Session extremes use actual price bars only; any other missing/untrusted interval
  still blocks the stop calculation. Existing frozen baseline values are not rewritten.
- A later genuine price bar takes precedence over older non-emission evidence.

## Causality and recovery

Repair is bounded to five plans per pass and eight intervals per plan, with a
20-second verification budget per plan. Least-attempted intervals go first so
uncertifiable early minutes cannot starve later ones. Ordinary successful bar
recovery persists even when optional verification fails.

As of v0.8.20, enabled Practice repairs retry at most once per minute; other
paths retain the five-minute interval. Freshly recovered native bars are removed
from the verification probe set. This does not reduce the evidence maturity or
relax the complete-response requirements.

Evidence is installed only while the plan remains armed/waiting. Installing new
evidence advances `observeAfter`; repaired history does not cause a retrospective
entry. Enabled Practice advances to the current bucket start, excluding every
already-closed bucket while allowing the current bucket's future close to be
evaluated. Existing arming, restart and pause cutoffs never move backward. Other
accounts retain the original repair-time boundary. Submission rechecks evidence and current feature/account scope. Disabling
the setting restores strict minute-presence behavior for new entries; it does not
stop protective position management.

Decision-context schema v2 stores the exact proof map used alongside immutable
session inputs. Historical/research replay without those proofs remains strict;
it cannot infer a missed trade or reproduce the repaired live decision merely from
today's revised bar table. The generic offline provider-volume experiment remains
separate and inactive.

The Armed page shows how many intervals have verified provider non-emission.
Remaining sampled data, missing history, ordinary no-trigger states and legitimate
invalidations must not be presented as repaired simply because this switch is on.
