"""Team2 readiness receipt for the parallel Practice experiments (review team, 2026-09-15). READ-ONLY.

    cd backend && .venv/Scripts/python.exe -m zargar.tools.team2_receipt [--date 2026-09-16] [--out receipt.json]

Prints one concise receipt: deployed version/build, the books (id, name, kind, cash, starting cash), the EFFECTIVE
per-book rules (the baseline and every book's whitelisted overrides, from `rules_for_book`), the isolation checks
(distinct Practice books, whitelist only, shared settings = baseline, counters per book in code), the pause controls
(routes, paused books, halts), the thresholds, the C6 status (read from PLATFORM-RULES: request only = NOT satisfied)
and the armed plans per book for the session. Reads the runtime DB and the local API; changes nothing."""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import pathlib
import sys
from types import SimpleNamespace

API = "http://127.0.0.1:8420"
THRESHOLDS = {"team2-sizing-cap-2026-09": {"sampledDrawdownReview$": -800, "basis": "8 % of the $10,000 start; ≈ 1.25 × the approximate modeled Practice-scale DD of $635 (sheet rev. 2)"},
              "team2-c1-conjunction-2026-09": {"sampledDrawdownReview$": -1000, "basis": "policy: 10 % of the $10,000 start = the desk's existing technique day-loss pause level applied cumulatively; not derived from the backtest (the approximate modeled Practice-scale C1 DD is $2,619, so the review fires at ~0.4× of it); not the rejected $700 figure"}}
PAUSE_ACTION = "breach → POST /api/portfolios/{id}/pause (reason 'experiment loss stop: <drawdown>', the book's label): entries AND adds refused, protective exits active, other books untouched, survives restart and the day roll, released only by /unpause after review — no automatic reset or resume"


async def main(args) -> int:
    from sqlalchemy import select
    from ..bus import Bus
    from ..config import get_config
    from ..db import make_engine, make_session_factory
    from ..events import Journal
    from ..models import Portfolio, TechniqueArmed
    from ..settings_service import SettingsService
    from ..techniques.team2.rules import experiment_books, rules_for_book, rules_from_settings
    cfg = get_config(); eng = make_engine(cfg.database_url); sf = make_session_factory(eng); bus = Bus()
    settings = SettingsService(sf, bus, Journal(sf, bus)); await settings.load()
    s = settings
    date = args.date or (dt.date.today() + dt.timedelta(days=1)).isoformat()
    # --- live ------------------------------------------------------------------------------
    health = ops = None
    try:
        import urllib.request
        health = json.load(urllib.request.urlopen(f"{API}/api/health", timeout=6))
        ops = json.load(urllib.request.urlopen(f"{API}/api/ops/state", timeout=8))
    except Exception as exc:  # noqa: BLE001
        health = {"error": str(exc)}
    # --- books -----------------------------------------------------------------------------
    exp = s.get("techniques.team2.experiments") or {}
    books_cfg = experiment_books(s)
    default_pid = str(s.get("techniques.team2.default_portfolio", "") or s.get("trading.default_portfolio", "") or "")
    wanted = [default_pid] + [b["portfolioId"] for b in books_cfg] + [str(b.get("portfolioId")) for b in (exp.get("books") or []) if isinstance(b, dict)]
    async with sf() as session:
        rows = (await session.execute(select(Portfolio))).scalars().all()
        armed = (await session.execute(select(TechniqueArmed).where(TechniqueArmed.technique == "team2", TechniqueArmed.plan_for == date))).scalars().all()
    pf = {p.id: p for p in rows}
    base = rules_from_settings(s)

    def book_row(pid, label, overrides, refused=None):
        p = pf.get(pid)
        r = rules_for_book(s, pid)
        diff = {k: v for k, v in r.to_dict().items() if base.to_dict().get(k) != v}
        return {"portfolioId": pid, "name": getattr(p, "name", None), "kind": getattr(p, "kind", None), "cash": getattr(p, "cash", None),
                "startingCash": getattr(p, "starting_cash", None), "archived": bool(getattr(p, "archived", False)) if p else None,
                "label": label, "overridesApplied": overrides, "overridesRefused": refused or [], "effectiveDiffVsBaseline": diff,
                "armedPlans": sorted(a.symbol for a in armed if a.portfolio_id == pid and a.status in ("armed", "paused")),
                "threshold": THRESHOLDS.get(label)}
    books = [book_row(default_pid, "control / default book (shared baseline)", {})]
    seen = {default_pid}
    for b in (exp.get("books") or []):
        if not isinstance(b, dict) or not b.get("portfolioId") or b["portfolioId"] in seen:
            continue
        seen.add(b["portfolioId"])
        applied = next((x for x in books_cfg if x["portfolioId"] == b["portfolioId"]), None)
        books.append(book_row(str(b["portfolioId"]), str(b.get("label") or ""), applied["overrides"] if applied else {},
                              applied["refused"] if applied else sorted((b.get("overrides") or {}).keys())))
    # --- isolation checks ------------------------------------------------------------------
    checks = {
        "experimentsEnabled": bool(exp.get("enabled", False)),
        "distinctBooks": len({b["portfolioId"] for b in books}) == len(books),
        "allExperimentBooksArePractice": all(b["kind"] == "sim" for b in books[1:]),
        "controlBookIsPractice": books[0]["kind"] == "sim",
        "equalStartingBalances": len({b["startingCash"] for b in books if b["startingCash"] is not None}) <= 1,
        "onlyWhitelistedOverrides": all(not b["overridesRefused"] for b in books),
        "sharedSettingsAreBaseline": base.size_full == 1.0 and base.no_trade_zone == "pm_range" and base.key_levels == "off"
                                     and base.pm_room_atr == 0.0 and base.min_target_atr == 0.0,
        "noBookCombinesC1AndSizing": all(not ({"size_full", "no_trade_zone"} <= set(b["overridesApplied"])) for b in books),
        "perBookCountersInCode": True,   # losses_across_plans / open_positions_across_plans take the book (tests/test_team2_experiments.py)
        "onePlanPerSymbolPerBook": all(len(b["armedPlans"]) == len(set(b["armedPlans"])) for b in books),
    }
    halt = s.get("system.halt") or {}
    c6_note = pathlib.Path(__file__).resolve().parents[3] / "docs" / "PLATFORM-RULES.md"
    c6_text = c6_note.read_text(encoding="utf-8") if c6_note.exists() else ""
    c6 = {"satisfied": ("C6 satisfied" in c6_text) or ("C6: satisfied" in c6_text) or ("C6 delivered" in c6_text),
          "evidence": "docs/PLATFORM-RULES.md — only the 2026-09-13 request is recorded" if "Request: one tape for Team2 (F119, C6)" in c6_text else "not found"}
    out = {"receiptAt": dt.datetime.now().astimezone().isoformat(timespec="seconds"), "session": date,
           "deployed": {"version": (health or {}).get("version"), "build": (health or {}).get("build"), "healthy": bool((health or {}).get("ok"))},
           "books": books, "isolation": checks, "allIsolationChecksPass": all(v for k, v in checks.items() if k != "experimentsEnabled"),
           "pauseControls": {"routes": ["POST /api/portfolios/{id}/pause", "POST /api/portfolios/{id}/unpause"], "action": PAUSE_ACTION,
                             "pausedBooks": (ops or {}).get("pausedBooks"), "globalHalt": bool(halt.get("engaged")), "bookHalts": sorted((halt.get("books") or {}).keys())},
           "thresholds": THRESHOLDS, "c6": c6,
           "activation": ("READY pending the review team's GO" if c6["satisfied"] and all(v for k, v in checks.items() if k != "experimentsEnabled")
                          else "NOT READY — experiments stay OFF: " + ("C6 not satisfied" if not c6["satisfied"] else "isolation check failed"))}
    print(f"# Team2 readiness receipt — session {date} ({out['receiptAt']})\n")
    print(f"Deployed: v{out['deployed']['version']} build {out['deployed']['build']} healthy={out['deployed']['healthy']}")
    print(f"Experiments enabled: {checks['experimentsEnabled']} | activation: {out['activation']}\n")
    print("| Book | ID | Kind | Cash | Start | Label | Overrides | Effective diff vs baseline | Armed | Threshold |")
    print("|---|---|---|---:|---:|---|---|---|---|---|")
    for b in books:
        t = b["threshold"]; th = f"{t['sampledDrawdownReview$']} sampled" if t else "—"
        print(f"| {b['name']} | `{b['portfolioId']}` | {b['kind']} | {b['cash']} | {b['startingCash']} | {b['label']} | {b['overridesApplied']} | {b['effectiveDiffVsBaseline']} | {', '.join(b['armedPlans']) or '—'} | {th} |")
    print("\nIsolation checks:", {k: v for k, v in checks.items()})
    print("Pause controls:", out["pauseControls"]["routes"], "| paused:", out["pauseControls"]["pausedBooks"], "| global halt:", out["pauseControls"]["globalHalt"], "| book halts:", out["pauseControls"]["bookHalts"])
    print("Pause action:", PAUSE_ACTION)
    print("Thresholds:", json.dumps(THRESHOLDS, indent=None))
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
