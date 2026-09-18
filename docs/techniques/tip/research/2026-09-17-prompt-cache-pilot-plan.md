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

## Budget (list price, upper bound)

One SBLK appraisal request ≈ 170k input tokens (the day's appraisals averaged 178k input per call) and ≈ 1.5k output.

| Arm | Calls | Input tokens | Est. cost |
|---|---:|---:|---:|
| off x3 | 3 | ~510k | ~$2.55 + output ~$0.11 |
| on warm-up | 1 | ~170k (write at 6.25) | ~$1.06 |
| on reads x3 | 3 | ~510k (prefix ~150k each read at 0.50; ~20k uncached header at 5.00) | ~$0.23 + ~$0.30 |
| on after expiry | 1 | ~170k (write) | ~$1.06 |
| **Total** | **8** | **~1.4M** | **≈ $5.5, cap $8** |

Stop rule: abort if any call reports `cache_creation_input_tokens` 0 AND `cache_read_input_tokens` 0 on the `on` arm
(caching not taking effect - prefix not identical or marker rejected) after the second `on` call; report the reason.

## Success / read-out (no policy change either way)

- Hits observed: reads x3 with `cacheRead` ≈ the prefix size, cost per call on the `on` arm below `off` after the
  warm-up, latency reported separately (expect lower time-to-first-token, not guaranteed).
- Judgments identical across arms on the frozen inputs.
- Output: a short report in `research/` with the per-call table, the priced totals (warm-up included), the prefix
  hashes and a break-even statement (5-minute writes pay off after one read; the desk's appraisal cadence decides
  whether hits would occur in production - that is the follow-on question, measured over a session only if this
  pilot is favourable and the user approves).

## What this pilot does NOT do

No live routing change, no recap route, no context trimming (a separate experiment), no order, no knowledge write, no
change to `techniques.tip.prompt_cache` in production. Approval needed: the ~$8 cap and the go.
