# Video evidence — S24 and S30

## S24 — September strategy overview

Source: [Sean's 3:31 video](https://www.tiktok.com/@sean.rechtman/video/7682454057855864094),
linked by S01. Reviewed 2026-09-06 after the user cleared TikTok's CAPTCHA.
Review used the displayed automatic captions, repeated timeline seeks and visible
chart/scanner frames. Caption timestamps are approximate; this is a method
summary, not a verbatim transcript or an audit of the author's returns.

| Video interval | Method evidence |
|---|---|
| 00:11–00:33 | Start on the daily chart. Buy stocks in strong uptrends and hold the larger trend as a swing, rather than repeatedly trying to capture small intraday moves. |
| 00:34–01:12 | Use the 8, 21 and 50 EMAs to identify direction. Above them favors longs; below them favors a shorter downside trade until the market recovers its trend. |
| 01:13–01:37 | Use the indices as context and find individual leaders with stronger moves. The comparative performance examples are illustrations, not verified expected returns. |
| 01:38–02:06 | TradingView stock screen: price over $3, capitalization over $300M, price above EMA21/50, relative volume over 1, average volume over 500K, ADR over 2%. The visible average-volume filter specifies 10 days. Sort volume descending. |
| 02:07–02:49 | Look for a prior advance followed by a sideways/tight base, with a clear resistance level rejected several times. Cups and flags are mentioned; the auto-caption's “penny” likely means pennant, but that word was not independently audio-verified. |
| 02:50–03:13 | Move from the marked daily level to a 5m or 15m chart. Enter when price breaks the level and volume appears. Place the initial stop at the day's low. |
| 03:14–03:31 | A recent breakout illustrates continuation. The ending invites practice; it does not specify a profit-taking ladder. |

## Consequences for implementation

- `september_2026_video` is a separate screen snapshot: ADR 2%, 10-session
  average volume, and relative volume >1. Earlier saved profiles retain their
  behavior. The screen applies the ratio to completed daily sessions; it does
  not claim to reproduce TradingView's unfinished intraday screen.
- Relative volume is the tested session's volume divided by the mean of the
  preceding ten sessions, excluding the tested session, following
  [TradingView's definition](https://www.tradingview.com/support/solutions/43000635874-how-do-we-calculate-relative-volume-and-relative-volume-at-time/).
  This differs from relative volume at time and from the entry candle's own
  time-of-day volume baseline. Missing/zero denominators remain unknown.
- The video describes entry at the break, without explicitly requiring a close.
  Zargar's closed-bar confirmation remains an explicit platform adaptation;
  do not label it a verbatim S24 rule. The video names 5m/15m, not 30m.
- The price-filter tooltip appears inclusive at $3, while the caption says
  over $3. The implementation retains the strict >$3 boundary from the written
  screen; this boundary choice is explicit, not exact UI-filter parity.
- The clip does not define contract delta/DTE, risk percentage, industry-rank
  gates, or exit fractions. Those need their separately cited written sources
  and reviewed choices. Do not infer a new exit policy from this clip.


## S30 — post-ignition continuation, September 11

[Video](https://www.youtube.com/watch?v=7xSMgmLoqM8), 20:20. Full English auto-generated transcript exported/read on September 12; scanner (~14:13), CRCL entry (~17:34) and developing SCCO (~19:11) frames checked. Initial transcript failures were resolved on retry. This is not frame-by-frame verification of every example or a profit audit.

| Interval | Evidence |
|---|---|
| 1:55–5:09 | Trend quality, EMA8/21/50, then emphasis on EMA8 catching up |
| 7:40–10:26 | Unusual ignition volume followed by quieter consolidation and renewed expansion |
| 10:28–13:39 | Earnings or other catalysts; a few consolidation days can suffice |
| 13:58–15:16 | Event-day discovery screen and a persistent PG/ignition watchlist |
| 15:18–17:49 | Daily levels, lower-timeframe entry illustration, day-low stop |
| 17:49–19:40 | Working positions can be held; developing setups need not trigger tomorrow |

Caption ticker/EMA spellings can be wrong; retain uncertainties rather than using them as instrument identity. See [IGNITION.md](IGNITION.md) for the implemented profile and [METHOD.md](METHOD.md) for source differences. Full transcript text is kept as local research evidence rather than republished in the repository.
