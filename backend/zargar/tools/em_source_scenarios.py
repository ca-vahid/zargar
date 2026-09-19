"""EM source report (integrated plan A + C): what the authors said, what we planned, which gate decided, and the order-free
candidates (source continuation + requalification) replayed causally on the session's bars. READ-ONLY; zero model calls.

    python -m zargar.tools.em_source_scenarios report --date 2026-09-18 [--corrections FILE] [--no-yahoo] [--stdout]

Scenarios are built on the fly from the immutable revision / transcript / extraction rows (nothing is stored by this
command; storing is the ingestion path's job behind `source_scenarios_observe`). `--corrections` applies an append-only
reviewed corrections file as a SEPARATE, later-usable layer: a corrected scenario is usable from its correction time, so
the report never presents a retrospective fix as knowledge the app had on the trading day. Outcomes are the UNDERLYING
walk-forward proxy - never option fills, never the author's result (which is unknown).
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import gzip
import json
import os
from zoneinfo import ZoneInfo

import asyncpg

from ..marketstructure.outcome import rows_to_bars
from ..technique import preparation_policy as pp
from ..technique import source_candidate_policy as scp
from ..technique import source_scenarios as ss
from ..technique.walkforward import build_profile, plan_window
from . import em_prep_ablation as abl

NY = ZoneInfo("America/New_York")
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
OUT_DIR = os.path.join(ROOT, "docs", "techniques", "enhanced-market", "research", "source-scenarios")
J = abl.J
GATE_TYPES = ("TechniquePlanArmed", "TechniquePlanTriggerSkipped", "TechniquePlanTriggerFired", "TechniquePlanDisarmed", "TechniquePlanPositionOpened")


def _hm(ts) -> str:
    if ts is None:
        return "-"
    d = dt.datetime.fromtimestamp(int(ts) / 1000, NY) if isinstance(ts, (int, float)) else dt.datetime.fromisoformat(str(ts).replace(" ", "T", 1)).astimezone(NY)
    return d.strftime("%H:%M")


async def build(date: str, *, allow_yahoo: bool, corrections: list | None) -> dict:
    c = await asyncpg.connect(abl._db_url())
    await c.execute("set transaction read only")
    try:
        day = dt.date.fromisoformat(date)
        a = dt.datetime(day.year, day.month, day.day, 0, 0, tzinfo=NY); b = a + dt.timedelta(days=1)
        notes = await c.fetch("select * from technique_method_notes where posted_at >= $1 and posted_at < $2 order by posted_at", a, b)
        universe = set()
        payloads = []
        for n in notes:
            revs = await c.fetch("select * from technique_source_revisions where note_id=$1 order by revision", n["id"])
            arts = await c.fetch("select id, revision_id, kind, completed_at, payload from technique_source_artifacts where note_id=$1 order by created_at", n["id"])
            if not revs:
                continue
            rev = revs[-1]
            ex = [x for x in arts if x["kind"] == "extraction" and x["revision_id"] == rev["id"]]
            tr = [x for x in arts if x["kind"] == "transcript"]
            if not ex:
                continue
            src = {"note": {"id": n["id"], "kind": n["kind"], "messageId": n["message_id"], "channelId": n["channel_id"], "channelName": n["channel_name"], "author": n["author"]},
                   "revision": {"id": rev["id"], "revision": rev["revision"], "kind": rev["kind"], "authorId": rev["author_id"], "authorName": rev["author_name"], "text": rev["text"],
                                "publishedAt": rev["published_at"], "receivedAt": rev["received_at"], "deleted": rev["deleted"]},
                   "transcript": ({"artifactId": tr[-1]["id"], "text": J(tr[-1]["payload"]).get("text"), "completedAt": tr[-1]["completed_at"]} if tr else None),
                   "extraction": {"artifactId": ex[-1]["id"], "payload": J(ex[-1]["payload"]), "completedAt": ex[-1]["completed_at"]}}
            p = ss.build_scenarios(src)
            p["boardCheck"] = J(n["board_check"])
            payloads.append(p)
        corrected = []
        if corrections:
            for p in payloads:
                mine = [x for x in corrections if x.get("noteId") == (p.get("note") or {}).get("id")]
                if mine:
                    corrected.append(ss.apply_corrections(p, mine, corrected_at=mine[0].get("correctedAt"), corrected_by=mine[0].get("correctedBy", "review")))
        symbols = sorted({(sc.get("symbol") or {}).get("resolved") for p in payloads + corrected for sc in p.get("scenarios") or []} - {None})
        plans, bars, profiles, thresholds, prev_close, baseline, events = {}, {}, {}, {}, {}, {}, {}
        for sym in symbols:
            runs = await c.fetch("""select id, created_at, trigger, config, result->'plan' p, result->'analysis' an from technique_runs where symbol=$1 and technique='enhanced_market' and status='done'
                                    and created_at >= $2 and created_at < $3 order by created_at""", sym, a - dt.timedelta(hours=20), b)
            plans[sym] = [{"runId": r["id"], "createdAt": r["created_at"].isoformat(), "trigger": r["trigger"], "plan": J(r["p"]), "analysis": J(r["an"]) or None, "config": J(r["config"])}
                          for r in runs if str(J(r["p"]).get("planFor") or "")[:10] == date]
            sb, _src = await abl._session_bars(c, sym, date, allow_yahoo=allow_yahoo)
            bars[sym] = sb
            last = plans[sym][-1] if plans[sym] else None
            if last:
                thresholds[sym] = abl._thresholds(last["config"])
                prev_close[sym] = float(last["plan"].get("referencePrice") or last["plan"].get("lastClose") or 0) or None
                aid = last["config"].get("barsAssetId")
                blob = await c.fetchval("select data from chat_assets where id=$1", aid) if aid else None
                if blob:
                    snap = json.loads(gzip.decompress(blob).decode("utf-8"))
                    by_tf = {tf: rows_to_bars(sym, tf, rows) for tf, rows in (snap.get("bars") or {}).items()}
                    ttf = last["plan"].get("triggerTf") or "1m"
                    built_ms = int(last["plan"].get("builtFromMs") or 0) or None
                    try:
                        profiles[sym] = build_profile((plan_window(by_tf, built_ms) if built_ms else by_tf).get(ttf) or [])
                    except Exception:
                        profiles[sym] = None
            for pl in plans[sym]:
                ev = await c.fetch("select ts, type, payload from events where aggregate_id=$1 and type = any($2::text[]) order by ts", pl["runId"], list(GATE_TYPES))
                events[pl["runId"]] = [{"ts": e["ts"].isoformat(), "type": e["type"].replace("TechniquePlan", ""), "trigger": J(e["payload"]).get("trigger"),
                                        "reason": J(e["payload"]).get("reason") or J(e["payload"]).get("why")} for e in ev]
                kinds = {t.get("id"): t for t in pl["plan"].get("triggers") or []}
                for e in events[pl["runId"]]:
                    if e["type"] == "TriggerSkipped" and e.get("reason") in ("invalidated", "gap_void", "gapped_past", "gapped_through", "exhausted"):
                        t = kinds.get(e.get("trigger")) or {}
                        baseline.setdefault(sym, []).append({"runId": pl["runId"], "trigger": e["trigger"], "status": e["reason"],
                                                             "direction": t.get("direction") or ("short" if t.get("kind") in ("reject", "breakdown") else "long"),
                                                             "ts": int(dt.datetime.fromisoformat(e["ts"]).timestamp() * 1000), "entry": (t.get("entry") or {}).get("price")})
    finally:
        await c.close()
    policy = {"preparationPolicy": "baseline", "gradeFloor": "B", "conditionalReviewFix": "report"}

    def table(pls):
        rows = []
        for p in pls:
            for sc in p.get("scenarios") or []:
                sym = (sc.get("symbol") or {}).get("resolved")
                ms = []
                for pl in plans.get(sym) or []:
                    m = ss.match_plan(sc, p, pl["plan"], plan_built_at=pl["createdAt"], plan_origin=pl["trigger"])
                    d = pp.decide(symbol=sym, plan=pl["plan"], analysis=pl.get("analysis"), policy=policy, origin=pl["trigger"], run_id=pl["runId"])
                    ms.append({"runId": pl["runId"], "origin": pl["trigger"], "createdAt": pl["createdAt"], "match": m, "modelReview": d["modelReview"], "baselineDisposition": d["disposition"],
                               "deterministic": pp.decide(symbol=sym, plan=pl["plan"], analysis=None, policy={**policy, "preparationPolicy": "deterministic"}, origin=pl["trigger"])["disposition"],
                               "events": events.get(pl["runId"], [])})
                rows.append({"author": (p.get("author") or {}).get("displayName"), "usableAt": ss.usable_at(sc, p), "scenario": sc, "plans": ms})
        return rows
    cands = scp.evaluate_session(payloads=payloads, plans_by_symbol=plans, bars_by_symbol=bars, baseline_by_symbol=baseline, session=date,
                                 thresholds_by_symbol=thresholds, profiles_by_symbol=profiles, prev_close_by_symbol=prev_close)
    cands_corr = scp.evaluate_session(payloads=corrected, plans_by_symbol=plans, bars_by_symbol=bars, baseline_by_symbol=baseline, session=date,
                                      thresholds_by_symbol=thresholds, profiles_by_symbol=profiles, prev_close_by_symbol=prev_close) if corrected else []
    diags = []
    for sym, pls in plans.items():
        for pl in pls:
            for e in events.get(pl["runId"], []):
                t = next((x for x in pl["plan"].get("triggers") or [] if x.get("id") == e.get("trigger")), None)
                if e["type"] == "TriggerSkipped" and "volume surge" in str(e.get("reason") or "") and t and bars.get(sym):
                    diags.append({"symbol": sym, **scp.exclusion_diagnostic(f"{sym} {e['trigger']} volume exclusion ({e['reason']})", t, bars[sym], thresholds=thresholds.get(sym),
                                                                           profile=profiles.get(sym), prev_close=prev_close.get(sym), relax="volume")})
            for t in pl["plan"].get("triggers") or []:
                why = " ".join(t.get("noTradeReasons") or [])
                if not t.get("valid") and "R2" in why and t.get("riskReward") and float(t["riskReward"]) >= 2.5 and bars.get(sym):
                    diags.append({"symbol": sym, **scp.exclusion_diagnostic(f"{sym} {t['id']} R2 rejection at {t['riskReward']}R", t, bars[sym], thresholds=thresholds.get(sym),
                                                                           profile=profiles.get(sym), prev_close=prev_close.get(sym))})
    seen = set()
    diags = [d for d in diags if not (d["exclusion"] in seen or seen.add(d["exclusion"]))]
    return {"date": date, "asOf": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "versions": {"scenarios": ss.VERSION, "matcher": ss.MATCHER_VERSION, "candidates": scp.VERSION,
            "requalification": scp.rq.VERSION, "policy": pp.VERSION}, "rows": table(payloads), "correctedRows": table(corrected), "candidates": [scp.table_row(x, x.get("baseline")) for x in cands],
            "candidatesAfterCorrection": [scp.table_row(x, x.get("baseline")) for x in cands_corr], "diagnostics": diags,
            "avoid": [{"author": (p.get("author") or {}).get("displayName"), **v} for p in payloads for v in p.get("avoid") or []],
            "barsCoverage": {s: len(v) for s, v in bars.items()}, "corrections": corrections or []}


def _row_md(r: dict) -> str:
    sc = r["scenario"]; sup, app = sc["authorSupplied"], sc["appDerived"]
    best = next((p for p in r["plans"] if p["match"]["alignedTrigger"]), (r["plans"] or [None])[-1])
    gate = "-"
    if best:
        ev = [e for e in best["events"] if e["type"] != "Armed"]
        armed = any(e["type"] == "Armed" for e in best["events"])
        gate = ("armed; " if armed else "not armed; ") + ("; ".join(f"{e.get('trigger') or ''} {e.get('reason') or e['type']} {_hm(e['ts'])}".strip() for e in ev[:4]) or "no trigger event")
    trig = "; ".join(f"{t['trigger']} {t['kind']}@{t['level']}{'' if t['valid'] else ' (rejected)'}: {t['verdict'].replace('_', ' ')}" for t in (best["match"]["triggers"] if best else []))
    sym = sc["symbol"]["resolved"] or f"{sup['symbolAsExtracted']} ({sc['symbol']['status']})"
    return (f"| {r['author']} | {_hm(r['usableAt'])} | {sym} | {sup['direction']}{' (pair)' if sc.get('pairId') else ''} | {sup['condition'] or '-'} | {app['level'] if app['level'] is not None else 'unknown'} | "
            f"{'/'.join(f'{x:g}' for x in app['underlyingTargets']) or 'unknown'} | {', '.join(o['raw'] for o in sup['optionMentions']) or '-'} | {sc['disposition'].replace('_', ' ')}"
            f"{' [' + '; '.join(sc['flags']) + ']' if sc['flags'] else ''} | {(best['match']['overall'].replace('_', ' ') + ' (' + best['origin'] + ')') if best else 'no plan'} | "
            f"{(best['modelReview'] + ' / baseline ' + best['baselineDisposition'] + ' / deterministic ' + best['deterministic']) if best else '-'} | {trig or '-'} | {gate} |")


def render(d: dict) -> str:
    L = [f"# EM source-to-plan report - {d['date']}", "",
         f"Generated {d['asOf']} (RETROSPECTIVE; read-only; zero model calls). Versions: {d['versions']}. `Usable` is when every input the scenario needed had actually completed "
         "(revision receipt, transcript, extraction) - never the message timestamp. The author's own trading result is UNKNOWN: no entry/exit ledger exists in the captured material, "
         "and platform P&L is not his result. Outcomes below are the underlying walk-forward PROXY, never option fills.", "",
         "## 1. What was said, what we planned, which gate decided (as the app could have known it on the day)", "",
         "| Author | Usable ET | Symbol | Side | Condition (author) | Level | Underlying targets | Option mentions | Source status | Plan match | Model review / policy | Every trigger of the matched plan | Gate events |",
         "|---|---|---|---|---|---:|---|---|---|---|---|---|---|"]
    L += [_row_md(r) for r in d["rows"]]
    if d["avoid"]:
        L += ["", "Authors passed on: " + ", ".join(f"{v['symbol']} ({v['status'].replace('_', ' ')}, {v['author']})" for v in d["avoid"]) + "."]
    L += ["", "## 2. Order-free candidates (replayed causally; nothing arms)", "",
          "| Author | Variant | Symbol | Side | Entry | Stop | Targets | Disposition | Why | Fired ET | Underlying proxy | Baseline triggers |", "|---|---|---|---|---:|---:|---|---|---|---|---|---|"]
    for c in d["candidates"]:
        L.append(f"| {c.get('author') or '-'} | {c['variant']} | {c.get('symbol') or 'unresolved'} | {c.get('direction')} | {c.get('entry') or 'unknown'} | {c.get('stop') or 'unknown'} | "
                 f"{'/'.join(str(x) for x in (c.get('targets') or [])) or 'unknown'} | {str(c['disposition']).replace('_', ' ')} | {(c.get('reason') or '')[:150]} | {_hm(c.get('firedTs'))} | "
                 f"{(str(c.get('outcomeProxy')) + ' ' + str(c.get('rProxy')) + 'R') if c.get('outcomeProxy') else '-'} | {', '.join(str(b['trigger']) + ' ' + str(b['status']) + ' ' + _hm(b.get('ts')) for b in (c.get('baseline') or [])) or '-'} |")
    L += ["", "Bars coverage (1m bars per symbol; 0 = the candidate stays `waiting`, never guessed): " + ", ".join(f"{k} {v}" for k, v in sorted(d["barsCoverage"].items())) + "."]
    if d["diagnostics"]:
        L += ["", "## 3. Named baseline exclusions - cost and benefit (HINDSIGHT, one path each; no threshold is changed)", "",
              "| Exclusion | Relaxed | Status | Outcome | R | Benefit of excluding | Cost of excluding |", "|---|---|---|---|---:|---:|---:|"]
        L += [f"| {x['exclusion']} | {x['relaxed'] or 'as-is'} | {x['status']} | {x['outcome']} | {x['rMultiple']} | {x['benefitOfExclusion']} | {x['costOfExclusion']} |" for x in d["diagnostics"]]
    if d["correctedRows"]:
        L += ["", "## 4. After the reviewed corrections (a SEPARATE layer - usable only from the correction time, NOT knowledge of the trading day)", "",
              "| Author | Usable ET | Symbol | Side | Condition (author) | Level | Underlying targets | Option mentions | Source status | Plan match | Model review / policy | Every trigger of the matched plan | Gate events |",
              "|---|---|---|---|---|---:|---|---|---|---|---|---|---|"]
        L += [_row_md(r) for r in d["correctedRows"] if r["scenario"].get("correction")]
        L += ["", "Corrections applied (append-only): " + "; ".join(f"{x['match']['symbolAsExtracted']} -> {x['set'].get('resolvedSymbol')} ({x.get('reason')})" for x in d["corrections"]) + "."]
    L += ["", f"Reproduce: `python -m zargar.tools.em_source_scenarios report --date {d['date']}` (read-only)."]
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("report"); r.add_argument("--date", required=True); r.add_argument("--corrections"); r.add_argument("--no-yahoo", action="store_true"); r.add_argument("--stdout", action="store_true")
    a = ap.parse_args(argv)
    corr = json.load(open(a.corrections, encoding="utf-8")) if a.corrections else None
    d = asyncio.run(build(a.date, allow_yahoo=not a.no_yahoo, corrections=corr))
    md = render(d)
    os.makedirs(OUT_DIR, exist_ok=True)
    json.dump(d, open(os.path.join(OUT_DIR, f"{a.date}.json"), "w", encoding="utf-8"), indent=1, default=str)
    open(os.path.join(OUT_DIR, f"{a.date}.md"), "w", encoding="utf-8", newline="\n").write(md)
    print(md if a.stdout else f"wrote {OUT_DIR}/{a.date}.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
