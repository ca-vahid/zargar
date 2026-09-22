# EM Experimental: which build ran each session

The experiment's frozen bundle is a set of SETTINGS, not a build. The runtime underneath it changes whenever any
desk deploys, and four desks share this host. A difference between sessions can therefore come from a build
change rather than from the method, so every session's build is recorded here and no session is compared with
another without checking this table first.

None of these deploys contained EM code. That is worth stating plainly and is also not a guarantee of
irrelevance: shared engine paths - the runner, the quote feed, the recorders - are used by EM whoever changed
them.

| Session (ET) | Version | Build | Deployed by / when | EM result that session |
|---|---|---|---|---|
| 2026-09-19 launch | 0.8.26 | `8645a612` | EM desk, 2026-09-19 | book created, no trading |
| **2026-09-21** | **0.8.28** | **`7ee5ad2a`** | in place before the session | experiment 13 fired, **0 filled** (host clock 10.5 s behind); baseline +201.70 |
| overnight | 0.8.30 | `11fb05f7` | Tips desk, 2026-09-22 01:00 ET, market closed | EM's 124 armed plans verified intact per book after the restart |
| ? to 09:20 ET | 0.8.31 | `3ac3dac7` | **unidentified desk, between 01:00 and 09:20 ET on a session day** | this is the build today's session actually ran on |
| **2026-09-22** | **0.8.31** | **`3ac3dac7`** | as above | experiment 18 fired, **6 filled**, 6 stops, −269.07; baseline 9 fired, 3 filled, 3 stops, −174.54 |
| after the close | 0.8.32 | `63613751` | Tips desk, 2026-09-22 16:15 ET, market closed | EM flat and disarmed; nothing of ours needed to survive it |

## What this table is for

**2026-09-21 is operationally impaired and not evaluable.** The host clock was 10.5 s behind, every venue
timestamp read as future-dated, and the experimental book could not submit. The build is not implicated.

**2026-09-22 is the first session where both books actually traded.** The clock repair is confirmed by the
experimental book placing 12 orders and taking 6 fills, with the admission gate refusing one entry rather than
all of them. The fault is closed by behaviour, not by argument.

**One thing to carry forward rather than conclude.** Nine of nine positions across both books exited on stops
that day, several within minutes, and both books lost. One session establishes nothing about the method, and
no threshold was changed in response. What it does establish is that the measurement path now works, which is
the only claim this table supports.

**A deploy landed on a session day between 01:00 and 09:20 ET and I could not identify its owner from the
journal.** Deploys are not journalled as events, so the lineage above is assembled from health readings and
desk messages rather than from a durable record. That is a gap: a shared host where four desks deploy should
be able to answer "what was running when this trade happened" from its own data. Recorded here rather than
fixed, because it belongs to the platform rather than to this desk.
