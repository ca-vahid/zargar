"""Frozen A/B of the INTAKE EXTRACTION model on real messages (2026-09-23, cost lever 4). Paid; guarded; read-only.

Each sampled message (caption + primary image, as production read it) is re-extracted once per arm with the
production Extractor (same prompt, same schema, same local validation). Each arm's signals are compared with the
signals production extracted from that message, on the fields that decide what the desk does:
ticker, direction, action, instrument, strike, expiry and is_actionable.

Judgement (fixed before the run): the FIRST arm is the reference (run-to-run noise). A later arm PASSES only when it
has no more MISSED actionable signals, no more CHANGED actionable signals and no more invalid replies than the
reference arm. Extra signals are reported apart. Multi-attachment messages are read with the primary image only (both
arms alike), so the comparison is between models, not a reproduction of the full multi-image path.

    python -m zargar.tools.tip_extraction_ab --arm ref=claude-opus-5-5 --arm sonnet=claude-sonnet-5 \
        --messages 40 --cap 8 --env-file C:/Cursor/zargar/backend/.env --out ex.json

The cap is an ESTIMATE-BASED spending guard: the run stops before an arm call once the priced spend so far plus the
largest call seen exceeds it. It is not a guaranteed maximum.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import sys

from .tip_cache_pilot import _load_env

VERSION = "extraction-ab-v1"
FIELDS = ("ticker", "direction", "action", "instrument", "strike", "expiry", "is_actionable")


def _norm(v):
    if isinstance(v, float):
        return round(v, 4)
    if isinstance(v, str):
        return v.strip().upper()
    return v


def sig_key(s: dict) -> tuple:
    return tuple(_norm(s.get(f)) for f in FIELDS)


def compare(prod: list[dict], cand: list[dict]) -> dict:
    """Pure. Matching on (ticker, action) identity, then field equality."""
    rest = list(cand)
    missed, changed = [], []
    for p in prod:
        exact = next((c for c in rest if sig_key(c) == sig_key(p)), None)
        if exact is not None:
            rest.remove(exact)
            continue
        same = next((c for c in rest if _norm(c.get("ticker")) == _norm(p.get("ticker"))
                     and _norm(c.get("action")) == _norm(p.get("action"))), None)
        if same is None:
            missed.append(p)
            continue
        rest.remove(same)
        changed.append({"ticker": p.get("ticker"), "prodActionable": bool(p.get("is_actionable")),
                        "fields": {f: {"prod": p.get(f), "cand": same.get(f)}
                                   for f in FIELDS if _norm(p.get(f)) != _norm(same.get(f))}})
    act = lambda s: bool(s.get("is_actionable"))  # noqa: E731
    return {"exact": not missed and not changed and not rest,
            "missedActionable": sum(1 for m in missed if act(m)), "missed": len(missed),
            "changedActionable": sum(1 for c in changed if c["prodActionable"]),
            "changed": len(changed), "extra": len(rest), "extraActionable": sum(1 for r in rest if act(r)),
            "detail": {"missed": missed, "changed": changed, "extra": rest}}


def verdict(ref: dict, arm: dict) -> dict:
    checks = {"missedActionable": arm["missedActionable"] <= ref["missedActionable"],
              "changedActionable": arm["changedActionable"] <= ref["changedActionable"],
              "invalid": arm["invalid"] <= ref["invalid"]}
    return {"pass": all(checks.values()), "checks": checks}


def usd(u: dict, rate: dict) -> float:
    return (u["in"] / 1e6 * rate["in"] + u["out"] / 1e6 * rate["out"]
            + u["cacheRead"] / 1e6 * rate.get("cacheRead", 0) + u["cacheWrite"] / 1e6 * rate.get("cacheWrite", 0))


async def load_messages(db: str, n: int) -> list[dict]:
    import asyncpg
    c = await asyncpg.connect(db, server_settings={"default_transaction_read_only": "on"})
    try:
        with_sig = await c.fetch("""select r.id, r.source_name, r.subject, r.body_text, r.meta, r.received_at
                                    from raw_content r where r.status = 'extracted'
                                      and exists (select 1 from signals s where s.raw_content_id = r.id)
                                    order by r.received_at desc limit $1""", n * 3 // 4)
        without = await c.fetch("""select r.id, r.source_name, r.subject, r.body_text, r.meta, r.received_at
                                   from raw_content r where r.status = 'extracted'
                                     and not exists (select 1 from signals s where s.raw_content_id = r.id)
                                   order by r.received_at desc limit $1""", n - len(with_sig))
        out = []
        for r in list(with_sig) + list(without):
            meta = r["meta"] if isinstance(r["meta"], dict) else json.loads(r["meta"] or "{}")
            aid = next((a.get("assetId") for a in (meta.get("attachments") or []) if a.get("assetId")), None) \
                or meta.get("imageAssetId")
            img = await c.fetchval("select data from chat_assets where id = $1", aid) if aid else None
            sigs = await c.fetch("""select extraction from signals where raw_content_id = $1 order by created_at""", r["id"])
            prod = []
            for s in sigs:
                ex = s["extraction"] if isinstance(s["extraction"], dict) else json.loads(s["extraction"] or "{}")
                if ex.get("signal"):
                    prod.append(ex["signal"])
            out.append({"id": r["id"], "source": r["source_name"], "subject": r["subject"] or "",
                        "text": r["body_text"] or "", "image": bytes(img) if img else None,
                        "receivedAt": r["received_at"].isoformat() if r["received_at"] else "", "prod": prod})
        return out
    finally:
        await c.close()


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="postgresql://zargar:zargar@127.0.0.1:5433/zargar")
    ap.add_argument("--arm", action="append", required=True, help="name=model")
    ap.add_argument("--messages", type=int, default=40)
    ap.add_argument("--cap", type=float, default=8.0)
    ap.add_argument("--effort", default="high")
    ap.add_argument("--env-file", default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    arms = [dict(zip(("name", "model"), x.split("=", 1))) for x in a.arm]
    _load_env(a.env_file)
    key = os.environ.get("ZARGAR_ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        print("no API key (pass --env-file)"); return 2
    import asyncpg
    from ..signals.extraction import Extractor
    c = await asyncpg.connect(a.db, server_settings={"default_transaction_read_only": "on"})
    try:
        v = await c.fetchval("select value from settings where key = 'llm.rates'")
    finally:
        await c.close()
    rates = json.loads(v) if isinstance(v, str) else v
    rates = rates.get("v", rates)
    if any(not rates.get(x["model"]) for x in arms):
        print("an arm's model has no llm.rates entry - refusing an unpriced paid run"); return 2
    msgs = await load_messages(a.db, a.messages)
    spent, biggest, stopped = 0.0, 0.0, None
    res = {x["name"]: {"missedActionable": 0, "changedActionable": 0, "missed": 0, "changed": 0, "extra": 0,
                       "extraActionable": 0, "exact": 0, "invalid": 0, "n": 0, "usd": 0.0} for x in arms}
    rows = []
    for m in msgs:
        row = {"id": m["id"], "source": m["source"], "prodSignals": len(m["prod"])}
        for x in arms:
            if spent + biggest > a.cap:
                stopped = f"spending guard: ${spent:.2f} spent, next call could exceed ${a.cap:.2f}"
                break
            calls: list[dict] = []

            async def ledger(**kw):
                r = kw.get("resp")
                u = getattr(r, "usage", None)
                calls.append({"in": int(getattr(u, "input_tokens", 0) or 0), "out": int(getattr(u, "output_tokens", 0) or 0),
                              "cacheRead": int(getattr(u, "cache_read_input_tokens", 0) or 0),
                              "cacheWrite": int(getattr(u, "cache_creation_input_tokens", 0) or 0)} if u else
                             {"in": 0, "out": 0, "cacheRead": 0, "cacheWrite": 0})

            class _S(dict):
                def get(self, k, d=None):
                    return super().get(k, d)
            ex = Extractor(key, x["model"], settings=_S({"techniques.tip.extraction_effort": a.effort}), ledger=ledger)
            try:
                out = await ex.extract(m["text"], subject=m["subject"], source_name=m["source"] or "",
                                       received_at=m["receivedAt"], image=m["image"])
                cand = [s.model_dump() for s in out.signals] if out.outcome == "ok" else None
            except Exception as exc:                          # a provider failure is a measured outcome
                cand, out = None, None
                row[x["name"] + "Error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
            cost = sum(usd(u, rates[x["model"]]) for u in calls)
            spent += cost
            biggest = max(biggest, cost)
            g = res[x["name"]]
            g["n"] += 1
            g["usd"] = round(g["usd"] + cost, 4)
            if cand is None:
                g["invalid"] += 1
                row[x["name"]] = {"invalid": True}
                continue
            cmp_ = compare(m["prod"], cand)
            for k in ("missedActionable", "changedActionable", "missed", "changed", "extra", "extraActionable"):
                g[k] += cmp_[k]
            g["exact"] += 1 if cmp_["exact"] else 0
            row[x["name"]] = {k: cmp_[k] for k in ("exact", "missedActionable", "changedActionable", "extra")} | {"detail": cmp_["detail"]}
        rows.append(row)
        print(m["id"][:8], m["source"], " ".join(f"{x['name']}:{'exact' if (row.get(x['name']) or {}).get('exact') else 'diff'}"
                                                 for x in arms), flush=True)
        if stopped:
            break
    ref = arms[0]["name"]
    verdicts = {x["name"]: verdict(res[ref], res[x["name"]]) for x in arms[1:]}
    outp = {"version": VERSION, "at": dt.datetime.now(dt.timezone.utc).isoformat(), "effort": a.effort, "messages": len(rows),
            "arms": {x["name"]: {**res[x["name"]], "model": x["model"]} for x in arms}, "verdicts": verdicts,
            "spentUsd": round(spent, 4), "capUsd": a.cap, "stopped": stopped, "rows": rows}
    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            json.dump(outp, fh, indent=1, default=str)
    print(json.dumps({k: outp[k] for k in ("arms", "verdicts", "spentUsd", "stopped")}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
