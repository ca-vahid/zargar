"""Historical-tip experiment CLI (KNOWLEDGE plan Phase 2) — drives the RUNNING
app's API (the engine, feed and analyst live there; this tool never opens its
own engine).

    python -m zargar.tools.tip_experiment run    --batch b1 --sample 20 --seed 7 --since 2026-06-01
    python -m zargar.tools.tip_experiment status --batch b1
    python -m zargar.tools.tip_experiment review --batch b1

`run` starts the batch and (with --watch, default on) polls progress until it
finishes, then prints the per-item table. Everything is out-of-band: replayed +
appraised, never traded (see tests/test_tip_experiment.py).
"""
import argparse
import asyncio
import secrets
import sys
import time

import httpx
import jwt

from zargar.config import AppConfig
from zargar.tools.mint_session import _secret


def _token(config: AppConfig) -> str:
    allowed = [e.strip().lower() for e in config.google_allowed_emails.split(",") if e.strip()]
    email = allowed[0] if allowed else "local@tooling"
    now = int(time.time())
    return jwt.encode({"sub": email, "name": "tip-experiment", "provider": "google",
                       "iat": now, "exp": now + 4 * 3600, "sid": secrets.token_hex(8)},
                      asyncio.run(_secret(config)), algorithm="HS256")


def _print_status(st: dict) -> None:
    prog = st.get("progress")
    head = f"batch {st['batch']}: " + ("RUNNING" if st.get("running") else "done")
    if prog:
        head += f" · {prog['done']}/{prog['total']} messages"
    head += f" · {st.get('messagesProcessed', 0)} processed · {len(st.get('signals', []))} signal(s)"
    print(head)
    for s in st.get("signals", []):
        replay = (f"replay {s['replayOutcome']} R={s['replayR']}" if s.get("replayOk")
                  else "no replay")
        print(f"  {s['ticker']:<6} [{s['status']:<9}] {s.get('statedAt') or '':<20} "
              f"{replay:<28} analyst={s.get('analystVerdict') or '—'} "
              f"sig={str(s['signalId'])[:8]} run={str(s.get('analystRunId') or '')[:8]}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", choices=["run", "status", "review"])
    ap.add_argument("--batch", required=True)
    ap.add_argument("--sample", type=int, default=20)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--since", default="")
    ap.add_argument("--channels", nargs="*", default=[])
    ap.add_argument("--api", default="http://127.0.0.1:8420")
    ap.add_argument("--no-watch", action="store_true",
                    help="run: start the batch and exit instead of polling")
    a = ap.parse_args()

    headers = {"Authorization": f"Bearer {_token(AppConfig())}"}
    with httpx.Client(base_url=a.api, headers=headers, timeout=180) as http:
        if a.cmd == "run":
            r = http.post("/api/tip/experiment/run",
                          json={"batch": a.batch, "sample": a.sample, "seed": a.seed,
                                "since": a.since, "channels": a.channels})
            if r.status_code != 200:
                sys.exit(f"start failed ({r.status_code}): {r.text}")
            print(f"batch {a.batch} started: {r.json().get('sampled')} message(s) sampled "
                  f"(seed {a.seed}, since {a.since or 'last 90d'})")
            if a.no_watch:
                return
            while True:
                time.sleep(15)
                st = http.get(f"/api/tip/experiment/{a.batch}").json()
                prog = st.get("progress") or {}
                print(f"  … {prog.get('done', '?')}/{prog.get('total', '?')} "
                      f"({len(st.get('signals', []))} signal(s) so far)")
                if not st.get("running"):
                    _print_status(st)
                    print(f"\nnext: python -m zargar.tools.tip_experiment review --batch {a.batch}")
                    return
        elif a.cmd == "status":
            _print_status(http.get(f"/api/tip/experiment/{a.batch}").json())
        else:  # review
            r = http.post(f"/api/tip/experiment/{a.batch}/review", timeout=600)
            if r.status_code != 200:
                sys.exit(f"review failed ({r.status_code}): {r.text}")
            out = r.json()
            print(f"review run {out.get('runId')} over {out.get('items')} item(s):\n")
            print(out.get("summary", ""))


if __name__ == "__main__":
    main()
