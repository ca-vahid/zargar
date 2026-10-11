# Scout replay - S1 screen, 2018-01-01 to 2026-09-10

Run 2026-10-11 00:28 ET, label `v1-no-insider-min`. Screens only, no LLM. Costs charged per trade: 0.63% round trip ($1 per order on $600 + 0.15% assumed half spread per side).

Parameters: `{"window_days": 10, "min_insiders": 2, "min_value_usd": 100000.0, "roles": ["officer", "director"], "min_insider_value_usd": 0, "max_row_value_usd": 0}`; gates: price >= $5, 20-day dollar volume >= $5M, market cap >= $300M. Hold: 20 sessions, stop 2 x ATR(14).

**Not applied / known biases:** the live entry-spread gate, earnings-in-hold, corporate-action and Tips gates (no point-in-time source); entry is the session OPEN, the live rule buys at 10:00 ET; a ticker with no price history today (renamed, delisted) is dropped and counted under `noBars`.

## Funnel

```json
{
 "s1_insider": {
  "clusters": 795,
  "noTicker": 45,
  "noBars": 26,
  "price": 154,
  "adv": 210,
  "marketCap": 10,
  "marketCapUnknown": 78,
  "unpriced": 1,
  "traded": 271
 },
 "s1_unclassified": {
  "clusters": 9743,
  "noTicker": 261,
  "noBars": 230,
  "price": 2160,
  "adv": 2931,
  "marketCap": 129,
  "marketCapUnknown": 637,
  "unpriced": 25,
  "traded": 3370
 }
}
```

## s1_insider

All years: **271 trades, mean net +0.80%** (median +0.14%, 51% winners, t +0.90); gross +1.44%; net minus SPY over the same days -0.44% (t -0.57). Month-clustered: net +0.91% (t +0.99, 87 months), net minus SPY -0.32% (t -0.38). Exits: {'time': 188, 'stop': 70, 'gap': 12, 'data_end': 1}.

| Year | Trades | Mean net | Median net | Winners | Mean net - SPY | t (net - SPY) | Stops+gaps |
|---|---|---|---|---|---|---|---|
| 2018 | 34 | -0.92% | -1.01% | 44% | -0.37% | -0.27 | 26% |
| 2019 | 25 | +2.29% | +3.77% | 64% | -0.33% | -0.23 | 12% |
| 2020 | 43 | -0.49% | -7.34% | 42% | -1.29% | -0.37 | 51% |
| 2021 | 23 | +0.94% | -0.74% | 48% | -0.91% | -0.38 | 26% |
| 2022 | 23 | +1.65% | -0.93% | 48% | +1.70% | +0.93 | 35% |
| 2023 | 45 | +2.42% | +2.09% | 64% | -0.64% | -0.64 | 20% |
| 2024 | 24 | +2.83% | -1.40% | 46% | +0.72% | +0.25 | 33% |
| 2025 | 25 | +1.75% | +1.82% | 56% | +1.15% | +0.44 | 32% |
| 2026 | 29 | -2.30% | -3.50% | 41% | -2.69% | -1.47 | 31% |

## s1_unclassified

All years: **3370 trades, mean net -0.07%** (median -1.28%, 46% winners, t -0.29); gross +0.56%; net minus SPY over the same days -1.08% (t -5.27). Month-clustered: net +0.50% (t +0.97, 105 months), net minus SPY -0.50% (t -1.32). Exits: {'time': 2120, 'stop': 1091, 'gap': 158, 'data_end': 1}.

| Year | Trades | Mean net | Median net | Winners | Mean net - SPY | t (net - SPY) | Stops+gaps |
|---|---|---|---|---|---|---|---|
| 2018 | 412 | -1.91% | -2.78% | 42% | -0.94% | -2.07 | 38% |
| 2019 | 411 | +1.57% | +1.06% | 53% | -0.22% | -0.49 | 31% |
| 2020 | 639 | -0.99% | -7.69% | 41% | -3.27% | -4.78 | 52% |
| 2021 | 317 | +0.19% | -0.57% | 48% | -0.99% | -1.73 | 30% |
| 2022 | 343 | -0.49% | -2.16% | 41% | -0.04% | -0.07 | 38% |
| 2023 | 343 | +1.67% | +0.82% | 51% | -0.61% | -1.02 | 34% |
| 2024 | 239 | -0.76% | -0.30% | 50% | -2.63% | -4.88 | 28% |
| 2025 | 391 | +0.03% | -0.21% | 49% | -0.21% | -0.38 | 34% |
| 2026 | 275 | +0.87% | -0.17% | 49% | +0.58% | +0.85 | 32% |
