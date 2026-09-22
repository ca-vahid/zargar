# Tips intake coverage (raw message -> signal) since 2026-09-21

Every received message ends in ONE class. A failed extraction is not proof the message held no opportunity, and it is not a missed winner either: it is an unclassified message until it is recovered or a human reads it. Replay is bounded (2 attempts per message in total) and idempotent; a replayed message re-enters the ordinary intake with its own stated time, so an old tip is replayed on history, never traded.

| source | received | extracted (signals) | extracted (no signal) | pending | failed | recovered | refused/ignored |
|---|---:|---:|---:|---:|---:|---:|---:|
| MK-alpha-trades | 1 | 0 | 0 | 0 | 1 | 0 | 0 |
| 🌟｜ab | 28 | 15 | 13 | 0 | 0 | 0 | 0 |
| 🌟｜common-stock | 8 | 4 | 4 | 0 | 0 | 0 | 0 |
| 🌟｜eva | 11 | 8 | 3 | 0 | 0 | 0 | 0 |
| 🌟｜giul-heatseeker | 2 | 2 | 0 | 0 | 0 | 0 | 0 |
| 🌟｜jon-and-kian | 1 | 1 | 0 | 0 | 0 | 0 | 0 |
| 🌟｜muggzone-options | 85 | 25 | 60 | 0 | 0 | 0 | 0 |
| 🌟｜neal | 6 | 4 | 2 | 0 | 0 | 0 | 0 |
| 🌟｜tt | 21 | 7 | 14 | 0 | 0 | 0 | 0 |
| **all** | 163 | 66 | 96 | 0 | 1 | 0 | 0 |

## Failed or pending messages (1) - each needs a recovery, a replay or a human read

| received (UTC) | source | id | class | retries | replayable | error | preview |
|---|---|---|---|---:|---|---|---|
| 09-21 12:32 | MK-alpha-trades | 85eb3bb1 | failed | 1 | yes | - | discord: MeetKevin |

Replay: `python -m zargar.tools.tip_intake_replay --content <id>` (journaled, bounded, stale content re-verified).
