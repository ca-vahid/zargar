"""Technique run review CLI — the tool the `/technique-review` skill drives.

Talks to Postgres directly (no running server needed) for everything except
`replay`, which needs the live engine + API key and therefore calls the API.

    python -m zargar.tools.technique_review list [--unreviewed] [--wrong] [--outcome X]
                                                [--symbol S] [--limit N] [--json]
    python -m zargar.tools.technique_review show <run_id>
    python -m zargar.tools.technique_review dump <run_id> [--out DIR]
    python -m zargar.tools.technique_review score <run_id> [--horizon N] | --pending
    python -m zargar.tools.technique_review replay-facts <run_id> [--set key=value ...]
    python -m zargar.tools.technique_review review <run_id> --verdict V [--root-cause S]
                                                [--expected setup|no_setup] [--expected-type T]
                                                [--expected-entry P --expected-stop P]
                                                [--expectation "..."] [--note "..."]
                                                [--action "..."]... [--reviewer user|claude]
    python -m zargar.tools.technique_review reviews [<run_id>]
    python -m zargar.tools.technique_review diff <run_a> <run_b>
    python -m zargar.tools.technique_review replay <run_id> [--api URL] [--set key=value ...]
                                                [--no-snapshot] [--note "..."]
    python -m zargar.tools.technique_review taxonomy
    python -m zargar.tools.technique_review plan <symbol> [--as-of YYYY-MM-DD] [--with-vision]
    python -m zargar.tools.technique_review sweep --start D --end D [--symbols A,B] [--structure 1h,30m]
                                                [--trigger 1m] [--include-invalid] [--label L]
    python -m zargar.tools.technique_review sweeps | sweep-report <sweep_id> [--rows]
    python -m zargar.tools.technique_review promote <sweep_id> <symbol> <session>
    python -m zargar.tools.technique_review arm <run_id> | arm-today <symbol> | armed | disarm <run_id>
                                                (through the API — the app must be running)

Output is plain text by default; `--json` prints machine-readable JSON.
Exit code 0 on success, 1 on a user error (bad id / bad value), 2 on a crash.
"""
from __future__ import annotations

import argparse
import asyncio
import dataclasses
import datetime as dt
import json
import os
import sys
from pathlib import Path

from ..config import AppConfig
from ..engine import Engine
from ..technique.bundle import write_bundle
from ..technique.review import REVIEW_VERDICTS, ROOT_CAUSE_STAGES
from ..technique.service import TechniqueService


class Ctx:
    """A TechniqueService over the real DB without starting brokers/feeds."""

    def __init__(self) -> None:
        cfg = AppConfig()
        if os.environ.get("ZARGAR_REVIEW_DATABASE_URL"):
            cfg = AppConfig(database_url=os.environ["ZARGAR_REVIEW_DATABASE_URL"])
        self.config = cfg
        self.engine = Engine(cfg)
        self.svc: TechniqueService | None = None

    async def __aenter__(self) -> "Ctx":
        from ..db import create_all
        from ..technique.chat import ChatService
        await create_all(self.engine.db)
        await self.engine.settings.load()
        svc = TechniqueService(self.engine)
        svc.chat = ChatService(self.engine, svc)
        self.engine.technique = svc
        self.engine.chat = svc.chat
        self.svc = svc
        return self

    async def __aexit__(self, *exc) -> None:
        await self.engine.db.dispose()


def _ts(ms: int | None) -> str:
    if not ms:
        return "live"
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%Y-%m-%d %H:%M")


def _outcome_cell(outs: list[dict]) -> str:
    if not outs:
        return "—"
    pri = next((o for o in outs if o.get("planSource") == "analysis"), None) \
        or next((o for o in outs if o.get("planSource") == "candidate"), None) or outs[0]
    src = {"analysis": "A", "candidate": "C", "market": "M"}.get(pri.get("planSource"), "?")
    if pri.get("status") in ("pending", "unscorable"):
        return f"{src}:{pri['status']}"
    oc = pri.get("outcome") or "path"
    r = pri.get("rMultiple")
    cell = f"{src}:{oc}" + (f" {r:+.2f}R" if r is not None and oc != "not_filled" else "")
    if pri.get("status") == "partial":
        cell += "*"
    return cell


def _print_table(rows: list[dict]) -> None:
    if not rows:
        print("(no runs)")
        return
    cols = [("id", 10), ("when", 16), ("sym", 7), ("tf", 3), ("verdict", 9), ("type", 14), ("conf", 5),
            ("grd", 3), ("outcome", 22), ("review", 22), ("ver", 10), ("trig", 6)]
    print(" ".join(f"{c[0]:<{c[1]}}" for c in cols))
    print(" ".join("-" * c[1] for c in cols))
    for r in rows:
        rev = r.get("lastReview")
        cells = [r["id"][:10], (r.get("createdAt") or "")[:16].replace("T", " "), r.get("symbol", "")[:7],
                 r.get("primaryTf", ""), (r.get("verdict") or r.get("status") or "")[:9],
                 (r.get("setupType") or "")[:14],
                 f"{r['confidence']:.2f}" if r.get("confidence") is not None else "—",
                 {True: "yes", False: "no"}.get(r.get("grounded"), "—"),
                 _outcome_cell(r.get("outcomes") or [])[:22],
                 (f"{rev['reviewVerdict']}" + (f"/{rev['rootCauseStage']}" if rev.get("rootCauseStage") else "")
                  if rev else f"— ({r.get('reviewCount', 0)})")[:22],
                 (r.get("processVersion") or "")[:10], (r.get("trigger") or "")[:6]]
        print(" ".join(f"{str(v):<{c[1]}}" for v, c in zip(cells, cols)))
    print(f"\n{len(rows)} run(s). outcome: A=analysis plan, C=rejected candidate, M=market path only; "
          f"* = partial (more bars to come)")


def _parse_sets(items: list[str] | None) -> dict:
    out: dict = {}
    for it in items or []:
        if "=" not in it:
            raise SystemExit(f"--set expects key=value, got {it!r}")
        k, v = it.split("=", 1)
        k = k.strip()
        v = v.strip()
        try:
            out[k] = json.loads(v)
        except json.JSONDecodeError:
            out[k] = v
    return out


# --- commands ------------------------------------------------------------------------------

async def cmd_list(args) -> int:
    async with Ctx() as c:
        rows = await c.svc.list_runs(
            limit=args.limit, symbol=args.symbol, verdict=args.verdict,
            reviewed=(False if args.unreviewed else (True if args.reviewed else None)),
            outcome=args.outcome,
            review_verdict=("wrong_verdict" if args.wrong and not args.review_verdict else args.review_verdict),
            process_version=args.process_version, trigger=args.trigger)
        if args.wrong and not args.review_verdict:
            # "wrong" = any non-correct review OR a scored analysis/candidate loss
            rows = [r for r in rows if (r.get("lastReview") and r["lastReview"]["reviewVerdict"] != "correct")
                    or any((o.get("rMultiple") or 0) < 0 for o in (r.get("outcomes") or []))]
    if args.json:
        print(json.dumps(rows, indent=1, default=str))
    else:
        _print_table(rows)
    return 0


async def cmd_show(args) -> int:
    async with Ctx() as c:
        r = await c.svc.get_run(args.run_id)
        if r is None:
            print(f"run {args.run_id} not found", file=sys.stderr)
            return 1
        from ..technique.bundle import build_bundle, render_readme
        b = await build_bundle(c.svc, args.run_id)
    if args.json:
        r.pop("facts", None)
        print(json.dumps(r, indent=1, default=str))
    else:
        print(render_readme(b))
        trace = (r.get("result") or {}).get("trace") or []
        if trace:
            print("## Trace")
            for t in trace:
                print(f"  {t.get('seq'):>3} {str(t.get('t') or ''):>7} {t.get('stage'):<10} {t.get('step'):<18} {t.get('reason')}")
    return 0


async def cmd_dump(args) -> int:
    out = Path(args.out or os.environ.get("ZARGAR_REVIEW_DIR") or (Path.cwd() / "technique-reviews"))
    async with Ctx() as c:
        try:
            root = await write_bundle(c.svc, args.run_id, out)
        except KeyError as exc:
            print(exc, file=sys.stderr)
            return 1
    files = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())
    if args.json:
        print(json.dumps({"dir": str(root), "files": files}))
    else:
        print(str(root))
        for f in files:
            print("  " + f)
    return 0


async def cmd_score(args) -> int:
    async with Ctx() as c:
        if args.pending:
            res = await c.svc.score_pending(limit=args.limit)
            print(json.dumps(res, indent=1))
            return 0
        try:
            outs = await c.svc.score_run(args.run_id, horizon_bars=args.horizon, force=True)
        except KeyError as exc:
            print(exc, file=sys.stderr)
            return 1
    if args.json:
        print(json.dumps(outs, indent=1, default=str))
    else:
        from ..technique.outcome import describe_outcome
        for o in outs:
            print(describe_outcome(o))
            if o.get("path"):
                print("  path:", json.dumps(o["path"]))
    return 0


async def cmd_replay_facts(args) -> int:
    """Recompute FACTS from the saved bars with the current code (+ overrides)
    and diff against what the run recorded — a detector regression check."""
    from ..technique.analysis import AnalysisRequest, compute_facts
    from ..technique.rulebook import Thresholds
    async with Ctx() as c:
        r = await c.svc.get_run(args.run_id)
        if r is None:
            print(f"run {args.run_id} not found", file=sys.stderr)
            return 1
        bars = await c.svc.load_bars_snapshot(args.run_id)
        if not bars:
            print("no bars snapshot for this run (pre-dates snapshots?)", file=sys.stderr)
            return 1
        t = c.svc.thresholds()
        overrides = _parse_sets(args.set)
        if overrides:
            fields = {f.name for f in dataclasses.fields(Thresholds)}
            bad = [k for k in overrides if k not in fields]
            if bad:
                print(f"unknown threshold(s): {bad}", file=sys.stderr)
                return 1
            t = dataclasses.replace(t, **overrides)
        req = AnalysisRequest(symbol=r["symbol"], as_of_ms=r.get("asOf"), primary_tf=r["primaryTf"], thresholds=t)
        new = compute_facts(req, bars, [])
    old = r.get("facts") or {}

    def lv(f):
        return [(round(x.get("price"), 4), x.get("kind"), x.get("touches")) for x in (f.get("keyLevels") or [])]

    def cands(f):
        return [(x.get("setupType"), (x.get("entry") or {}).get("price"), (x.get("stop") or {}).get("price"),
                 x.get("riskReward"), x.get("valid")) for x in (f.get("candidateSetups") or [])]

    diff = {
        "keyLevels": {"stored": lv(old), "now": lv(new)},
        "candidateSetups": {"stored": cands(old), "now": cands(new)},
        "trend": {"stored": old.get("trend"), "now": new.get("trend")},
        "recentBreak": {"stored": bool(old.get("recentBreak")), "now": bool(new.get("recentBreak"))},
        "lastClose": {"stored": old.get("lastClose"), "now": new.get("lastClose")},
        "overrides": overrides,
    }
    same = all(diff[k]["stored"] == diff[k]["now"] for k in ("keyLevels", "candidateSetups", "recentBreak"))
    diff["detectorsUnchanged"] = same
    if args.json:
        print(json.dumps(diff, indent=1, default=str))
    else:
        print("detectors unchanged" if same else "DETECTORS DIFFER")
        for k in ("keyLevels", "candidateSetups", "trend", "recentBreak", "lastClose"):
            if diff[k]["stored"] != diff[k]["now"]:
                print(f"- {k}:\n    stored: {diff[k]['stored']}\n    now:    {diff[k]['now']}")
    return 0


async def cmd_review(args) -> int:
    plan = {}
    if args.expected_entry is not None:
        plan["entry"] = args.expected_entry
    if args.expected_stop is not None:
        plan["stop"] = args.expected_stop
    if args.expected_targets:
        plan["targets"] = [float(x) for x in args.expected_targets.split(",") if x.strip()]
    async with Ctx() as c:
        try:
            d = await c.svc.add_review(
                args.run_id, review_verdict=args.verdict, reviewer=args.reviewer,
                expected_verdict=args.expected, expected_setup_type=args.expected_type,
                expected_plan=plan, expectation_note=args.expectation or "",
                root_cause_stage=args.root_cause, notes=args.note or "",
                actions=[{"desc": a} for a in (args.action or [])])
        except KeyError as exc:
            print(exc, file=sys.stderr)
            return 1
        except ValueError as exc:
            print(exc, file=sys.stderr)
            return 1
    print(json.dumps(d, indent=1, default=str) if args.json else f"review {d['id']} saved for run {args.run_id}")
    return 0


async def cmd_reviews(args) -> int:
    async with Ctx() as c:
        rows = await c.svc.list_reviews(args.run_id, limit=args.limit)
    if args.json:
        print(json.dumps(rows, indent=1, default=str))
    else:
        for r in rows:
            print(f"{(r['createdAt'] or '')[:16]} run {r['runId'][:10]} {r['reviewer']:<6} {r['reviewVerdict']:<14} "
                  f"{r.get('rootCauseStage') or '-':<12} {(r.get('notes') or '')[:80]}")
        if not rows:
            print("(no reviews)")
    return 0


async def cmd_diff(args) -> int:
    async with Ctx() as c:
        try:
            d = await c.svc.diff(args.run_a, args.run_b)
        except KeyError as exc:
            print(exc, file=sys.stderr)
            return 1
    if args.json:
        print(json.dumps(d, indent=1, default=str))
        return 0
    print(f"A {d['a']['id']} ({d['a']['symbol']} as of {_ts(d['a']['asOf'])})")
    print(f"B {d['b']['id']} ({d['b']['symbol']} as of {_ts(d['b']['asOf'])})")
    print("same inputs:", d["sameInputs"])
    for sec in ("versions", "thresholds", "settings", "analysis"):
        if d[sec]:
            print(f"\n{sec}:")
            for k, v in d[sec].items():
                print(f"  {k}: {v['a']}  ->  {v['b']}")
        else:
            print(f"\n{sec}: identical")
    print(f"\nusage A {d['usage']['a']} / B {d['usage']['b']} · seconds A {d['seconds']['a']} / B {d['seconds']['b']}")
    return 0


async def cmd_replay(args) -> int:
    import httpx
    cfg = AppConfig()
    base = args.api or f"http://{cfg.host}:{cfg.port}"
    headers = {"Authorization": f"Bearer {cfg.auth_token}"} if cfg.auth_token else {}
    body = {"thresholds": _parse_sets(args.set) or None, "useSnapshot": not args.no_snapshot,
            "note": args.note or "", "wait": True}
    async with httpx.AsyncClient(timeout=900, headers=headers) as http:
        try:
            r = await http.post(f"{base}/api/technique/runs/{args.run_id}/replay", json=body)
        except httpx.HTTPError as exc:
            print(f"API not reachable at {base}: {exc} (start the app first)", file=sys.stderr)
            return 1
        if r.status_code >= 400:
            print(f"replay failed: {r.status_code} {r.text}", file=sys.stderr)
            return 1
        run = r.json()
        if args.json:
            print(json.dumps(run, indent=1, default=str))
        else:
            print(f"replay run {run['id']}: {run.get('status')} verdict {run.get('verdict')} "
                  f"({run.get('setupType')}) conf {run.get('confidence')}")
            if run.get("status") == "done":
                d = await http.get(f"{base}/api/technique/runs/{args.run_id}/diff/{run['id']}")
                if d.status_code == 200:
                    dd = d.json()
                    print("analysis changes:", json.dumps(dd.get("analysis"), default=str))
    return 0


async def cmd_plan(args) -> int:
    """Build a session plan through the API (needs the app for a live as-of) or
    deterministically offline when --as-of is given (no model needed)."""
    import httpx
    from ..technique.rulebook import session_bounds
    as_of = None
    if args.as_of:
        _, close = session_bounds(args.as_of)
        as_of = close + 1
    cfg = AppConfig()
    base = args.api or f"http://{cfg.host}:{cfg.port}"
    headers = {"Authorization": f"Bearer {cfg.auth_token}"} if cfg.auth_token else {}
    async with httpx.AsyncClient(timeout=900, headers=headers) as http:
        try:
            r = await http.post(f"{base}/api/technique/plan",
                                json={"symbol": args.symbol.upper(), "asOf": as_of, "withVision": args.with_vision,
                                      "wait": True})
        except httpx.HTTPError as exc:
            print(f"API not reachable at {base}: {exc} (start the app first)", file=sys.stderr)
            return 1
        if r.status_code >= 400:
            print(f"plan failed: {r.status_code} {r.text}", file=sys.stderr)
            return 1
        run = r.json()
    if args.json:
        print(json.dumps(run, indent=1, default=str))
        return 0
    from ..technique.plans import plan_summary_text
    plan = (run.get("result") or {}).get("plan")
    print(f"run {run['id']} ({run.get('status')})")
    if plan:
        print(plan_summary_text(plan))
    for o in run.get("outcomes") or []:
        print(" outcome:", o.get("planSource"), o.get("status"), o.get("outcome"), o.get("rMultiple"))
    return 0


async def cmd_sweep(args) -> int:
    async with Ctx() as c:
        syms = [s.strip().upper() for s in (args.symbols or "").split(",") if s.strip()] or \
            list(c.engine.settings.get("technique.walkforward.symbols", []))
        stf = [s.strip() for s in args.structure.split(",")] if args.structure else None
        d = await c.svc.start_sweep(syms, args.start, args.end, structure_tfs=stf, trigger_tf=args.trigger,
                                    include_invalid=args.include_invalid, label=args.label or "", wait=True)
    if args.json:
        print(json.dumps(d, indent=1, default=str))
    else:
        _print_sweep(d, rows=False)
    return 0


async def cmd_sweeps(args) -> int:
    async with Ctx() as c:
        rows = await c.svc.list_sweeps(limit=args.limit)
    if args.json:
        print(json.dumps(rows, indent=1, default=str))
        return 0
    for s in rows:
        smp = (s.get("summary") or {}).get("sample") or {}
        print(f"{s['id'][:10]} {(s.get('createdAt') or '')[:16]} {s['status']:<8} {s['start']}..{s['end']} "
              f"{','.join(s['symbols'])[:40]:<40} sessions={(s.get('summary') or {}).get('sessions', '-')} "
              f"fired={smp.get('fired', '-')}")
    if not rows:
        print("(no sweeps)")
    return 0


def _print_sweep(d: dict, *, rows: bool) -> None:
    sm = d.get("summary") or {}
    print(f"sweep {d['id']} [{d['status']}] {d['start']}..{d['end']} symbols {', '.join(d['symbols'])}")
    print(f"params: {json.dumps({k: v for k, v in (d.get('params') or {}).items() if k != 'thresholds'})}")
    if not sm:
        print("(no summary yet)", d.get("progress"))
        return
    print(f"sessions {sm.get('sessions')} · fired {(sm.get('sample') or {}).get('fired')} of target "
          f"{(sm.get('sample') or {}).get('target')}")
    print("\nLEVEL QUALITY (tested respect rate):")
    for key in ("priorDayVsOther", "bySource", "byTouches", "byTimeframe"):
        print(f"  {key}:")
        for k, v in ((sm.get("levels") or {}).get(key) or {}).items():
            print(f"    {k:<12} n={v['n']:<4} respected={v['respected']:<4} broken={v['broken']:<4} "
                  f"flipped={v['flipped']:<3} untested={v['untested']:<4} testedRespect={v.get('testedRespectRate')}")
    print("\nTRIGGER QUALITY:")
    for key in ("byKind", "byWindow", "counterfactual", "byRrGate"):
        print(f"  {key}:")
        for k, v in ((sm.get("triggers") or {}).get(key) or {}).items():
            print(f"    {k:<14} " + " ".join(f"{kk}={vv}" for kk, vv in v.items()
                                             if kk in ("planned", "fired", "wins", "winRate", "avgR", "sumR",
                                                       "gappedPast", "gappedThrough", "gapVoid", "observedMidday",
                                                       "notTriggered", "triggerRate")))
    md = (sm.get("triggers") or {}).get("middayFiresWithoutGate")
    if md:
        print(f"  mid-day fires without the R6 gate: {md}")
    print("\nCLAIMS (book vs data):")
    for c in sm.get("claims") or []:
        print(f"  [{c['verdict']:<12}] {c['claim']} ({c['rule']}) — {c['metric']}: {json.dumps(c['detail'], default=str)[:160]}")
    if sm.get("errors"):
        print("\nerrors:", sm["errors"])
    if rows and d.get("rows"):
        print("\nROWS:")
        for r in d["rows"]:
            s = r.get("summary") or {}
            print(f"  {r['symbol']:<6} {r['session']} -> {r.get('planFor')}: triggers {s.get('triggers')} fired {s.get('fired')} "
                  f"sumR {s.get('sumR')} levels R/B/U {s.get('levelsRespected')}/{s.get('levelsBroken')}/{s.get('levelsUntested')} "
                  f"gap {s.get('gapPct')}%" + (f" promoted {r['promotedRunId'][:8]}" if r.get("promotedRunId") else ""))


async def cmd_sweep_report(args) -> int:
    async with Ctx() as c:
        d = await c.svc.get_sweep(args.sweep_id, rows=True)
    if d is None:
        print("sweep not found", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(d, indent=1, default=str))
    else:
        _print_sweep(d, rows=args.rows)
    return 0


async def _api_call(args, method: str, path: str, body: dict | None = None) -> int:
    import httpx
    cfg = AppConfig()
    base = args.api or f"http://{cfg.host}:{cfg.port}"
    headers = {"Authorization": f"Bearer {cfg.auth_token}"} if cfg.auth_token else {}
    async with httpx.AsyncClient(timeout=600, headers=headers) as http:
        try:
            r = await http.request(method, f"{base}{path}", json=body)
        except httpx.HTTPError as exc:
            print(f"API not reachable at {base}: {exc} (start the app first)", file=sys.stderr)
            return 1
        if r.status_code >= 400:
            print(f"{path} failed: {r.status_code} {r.text}", file=sys.stderr)
            return 1
        print(json.dumps(r.json(), indent=1, default=str))
    return 0


async def cmd_promote(args) -> int:
    return await _api_call(args, "POST", f"/api/technique/walkforward/{args.sweep_id}/promote",
                           {"symbol": args.symbol.upper(), "session": args.session})


async def cmd_arm(args) -> int:
    body = {k: v for k, v in {"portfolioId": args.portfolio, "mode": args.mode, "riskPct": args.risk_pct,
                              "maxQty": args.max_qty, "allowLive": args.allow_live}.items() if v not in (None, False)}
    return await _api_call(args, "POST", f"/api/technique/runs/{args.run_id}/arm", body or None)


async def cmd_disarm(args) -> int:
    return await _api_call(args, "DELETE", f"/api/technique/runs/{args.run_id}/arm")


async def cmd_arm_today(args) -> int:
    return await _api_call(args, "POST", "/api/technique/arm-today", {"symbol": args.symbol.upper()})


async def cmd_armed(args) -> int:
    return await _api_call(args, "GET", "/api/technique/armed")


async def cmd_armed_show(args) -> int:
    """One armed/live plan and its execution scorecard (what it actually did vs
    the deterministic replay of the same session)."""
    import httpx
    cfg = AppConfig()
    base = args.api or f"http://{cfg.host}:{cfg.port}"
    headers = {"Authorization": f"Bearer {cfg.auth_token}"} if cfg.auth_token else {}
    async with httpx.AsyncClient(timeout=60, headers=headers) as http:
        # live plan first, else the persisted history row
        d = None
        try:
            r = await http.get(f"{base}/api/technique/armed/{args.run_id}")
            if r.status_code == 200:
                d = r.json()
        except httpx.HTTPError as exc:
            print(f"API not reachable at {base}: {exc}", file=sys.stderr)
            return 1
        if d is None:
            r = await http.get(f"{base}/api/technique/armed/history")
            row = next((h for h in r.json() if h["runId"].startswith(args.run_id)), None)
            if row is None:
                print(f"no armed plan for {args.run_id!r}", file=sys.stderr)
                return 1
            d = {**row, **(row.get("state") or {})}
    if args.json:
        print(json.dumps(d, indent=1, default=str))
        return 0
    print(f"{d.get('symbol')}  {d.get('runId','')[:12]}  status={d.get('status')}  mode={(d.get('config') or {}).get('mode')}")
    if d.get("stopReason"):
        print(f"  stopped: {d['stopReason']}")
    for t in d.get("trades", []):
        print(f"  trade {t.get('triggerId')}: {t.get('status')} qty={t.get('filledQty')} "
              f"realised={t.get('realizedPnl')} exits={[e.get('kind') for e in t.get('exits', [])]}")
    sc = d.get("scorecard")
    if sc:
        print(f"\n  SCORECARD ({sc.get('planFor')}): theoretical fires {sc.get('theoreticalFires')} "
              f"(ΣR {sc.get('theoreticalSumR')}), actual fires {sc.get('actualFires')}, "
              f"matched {sc.get('matched')}, realised {sc.get('realizedPnl')}")
        for row in sc.get("rows", []):
            th, ac = row.get("theoretical") or {}, row.get("actual") or {}
            print(f"    {row['trigger']} {row['kind']}: replay {th.get('status')}/{th.get('outcome')} R={th.get('rMultiple')}"
                  f" | live {(ac or {}).get('status', '—')}"
                  + (f"  ({'; '.join(row['notes'])})" if row.get("notes") else ""))
    else:
        print("  (no scorecard yet — the session has not closed)")
    return 0


def cmd_taxonomy(args) -> int:
    if args.json:
        print(json.dumps({"reviewVerdicts": REVIEW_VERDICTS, "rootCauseStages": ROOT_CAUSE_STAGES}, indent=1))
        return 0
    print("review verdicts:")
    for k, v in REVIEW_VERDICTS.items():
        print(f"  {k:<14} {v}")
    print("\nroot-cause stages:")
    for k, v in ROOT_CAUSE_STAGES.items():
        print(f"  {k:<14} {v}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="technique_review", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("list", help="recent runs with outcome + review status")
    p.add_argument("--limit", type=int, default=30)
    p.add_argument("--symbol")
    p.add_argument("--verdict", choices=["setup", "no_setup"])
    p.add_argument("--unreviewed", action="store_true")
    p.add_argument("--reviewed", action="store_true")
    p.add_argument("--wrong", action="store_true", help="non-correct review or a losing outcome")
    p.add_argument("--outcome", help="stopped|tp1|tp2|tp3|horizon|not_filled|win|loss|scored|pending|partial|unscorable|none")
    p.add_argument("--review-verdict", dest="review_verdict", choices=sorted(REVIEW_VERDICTS))
    p.add_argument("--process-version", dest="process_version")
    p.add_argument("--trigger", choices=["manual", "scan", "chat", "replay"])
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser("show", help="one-screen summary of a run (README + trace)")
    p.add_argument("run_id")
    p.set_defaults(fn=cmd_show)

    p = sub.add_parser("dump", help="write the full bundle to DIR/<run_id>/")
    p.add_argument("run_id")
    p.add_argument("--out")
    p.set_defaults(fn=cmd_dump)

    p = sub.add_parser("score", help="(re)score what price did after a run")
    p.add_argument("run_id", nargs="?")
    p.add_argument("--horizon", type=int)
    p.add_argument("--pending", action="store_true", help="score every run that is missing an outcome")
    p.add_argument("--limit", type=int, default=50)
    p.set_defaults(fn=cmd_score)

    p = sub.add_parser("replay-facts", help="recompute detectors from the saved bars and diff")
    p.add_argument("run_id")
    p.add_argument("--set", action="append", metavar="KEY=VALUE", help="threshold override (repeatable)")
    p.set_defaults(fn=cmd_replay_facts)

    p = sub.add_parser("review", help="record a review for a run")
    p.add_argument("run_id")
    p.add_argument("--verdict", required=True, choices=sorted(REVIEW_VERDICTS))
    p.add_argument("--root-cause", dest="root_cause", choices=sorted(ROOT_CAUSE_STAGES))
    p.add_argument("--expected", choices=["setup", "no_setup"])
    p.add_argument("--expected-type", dest="expected_type")
    p.add_argument("--expected-entry", dest="expected_entry", type=float)
    p.add_argument("--expected-stop", dest="expected_stop", type=float)
    p.add_argument("--expected-targets", dest="expected_targets", help="comma-separated prices")
    p.add_argument("--expectation", help="what you expected, in words")
    p.add_argument("--note", help="review notes / diagnosis")
    p.add_argument("--action", action="append", help="planned fix (repeatable)")
    p.add_argument("--reviewer", default="user", choices=["user", "claude"])
    p.set_defaults(fn=cmd_review)

    p = sub.add_parser("reviews", help="list reviews (optionally for one run)")
    p.add_argument("run_id", nargs="?")
    p.add_argument("--limit", type=int, default=100)
    p.set_defaults(fn=cmd_reviews)

    p = sub.add_parser("diff", help="compare two runs (analysis, thresholds, versions)")
    p.add_argument("run_a")
    p.add_argument("run_b")
    p.set_defaults(fn=cmd_diff)

    p = sub.add_parser("replay", help="re-run a past moment through the live API (needs the app running)")
    p.add_argument("run_id")
    p.add_argument("--api", help="base URL, default from ZARGAR_HOST/PORT")
    p.add_argument("--set", action="append", metavar="KEY=VALUE", help="threshold override (repeatable)")
    p.add_argument("--no-snapshot", dest="no_snapshot", action="store_true", help="refetch bars from Yahoo")
    p.add_argument("--note")
    p.set_defaults(fn=cmd_replay)

    p = sub.add_parser("taxonomy", help="print the review verdict / root-cause vocabularies")
    p.set_defaults(fn=cmd_taxonomy)

    p = sub.add_parser("plan", help="build a session plan (through the API)")
    p.add_argument("symbol")
    p.add_argument("--as-of", dest="as_of", help="YYYY-MM-DD: plan built at that session's close")
    p.add_argument("--with-vision", dest="with_vision", action="store_true")
    p.add_argument("--api")
    p.set_defaults(fn=cmd_plan)

    p = sub.add_parser("sweep", help="walk-forward sweep (deterministic, direct DB)")
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--symbols", help="comma-separated; default technique.walkforward.symbols")
    p.add_argument("--structure", help="comma-separated structure tfs, default technique.structure_tfs")
    p.add_argument("--trigger", help="trigger tf, default technique.trigger_tf")
    p.add_argument("--include-invalid", dest="include_invalid", action="store_true")
    p.add_argument("--label")
    p.set_defaults(fn=cmd_sweep)

    p = sub.add_parser("sweeps", help="list sweeps")
    p.add_argument("--limit", type=int, default=30)
    p.set_defaults(fn=cmd_sweeps)

    p = sub.add_parser("sweep-report", help="aggregate report for a sweep")
    p.add_argument("sweep_id")
    p.add_argument("--rows", action="store_true")
    p.set_defaults(fn=cmd_sweep_report)

    p = sub.add_parser("promote", help="promote a sweep row to a full plan run (API)")
    p.add_argument("sweep_id")
    p.add_argument("symbol")
    p.add_argument("session")
    p.add_argument("--api")
    p.set_defaults(fn=cmd_promote)

    for name, fn, extra in (("arm", cmd_arm, "run_id"), ("disarm", cmd_disarm, "run_id"),
                            ("arm-today", cmd_arm_today, "symbol")):
        p = sub.add_parser(name, help=f"{name} (API)")
        p.add_argument(extra)
        p.add_argument("--api")
        if name == "arm":
            p.add_argument("--portfolio", help="account id the plan trades in")
            p.add_argument("--mode", choices=["alert", "proposal", "auto"])
            p.add_argument("--risk-pct", dest="risk_pct", type=float)
            p.add_argument("--max-qty", dest="max_qty", type=float)
            p.add_argument("--allow-live", dest="allow_live", action="store_true",
                           help="acknowledge auto execution on a live/paper account")
        p.set_defaults(fn=fn)
    p = sub.add_parser("armed", help="list armed plans (API)")
    p.add_argument("--api")
    p.set_defaults(fn=cmd_armed)
    p = sub.add_parser("armed-show", help="one armed/live plan + its execution scorecard (API)")
    p.add_argument("run_id")
    p.add_argument("--api")
    p.set_defaults(fn=cmd_armed_show)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    fn = args.fn
    try:
        if asyncio.iscoroutinefunction(fn):
            return asyncio.run(fn(args))
        return fn(args)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
