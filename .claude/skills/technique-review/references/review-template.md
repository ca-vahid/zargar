# Review write-up template

Use this shape when presenting the review to the user (before/with persisting it).
Keep it short; the table is the substance.

```
## Run <id> — <SYMBOL> <tf> · as of <date time ET> · process <processVersion>

**Verdict:** <setup (type) | no_setup> · confidence <x> · grounded <yes/no>
**Plan:** entry <p> (<basis>) · stop <p> · targets <a/b/c> · R:R <x>        ← if any
**Outcome:** <analysis: tp3 +2.4R (MFE 3.1R / MAE 0.2R) | candidate: stopped −1.0R | not_filled>
**Expected (user):** <setup support_bounce at ~101.20 | no setup | …>

| stage | saw | decided | evidence | rules |
|---|---|---|---|---|
| data | 1m ×780, 5m, 1h; as_of 14:10 | — | ok | — |
| detectors | S 101.20 ×3, R 104.00 ×2; vol 1.3× | candidate bounce, valid, R:R 4.1 | chart agrees | T1.2 T2.9 R2 |
| facts→prompt | … | … | … | … |
| pass 1 context | … | … | … | … |
| pass 2 pattern | … | … | … | … |
| pass 3 entry | … | **no_setup**: "R3.1 volume" | FACTS volume.relative 1.3, belowFloor false → reason unsupported | R3.1 |
| critic | skipped (no setup) | — | — | — |
| grounding | 3/3 passed | accepted | — | — |
| outcome | candidate filled, ran to TP3 | — | the declined trade worked | — |

**First wrong turn:** pass 3 — cited R3.1 against FACTS.
**review_verdict:** wrong_verdict · **root_cause_stage:** pass_entry

**Fix plan**
1. `schemas.SYSTEM_PROMPT`: "R3.1 applies only when FACTS volume.belowFloor is true" — test: replay <id> → setup.
2. `grounding.ground_analysis`: no_setup reason citing R3.1 requires volume.belowFloor — test in `test_technique_api.py`.

**Lesson for docs/techniques/enhanced-market/PIPELINE-PLAN.md:** <one line>
```

Then:

```bash
cd backend && .venv/Scripts/python.exe -m zargar.tools.technique_review review <id> \
  --verdict wrong_verdict --root-cause pass_entry --expected setup --expected-type support_bounce \
  --expected-entry 101.20 --expected-stop 100.80 --expectation "<user's words>" \
  --note "<First wrong turn + evidence, 1-3 sentences>" \
  --action "<fix 1>" --action "<fix 2>" --reviewer claude
```
