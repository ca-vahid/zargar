"""Tips five-session checkpoint status (S21-02, 2026-09-21 review) - the durable owner's tooling.

The scheduled `scripts/tips-five-session.ps1` used to count ANY weekday decision as an observed session, ignore native
exit codes, cut its reports at inconsistent dates and could write READY beside a failed report. This module is the one
place that decides, and it is testable without a scheduler:

* an OBSERVED session is a COMPLETED accounting day (04:00 ET -> 04:00 ET, so today's day never counts) on which the
  relevance filter journaled `mode=observe` decisions; a weekday in the window with none is a GAP, printed for a human;
* ONE cutoff (`until` = the last completed accounting day) is used for the count AND for every report command;
* the gate must be in `observe` for the day to count as an observe session at all (any other mode = INVALID);
* every report command's exit code is checked; a failure anywhere makes the publication FAILED, never READY;
* STATUS.json is written atomically (tmp + replace) with READY / NOT-YET / INCOMPLETE / FAILED / INVALID.

Read-only on the database; writes only inside `out_dir`.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import subprocess
import sys
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
VERSION = "checkpoint-status-v2"


def accounting_day(ts: dt.datetime) -> dt.date:
    """04:00 ET anchor: everything before 04:00 ET belongs to the previous day."""
    return (ts.astimezone(ET) - dt.timedelta(hours=4)).date()


def last_completed_day(now: dt.datetime) -> dt.date:
    """The last accounting day whose 03:59 ET mark has passed."""
    return accounting_day(now) - dt.timedelta(days=1)


def weekdays_between(start: dt.date, end: dt.date) -> list[dt.date]:
    out, d = [], start
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += dt.timedelta(days=1)
    return out


def compute_status(*, decisions: list[dict], since: dt.date, now: dt.datetime, need: int, gate_mode: str | None) -> dict:
    """Pure: `decisions` = [{ts, mode}] of TipReviewGate events since `since`. Returns the observation status with its
    coverage and gaps; never touches a file."""
    until = last_completed_day(now)
    by_day: dict[dt.date, dict] = {}
    for d in decisions:
        day = accounting_day(d["ts"])
        if day < since or day > until:
            continue
        rec = by_day.setdefault(day, {"observe": 0, "other": 0})
        rec["observe" if str(d.get("mode") or "") == "observe" else "other"] += 1
    observed = sorted(day for day, rec in by_day.items() if rec["observe"] > 0 and rec["other"] == 0 and day.weekday() < 5)
    mixed = sorted(day for day, rec in by_day.items() if rec["other"] > 0)
    gaps = [d for d in weekdays_between(since, until) if d not in by_day]
    today_partial = accounting_day(now)
    if gate_mode is not None and gate_mode != "observe":
        state = "INVALID"
    elif mixed:
        state = "INVALID"
    elif len(observed) >= need:
        state = "READY"
    else:
        state = "NOT-YET"
    return {"version": VERSION, "state": state, "since": since.isoformat(), "until": until.isoformat(),
            "need": need, "observedSessions": len(observed), "observedDays": [d.isoformat() for d in observed],
            "gaps": [d.isoformat() for d in gaps], "mixedModeDays": [d.isoformat() for d in mixed],
            "gateMode": gate_mode, "partialDayExcluded": today_partial.isoformat(),
            "decisionsPerDay": {d.isoformat(): rec for d, rec in sorted(by_day.items())},
            "note": ("an observed session is a COMPLETED accounting day with observe decisions; the current day never counts; "
                     "gaps are weekdays without decisions and need a human explanation (holiday / outage)")}


def run_reports(commands: list[tuple[str, list[str]]], *, out_dir: str, runner=subprocess.run) -> dict:
    """Run each (name, argv) command, capture stdout into <out_dir>/<name>, and record the exit code. A non-zero exit
    or a raised error marks the report failed; the partial output is kept under a .failed suffix, never as the report."""
    results: dict = {}
    for name, argv in commands:
        target = os.path.join(out_dir, name)
        try:
            proc = runner(argv, capture_output=True, text=True, encoding="utf-8", errors="replace")
            code = int(proc.returncode)
            out = proc.stdout or ""
            err = (proc.stderr or "")[-2000:]
        except Exception as exc:                          # noqa: BLE001 - a launcher failure is a failed report
            code, out, err = 127, "", f"{type(exc).__name__}: {exc}"
        if code == 0 and out.strip():
            _atomic_write(target, out)
            results[name] = {"exit": 0, "bytes": len(out)}
        else:
            _atomic_write(target + ".failed", out + ("\n\n[stderr]\n" + err if err else ""))
            results[name] = {"exit": code, "bytes": len(out), "error": err[-300:] or ("empty output" if code == 0 else "")}
    return results


def _atomic_write(path: str, text: str) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)


def publish(status: dict, reports: dict, *, out_dir: str) -> dict:
    failed = {k: v for k, v in reports.items() if v.get("exit") != 0}
    final = dict(status)
    final["reports"] = reports
    if failed:
        final["state"] = "FAILED"
        final["failedReports"] = sorted(failed)
    elif status["state"] == "READY" and status.get("gaps"):
        final["state"] = "INCOMPLETE"                      # enough days, but the window has holes a human must explain
    final["generatedAt"] = dt.datetime.now(dt.timezone.utc).isoformat()
    final["next"] = ("Tips desk writes ONE report from these files (FIVE-SESSION-CHECKPOINT.md); READY means five completed "
                     "observe sessions with no gaps and every report produced; nothing is enforced by this status.")
    _atomic_write(os.path.join(out_dir, "STATUS.json"), json.dumps(final, indent=1))
    return final


async def _load(db: str, since: dt.date) -> tuple[list[dict], str | None]:
    import asyncpg
    c = await asyncpg.connect(db, server_settings={"default_transaction_read_only": "on"})
    try:
        rows = await c.fetch("select ts, payload->>'mode' as mode from events where type='TipReviewGate' and ts >= $1",
                             dt.datetime.combine(since, dt.time(4, 0), tzinfo=ET))
        gate = await c.fetchval("select value from settings where key='techniques.tip.review_gate'")
    finally:
        await c.close()
    mode = None
    if gate is not None:
        v = json.loads(gate) if isinstance(gate, str) else gate
        mode = str(v.get("v")) if isinstance(v, dict) and "v" in v else str(v)
    else:                                                  # no override row: the code default is the effective mode
        try:
            from ..settings_service import DEFAULTS
            mode = str(DEFAULTS.get("techniques.tip.review_gate") or "")
        except Exception:                                  # noqa: BLE001 - unknown stays unknown
            mode = None
    return [{"ts": r["ts"], "mode": r["mode"]} for r in rows], mode


def report_commands(python: str, *, since: str, until: str) -> list[tuple[str, list[str]]]:
    return [("review-gate-prospective.md", [python, "-m", "zargar.tools.tip_review_gate_eval", "--since", since, "--until", until, "--prospective"]),
            ("scorecard.md", [python, "-m", "zargar.tools.tip_scorecard", "--since", since, "--until", until]),
            ("opportunity-dispositions.md", [python, "-m", "zargar.tools.tip_outcomes", "--dispositions", "--since", since]),
            ("intake-coverage.md", [python, "-m", "zargar.tools.tip_outcomes", "--coverage", "--since", since]),
            ("review-model-cases.md", [python, "-m", "zargar.tools.tip_review_gate_eval", "--since", since, "--model-plan"])]


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="postgresql://zargar:zargar@127.0.0.1:5433/zargar")
    ap.add_argument("--since", default="2026-09-21")
    ap.add_argument("--need", type=int, default=5)
    ap.add_argument("--out", default=r"C:\ProgramData\Zargar\tips-five-session")
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--status-only", action="store_true", help="compute and print the status; run no report")
    a = ap.parse_args()
    since = dt.date.fromisoformat(a.since)
    decisions, gate = await _load(a.db, since)
    status = compute_status(decisions=decisions, since=since, now=dt.datetime.now(dt.timezone.utc), need=a.need, gate_mode=gate)
    if a.status_only:
        print(json.dumps(status, indent=1))
        return 0
    os.makedirs(a.out, exist_ok=True)
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    reports = run_reports(report_commands(a.python, since=a.since, until=status["until"]), out_dir=a.out)
    final = publish(status, reports, out_dir=a.out)
    print(f"tips five-session: {final['state']} ({final['observedSessions']} of {a.need} observed sessions, through {final['until']}; "
          f"gaps {final['gaps'] or 'none'}; reports {', '.join(f'{k}={v['exit']}' for k, v in reports.items())}) -> {a.out}")
    return 0 if final["state"] in ("READY", "NOT-YET", "INCOMPLETE") else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
