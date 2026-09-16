"""Team2 readiness receipt for the parallel Practice experiments (review team, 2026-09-15; hardened per the review of
41ec565). READ-ONLY: settings are loaded without migration or journal writes, the DB is only read, the API only GET.

    cd backend && .venv/Scripts/python.exe -m zargar.tools.team2_receipt [--date 2026-09-16] [--out receipt.json]

Missing evidence is a BLOCKER, never a pass. Two states are distinguished: PREPARED (the configuration is valid but
disabled: nothing armed, nothing trades) and READY (enabled, the three books valid and fresh, every expected plan
armed under its stamped role and the deployed version, healthy deployed code with the feature, no extra Team2 plans
on other books, no pause or halt on the experiment books, thresholds owned, C6 evidence on file) — READY still means
"pending the review team's GO", never activation by itself."""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import pathlib
import sys
from types import SimpleNamespace

API = "http://127.0.0.1:8420"
FEATURE_VERSION = (0, 7, 93)             # the release that carries the per-book experiments
THRESHOLDS = {"sizing": {"sampledDrawdownReview$": -800, "basis": "8 % of the $10,000 start; ≈ 1.25 × the approximate modeled Practice-scale DD of $635 (sheet rev. 2)"},
              "c1": {"sampledDrawdownReview$": -1000, "basis": "policy: 10 % of the $10,000 start = the desk's technique day-loss pause level applied cumulatively; a stated Practice policy choice, not a guaranteed maximum loss nor backtest-derived (the approximate modeled Practice-scale C1 DD is $2,619)"}}
PAUSE_ACTION = ("breach → POST /api/portfolios/{id}/pause (reason 'experiment loss stop: <drawdown>', the book's label): entries AND adds refused, "
                "protective exits active, other books untouched, survives restart and the day roll, released only by /unpause after review — no automatic reset or resume")
WATCH = "the team2-market-watch job (30 min) and the close; owner: the Team2 desk"
C6_EVIDENCE = pathlib.Path(__file__).resolve().parents[3] / "docs" / "techniques" / "team2" / "notes" / "research" / "c6-evidence.json"


def _version_tuple(v) -> tuple:
    try:
        return tuple(int(x) for x in str(v).split(".")[:3])
    except (TypeError, ValueError):
        return ()


def c6_status() -> dict:
    """C6 is satisfied only by an explicit reviewed evidence record (JSON: satisfied, reviewedBy, date, datasetVersion,
    reference) — never by a phrase found in prose."""
    try:
        d = json.loads(pathlib.Path(C6_EVIDENCE).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - absent or unparsable = not satisfied
        return {"satisfied": False, "evidence": f"no reviewed evidence record at {C6_EVIDENCE.name}"}
    ok = isinstance(d, dict) and bool(d.get("satisfied")) and all(d.get(k) for k in ("reviewedBy", "date", "datasetVersion", "reference"))
    return {"satisfied": ok, "evidence": d if isinstance(d, dict) else str(d)}


async def main(args) -> int:
    from sqlalchemy import select
    from ..bus import Bus
    from ..config import get_config
    from ..db import make_engine, make_session_factory
    from ..events import Journal
    from ..models import Portfolio, TechniqueArmed, TechniqueRun
    from ..settings_service import SettingsService
    from ..techniques.team2.rules import EXPERIMENT_ROLES, rules_from_settings, validate_experiments
    cfg = get_config(); eng = make_engine(cfg.database_url); sf = make_session_factory(eng); bus = Bus()
    settings = SettingsService(sf, bus, Journal(sf, bus))
    settings.readonly = True                                   # never migrate or journal from the receipt
    await settings.load()
    s = settings
    date = args.date or (dt.date.today() + dt.timedelta(days=1)).isoformat()
    symbols = [str(x).upper() for x in (s.get("techniques.team2.symbols", []) or [])]
    # --- live (GET only) ---------------------------------------------------------------------
    health, ops = {}, {}
    try:
        import urllib.request
        health = json.load(urllib.request.urlopen(f"{API}/api/health", timeout=6)) or {}
    except Exception as exc:  # noqa: BLE001
        health = {"ok": False, "error": str(exc)}
    try:
        import urllib.request
        ops = json.load(urllib.request.urlopen(f"{API}/api/ops/state", timeout=8)) or {}
    except Exception as exc:  # noqa: BLE001
        ops = {"error": str(exc)}
    # --- DB (read) --------------------------------------------------------------------------
    async with sf() as session:
        rows = (await session.execute(select(Portfolio))).scalars().all()
        armed = (await session.execute(select(TechniqueArmed).where(TechniqueArmed.technique == "team2", TechniqueArmed.plan_for == date))).scalars().all()
    pf = {p.id: p for p in rows}

    def lookup(pid):
        p = pf.get(pid)
        return None if p is None else {"kind": getattr(p, "kind", None), "archived": bool(getattr(p, "archived", False))}
    v = validate_experiments(s, portfolio_lookup=lookup)
    raw = s.get("techniques.team2.experiments") or {}
    if not v["enabled"] and isinstance(raw, dict):
        # PREPARED view: validate the map as if enabled so the receipt shows what WOULD run and what still blocks it
        dry = validate_experiments({"techniques.team2.experiments": {**raw, "enabled": True}}, portfolio_lookup=lookup)
        v = {**dry, "enabled": False}
    default_pid = str(s.get("techniques.team2.default_portfolio", "") or s.get("trading.default_portfolio", "") or "")
    base = rules_from_settings(s)
    blockers: list[str] = []
    if v["errors"]:
        blockers += [f"configuration: {e}" for e in v["errors"]]
    roles = {b["role"] for b in v["books"]}
    if v["enabled"] and roles != set(EXPERIMENT_ROLES):
        blockers.append(f"configuration: both experiment roles are required, have {sorted(roles)}")
    if v["enabled"] and v["control"] and v["control"] != default_pid:
        blockers.append(f"configuration: the designated control {v['control']} is not the default book {default_pid}")
    # the three books
    books = []
    all_books = ([{"portfolioId": v["control"] or default_pid, "label": "control", "role": "control", "overrides": {}}] + list(v["books"]))
    if not v["enabled"] and default_pid and default_pid != (v["control"] or default_pid):
        # while disabled the default book is today's legitimate baseline trader; show it, never count it as "extra"
        all_books = [{"portfolioId": default_pid, "label": "default book today (baseline)", "role": "baseline-today", "overrides": {}}] + all_books
    armed_ok = [a for a in armed if a.status in ("armed", "paused")]
    # stamped roles per armed plan (best effort: missing evidence is a blocker)
    stamps: dict[str, dict] = {}
    try:
        async with sf() as session:
            runs = (await session.execute(select(TechniqueRun).where(TechniqueRun.id.in_([a.run_id for a in armed_ok] or ["-"])))).scalars().all()
        for r in runs:
            stamps[r.id] = {"experiment": ((r.result or {}).get("plan") or {}).get("experiment") or (r.config or {}).get("experiment") or {},
                            "codeVersion": (r.config or {}).get("codeVersion"), "thresholds": (r.config or {}).get("thresholds") or {}}
    except Exception as exc:  # noqa: BLE001
        blockers.append(f"evidence: could not read the armed plans' stamped rules ({type(exc).__name__})")
    for b in all_books:
        pid = b["portfolioId"]; p = pf.get(pid)
        plans = [a for a in armed_ok if a.portfolio_id == pid]
        by_sym = {a.symbol: a for a in plans}
        ov = b["overrides"]
        row = {"portfolioId": pid, "name": getattr(p, "name", None), "kind": getattr(p, "kind", None), "archived": bool(getattr(p, "archived", False)) if p else None,
               "cash": getattr(p, "cash", None), "startingCash": getattr(p, "starting_cash", None), "role": b["role"], "label": b["label"],
               "overrides": ov, "effectiveDiffVsBaseline": {k: v_ for k, v_ in ov.items() if base.to_dict().get(k) != v_},
               "armedPlans": sorted(by_sym), "threshold": THRESHOLDS.get(b["role"]), "stampOk": None}
        if b["role"] == "baseline-today":
            books.append(row); continue                         # informational only
        if p is None:
            blockers.append(f"{b['role']}: portfolio {pid or '(none)'} does not exist")
        else:
            if row["kind"] != "sim" or row["archived"]:
                blockers.append(f"{b['role']}: {row['name']} is not an unarchived Practice book")
            if row["cash"] is None or row["startingCash"] is None or abs(float(row["cash"]) - float(row["startingCash"])) > 0.005:
                blockers.append(f"{b['role']}: {row['name']} is not at its fresh starting balance (cash {row['cash']} vs start {row['startingCash']})")
        if v["enabled"]:
            missing = [x for x in symbols if x not in by_sym]
            if missing:
                blockers.append(f"{b['role']}: no armed plan for {missing} on {date}")
            ok_stamps = True
            for sym, a in by_sym.items():
                st = stamps.get(a.run_id)
                if st is None:
                    ok_stamps = False; blockers.append(f"{b['role']}: {sym} plan {a.run_id[:8]} has no readable stamp"); continue
                exp = st["experiment"] or {}
                want_role = None if b["role"] == "control" else b["role"]
                if (exp.get("role") or None) != want_role or (exp.get("overrides") or {}) != ov:
                    ok_stamps = False; blockers.append(f"{b['role']}: {sym} plan {a.run_id[:8]} is stamped {exp.get('role')} {exp.get('overrides')} — expected {want_role} {ov}")
                for k, val in ov.items():
                    if st["thresholds"].get(k) != val:
                        ok_stamps = False; blockers.append(f"{b['role']}: {sym} plan {a.run_id[:8]} thresholds carry {k}={st['thresholds'].get(k)}, expected {val}")
                if health.get("version") and st["codeVersion"] and _version_tuple(st["codeVersion"]) < FEATURE_VERSION:
                    ok_stamps = False; blockers.append(f"{b['role']}: {sym} plan {a.run_id[:8]} was minted by code {st['codeVersion']} (feature needs {'.'.join(map(str, FEATURE_VERSION))}+)")
            row["stampOk"] = ok_stamps
        books.append(row)
    starts = {b["startingCash"] for b in books if b["startingCash"] is not None and b["role"] != "baseline-today"}
    if len(starts) > 1:
        blockers.append(f"books do not share one starting balance: {sorted(starts)}")
    # extra Team2 plans for the session on books outside the set
    in_set = {b["portfolioId"] for b in all_books}
    extra = [{"runId": a.run_id, "symbol": a.symbol, "portfolioId": a.portfolio_id, "book": getattr(pf.get(a.portfolio_id), "name", a.portfolio_id)}
             for a in armed_ok if a.portfolio_id not in in_set]
    if v["enabled"] and extra:
        blockers.append(f"{len(extra)} armed Team2 plan(s) for {date} on books outside the experiment set (a fourth book): {sorted({e['book'] for e in extra})}")
    # deployed code
    if not health.get("ok"):
        blockers.append("deployed engine is not healthy")
    if _version_tuple(health.get("version")) < FEATURE_VERSION:
        blockers.append(f"deployed version {health.get('version')} predates the feature ({'.'.join(map(str, FEATURE_VERSION))})")
    # pauses / halts
    paused = ops.get("pausedBooks") if isinstance(ops, dict) else None
    halt = s.get("system.halt") or {}
    if paused is None:
        blockers.append("pause state unknown (ops state unavailable)")
    else:
        for b in books:
            if b["portfolioId"] in (paused or []):
                blockers.append(f"{b['role']}: {b['name']} is paused")
            if b["portfolioId"] in (halt.get("books") or {}):
                blockers.append(f"{b['role']}: {b['name']} has a daily-loss halt")
    if halt.get("engaged"):
        blockers.append("the global kill switch is engaged")
    for role in EXPERIMENT_ROLES:
        if role not in THRESHOLDS:
            blockers.append(f"no threshold owned for role {role}")
    c6 = c6_status()
    if not c6["satisfied"]:
        blockers.append("C6 not satisfied (no reviewed evidence record)")
    if not v["enabled"]:
        state = "PREPARED (disabled) — nothing armed for the experiments, nothing trades on them" if not v["errors"] else "INVALID configuration (disabled)"
        activation = "NOT READY — experiments disabled; blockers before activation: " + ("; ".join(blockers) if blockers else "none besides enablement")
    else:
        activation = ("READY — armed for " + date + "; pending the review team's GO") if not blockers else "NOT READY — blockers: " + "; ".join(blockers)
        state = "ENABLED"
    out = {"receiptAt": dt.datetime.now().astimezone().isoformat(timespec="seconds"), "session": date, "state": state,
           "deployed": {"version": health.get("version"), "build": health.get("build"), "healthy": bool(health.get("ok"))},
           "defaultBook": default_pid, "configuration": {"enabled": v["enabled"], "control": v["control"], "errors": v["errors"]},
           "books": books, "extraArmedPlans": extra, "blockers": blockers, "activation": activation,
           "pauseControls": {"routes": ["POST /api/portfolios/{id}/pause", "POST /api/portfolios/{id}/unpause"], "action": PAUSE_ACTION, "pausedBooks": paused,
                             "globalHalt": bool(halt.get("engaged")), "bookHalts": sorted((halt.get("books") or {}).keys()), "watch": WATCH},
           "thresholds": THRESHOLDS, "c6": c6}
    print(f"# Team2 readiness receipt — session {date} ({out['receiptAt']})\n")
    print(f"Deployed: v{out['deployed']['version']} build {out['deployed']['build']} healthy={out['deployed']['healthy']}")
    print(f"State: {state}\nActivation: {activation}\n")
    print("| Role | Book | ID | Kind | Cash | Start | Label | Override | Armed | Stamp OK | Threshold |")
    print("|---|---|---|---|---:|---:|---|---|---|---|---|")
    for b in books:
        t = b["threshold"]; th = f"{t['sampledDrawdownReview$']} sampled" if t else "existing protections"
        print(f"| {b['role']} | {b['name']} | `{b['portfolioId']}` | {b['kind']}{' (archived)' if b['archived'] else ''} | {b['cash']} | {b['startingCash']} | {b['label']} | {b['overrides']} | {', '.join(b['armedPlans']) or '—'} | {b['stampOk']} | {th} |")
    if extra:
        print("\nExtra armed Team2 plans outside the set:", extra)
    print("\nBlockers:", blockers or "none")
    print("Pause controls:", out["pauseControls"]["routes"], "| paused:", paused, "| global halt:", bool(halt.get("engaged")), "| book halts:", out["pauseControls"]["bookHalts"], "| watch:", WATCH)
    print("Pause action:", PAUSE_ACTION)
    print("Thresholds:", json.dumps(THRESHOLDS))
    print("C6:", c6)
    if args.out:
        pathlib.Path(args.out).write_text(json.dumps(out, indent=1, default=str), encoding="utf-8"); print("written", args.out)
    await eng.dispose()
    return 0


def cli() -> None:
    p = argparse.ArgumentParser(description="Team2 readiness receipt (read-only)")
    p.add_argument("--date", default=None); p.add_argument("--out", default="")
    sys.exit(asyncio.run(main(p.parse_args())))


if __name__ == "__main__":
    cli()
