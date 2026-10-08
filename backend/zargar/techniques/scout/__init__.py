"""Scout - research-only idea finder (docs/techniques/scout/PLAN.md, 2026-10-07).

P1 (this package today): EDGAR Form 4 ingestion (daily index + quarterly insider data
sets), the Cohen-Malloy-Pomorski routine/opportunistic classifier, the S1 insider-cluster
and S2 earnings-reaction screens, the preregistered gates, and a candidate table written by
a daily job. Scout NEVER places orders and never routes to a broker: nothing in this
package imports the order path outside `desk.py`.

P3 (`desk.py`, `analyst.py`, `books.py`, `entry.py`): masked fact packets judged by two LLM lanes
(filter + explainer), research books on the SIM executor only (shadow kind), the preregistered
10:00-11:30 ET entry-spread rule, managed stops/time exits, after-cost lane accounting and the daily report.
"""
SCREEN_VERSION = "scout-p1-v1"
