# Method lab: source-to-code contract

Research date September 18, 2026. User approved implementation of phases 0-6.
The new lab is non-ordering Practice research. Economic validation and activation
are distinct from implementing this contract. No verified profitability claimed.

## Evidence classifications

- **A — author archive:** retrieved complete author thread, with a stable post ID
  and the date recorded in the existing source ledger. This is evidence of what
  was said, not evidence of returns or a universal rule across versions.
- **B — mirrored statement:** matching author-attributed text appears in multiple
  indexed mirrors, but original date/context could not be independently recovered.
  It can motivate a labeled experiment, not an asserted exact author replica.
- **E — engineering:** an explicit deterministic definition selected for testing.
- **S — safeguard:** platform/account/data constraint independent of the method.

| Requirement | Evidence and uncertainty | Existing implementation | Lab decision and acceptance |
|---|---|---|---|
| Leaders within strong groups | A, S02 June 27 2026; exact thematic universe unresolved | `quality.py` structural R/relative strength/volume; `leader_context.py` advisory proxies | Preserve baseline and label industry proxies. Add compression/leadership features without calling a proxy a verified catalyst. Same pre-open denominator for comparisons. |
| Tight base and contracting volume | A, S02; B rating post suggests ADR-relative tightness and maturity | `setups.py` fixed range, dry-up and history windows | Volatility-adjusted range, maturity and EMA slope become dated advisory features; no retrospective star filter. |
| Breakout confirmation | A, S02 supports 5m/15m; text also says entry on break | `entry.py`, default 15m closed bar | Fixed 5m and 15m controls require their own same-time volume baselines. Closed-bar rule S remains; no intrabar shortcut. |
| Undercut and reclaim | B, matching indexed text in NativeMango, Robaperes and on_theway_ mirrors; original date unavailable | No dedicated entry mode | `shadow_entries.py`: long-only support break then reclaim. Support frozen pre-open. Numeric depth/horizon/volume/close thresholds E, not attributed to Sean. |
| 30-minute pivot | B, same mirrors; first green 30m candle at support then break of its high | MA pullback currently uses a daily candle high/low | Dedicated shadow sequence. Pivot must finish before a later 5m/15m confirmation can break its high. A generic 30m breakout is not this model. |
| Initial stop | A S02 day-low; older S03 breakout-candle low; B entry models also say day-low | Session extreme, breakout bar and preplanned alternatives | First new experiments use low-so-far from complete known session inputs. Final daily low is prohibited. Other stop variants need separate IDs. |
| Volume multiple and close quality | No verified universal 1.5x/70% author requirement | `EntryPolicy` engineering defaults | Keep these explicit for controlled comparison; vary separately, never simultaneously with model and ranking. |
| Theme-specific risk-on/off | A context; B suggests reclaim in weaker conditions and breakout/pivot with momentum | Strict/Moderate index gate plus research market observations | Capture market eligibility separately at signal. A shadow signal cannot authorize a trade or bypass a market gate. |
| Shares versus options | A S10 Sep 27 2025 describes shifting toward shares as momentum fades | Auto preparation options; existing conditional shares research | Compare option, unlevered shares and pass with explicit caps and cost evidence. Historical source variant, not universal latest policy. |
| Partial exits and runners | A S01/S02 have different allocations | Versioned exit campaigns and integer allocation experiments | Reuse saved exit campaign, keep quantities/fees explicit, never use highest trim as weighted P&L. |
| Fundamental growth | B mention of four quarters; sequential vs YoY unresolved | No verified growth factor in selection | Missing/unresolved advisory evidence only. Do not add a mandatory growth exclusion. |
| Provider interval evidence | S, verified native bars or complete non-emission certificates | `nonemission.py`, immutable decision evidence | Respect certificate availability; sampled prices cannot create a setup, stop or fill. |
| Trial promotion | E/S statistical and operating protocol | No automatic research promotion | Immutable one-challenger protocol; common cohorts, cost/coverage gates, no automatic execution even when review-ready. |

## Source links

- S02: https://threadreaderapp.com/thread/2070969718882623784.html
- S01: https://threadreaderapp.com/thread/2096632160639734027.html
- S03: https://threadreaderapp.com/scrolly/1788735674104889552
- S10: https://threadreaderapp.com/thread/1971976644362674547.html
- Entry-model mirrors inspected via indexed author-attributed text:
  https://w.twstalker.com/NativeMango,
  https://site.twstalker.com/Robaperes,
  https://www.twstalker.com/on_theway_
- Rating mirror: https://mobile.twstalker.com/coinking211

Mirrors were retrieved/searched September 18 PT. Relative ages differ between
mirrors and cannot establish a publication date. Do not convert them into precise
dates. Matching copies strengthen the wording attribution but do not prove the
original post's surrounding context. No profit figure from those pages is an
acceptance criterion.

## Initial shadow definitions (E)

- Long side only. No unsourced bearish mirror of reclaim/pivot.
- Pre-open support, targets, daily inputs, parameters and volume baselines.
- Reclaim support starts with a versioned prior-day-low candidate; pivot support
  with a versioned EMA8 candidate. Alternative levels are separate specifications,
  not selected after seeing the intraday path.
- Numerical defaults: 1.5x corresponding-timeframe baseline; close in upper 70%
  of the range; minimum target room 0.25R; pivot zone 0.25%; maximum undercut 3%;
  reclaim within 60 minutes; chase limit 0.5 trigger-to-known-stop R. These are
  research assumptions, not author rules. The pivot candle low must be within
  the support zone, not merely a wide candle spanning it.
- Reclaim may occur in one complete candle whose low is below support and close
  above it, because the close follows the low. A pivot candle cannot confirm its
  own later high break. A failed pivot retires that specification for the session.
- Missing/untrusted input resets sequence state and unresolved session coverage
  prevents a session-low stop. An all-non-emitted bucket has no price candle.
- At most one research signal per specification/session. No automatic re-entry.
- No signals at/after the closing bell; no previously completed bucket is revived
  after restart. The collector must preserve and check the observation deadline.

## Implementation and open work

Pure evaluator: `shadow_entries.ShadowEntrySpec` and `read_shadow_entry`.
Regressions: `test_cartel_shadow_entries.py` covers pre-open freezing, complete
sequence, future exclusion, pivot timing, failures, coverage, duplicate evidence,
restart boundary and closing bell. These tests prove mechanics, not source-example
calibration or profitable fills.

Pre-session candidate freezing, distinct 5m/15m baselines, an append-only trial
contract and bounded shadow collection now have implementation and focused tests.
The original trading-plan schema does not accept these new model types. The
method lab remains disabled by default while integration is being completed.

Receipt-timed quote/cost reconciliation and paired trial reporting are now
implemented, including separate shares/options/pass results. Their fixed
`receipt_minute_close_v1` exit cadence is a modeling assumption, not tick-for-tick
execution replication. Alpaca's dated share-size schema change is independently
documented in METHOD-LAB.md and PLATFORM-RULES.md.

Still required before full economic acceptance: source-example calibration where
original dated evidence is obtainable, verified release/rollout and prospective
economic evidence. A read-only smoke over the September 18 preparation's 13 saved
non-filtered analyses produced 13 long candidates and 13 definitions of each new
entry model; this tests mechanics, not historical profitability or complete-universe coverage.
Unverified original post context stays
an explicit open source task; it does not gain verified status through a green test.
