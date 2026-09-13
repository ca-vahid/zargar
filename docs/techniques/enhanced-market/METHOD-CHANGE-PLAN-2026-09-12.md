# EM method change plan — after twelve sessions (2026-08-26 .. 2026-09-11)

Written 2026-09-12 (weekend) by the EM desk for review by the other desks BEFORE anything is
implemented. Every number below is in TRADING-RULES (§1.4b, §2 day entries, §3 T-11..T-14) or
the cited sweep ids. Nothing here changes live behaviour until it has passed the loop in
EVOLUTION-PLAN (sweep -> shadow/Practice -> §5 change log).

## 1. The twelve-session scorecard, in plain words

| | |
|---|---|
| sessions | 12 |
| EM fills | 1 (HOOD puts, 2026-09-10, -$66) |
| fires reaching the order path | 9 in the two critic-advisory sessions; 8 blocked by the option spread gate, 1 filled |
| critic kills before that | 25 scored: 16 right, 9 wrong, net +0.5R (a coin flip) |
| deterministic method on the replay (valid fires) | +3.98R over 37 fires, 12 sessions (`b48db0763a`) — about +0.1R per fire before option costs |
| sub-R2 fires (the gate audit) | +6.1R Thu, +3.7R Wed, +0.04R/fire over the audit — R2 stays by user decision |
| theories tested and rejected | T-11 window extremes, T-12 flow confirmation (two forms), T-13 gap-through continuation (two forms), T-14 scratch rule (three levels) |
| EM Practice book | $9,929.64 |

The method as coded is roughly breakeven on the underlying and has not been able to express
itself in options at all. That second fact is the one to fix first.

## 2. What the author did this week that we did not

Sources: his Discord video transcripts and morning posts (ingested daily), X feed read on 09-09
and 09-10, and again on 09-12 for Thu/Fri: **he posted no trade on X on Thursday or Friday** -
only Alertsify marketing - which matches his Friday video ("I won't guess"). His wins are
self-selected; we have no record of his losses.

| day | his trade / stance | what we did | gap |
|---|---|---|---|
| Tue 09-09 | SPY puts on the breakdown of the prior-day low, +126% | SPY trigger voided `gapped_through`; Tips "not chasing"; Team2 read "focus on puts", no entry | he trades continuation THROUGH a level the open gapped past; we void it (T-13 tested: +0.05R/fire loose, not adopted) |
| Wed 09-10 | held MSFT puts from a wedge breakdown into the gap-down; IWM 293P off the pre-market low, +141% (Team2 desk's EOD note) | 6 fires, 5 spread-gated, HOOD -$66 after +2.5R MFE | index / mega-cap vehicles with penny spreads; multi-day hold on a structure trade |
| Thu 09-10 video | "everything gapping down, indices untouchable, give the open time; continuation names" | 3 fires at 09:31-09:37 on the gap, all spread-gated | he waits on gap days; we fire into the first bars |
| Fri 09-11 | "everything gapping up, moves exhausted, no risk/reward, I won't guess" - sat out | 3 fires at 09:37-09:46, all spread-gated (spreads 36-80%) | same: no entry without consolidation |

Three differences explain the week, and none of them is a filter we can loosen:

1. **Vehicle.** His names are SPY/QQQ/IWM and mega-caps whose options have 1-8% spreads. Our
   fires land on BSX ($0.15/$0.35), KLAC (64%), AVAV (67%), HPE (42%). The nightly chain
   snapshot says only **16 of 135** universe names have a median near-money spread <= 10%
   (SPY, QQQ, IWM, TLT, IBIT, SLV, TSLA, NVDA, AMZN, INTC, NOW, SMCI, BAC, PFE, CRWV, SPCX);
   **83 are above 20%**. The spread gate was right to refuse (it saved four stops for four
   missed TP1s this week, net about zero) - the error is upstream: we plan setups on names we
   cannot trade.
2. **Gap days.** Six of twelve sessions opened on a gap. He sits out or trades continuation;
   we void 60+ triggers at 09:30, fire the survivors into the first bars, and the critic kills
   them. Our gap-day fires are where the wrong kills and the HOOD-type stop-outs live.
3. **Structure over touches.** His entries this week were a wedge breakdown (MSFT), a
   pre-market-low break (IWM), a prior-day-low break (SPY): the level as a break in the
   direction of the day, held for hours or overnight. Ours are at-level bounces/rejects with
   the entry AT the level and targets 3-7R away on re-planned gap-day geometry.

## 3. The proposal (six changes, in the order to test them)

Each item names the knob, the test that decides it, and the adopt bar. D7 applies throughout:
+0.3R/fire over baseline on the same sessions, fires <= 2x.

### C1 · Tradeable-vehicle universe (the fix for 8 of 9 fires) — build first
- Nightly liquidity screen from `option_chain_snapshots`: a name is EM-tradeable when its
  near-the-money contracts (mid $0.50-$5, nearest expiry >= 3 DTE) have a median spread
  <= `techniques.enhanced_market.max_spread_pct` (start 12%) and open interest >= 500. Names
  that fail are still PLANNED (sheet, scorecards) but are armed with `entry_fallback=shares`
  by default, or not armed (user knob `ingest.untradeable = shares | skip`).
- Contract pick retries: when the just-OTM strike fails T5.4, try the next strike in and the
  next weekly before giving up (1.6 already lists this; it was never built).
- Test: re-run the 12-session baseline restricted to the tradeable set - what fraction of the
  +3.98R survives? If most of the R is in untradeable names, the shares fallback is the
  method's vehicle in Practice and the option leg waits for liquidity.
- Owner: EM (universe.py, arming.py contract pick). Platform touch: none.

### C2 · Shares fallback ON in Practice (immediate, no sweep needed)
- `entry_fallback=shares` becomes the Practice default for EM arms. A fire whose option is
  untradeable buys shares sized by risk %. This turns this week's 8 gated fires into 8 fills
  and makes the method measurable in money. Real-money profile keeps it off.
- Owner: EM. Reversible with one setting.

### C3 · Gap-day policy (his rule, as data)
- At 09:25, if |SPY gap| > `gap_day_pct` (start 0.5%): (a) bounce/reject triggers in the
  gap direction are demoted to watch until 10:00 ET (he "gives the open time"); (b) the
  loose continuation trigger (T-13b, already built) is enabled for that session only.
- Test: sweep `--set gap_day_policy=wait_then_continue` vs baseline; report by gap/no-gap
  sessions separately. Adopt only if the gap-day slice improves AND non-gap days are untouched.
- Owner: EM (arming pre-open hook + one MarketRules knob).

### C3b · The pre-open re-plan itself (added after Friday's replay)
- Friday's replay found +7.4R on 5 valid fires; the best, IBIT r2 (+4.8R, an option-liquid
  name, armed), never fired live because the 09:25 re-plan on a +0.68% pre-market print
  discarded the original triggers and re-armed a plan that was invalidated at 09:31. The
  re-plan has now cost IBIT (Fri), HOOD and KLAC (Thu, far-TP1 geometry) with no documented
  save. Proposal: the re-plan KEEPS the original triggers alongside the re-derived ones (both
  tracked, whichever the tape reaches), or is limited to gaps beyond `gap_void_r`.
- Test: sweep is not possible (the static sweep cannot see re-plans, 2026-09-05 finding);
  measure live with both trigger sets journaled for ten sessions, then decide.
- Owner: EM (`_preopen_check`, `build_session_plan(reference_price=)`).

### C4 · Exit geometry on re-planned levels
- The far first target is the problem only when the pre-open re-plan pushed TP1 > 3R away
  (HOOD, KLAC, LITE, WDC). Variant: scratch rule (T-14, built) applied ONLY when TP1 > 3R.
- Test: sweep `--set scratch_r=1.0 --set scratch_only_far_tp1=true` vs baseline. T-14's
  blanket version lost (-4.1R at 1.0R); the targeted one is untested.
- Owner: EM. Platform touch: one boolean in MarketRules.

### C5 · Structure breaks as a first-class trigger (his MSFT / IWM shape)
- Today EM's breakout/breakdown triggers require surge + decisive candle + follow-through and
  fire 3-8 times in 12 sessions at -0.5R each. His breaks are (i) a wedge/consolidation break
  after a multi-bar squeeze, (ii) a pre-market extreme break at the open. Proposal: a
  `consolidation_break` trigger kind - N bars of range < X ATR ending at the level, entry on
  the first close outside the range, stop at the range's other side, TP1 = range height x2.
- Test: sweep as a new kind (new fires only; existing kinds unchanged). This is the biggest
  build (tracker + plans.py) and the least certain; it goes last.
- Owner: EM, marketstructure (new kind is shared code - PLATFORM-RULES entry).

### C6 · Keep, and keep measuring
- Critic stays advisory on at-level triggers (§5 2026-09-09); re-tally advisory-"no" fills vs
  "yes" fills at 10 sessions of fills.
- LLM plan review: decision at ten sessions (~09-19); four sessions in, accepted -0.09R/fire
  vs rejected -0.48R/fire.
- R2 stays (user decision); the gate audit keeps reporting the sub-R2 number weekly.
- Board auto-arm stays; his morning names have not fired for us in eight sessions - after C1
  most of them (MSFT, NFLX, META, AMZN) become tradeable-set names.

## 4. Order of work and what each step costs

| step | needs | effort | decides |
|---|---|---|---|
| C2 shares fallback default | settings only | minutes | fills start Monday |
| C1 liquidity screen + pick retry | universe.py, arming.py, one nightly job | 1 day | which names EM may trade in options |
| C1 test: baseline on the tradeable set | sweep | 1 hour | how much R the method keeps on liquid names |
| C3 gap-day policy | pre-open hook + knob + sweep | 1 day | gap days |
| C3b keep original triggers through the re-plan | pre-open hook, journal both sets | half a day | whether the re-plan is a net loss |
| C4 targeted scratch | knob + sweep | 2 hours | re-planned levels |
| C5 consolidation break | tracker kind + plans + sweep | 3 days | a new lane |

Suggested reviewer questions for the other desks: does C1's screen belong in the shared
research feed (Flow already reads the same snapshots)? Does C2 conflict with the per-technique
book rules? Is the shares fallback acceptable for auto-armed board plans?

## 5. What this plan does NOT claim

- It does not claim the author's numbers are reproducible. Every theory taken directly from
  his feed (T-12 flow, T-13 continuation, T-6/T-14 tempo) failed its sweep.
- It does not loosen R2, the gap rules or the windows.
- It does not add LLM steps. The one LLM step under measurement (the plan review) keeps its
  09-19 decision date.
