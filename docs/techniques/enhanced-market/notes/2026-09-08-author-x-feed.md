# The author's X feed, read 2026-09-08 evening (what he does that we do not)

Source: x.com/EnhancedMarket, posts 2026-08-21 .. 2026-09-08, read through the user's
logged-in browser. Promotional posts for his copy-trading product were ignored on the
user's instruction; only the trade content was kept. Everything below is what HE says
he did; none of it is broker-verified by us.

## The trades he posted

| date | post | what it tells us |
|---|---|---|
| Aug 31 | "+240% on $TSLA calls today. 9:49am, TSLA at $358.53. Sweeps started lifting the $360 calls expiring TODAY at $2.33. 122,038 contracts against 6,742 open interest. Closed at $7.93. TSLA closed $367.19. The tape was screaming at 9:49." | Entry trigger = a burst of aggressive buying (sweeps on the ask) in a 0DTE strike just above price, 19 minutes after the open. Size of the print vs open interest is the signal. Exit the same day into the move. |
| Aug 31 | "$GPRO 9/18 $1 calls closed Friday at a penny. 52 contracts traded the whole day. Today 32,702 contracts went through against 2,733 open interest. Almost all of it on the ask. Closed at $0.24. The tape told you before the chart did." | Same signal on a name with NO chart setup at all: volume 12x open interest, on the ask, in a dead contract. Pure flow. |
| Sep 4 | "$NVDA calls over 115% here" (chart image only) | Flow-plus-level on a mega-cap; NVDA was his "at resistance for continuation" name that morning. |
| Sep 8 | "Some huge OTM trades on the ask side" (SNDK $1820C 3d, META $640C, prints of 3,468 / 517 / 235 / 5,000 contracts) | He reads the flow screen live during the session and trades from it. |
| Sep 5 | "Someone up $10,000 could be a better trader than someone up $1,000,000. How much capital did they use? How much did they risk? What did they lose along the way?" | His own framing: judge by risk taken, not dollars. |
| Aug 21 | (a follower's verified record) 351 trades since February, 75.8% win rate, +$6,877 realized, +165% ROI, August 13 green days / 1 red | The scale he considers a good month: small, frequent, high win-rate, most days green. |

## What the pattern is

1. **The trigger is order flow, not the chart.** Every winning post names a sweep: a burst of
   contracts bought at the ask, many times the open interest, in a near-the-money contract
   expiring today or this week. The level (his morning video) says WHERE to look; the sweep
   says WHEN. GPRO shows the flow alone is enough for him.
2. **Timing is minutes after the open.** 9:49 on TSLA; his videos say "wait for the break at
   the open". This is inside our prime-open window, so the window is not the difference.
3. **Exits are fast and whole.** He banks the move the same day, often within the hour, and
   quotes the exit as a percent of premium (+115%, +240%), not as R on the underlying. No
   three-target ladder, no runner to the horizon.
4. **Contracts are 0DTE or weekly, just OTM.** $360 calls with TSLA at 358.5, expiring that
   day; $1 GPRO calls. Cheap premium, convex payoff, the sweep itself is the confirmation
   that someone large is on the same side.
5. **He accepts a low structural bar.** No R:R gate on the underlying, no touch count, no
   "stop must sit outside the chop". His risk control is the premium: a $2.33 call is the
   whole risk.

## Where we differ

| dimension | us (EM as built) | him (as posted) |
|---|---|---|
| trigger | price touches a planned level with volume and follow-through, judged on closed 1m bars | a sweep on the ask hits the tape near the level, judged live |
| confirmation | fire critic (vision) reads structure and momentum | size of the print vs open interest |
| R:R gate | >= 3 to the exit target on the underlying | none stated; premium is the risk |
| exits | 30/40/15 ladder, stop on close, runner to the horizon | one exit, same day, on premium percent |
| kill rate | 9 of 9 fires killed today; 20 kills in 5 days | takes the trade when the tape confirms |
| data we lack | intraday option prints (sweeps, size vs OI) in real time | that is his whole screen |

## What we already have that points the same way

- The Flow lane's nightly reads flagged NVDA (11) on Sep 3 and Sep 4, MU (11) on Sep 1, TSLA
  (9) on Sep 4, and DELL / AVGO / COIN on the days they moved. The raw signal is in our data,
  once a day, from chain snapshots. He has it live.
- The board check already builds plans on his names; what it cannot see is the sweep that
  tells him which of the seven names is live this morning.
- Our week-1 autopsy said the same thing from the other side: the R2 gate kills two thirds
  of the funnel and the survivors' problem is tempo, not level quality (TRADING-RULES 1.8,
  T-6). His tempo is the missing piece, and flow is how he times it.

## What to do with this (proposals, not changes)

1. **T-12 in TRADING-RULES: flow-confirmed entries.** A fire counts only if a sweep on the
   ask (volume vs open interest above a threshold) prints in the contract we would buy,
   within N minutes of the level touch. Test first as a variant on history where we have
   chain snapshots, then as a shadow instance. Adopt bar as for every theory: +0.3R/fire.
2. **Flow, intraday.** The Flow technique reads end-of-day snapshots. Real-time option
   prints exist on the same Alpaca subscription that gives us the NBBO; a sweep detector
   over that stream is the engine piece the theory needs. Platform work, not EM code.
3. **Exit tempo variant** (already queued, T-6): bank on premium percent, one exit, no
   runner. His numbers are premium numbers; ours must be measured the same way to compare.
4. **Do not loosen R2 or the critic on this evidence.** Today the critic was right 8 times
   in 9 and avoided -8.3R. His edge is an input we do not have, not a gate we have wrong.

Recorded by the EM desk on 2026-09-08. Evidence: the posts above (status ids not kept; search
`from:EnhancedMarket TSLA 358.53` reproduces the key one), flow_reads Sep 1..8, TRADING-RULES
day-9 entry.
