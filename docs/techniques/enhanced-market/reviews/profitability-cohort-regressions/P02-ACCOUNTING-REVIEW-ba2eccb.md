# P-02 focused research review at ba2eccb

Scope: frozen `small-position-exit-v1`, the report reducer/assembly, and the actual observation payload. No database, runtime, order, setting, or production-source changes. Three regression cases are in `test_p02_real_payload_and_fee_conservation.py`; the parent reviewer runs them.

The one-of-two accounting and explicit winner opportunity cost are appropriate when fees are uniform and the supplied per-contract production outcomes reconcile. Missing observations stay unknown. These are useful research definitions, not evidence that the alternative is profitable.

## PF-01: Join the actual observations to the declared experiment

At `backend/zargar/tools/em_profitability.py:130`, the reducer requires `disposition=covered`, top-level `bid`, and `observedTs`. The actual producer at `backend/zargar/execution/planrunner.py:674` emits `disposition=observed`, nested `modeled.scorable/coveredQty/bid`, and `observedAt`. Consequently a valid, covered P-02 observation is rejected as absent. The integration regression passes a real `_shadow_capture` result directly into `p02_compare`: the expected alternative is $185.84 versus $195.84 production, including $10 forgone on a winner.

The same P-02 contract chooses the first *covered* bid at or after TP1. The producer records and marks the first rung observation seen even when its contract quote is missing (`planrunner.py:707`). A later covered quote cannot become the selected observation. The second integration regression records a missing-quote first touch and supplies a valid OPRA bid 500 ms later: the subsequent candidate record is suppressed.

Correct the producer/consumer contract together: retain unscorable evidence but keep the candidate eligible until its first qualifying covered observation, or explicitly version a different experiment. Match the selected observation to the entry-order trade instance, exact contract, applicable policy, and observation time within that position's life. Current assembly at `em_profitability.py:224` matches only trigger ID. Do not infer a fill from a contemporaneous quote: the comparison remains a model of the recorded liquidation opportunity.

## PF-02: Preserve actual fees on the unchanged side of the comparison

At `em_profitability.py:201`, the report takes the day's median fee per contract per side. At line 248 it uses that median to rebuild every production contract's realized result, whereas whole-position production net uses actual execution fees. At line 140 it also substitutes the median for the already-paid entry fee of the alternative. These two production totals need not reconcile.

Counterexample exercised through report assembly with an in-memory connection: buy two contracts at $1 with total entry fees $2, sell both at $2 with total exit fees $4. Actual net is $194. An alternative selling its one early contract at the same $2 bid with the same $2 exit fee, retaining the other's actual exit, must still net $194. The implementation observes median fee-side $2, rebuilds each production contract as $96, and reports $192 / delta -$2. The apparent policy loss comes entirely from changing historical fees.

Allocate the actual entry fee and actual retained-exit fee by their filled quantities. Apply the declared hypothetical exit fee only to the hypothetical sale. Require reconstructed production components to sum to the execution-backed production net before reporting a paired delta; otherwise leave the comparison unknown. Keep the existing big-winner case.

This is a bounded correction to profitability measurement. Disabled integration and unchanged baseline trading do not need to wait for a new infrastructure project. P-02 comparisons should not be used for activation until the actual-observation and fee cases pass.
