# Tips September21 — comprehensive economics and execution review

Reviewed main `7eb89303` in isolated detached `C:/Cursor/zargar-codex/.cache/tips-sep21-review`. Primary branch `codex/zargar-development` and other worktrees preserved. Live read-only health: **0.8.28 / 7ee5ad2a855b52c9123da5ebc250f3d93c707d60**. Database reads used read-only connections. No orders, settings, production code, deployments or paid model calls changed. Read window approximately 20:25–20:32 ET September21. The accounting day is not yet complete.

## Outcome and what is working

Tips Practice realized **+$16.628 net**: AAL two contracts +$13.84 after allocated entry/exit fees, VKTX17-share trim +$2.788. Six entries filled: NFLX1, PL59 shares, IONQ28 shares, CORZ1, ACHR Sep25 5.5C5, VKTX50 shares. Eight positions remain, including ACHR Jan27 7C3 and SBLK62 shares carried in. Marked value of holdings at the close approximately $5,481.08, 61.1% of $8,965.8929 equity; cash $3,484.8129. This is exposure, not planned risk.

Regular-session reference marks: Friday last pre-close $8,965.0849; Monday pre-open $8,978.7249; Monday last pre-close (15:59:48 ET) $8,965.8929. Thus +$0.808 from Friday's close and -$12.832 from Monday's pre-open. Latest read at approximately 20:32 ET: $8,966.6129. These are explicit observation timestamps, not the still-future 03:59 accounting close.

Recorded model usage from 04:00 ET to the read: **$115.0491 priced subtotal**, list-price estimate and lower bound, not an invoice. Intake reviews $92.0695 (133 reviews / 422 calls / 17.057M input tokens), appraisal $20.3239, retros $2.4709, digest $0.1848. Twenty-nine intake records lack usage, including 27 handoffs that are not automatically missing paid calls and two failed extraction records. Stage-only extraction/transcription usage is not included in this subtotal. Do not add this read to prior cost reports; it is a later snapshot.

133 observe decisions match those 133 reviews: 106 review ($74.6010), 27 would-skip ($17.4685), no unmatched/non-done reviews in this particular live join. Eight reviews on the keep side called management tools; none of the would-skips did. **All 27 would-skips carry watch/deferred content**, so human adjudication remains material. The gross would-save is only about 19% of intake spending and 15% of this priced total; even removing it leaves ~$97.58 for this snapshot. This is not realized savings because observe still ran every review.

All 133 review runs have captured request manifests. Rule supply recording is working: 47 of 56 nonsuperseded/nondeleted rule rows have a nonzero supplied count (counts include history of supply; not a claim that all are currently operative). Relevance remains observe, geometry enforce, integrity pause and review capture on. Existing report records the successful 7-second ARM cold-park recheck; do not reopen that accepted implementation without contrary evidence.

## One consolidated development goal

Improve actual trade capture and net economics, and make Friday's decision evidence complete. Implement confirmed reporting/wiring/recovery corrections together. Prepare, but do not silently activate, changes to target execution, intake routing/models, portfolio risk or source policy. Use the existing studies, ledgers and scripts. Tips owns the package; coordinate shared quote/position paths with their owner. One combined handoff after focused checks, not an approval request for each routine fix.

### S21-01 — submitted-card payoff diverges from the analyst and execution costs (confirmed, P1)

`approvals/proposals.py::_compute_risk_plan` calls payoff_preview with only options.fee_per_contract, omitting sim.reg_fee_per_contract, and omits strike, premium, expiry and hold metadata. Analyst preview uses the complete fee helper; the approval path does not. Live NFLX/CORZ/ACHR cards have feePerUnit0.99 versus actual/execcost1.04 and null expiry/break-even despite identifiable OCC contracts. ACHR5 understates a round trip by $0.50. This is not the major trading loss, but it falsifies decision arithmetic and the previously built horizon explanation.

Fix the actual card creation/revalidation/submission wiring using the shared fee basis and verified contract metadata (decode/resolve where vehicle currently omits strike/expiry). Populate premium, type and hold from the confirmed plan. Keep estimator labels; do not invent missing Greeks. Regenerate diagnostics, not ledger fills. Two supplied tests fail on this head: fee1.04 expected, got0.99; known strike5.5 plus premium0.14 expected break-even5.64, gotNone. Include a positive put and missing-metadata control when completing the wiring.

### S21-02 — Friday's observation report can falsely appear complete (confirmed, P1 before checkpoint)

`tip_review_gate_eval.prospective` turns a missing joined run into an empty opinion, reports zero management false negatives, and never exposes unresolved coverage; it does not query terminal status. It also prints only `other[:20]` despite requiring a human review of all candidates. Two supplied tests fail. Today's real list already has27 would-skips with watch content, so seven candidates disappear from the printed human list.

Fix: join/retain run status and identity; report complete, running, failed, unmatched and unevaluable decisions separately. Unknown outcome cannot certify a clean checkpoint. Export every correction/mixed/new-entry/deferred candidate with message/run ids, source text or links, rationale and relevant receipts; paginate the UI if desired, not the artifact. Keep management proposals distinct from successful actions. Mark incomplete checkpoint eligibility explicitly. No gate enforcement change.

The scheduled `tips-five-session.ps1` has a related code-confirmed weakness: ErrorActionPreference Continue, native exit codes ignored, READY based only on decision-day count. It counts any weekday decision (not specifically completed observe sessions), while report commands have inconsistent upper cutoffs. A failed tool can be written into a .md file while STATUS says READY. Check every process exit code, use one completed accounting-session cutoff for count and all reports, require observe mode, and publish atomically with FAILED/INCOMPLETE on errors. Include a command-failure test and incomplete-fifth-day test. Don't invent five full sessions from a single decision each; print coverage and gaps for human assessment.

### S21-03 — target touches are sold later at market, not at the target (observed design gap, P1 research/design)

VKTX entry50 @29.74 at15:23:26. Alpaca exchange 1m bars show15:26 high30.70/close30.65: target30.60 really was reached AFTER entry. At15:30 the15m policy fired a market trim17 @29.904 (fresh receipt bid29.91/ask30.03), realizing+$2.788. At target price those17 shares would gross+$14.62, a difference of$11.832. This is arithmetic measuring target-to-fill shortfall, **not proof a17-share limit would have filled at30.60**. No false-hit or pre-entry-bar explanation is supported for this instance.

The code uses the completed bar high/low for a target decision, then exits at the current market; the initial venue TP bracket had been cancelled on adoption. Current payoff scenarios assume target-price exits and do not model this delay. Preserve the actual fill and do not call it a30.60 execution.

Implement first-touch time, decision time, order time, fill time, target-price shortfall and quote/depth evidence in the existing exit report. Prepare one explicit execution-policy comparison: current bar-touch/market-at-close versus executable quote touch or appropriately coordinated resting limit. Include reversal and failed-fill cases, partials, outstanding stop resizing, restart and one-exit ownership. Do not activate a new target policy as a 'bug fix' or touch other techniques without review. Make preview target-price assumptions visible immediately.

### S21-04 — cheap option friction and delayed fills need honest diagnostics (observed, P1 economics)

ACHR Sep25 5.5C5 filled at0.14, debit$70. Entry fees$5.20; estimated exit fees another$5.20: **14.9% of debit in round-trip fees alone**. Fill-time bid0.13/ask0.14 implies a further$5 immediate spread, total$15.40 (22% of debit) for an immediate round trip at that quote. This is a friction diagnostic, not a prediction of the eventual exit. The same ticker also has a Jan27 call position; assess combined exposure, not just each card alone.

The ACHR order was approved automatically14:00:49 and filled14:58:53: ~58 minutes as a resting limit. That is not the cold-symbol delay and not a missed fill. Its stored execCost sample is14:00:49, although fill evidence is fresh14:58:53. Label decision-, submission- and fill-time quote diagnostics independently, rather than treating a stale decision comparison as fill-time market quality. Reassess thesis/stop validity for delayed fills using existing admission/adoption contracts; propose any expiry/cancellation policy explicitly, never chase the limit upward.

Add all-in friction dollars and percent, net payoff, hold horizon and same-underlying portfolio exposure to the opportunity report. Evaluate lower-friction instruments/contract expressions at equal risk as research. Do not add a hard friction rejection threshold from one trade. Six new entries expanded held exposure to~61% of equity without meaningful marked gain today; report aggregate planned/stress risk and concentration before proposing more size.

### S21-05 — stock quote provenance is absent (observed evidence gap, P2 shared owner)

PL/IONQ/VKTX card fill diagnostics have sourceTs0; the VKTX exit receipt has empty source and null sourceAt while receivedAt is populated. Receive freshness is not independent source-age proof. This does not prove these fills were stale or bad.

Carry provider/source timestamp where supplied through feed/cache/entry/exit evidence; where unavailable label receipt-age-only and unknown source age explicitly. Keep decision and fill evidence separate. Acceptance: missing source timestamp never becomes a claimed source timestamp; provider timestamps survive through receipt; an old source observation newly received stays old. Coordinate shared quote changes; don't globally disable share trading as an incidental diagnostic change.

### S21-06 — intake cost dominates, and new knowledge can perpetuate that cost (economics, P1 plan)

The would-skip portion is$17.47, not the entire$92.07 intake expense. Do not promise the five-session filter will solve profitability. Existing note inventory includes420 MuggZone source rows,126 tt,107 general,102 ab (nonsuperseded/nondeleted; expiry not screened by this count). This is not proof they are all injected or useless. Measure actual supplied context tokens, read tools and useful management/new-entry/deferred actions per source/class before changing retention.

Use captured cases now to prepare the already-agreed cheaper-intake evaluation and compact-context comparison: source/schema/history/knowledge token contribution, redundant retrieval, completed management actions, cost per useful action, and missing evidence. Compare full context on identical inputs; keep mixed/correction/protective cases. Preserve pending-vs-operative rules and reliance-vs-supply tracking. Do not bulk delete notes or activate a cheaper model/route without the existing evaluation approval. Put a concrete study budget and readiness count in the single packet; no paid calls in this review. Retain the original five-session D1 boundary.

### S21-07 — recovery still has two observed holes (P2)

Trading-floor digest run10d44367b76b42bd8f22b7c3d15a2a8e failed at17:14 ET: input21199, output2000, stop=max_tokens, invalid/truncated JSON. `digest.py` records truncation but has no bounded repair before failure. Reuse the established typed final-answer/repair contract with a bounded budget and no duplicate knowledge writes. Preserve failure metadata and partial paid usage; do not simply increase every call's token cap. Test truncation then success, terminal truncation and cancellation.

MK-alpha-trades extraction failed twice on provider529 overload. The opportunity census begins from extracted signals; it cannot establish that this raw message contained no opportunity. The desk calls it an Alpha Report/context source, which may be correct, but extraction failure is not proof of no actionable content. Add raw-message-to-signal coverage: received, extracted, intentionally non-actionable, failed/unclassified, recovered and linked dispositions. Provide bounded idempotent retry/manual replay for transient failures, with stale-event revalidation and source timestamps. Never create an old trade blindly after recovery. Don't label this a missed winner.

### S21-08 — source evidence must carry its research limitations (P2)

Today's IONQ rationale cites neal's immediate book +$2.7k as support. The economics report explicitly says shadow books have execution/attribution limitations and are not valid controls. This is a hypothesis about influence, not proof that neal's particular book is corrupt. Audit the `get_source_stats` output and injected source notes for book kind, fee parity, quarantine/unallocated sells, completed episodes and sample size. Ensure invalid books cannot become positive trust evidence or operative lessons. NeverTriggered is not a losing trade. No source promotion/demotion based on this one day.

## Execution order, ownership and guardrails

1. Tips: S21-01/02 and S21-07 confirmed corrections; add the complete exit/cost evidence from03/04. Shared quote owner:05. Use focused tests and normal coordinated deployment; preserve all stops, risk limits and approvals.
2. Tips: prepare target-execution and cost-routing/model proposals with frozen controls, no activation; report portfolio risk/concentration and source-evidence validity alongside them. Do not defer building evidence until Friday, but do not prematurely enforce D1.
3. Return one package: evidence-linked findings, code/commit/test status, applied changes versus proposed policy, exact current economics with cutoff, unresolved coverage, and one decision table. Do not silently apply stop/overnight/model/source/risk changes. No general rewrite, broad test sweep or revived cache pilot.

## Verification and scope limits

`test_sep21_economics_review.py` + existing payoff-feasibility and review-gate files: **4 failed,23 passed in0.78s**. Failures reproduce fee wiring, contract/horizon wiring, unmatched observation handling and truncated human candidate export. Cases use scripted/fake collaborators and no paid calls. Copy in `reviews/kfin-final-regressions/test_sep21_economics_review.py`.

No claim of full incident-free operation, guaranteed missed profit, stable expectancy or a complete provider invoice. Shared deployment and unrelated desk changes were not audited. The full accounting day and five-session sample have not finished. Today supplies one session of evidence, but it is enough to fix the confirmed measurement defects and identify concrete execution/cost work.
