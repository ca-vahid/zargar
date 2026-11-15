# Tips source replay (tip-source-replay-v1)

Since 2026-08-28; 481 opening signals, 434 distinct tips (one per source, name, side and day), 383 scored, 51 without usable history. Cost allowance 0.3% of the entry price per round trip. A verdict needs 20 scored tips and 5 days. The armed book is in R against the replay plan's stop; the immediate book is in % of price after cost MINUS SPY's move over the same bars. Results are the underlying's move, not option fills.

## By source

| Group | Tips | Book | Scored | Days | Hit rate | Mean | Shrunk | 90% interval | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| ALL | 383 | immediate | 314 | 32 | 51% | -0.04 | -0.03 | -0.74 to +0.66 | no edge shown |
| ALL | 383 | armed | 274 | 32 | 26% | -0.28 | -0.26 | -0.63 to +0.05 | no edge shown |
| 🌟｜eva | 142 | immediate | 135 | 26 | 64% | +0.88 | +0.76 | -0.18 to +1.93 | no edge shown |
| 🌟｜eva | 142 | armed | 102 | 25 | 22% | -0.16 | -0.13 | -0.76 to +0.36 | no edge shown |
| 🌟｜muggzone-options | 108 | immediate | 95 | 28 | 48% | -0.20 | -0.16 | -1.09 to +0.78 | no edge shown |
| 🌟｜muggzone-options | 108 | armed | 69 | 28 | 39% | -0.00 | -0.00 | -0.41 to +0.47 | no edge shown |
| 🌟｜ab | 42 | immediate | 29 | 15 | 41% | -1.52 | -0.90 | -3.23 to +0.12 | no edge shown |
| 🌟｜ab | 42 | armed | 31 | 19 | 16% | -0.83 | -0.50 | -1.17 to -0.39 | negative |
| 🌟｜jon-and-kian | 26 | immediate | 15 | 13 | 13% | -5.11 | -2.19 | -9.53 to -0.73 | not enough |
| 🌟｜jon-and-kian | 26 | armed | 22 | 19 | 23% | -0.96 | -0.50 | -1.34 to -0.53 | negative |
| 🌟｜tt | 26 | immediate | 15 | 12 | 47% | +1.65 | +0.71 | -0.28 to +4.03 | not enough |
| 🌟｜tt | 26 | armed | 17 | 15 | 41% | -0.11 | -0.05 | -0.68 to +0.56 | not enough |
| 🌟｜common-stock | 15 | immediate | 10 | 8 | 10% | -5.38 | -1.79 | -12.74 to +5.28 | not enough |
| 🌟｜common-stock | 15 | armed | 14 | 11 | 21% | -0.38 | -0.16 | -1.23 to +0.64 | not enough |
| 🌟｜neal | 14 | immediate | 8 | 7 | 38% | +2.78 | +0.79 | -4.86 to +12.03 | not enough |
| 🌟｜neal | 14 | armed | 9 | 8 | 22% | +0.51 | +0.16 | -1.06 to +3.33 | not enough |
| flow-scan | 3 | immediate | 3 | 1 | 100% | +10.16 | +1.32 | - | not enough |
| flow-scan | 3 | armed | 3 | 1 | 0% | -1.49 | -0.19 | - | not enough |
| MK-alpha-trades | 3 | immediate | 1 | 1 | 0% | -1.33 | -0.06 | - | not enough |
| MK-alpha-trades | 3 | armed | 3 | 3 | 33% | -0.34 | -0.04 | - | not enough |
| 🌟｜florida-man | 2 | immediate | 1 | 1 | 0% | -12.11 | -0.58 | - | not enough |
| 🌟｜florida-man | 2 | armed | 2 | 2 | 0% | -1.39 | -0.13 | - | not enough |
| Claude-Verify | 1 | immediate | 1 | 1 | 0% | -0.29 | -0.01 | - | not enough |
| Claude-Verify | 1 | armed | 1 | 1 | 0% | -1.91 | -0.09 | - | not enough |
| Claude-Verify2 | 1 | immediate | 1 | 1 | 0% | -0.27 | -0.01 | - | not enough |
| Claude-Verify2 | 1 | armed | 1 | 1 | 0% | -1.76 | -0.08 | - | not enough |

## By the analyst's verdict at tip time

| Group | Tips | Book | Scored | Days | Hit rate | Mean | Shrunk | 90% interval | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| ALL | 383 | immediate | 314 | 32 | 51% | -0.04 | -0.03 | -0.74 to +0.66 | no edge shown |
| ALL | 383 | armed | 274 | 32 | 26% | -0.28 | -0.26 | -0.63 to +0.05 | no edge shown |
| skip | 230 | immediate | 201 | 29 | 57% | +0.34 | +0.31 | -0.45 to +1.26 | no edge shown |
| skip | 230 | armed | 159 | 31 | 30% | -0.23 | -0.21 | -0.57 to +0.12 | no edge shown |
| take | 111 | immediate | 77 | 27 | 34% | -1.33 | -1.06 | -3.44 to +0.57 | no edge shown |
| take | 111 | armed | 82 | 27 | 22% | -0.67 | -0.54 | -1.01 to -0.31 | negative |
| none | 23 | immediate | 23 | 9 | 57% | +0.48 | +0.26 | -4.63 to +7.29 | no edge shown |
| none | 23 | armed | 22 | 8 | 23% | +0.66 | +0.34 | -0.99 to +2.27 | no edge shown |
| watch | 19 | immediate | 13 | 10 | 46% | +0.94 | +0.37 | -4.19 to +4.80 | not enough |
| watch | 19 | armed | 11 | 10 | 18% | +0.00 | +0.00 | -1.28 to +1.97 | not enough |

## By stated instrument

| Group | Tips | Book | Scored | Days | Hit rate | Mean | Shrunk | 90% interval | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| ALL | 383 | immediate | 314 | 32 | 51% | -0.04 | -0.03 | -0.74 to +0.66 | no edge shown |
| ALL | 383 | armed | 274 | 32 | 26% | -0.28 | -0.26 | -0.63 to +0.05 | no edge shown |
| call | 286 | immediate | 234 | 30 | 56% | +0.86 | +0.80 | -0.03 to +1.78 | no edge shown |
| call | 286 | armed | 196 | 31 | 25% | -0.31 | -0.28 | -0.70 to +0.12 | no edge shown |
| put | 52 | immediate | 48 | 20 | 42% | -2.57 | -1.82 | -4.04 to -0.94 | negative |
| put | 52 | armed | 41 | 17 | 32% | -0.62 | -0.42 | -0.89 to -0.35 | negative |
| shares | 23 | immediate | 13 | 9 | 15% | -5.02 | -1.98 | -12.95 to +6.89 | not enough |
| shares | 23 | armed | 20 | 15 | 20% | +0.06 | +0.03 | -0.94 to +1.47 | no edge shown |
| unspecified | 22 | immediate | 19 | 10 | 37% | -1.29 | -0.63 | -2.85 to +0.66 | not enough |
| unspecified | 22 | armed | 17 | 10 | 35% | +0.44 | +0.20 | -0.76 to +2.00 | not enough |
