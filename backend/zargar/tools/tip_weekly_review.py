"""Weekly Tips decision review: one page from the existing reports (ADV-12, 2026-09-23). Read-only.

Runs, with ONE window, the tools the desk already trusts and stitches their headline sections: the scorecard (primary
metric, how positions ended, source return net of model cost, friction), dispositions, the relevance-gate report, the
knowledge ledger, the overnight carry study and the shadow-book audit - plus the research switches that are ON, so
each one is justified by a question or switched off. It decides nothing; the decisions are logged by a human in
TRADING-RULES with the evidence cited.

    python -m zargar.tools.tip_weekly_review --since 2026-09-21 --until 2026-09-25 [--out path.md]
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import subprocess
import sys

RESEARCH_SWITCHES = [
    ("techniques.tip.review_gate", "relevance filter - observe until the five-session report"),
    ("techniques.tip.review_capture_context", "captures review requests for the cheaper-model / context evaluations"),
    ("techniques.tip.frozen_capture_context", "captures appraisal requests for frozen replays"),
    ("techniques.tip.entry_cohort_enabled", "entry-timing cohort (every eligible idea, delayed samples)"),
    ("techniques.tip.hold_study_enabled", "hold study: 15:50 + next-open samples (feeds the overnight carry study)"),
    ("techniques.tip.mk_ownbook_mode", "MK own-book (off | observe | shadow)"),
    ("techniques.tip.prompt_cache", "prompt caching (cost only)"),
    ("techniques.tip.prompt_cache_scope", "prefix | conversation"),
    ("techniques.tip.review_context", "full | compact (compact measured unsafe 2026-09-23)"),
    ("techniques.tip.review_source_budgets", "per-source review budgets"),
    ("techniques.tip.max_book_exposure_pct", "book exposure cap"),
    ("techniques.tip.max_name_exposure_pct", "name exposure cap"),
    ("techniques.tip.shares_alternative", "equal-risk share size on infeasible option cards"),
    ("techniques.tip.friction_flag_pct", "friction flag on cards"),
]

SECTIONS = {  # tool -> headings to keep (prefix match)
    "scorecard": ["## Reconciliation", "## How closed positions ended", "## Source return net of model cost",
                  "## Friction and exposure", "## Model operating cost by stage"],
}


def pick_sections(md: str, prefixes: list[str]) -> str:
    out, keep = [], False
    for line in md.splitlines():
        if line.startswith("## "):
            keep = any(line.startswith(p) for p in prefixes)
        if keep:
            out.append(line)
    return "\n".join(out)


def headline(md: str, n: int = 16) -> str:
    """The first `n` lines, stopping before the report's first `## ` section (those are picked explicitly)."""
    out = []
    for line in md.splitlines()[:n]:
        if line.startswith("## ") and out:
            break
        out.append(line)
    return "\n".join(out)


def run(python: str, args: list[str]) -> tuple[int, str]:
    p = subprocess.run([python, "-m", *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.returncode, p.stdout


async def switches(db: str) -> list[tuple[str, str, str]]:
    import asyncpg
    from ..settings_service import DEFAULTS
    c = await asyncpg.connect(db, server_settings={"default_transaction_read_only": "on"})
    try:
        rows = {r["key"]: r["value"] for r in await c.fetch("select key, value from settings where key = any($1::text[])",
                                                               [k for k, _ in RESEARCH_SWITCHES])}
    finally:
        await c.close()
    out = []
    for k, why in RESEARCH_SWITCHES:
        v = rows.get(k)
        if v is not None:
            v = json.loads(v) if isinstance(v, str) else v
            v = v.get("v") if isinstance(v, dict) and "v" in v else v
        else:
            v = DEFAULTS.get(k)
        out.append((k, json.dumps(v, default=str), why))
    return out


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="postgresql://zargar:zargar@127.0.0.1:5433/zargar")
    ap.add_argument("--since", required=True)
    ap.add_argument("--until", required=True)
    ap.add_argument("--out", default=None)
    ap.add_argument("--python", default=sys.executable)
    a = ap.parse_args()
    py, s, u = a.python, a.since, a.until
    L = [f"# Tips weekly decision review - {s} to {u}\n", f"Generated {dt.datetime.now(dt.timezone.utc).isoformat()[:19]}Z. "
         "Read-only; decisions are a human's, logged in TRADING-RULES with the evidence cited.\n"]
    failures = []
    code, sc = run(py, ["zargar.tools.tip_scorecard", "--since", s, "--until", u])
    (failures.append("scorecard") if code else None)
    L += ["## 1. Scorecard (primary metric first)\n", headline(sc, 30), "", pick_sections(sc, SECTIONS["scorecard"])]
    for title, args in (("2. Opportunity dispositions", ["zargar.tools.tip_outcomes", "--dispositions", "--since", s, "--until", u]),
                        ("3. Relevance filter (observe)", ["zargar.tools.tip_review_gate_eval", "--since", s, "--until", u, "--prospective"]),
                        ("4. Intake coverage", ["zargar.tools.tip_outcomes", "--coverage", "--since", s, "--until", u]),
                        ("5. Overnight carry", ["zargar.tools.tip_overnight_study"]),
                        ("6. Knowledge ledger", ["zargar.tools.tip_knowledge_ledger"]),
                        ("7. Shadow-book integrity", ["zargar.tools.tip_shadow_audit"])):
        code, md = run(py, args)
        if code:
            failures.append(title)
        L += [f"\n## {title}\n", headline(md, 40)]
    L.append("\n## 8. Research switches (each must answer a question or be switched off)\n")
    L.append("| setting | value | why it exists |\n|---|---|---|")
    for k, v, why in await switches(a.db):
        L.append(f"| `{k}` | {v} | {why} |")
    if failures:
        L.append(f"\n**Report failures: {', '.join(failures)}** - the sections above for them are incomplete.")
    text = "\n".join(L) + "\n"
    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            fh.write(text)
    print(text)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
