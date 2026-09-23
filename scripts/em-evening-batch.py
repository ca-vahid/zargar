"""EM evening batch (em-evening-batch-v1, 2026-09-22): the paid model review that prepares the BASELINE book.

The recipe that ran by hand as one-off scripts on 2026-09-21 and 09-22, made recurring and versioned:

  * discovers the next session's graded sheet itself (the engine builds it at 16:15 ET, `technique.sheet.auto`);
  * RESUMES: a symbol that already has a finished promote run for that session is never paid for twice;
  * ONE read in flight (the engine's vision reads are what consume memory on this host) and ONE batch at a time
    (a lock file; a second start exits without doing anything);
  * honours `techniques.enhanced_market.paid_review` - the switch the EM stop rule turns off. Off = no paid read
    and no baseline arm; the rules-only experimental book prepares itself inside the engine and is untouched;
  * arms setups into the baseline book only; a symbol already held IN THE BASELINE BOOK is skipped - the
    experimental book's plans never block the baseline.

It reads secrets from the runtime .env and never prints them. Usage (the scheduled task passes the log path):
    python scripts/em-evening-batch.py [log path; default C:/ProgramData/Zargar/logs/em-evening-batch-<today>.log]
"""
import asyncio
import collections
import datetime as dt
import io
import json
import os
import re
import sys
import time
from zoneinfo import ZoneInfo

import asyncpg
import httpx

VERSION = "em-evening-batch-v1"
RUNTIME_ENV = r"C:\Cursor\zargar\backend\.env"
BASE = "http://127.0.0.1:8420"
EM_BOOK = "045d8c35b3f149628ea001ae90a58edb"
MAX_INFLIGHT = 1
WAIT_S = 5400
LOCK = r"C:\ProgramData\Zargar\em-evening-batch.lock"
ET = ZoneInfo("America/New_York")

env = io.open(RUNTIME_ENV, encoding="utf-8").read()
TOKEN = re.search(r"^ZARGAR_AUTH_TOKEN=(.+)$", env, re.M).group(1).strip()
DB = re.search(r"^ZARGAR_DATABASE_URL=(.+)$", env, re.M).group(1).strip().strip('"').replace("postgresql+asyncpg://", "postgresql://")
H = {"Authorization": f"Bearer {TOKEN}"}
# default log = one file per evening (local date), which the after-arming check reads to tell "paid review off" from
# "the batch failed"
LOG = io.open(sys.argv[1] if len(sys.argv) > 1 else rf"C:\ProgramData\Zargar\logs\em-evening-batch-{time.strftime('%Y-%m-%d')}.log",
              "a", encoding="utf-8")


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, file=LOG, flush=True)


def take_lock() -> bool:
    """One batch at a time. A lock older than 12 h is a dead batch's, and is taken over."""
    try:
        if os.path.exists(LOCK) and time.time() - os.path.getmtime(LOCK) < 12 * 3600:
            return False
        with open(LOCK, "w", encoding="utf-8") as f:
            f.write(f"{os.getpid()} {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        return True
    except OSError:
        return False


async def read_state() -> dict:
    """Read-only: the next session's sheet, the paid-review switch, and what is already reviewed for that session."""
    c = await asyncpg.connect(DB)
    try:
        await c.execute("set default_transaction_read_only = on")
        # the NEXT session: after today in ET, or today while its open is still ahead (a batch resumed after
        # midnight ET prepares the session that opens this morning - 2026-09-22 found nothing at 00:08 ET)
        now_et = dt.datetime.now(ET)
        today = now_et.date().isoformat()
        floor = today if (now_et.hour, now_et.minute) < (9, 30) else None
        sheet = await c.fetchrow(
            "select id, params->>'planFor' as plan_for from technique_sweeps where params->>'kind'='next' and status='done' "
            "and (params->>'planFor' > $1 or params->>'planFor' = $2) order by created_at desc limit 1", today, floor or "")
        raw = await c.fetchval("select value from settings where key='techniques.enhanced_market.paid_review'")
        paid = True if raw is None else bool((json.loads(raw) if isinstance(raw, str) else raw).get("v", True))
        have = {}
        if sheet:
            rows = await c.fetch(
                "select distinct on (symbol) symbol, id from technique_runs where trigger='promote' and status='done' "
                "and result->'plan'->>'planFor'=$1 and result->'analysis'->>'verdict' is not null "
                "order by symbol, created_at desc", sheet["plan_for"])
            have = {r["symbol"]: r["id"] for r in rows}
        return {"sheet": sheet["id"] if sheet else None, "planFor": sheet["plan_for"] if sheet else None,
                "paid": paid, "have": have}
    finally:
        await c.close()


def baseline(a: dict) -> bool:
    return ((a.get("technique") or "enhanced_market") == "enhanced_market"
            and str((a.get("config") or {}).get("portfolioId") or "") == EM_BOOK and a.get("status") in ("armed", "paused"))


async def main():
    log(f"{VERSION} start")
    if not take_lock():
        log("another batch holds the lock - this start does nothing")
        return
    try:
        s = await read_state()
        if not s["sheet"]:
            log("no finished sheet for the next session yet - nothing to do")
            return
        if not s["paid"]:
            log(f"paid review is OFF (techniques.enhanced_market.paid_review) - no read, no baseline arm for {s['planFor']}")
            return
        have = s["have"]
        log(f"session {s['planFor']} sheet {s['sheet']}: {len(have)} symbol(s) already reviewed - not paid for again")
        async with httpx.AsyncClient(base_url=BASE, headers=H, timeout=120) as c:
            h = (await c.get("/api/health")).json()
            log("engine:", {k: h.get(k) for k in ("ok", "started", "version")})
            if not h.get("started"):
                log("engine not started - abort")
                return
            sw = (await c.get(f"/api/technique/walkforward/{s['sheet']}", params={"rows": "true"})).json()
            rows = [r for r in sw.get("rows") or [] if any(t.get("valid") for t in ((r.get("plan") or {}).get("triggers") or []))]
            todo_rows = [r for r in rows if r["symbol"] not in have]
            log(f"step 1: {len(rows)} setup rows, {len(rows) - len(todo_rows)} done, {len(todo_rows)} to read (concurrency {MAX_INFLIGHT})")
            run_ids = dict(have)

            async def wait_room():
                while True:
                    try:
                        hh = (await c.get("/api/health")).json()
                        if int((hh.get("local") or {}).get("techniqueRunning") or 0) < MAX_INFLIGHT:
                            return
                    except Exception:  # noqa: BLE001 - a transient health miss only delays
                        pass
                    await asyncio.sleep(10)

            for r in todo_rows:                                    # sequential by design: one paid read at a time
                await wait_room()
                resp = None
                for _ in range(3):
                    try:
                        resp = await c.post(f"/api/technique/walkforward/{s['sheet']}/promote",
                                            json={"symbol": r["symbol"], "session": r["session"], "withVision": True, "wait": False})
                    except httpx.HTTPError as exc:
                        log("  promote transport error", r["symbol"], type(exc).__name__)
                        await asyncio.sleep(15)
                        continue
                    if resp.status_code < 500:
                        break
                    log("  promote", r["symbol"], resp.status_code, "- retrying")
                    await asyncio.sleep(15)
                if resp is None or resp.status_code >= 400:
                    log("  promote failed", r["symbol"], resp.status_code if resp is not None else "-")
                    continue
                run_ids[r["symbol"]] = resp.json()["id"]
            pending = {rid for sym, rid in run_ids.items() if sym not in have}
            verdicts = {rid: None for rid in run_ids.values()}
            t0 = time.time()
            while pending and time.time() - t0 < WAIT_S:
                await asyncio.sleep(20)
                for rid in list(pending):
                    run = (await c.get(f"/api/technique/runs/{rid}")).json()
                    if run.get("status") in ("done", "error", "failed") or run.get("error"):
                        pending.discard(rid)
                        verdicts[rid] = run
            for rid in list(verdicts):
                if verdicts[rid] is None:
                    verdicts[rid] = (await c.get(f"/api/technique/runs/{rid}")).json()
            cnt = collections.Counter(((v.get("result") or {}).get("analysis") or {}).get("verdict") or v.get("status")
                                      for v in verdicts.values())
            log("step 1 done:", dict(cnt), "unfinished", len(pending))

            held = {a.get("symbol") for a in (await c.get("/api/technique/armed", params={"slim": "1"})).json() if baseline(a)}
            todo = []
            for rid, run in verdicts.items():
                res = run.get("result") or {}
                if (res.get("analysis") or {}).get("verdict") != "setup":
                    continue
                if not any(t.get("valid") for t in ((res.get("plan") or {}).get("triggers") or [])):
                    continue
                if run.get("symbol") in held:
                    log("  skip", run.get("symbol"), "already held in the baseline book")
                    continue
                todo.append((rid, run.get("symbol")))
            log("step 2: arming", len(todo), "setups into EM Practice")
            ok, fails = 0, []
            for rid, sym in todo:
                resp = await c.post(f"/api/technique/runs/{rid}/arm", json={"portfolioId": EM_BOOK})
                if resp.status_code >= 400:
                    fails.append(f"{sym}: {resp.text[:100]}")
                else:
                    ok += 1
            n = sum(1 for a in (await c.get("/api/technique/armed", params={"slim": "1"})).json() if baseline(a))
            log("step 2 done: armed", ok, "failed", len(fails), "server shows EM Practice armed =", n)
            for f in fails[:15]:
                log("   fail:", f)
        log("DONE")
    finally:
        try:
            os.remove(LOCK)
        except OSError:
            pass


asyncio.run(main())
