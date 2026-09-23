# EM preparation reconciliation - 2026-09-22 (prep-reconcile-v1)

Three different counts, never conflated: symbols are what the session has, runs are every attempt, requests are what was billable.

- **Unique symbols with a usable verdict: 107** -> {'no_setup': 74, 'setup': 33}
- Runs of every kind: 108 -> {'done': 108}
- Symbols with more than one run: 1 -> {'INTC': 2}
- Symbols actually REVIEWED more than once (paid twice): 1 -> {'INTC': 2}
- Model requests counted: 511; **unresolved: 0**
- Estimated cost: **61.6799 USD** (current price card; an ESTIMATE, never an invoice, never netted into trading P&L)

Arms by book:

- baseline: {'armed': 33}
- experiment: {'armed': 91}

an unresolved request asked a model and recorded no completion: killed, failed or still running. It is not free and it is not an invoice line either

