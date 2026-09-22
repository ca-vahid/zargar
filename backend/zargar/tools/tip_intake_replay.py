"""Bounded manual replay of ONE failed raw message through the running app (S21-07, 2026-09-21 review).

    python -m zargar.tools.tip_intake_replay --content <raw_content id> [--reason "..."]

Calls `POST /api/tip/intake/replay/{id}` with a minted session: at most two attempts per message in total, journaled
(`TipIntakeReplayed`), and the message re-enters the ordinary intake - stale content is replayed on history, never traded.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--content", required=True)
    ap.add_argument("--reason", default="manual replay after a transient extraction failure")
    ap.add_argument("--api", default="http://127.0.0.1:8420")
    a = ap.parse_args()
    import httpx
    tok = subprocess.run([sys.executable, "-m", "zargar.tools.mint_session"], capture_output=True, text=True).stdout.strip().splitlines()[-1]
    r = httpx.post(f"{a.api}/api/tip/intake/replay/{a.content}", json={"reason": a.reason},
                   headers={"Authorization": f"Bearer {tok}"}, timeout=180)
    print(r.status_code, json.dumps(r.json(), default=str)[:1500])
    return 0 if r.status_code == 200 else 1


if __name__ == "__main__":
    sys.exit(main())
