# Method lab — prospective Practice comparisons

The method lab records experiments, not orders. Its confirmations, modeled fills
and trial totals are separate from the actual Practice book's daily P&L. It does
not add a new live execution mode, change existing arms or activate a winning
experiment automatically.

## Use

1. In Practice, open Options Cartel > Settings > Method lab. Enable collection.
   This setting is independent of the older profitability-research switch.
2. Run fresh preparation before the session opens, or use the scheduled run.
   Enabling collection after the open cannot manufacture a pre-open cohort.
3. Under Validation > Method lab, select the entry session. Inspect candidates,
   baseline readiness, model observations and quote-attempt reasons.
4. Use **Review trial economics** for the paired trial, selection comparisons,
   modeled fill times/quantities/fees and missing evidence. The account's real
   orders, fills and P&L remain in Daily review.

Collection defaults off until the reviewed release is enabled for Practice. Live
and broker-paper accounts cannot participate. Turning collection off cancels its
owned tasks, preserves existing records and does not stop protective management.

## Fixed research definitions

Every context is frozen before the open from saved analyses. The lab keeps the
full eligible long pool and any capacity omissions. Quality, leadership proxy,
compression, proximity and liquidity rankings are recorded before outcomes.
Industry relative strength is a proxy, not a verified narrative or catalyst.
Unknown fundamentals remain unknown.

The primary paired trial is breakout-5m versus undercut/reclaim-5m. Breakout-15m
and 30-minute-pivot/5m confirmation are diagnostics, not additional primary
challengers from which the best winner is chosen after the fact. Each timeframe
uses its own historical volume baseline. Missing baseline slots cannot confirm.

Reclaim and pivot definitions are experimental closed-bar interpretations of
mirrored author statements. See METHOD-LAB-SOURCE-MATRIX.md for confidence,
source differences and numerical engineering assumptions. A pivot's own candle
cannot prove a subsequent breakout. Restarts do not recreate missed signals.

## Receipt-timed economics

Signals retain their original decision inputs. Quote attempts have durable start,
result and terminal records; at most two provider requests run per pass, at most
three attempts per signal, inside the 120-second observation deadline. Failures
and exhausted capacity remain visible rather than becoming zero-return trades.

Option admission uses the existing reviewed limits and fresh OPRA/IBKR quote
evidence, plus an attributed current underlying SIP price. The current-price
check uses a recent qualified trade, or a fresh SIP ask when the trade is stale;
the basis is recorded. A configured provider or transformed cache price is not
proof. Shares additionally need a fresh two-sided SIP book and affordable whole
units. No funds are reserved.

The primary economic model is `receipt_minute_close_v1`:

- It buys at the recorded ask and sells at fresh recorded bids, up to displayed
  size. It does not invent fills at historical candle times.
- Underlying exit decisions occur when completed minute prices become available
  to the collector. Daily EMA exits require complete completed-session inputs.
- Partial fills advance the existing whole-unit exit campaign. Breakeven moves
  only after the allocated trim quantity has filled. A repeated observation of
  the same quote does not replenish consumed displayed size.
- Option fees are per contract. Share per-order fees are not charged again for
  another partial fill of the same modeled exit intent. Spread cost is measured
  against recorded midpoints and already included in ask/bid P&L.
- A missing price interval, missing fee, stale quote, unsupported size or absent
  liquidation mark prevents a complete economic result. Open marks may be
  unavailable after hours; that is not zero P&L.
- Observations for previously selected, unexpired instruments continue across
  sessions even if they leave the next day's candidate list. Work remains bounded.

These remain **models**, not actual executions. They do not reproduce every
intraminute move, queue priority, extra market impact, premium-triggered stops or
expiry settlement. The receipt-time assumption is frozen in the trial contract.
No result is evidence that a live broker would fill identically.

## Share-size units

Alpaca's dated October 30, 2025 changelog states that CTA/UTP quote sizes became
shares on November 3, 2025:
https://docs.alpaca.markets/us/v1.1/changelog/marketdata-bid-and-ask-size-display-change

The equity SIP adapter uses the quote's venue timestamp to select this schema;
modern sizes are not multiplied by 100. Earlier SIP and the existing IEX path
retain the legacy conversion. Missing venue time yields unknown size, not a
receipt-time guess. The lab consumes normalized share counts without another
multiplier. OPRA option contract sizes are a separate path and are unchanged.

The prior adapter's unconditional x100 could overstate share liquidity. This
does not establish that a particular old fill was wrong. Old fills and P&L are
not rewritten; their execution-evidence limits remain visible.

## Trial review and operating cycle

The protocol records starting capital, cash/risk bounds, source policy hash,
entry/exit model versions, fees, one challenger and sample requirements before
the first session. The selected context is the latest fully frozen pre-open
context for each session; it is never selected by profitability.

The first review requires at least 20 observed sessions, 30 complete closed
outcomes per variant and more than one market regime. Incomplete/unmatched
pairs remain in the denominator. A no-entry outcome is zero only when the full
required observation windows support that conclusion.

Review includes after-cost net dollars, a paired-session bootstrap, extra cost
stress, conservative overlapping exposure/drawdown bounds and concentration.
These are review criteria, not a guarantee or automatic trading permission.
Actual profitability is unproven until prospective observations exist; a green
unit test or a deployment cannot supply those observations.

The app schedules `options_cartel_method_lab_review` at 16:10 ET on trading
days. Friday records also carry the weekly-checkpoint marker. Each daily review
is immutable and idempotent. It does not alter policy or submit orders.

## Rollback

Disable `techniques.options_cartel.method_lab` to stop further collection while
preserving records. Existing trading policies and protective exits are separate.
Deploy/restart only through the shared guarded deployment path, preserving other
teams' work and verifying restored inventory. Never revert the SIP size fix to
hide differences from older inflated liquidity observations.
