# 2026-09-28 — QQQ puts +300%: an intraday support flipped to resistance (captured 2026-09-28, signed-in Chrome)

Source: @Team2Trading on X, posts of 2026-09-28. The main post carries a 2m QQQ chart with two Discord screenshots.
The images are not stored in the repo. What they show, transcribed:

- **Bias box (ticked):** "Rejects pre market high ✅ · Break previous day low ✅ · Bearish EMA trend ✅". Levels on the
  chart: PMH 741.31, PDL zone 739.64 ("under this we focus on puts"), PML 736.03, a support zone ~734.6–735.0 ("trim
  here").
- **10:25 (Discord):** "Would love to see QQQ reject here."
- **10:36 (Discord):** "QQQ flipped that morning low into resistance. I'm looking at the 733p for a move down to those
  next support zones." Then "@everyone I'm taking QQQ 733p".
- **Chart annotation:** "Intraday support flips to resistance. Multiple confirmations to focus on puts down to our
  support target." The level is the morning's intraday low (~737.4, marked "support" early in the session). It is
  retested from below around 10:34–10:36 and rejected.
- **Result:** "QQQ puts for over 300%+ today". A second post says he "sold my puts at the exact low of day" and calls
  these "3 bar plays" on QQQ "a killer chart pattern on any timeframe". The pattern itself is not defined in the
  post.

## What our desk did (Control, the only unpaused Team2 book)
- The QQQ read had the same bias: bear stack, trend fan, strength 3 at 10:36.
- It produced **no setup at 10:36**. The only candidates all morning were a 09:50 entry inside the pre-market range
  (V6/B5 no-trade zone) and an 11:02 setup whose target was already behind price (F72).
- The desk traded IWM twice and SPY once instead: −$189 net, +$48 before fees.

## Why — the gap is a rule we do not have, not a bug
- `METHOD.md` L1.4 has level flips only for the **daily** levels (a broken PDH/PDL that holds on the retest). An
  **intraday** swing level (the morning low) flipping role is not a written rule, and neither is a "3 bar play".
- C2 (multi-day key levels as entry levels) is built and OFF. Its validation window (09-14..10-09) is sealed and must
  not be touched. It also concerns multi-day levels, not intraday ones.

## Status: candidate rule, NOT adopted
- **"Intraday swing low/high that breaks and is retested from the other side = entry level (role reversal)."** One
  documented instance, a self-selected recap. To adopt it:
  1. Collect his posts that use it (the weekly capture, plan P3.1).
  2. Freeze a causal definition of "intraday swing level" and "flip".
  3. Measure it order-free on real prints, like C2. Only then consider a registered Practice test.
- **"3 bar play":** undefined. Capture examples before defining anything.
