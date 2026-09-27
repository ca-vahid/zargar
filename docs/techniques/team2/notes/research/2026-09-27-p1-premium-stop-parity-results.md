# P1.1 — premium-stop parity: results (2026-09-27)

Registration: `2026-09-27-p1-premium-stop-parity-registration.md`, committed `715d517b` before any number was
computed. Tool: `profitability-2026-09-19/harness/parity_premium_stop.py`. Input: `train_base_s0.json` (282 training
trades, 2026-05-07..08-14, harness v2, real prints, code `fed75988`). This is simulated execution on real prints, not
fills.

## Answer: **the stop's sampling is not the leak.**

| proxy for the live 2 s mid | trades whose stop fires earlier | mean change per trade | 95% interval (date-clustered, 59 sessions) |
|---|---|---|---|
| **P-close** (minute close ≤ line) | 57 of 263 | **−0.13 points** | −0.39 .. +0.14 |
| **P-low** (minute low ≤ line; pessimistic) | 87 of 263 | **−0.61 points** | −1.68 .. +0.36 |
| *supplementary, 1-tick replay:* P-close / P-low | 52 / 92 | +0.26 / −0.06 | +0.01..+0.53 / −1.06..+0.76 |

Both registered proxies fall well inside the 3-point line, so under the frozen rule the stop's sampling is **not the
leak**. The baseline stays at −3.61% per trade gross (−3.74 / −4.22 with the live stop). Running the stop every 2
seconds instead of on 2-minute closes changes the result by less than one point.

## Checks
- **Excluded and censored trades.** 19 trades with X5 adds were excluded, as registered. None were censored, and none
  were missing prints.
- **Baseline reconstruction.** Rebuilding each baseline trade from its exit legs reproduces the replay's `pnlPct` up to
  its fee convention: net of $1.04 per side, with the entry fee inside the denominator. That scales a paired
  difference by about 2%. The comparison is on gross % per unit of the initial position; fees are identical in both
  arms.
- **The 1-tick run is supplementary, not a registered test.** Its overlay exits carry no extra tick, so that run is
  slightly favourable to the variant.

## What this means
The live desk's larger loss (−7.2% gross per trade over 30 live trades, against the replay's −3.6%) is **not**
explained by how often the premium stop is checked. What remains are the parts already measured or visible in the
fills:
- **Cheaper contracts live:** IWM at $0.25–0.36, where fee plus spread is 8–12% per round trip.
- **Fill slippage:** entries fill at the ask, about 1% over mid, and stop exits 1–2 ticks below mid.
- **The two stale fills:** −$690, fixed in 0.8.49.
- **The period and sample size:** 30 trades across 9 dates is noise.

Consequences:
- The premium-stop rule stays as it is. H6 (width) and now P1.1 (sampling) both say it is not the lever.
- The cost side (P1.2 venue lines, P2.1 dearer contracts) is the remaining concrete lever.
- Prospective counts from `team2_exit_review` continue.
