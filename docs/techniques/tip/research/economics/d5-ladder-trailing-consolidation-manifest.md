# D5 - consolidation manifest: duplicate pending ladder/trailing-coherence proposals (PROPOSAL, not applied)

Manifest hash `30c9891efc712b49` - 6 pending proposals restate one clause. Knowledge maintenance is propose-only: this file is the reviewed candidate and its reversible mapping. Nothing was superseded, deleted or promoted.

## Candidate (born pending review)

> RULE (adoption geometry - LADDER/TRAILING COHERENCE; CANDIDATE consolidated 2026-09-19 from 6 pending proposals, NOT operative until a human approves it): an exit policy must be internally reachable at the size actually held. (1) REACHABILITY - a trailing trigger (trailing.after_r) must be reachable by the ladder: it may not sit beyond the last target, and a ladder whose final rung exits 100% leaves nothing to trail. (2) INTEGER LADDER - fractions are judged on whole contracts: at 1-2 lots a multi-rung ladder collapses to the rungs that round to at least one contract; say which rung is the full exit and do not plan a runner that rounds to zero. (3) TRAIL SANITY - a structure trail may only tighten, and only after the trigger it names has been reached. (4) TIME BOX - a hold cap the policy states must be one the manager can enforce (sessions or DTE), not prose. Evidence: the dated cases cited by the source proposals (listed in the manifest with their ids and revisions). This text REPLACES nothing by itself.

## Members (retained: ids, revisions, text hashes, cited cases)

| id | rev | created | chars | text sha | dated cases cited | first line |
|---|---:|---|---:|---|---|---|
| `d8e38ea9` | 1 | 2026-09-15 | 1538 | `bc7c2352738164f5` | - | RULE refinement — adoption geometry, clause 3 (TARGET WIDTH), new LADDER/TRAILING COHERENCE clause: a policy's trailing trigger (trailing.after_r) mus |
| `907688c7` | 1 | 2026-09-17 | 1886 | `6a1a06389e704b80` | MSTR 9/04, ORCL 9/10, PURR 9/10 | RULE refinement — adoption geometry, LADDER/TRAILING COHERENCE clause (4th dated case; consolidates with MSTR 9/04, ORCL 9/10, PURR 9/10 rather than d |
| `d08fb7a0` | 1 | 2026-09-17 | 2596 | `574baa76f9d6bf7e` | CCXI 9/09, MRVL 9/04, MSTR 9/04, MU 9/04, ORCL 9/10, PURR 9/10 | RULE refinement — adoption geometry, LADDER/TRAILING COHERENCE + TRAIL-SANITY + a new TIME-BOX ENFORCEMENT clause (5th dated case; consolidates with M |
| `cf07b1be` | 1 | 2026-09-18 | 1810 | `85057eedb3f61235` | MRVL 9/04, MSTR 9/04, ORCL 9/10, PURR 9/10, TSLA 9/03 | RULE refinement — adoption geometry, LADDER/TRAILING COHERENCE clause (6th dated case; consolidates with MSTR 9/04, ORCL 9/10, PURR 9/10, MRVL 9/04, T |
| `8dfdf66a` | 1 | 2026-09-18 | 2229 | `2da94cbbc8277ac1` | MRVL 9/04, MSTR 9/04, MU 9/11, ORCL 9/10, PURR 9/10, TSLA 9/03 | RULE refinement — adoption geometry, LADDER/TRAILING COHERENCE clause (7th dated case; consolidates with MSTR 9/04, ORCL 9/10, PURR 9/10, MRVL 9/04, T |
| `89090046` | 1 | 2026-09-18 | 1847 | `fea0cba168550602` | AAPL 9/03, DAL 11/20, MRVL 9/04, TSLA 9/03 | RULE (new, sits with the LADDER/TRAILING COHERENCE family — the INTEGER-LADDER FEASIBILITY clause; consolidates the "runner rounded away" evidence fro |

## Apply path

human decision first. A DISPUTED/pending row is never superseded by any writer: each member must be resolved by a human (Knowledge tab) before the audited batch path (`apply_knowledge_batch`, revision-checked, receipt in `tip_knowledge_batches`) can supersede it at the recorded revision. Nothing is deleted; superseded rows stay with their revisions.

## Rollback

supersede the candidate with `expired:rollback` and restore `superseded_by = NULL` on each member ONLY at its recorded revision (the same revision-transition rollback as the 2026-09-14 consolidation).

## Not a promotion

approval of the candidate as OPERATIVE policy is a separate human decision; consolidation alone changes no operative rule.
