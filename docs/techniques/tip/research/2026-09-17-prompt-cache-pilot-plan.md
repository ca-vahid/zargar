# Prompt-cache pilot - plan for approval (E17-03, opened 2026-09-17; NOT run)

The knob `techniques.tip.prompt_cache` stays OFF until this pilot is approved, run and read. The pilot is small,
side-effect-free and budgeted; it measures, it does not decide a trading policy. Register entry: `prompt-cache`.

## Question

Does caching the identical STABLE prefix (system prompt + output schema + tool definitions) of an analyst request
produce actual cache hits, and what does it cost and save at the verified rate card - including the warm-up write -
without changing any judgment? The dynamic header (quotes, positions, evidence, notes) stays outside the cache.

## Design (side-effect-free)

- **Harness:** the frozen-context replay (`tip_frozen replay`) on ONE captured bundle - inputs are frozen, no tool
  acts, no order, no note, no proposal; the only side effect is the replay report row. Bundle: `fb-e0221ed3d071cc60`
  (SBLK take, 2026-09-17, manifest exact, classifier read captured) - the same request replayed keeps the prefix
  byte-identical, which is the precondition for a hit (exact prefix match).
- **Arms:** `off` (today's request shape) and `on` (`cacheable_request`: system as one cache-marked block, last tool
  definition marked). Same model (`claude-opus-5`), same frozen inputs, same `max_tokens`.
- **Sequence:** off x3 (baseline), then on x4 within the 5-minute cache window: call 1 = warm-up (expect
  `cache_creation_input_tokens` > 0, `cache_read_input_tokens` 0), calls 2-4 = expect reads. Then one `on` call after a
  deliberate > 5-minute gap to observe expiry (expect a new write).
- **Recorded per call (already on the run record):** `usage.in`, `out`, `cacheRead`, `cacheWrite`, `promptCache`,
  latency (`perCall.latencyMs`), stop reason; prefix hash of the system/tools blocks (sha256, added to the replay
  report so "identical prefix" is a checked fact, not an assumption); verdict/contract equality across arms
  (judgments must not change; the header is uncached).
- **Pricing:** `tools/tip_llm_cost.py` with the verified card (Opus 5: in 5.00, out 25.00, cache read 0.50, 5-minute
  cache write 6.25 USD/MTok) - warm-up cost counted, list price = estimate.

## Budget (list price, upper bound) - CORRECTED 2026-09-17 late (R3)

**Correction of the earlier estimate.** The first draft read "≈ 170k input tokens per request (the day's appraisals
averaged 178k input per call)". That was wrong: the day's 12 appraisals made **46 provider calls for 2.14M input
tokens = ~46.5k input tokens per call on average**, not 178k (178k was the per-RUN average: a run is a multi-turn
tool loop and each turn re-sends the growing conversation). Everything below is recomputed from measured sizes.

**Measured on the pilot bundle `fb-e0221ed3d071cc60` (dry-run harness, chars/4 estimates - the provider's own count
is what the pilot will record):**

| Part of the request | Chars / 4 | What it is |
|---|---:|---|
| Cacheable PREFIX (system prompt + 13 tool definitions), byte-identical across calls | **~5.3k tokens** | the only part `cacheable_request` marks |
| Uncached HEADER (rules, notes, positions, evidence, quotes for this tip) | **~20.4k tokens** | changes per tip, outside the cache |
| First call total | ~26.5k tokens | matches the 26,530 the cache-off dry run reported |

So the cacheable share of a FIRST call is ~20%, and of the day's average call (~46.5k, conversation included) ~11%.

**Savings ceiling from the prefix alone (Opus 5 list: in 5.00, cache read 0.50, 5-minute write 6.25 USD/MTok):**
one read saves 5.3k x (5.00 - 0.50) / 1e6 ≈ **$0.024**; the warm-up write costs 5.3k x 1.25 / 1e6 ≈ $0.007 extra.
Upper bound for a day like 2026-09-17 (46 calls, EVERY one a hit - not realistic within 5-minute windows):
≈ $1.10 against the $11.83 appraise spend, i.e. under 10%. The larger, uncached part is the conversation that
multi-turn loops re-send; extending the cache marker to the last message of the conversation (a different request
shape, not part of this pilot) is the follow-on question the pilot's per-attempt data can inform.

**Pilot budget at measured sizes (first-call replays; a real model may take up to `analyst_max_tools` tool turns,
each re-sending the conversation, so a replay can be several attempts - the ceiling is enforced per attempt):**

| Arm | Calls | Est. cost (first call only) | Worst case incl. tool turns |
|---|---:|---:|---:|
| off x3 | 3 | ~$0.51 | ~$2.4 |
| on warm-up | 1 | ~$0.18 | ~$0.8 |
| on reads x3 | 3 | ~$0.44 | ~$2.2 |
| on after expiry (write) | 1 | ~$0.18 | ~$0.8 |
| **Total** | **8+** | **≈ $1.3** | **≈ $6.2; hard cap $8 enforced** |

## Harness (executable, CACHE-P1/P2, 2026-09-17 late)

```
python -m zargar.tools.tip_frozen replay --bundle fb-e0221ed3d071cc60 --variants current --cache off --budget-usd 8 --repeats 3
python -m zargar.tools.tip_frozen replay --bundle fb-e0221ed3d071cc60 --variants current --cache on  --budget-usd 8 --repeats 4
# > 5 minutes later
python -m zargar.tools.tip_frozen replay --bundle fb-e0221ed3d071cc60 --variants current --cache on  --budget-usd 8
```

- `--cache off|on` (default off) shapes the request through the SAME `analyst.cacheable_request` production uses.
- `--budget-usd` is an ENFORCED ceiling shared by every attempt of the invocation: `ReplayBudget` checks a
  conservative estimate (prompt chars/4 at the input rate + the full `max_tokens` at the output rate) BEFORE each
  attempt and charges the provider's own usage AFTER (input, output, cache read, cache write at `llm.rates`);
  a failed or cut attempt with unknown billing is charged at its estimate. A paid replay without a cap is refused
  before any client is built; without a complete rate card for the model it is refused too.
- Per attempt on the replay report: tokens in/out, cache write/read, latency, stop reason, estimate, priced usd and the
  billing basis; the report also carries `promptCache`, `prefixChars`/`prefixTokensEst` and `headerChars`/
  `headerTokensEst` separately.
- **Scripted dry run (2026-09-17 late, stub model, synthetic usage, $0):** cache off -> 26,530 in, prefix ~5,331 /
  header ~20,418; cache on x2 under `--budget-usd 8` -> attempt 1 write 5,573 ($0.1408), attempt 2 read 5,573
  ($0.1087), spent $0.2495 of $8; `--budget-usd 0.05` -> attempt 1 REFUSED before the call ("would cost ~$0.21 on
  top of $0.00 spent (cap $0.05)"), no verdict, nothing sent; no cap on a paid replay -> refused. Dry-run rows are
  persisted with model `dry-run-stub(claude-opus-5)` and `dryRun: true`, never attributed to the real model.

Stop rule: abort if any call reports `cache_creation_input_tokens` 0 AND `cache_read_input_tokens` 0 on the `on` arm
(caching not taking effect - prefix not identical or marker rejected) after the second `on` call; report the reason.

## Success / read-out (no policy change either way)

- Hits observed: reads x3 with `cacheRead` ≈ the measured prefix (~5k tokens, provider count), priced cost per call on
  the `on` arm below `off` after the warm-up, latency reported separately (expect lower time-to-first-token, not
  guaranteed).
- Judgments identical across arms on the frozen inputs.
- Output: a short report in `research/` with the per-attempt table, the priced totals (warm-up included), the prefix
  hashes and a break-even statement (a 5-minute write pays off after one read; the desk's appraisal cadence decides
  whether hits would occur in production - that is the follow-on question, measured over a session only if this
  pilot is favourable and the user approves). State the savings ceiling honestly: at the measured prefix it is under
  10% of appraisal spend unless the cached span is extended to the conversation.

## What this pilot does NOT do

No live routing change, no recap route, no context trimming (a separate experiment), no order, no knowledge write, no
change to `techniques.tip.prompt_cache` in production (OFF). Approval needed: the $8 cap and the go for PAID calls.

## User decision 2026-09-17 late: paid pilot SKIPPED for now, caching stays OFF

The user closed E17 without running the paid pilot: "Its expected benefit is small, and the claimed $8 hard cap still
relies on estimated tokens and doesn't fully account for retries across separate invocations. It is not a deployment
blocker." Both caveats are correct and recorded here: (1) the pre-call check prices a chars/4 ESTIMATE - only the
post-call charge uses the provider's count, so a single attempt can overshoot the remaining headroom by the gap between
estimate and actual; (2) `ReplayBudget` lives for ONE CLI invocation - a second invocation starts a fresh ledger, so the
ceiling is per command, not per day. Neither is fixed here (no further feature work for this review). Production
`techniques.tip.prompt_cache` remains False; the harness stays available for a later, separately approved measurement.
