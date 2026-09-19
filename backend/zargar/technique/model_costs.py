"""EM model-cost accounting (`model-costs-v1`, 2026-09-18; integrated plan workstream B). Pure.

A DATED, CONFIGURABLE pricing table (`llm.pricing_table`, a list of rows) prices token usage. Four kinds of money are
kept apart and never summed into one another: invoice-verified, estimated (tokens x a dated list price), unknown (no
price configured, or a request whose completion never arrived) and a subscription allocation. Nothing here invents a
price: with no matching row the cost is UNKNOWN and the tokens are still reported. An interrupted request is never free.

Pricing row: {"provider": "anthropic", "model": "claude-opus-5", "from": "2026-09-01", "to": null,
              "inputPerMTok": 0.0, "outputPerMTok": 0.0, "cacheReadPerMTok": 0.0, "cacheWritePerMTok": 0.0,
              "source": "where this price came from", "verifiedAt": "2026-09-18"}
"""
from __future__ import annotations

import datetime as dt

VERSION = "model-costs-v1"
TOKEN_KEYS = ("input", "output", "cacheRead", "cacheWrite")
_RATE = {"input": "inputPerMTok", "output": "outputPerMTok", "cacheRead": "cacheReadPerMTok", "cacheWrite": "cacheWritePerMTok"}


def _date(v) -> dt.date | None:
    if v in (None, ""):
        return None
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    try:
        return dt.date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def price_row(table, provider: str, model: str, at) -> dict | None:
    """The row in force for (provider, model) on the date - the latest `from` not after it, inside any `to`."""
    day = _date(at)
    best = None
    for r in table or []:
        if str(r.get("model") or "") != str(model or "") or str(r.get("provider") or "anthropic") != str(provider or "anthropic"):
            continue
        f, t = _date(r.get("from")), _date(r.get("to"))
        if day is None or f is None or f > day or (t is not None and day > t):
            continue
        if best is None or f > _date(best.get("from")):
            best = r
    return best


def estimate(usage: dict | None, *, provider: str, model: str, at, table) -> dict:
    u = {k: int((usage or {}).get(k) or 0) for k in TOKEN_KEYS}
    row = price_row(table, provider, model, at)
    if row is None:
        return {"status": "unknown", "why": f"no dated price configured for {provider}/{model}", "usd": None, "tokens": u}
    missing = [k for k in TOKEN_KEYS if u[k] and row.get(_RATE[k]) is None]
    if missing:
        return {"status": "unknown", "why": "price row has no rate for " + ",".join(missing), "usd": None, "tokens": u}
    usd = sum(u[k] * float(row.get(_RATE[k]) or 0.0) for k in TOKEN_KEYS) / 1_000_000.0
    return {"status": "estimated", "usd": round(usd, 6), "tokens": u,
            "basis": {"from": row.get("from"), "source": row.get("source"), "verifiedAt": row.get("verifiedAt")}}


def summarize(requests: list, *, table, invoices: list | None = None, subscription: dict | None = None) -> dict:
    """`requests` = [{runId, pass?, provider, model, at, status: completed|failed|interrupted|started, attempts, usage}].
    A request without a completion (`failed` / `interrupted` / `started`) is counted and its cost is UNKNOWN."""
    tokens = {k: 0 for k in TOKEN_KEYS}
    est_usd, est_n, unk_n, retries, incomplete = 0.0, 0, 0, 0, 0
    unknown_why: dict[str, int] = {}
    by_model: dict[str, dict] = {}
    for r in requests or []:
        retries += max(0, int(r.get("attempts") or 1) - 1)
        key = f"{r.get('provider') or 'anthropic'}/{r.get('model') or '?'}"
        m = by_model.setdefault(key, {"requests": 0, "tokens": {k: 0 for k in TOKEN_KEYS}, "estimatedUsd": 0.0, "unknownRequests": 0})
        m["requests"] += 1
        if str(r.get("status") or "completed") != "completed":
            incomplete += 1; unk_n += 1; m["unknownRequests"] += 1
            unknown_why["request_without_completion"] = unknown_why.get("request_without_completion", 0) + 1
            continue
        e = estimate(r.get("usage"), provider=r.get("provider") or "anthropic", model=r.get("model") or "", at=r.get("at"), table=table)
        for k in TOKEN_KEYS:
            tokens[k] += e["tokens"][k]; m["tokens"][k] += e["tokens"][k]
        if e["status"] == "estimated":
            est_usd += e["usd"]; est_n += 1; m["estimatedUsd"] = round(m["estimatedUsd"] + e["usd"], 6)
        else:
            unk_n += 1; m["unknownRequests"] += 1
            unknown_why[e["why"]] = unknown_why.get(e["why"], 0) + 1
    inv = [i for i in (invoices or []) if i.get("usd") is not None]
    return {"version": VERSION, "requests": len(requests or []), "retries": retries, "requestsWithoutCompletion": incomplete, "tokens": tokens,
            "invoiceVerified": {"usd": (round(sum(float(i["usd"]) for i in inv), 2) if inv else None), "invoices": len(inv)},
            "estimated": {"usd": (round(est_usd, 4) if est_n else None), "requests": est_n},
            "unknown": {"requests": unk_n, "why": unknown_why},
            "subscriptionAllocation": ({"usd": subscription.get("usd"), "basis": subscription.get("basis")} if subscription else None),
            "byModel": by_model,
            "note": "the four categories are never added together; unknown is not zero; R multiples are never converted into cost"}


def requests_from_runs(runs: list) -> list:
    """Model requests from saved `technique_runs` rows ({id, created_at, status, llm, usage, result}). A run that asked for
    a model review but has no recorded usage (failed / still running / killed) is one request WITHOUT a completion."""
    out = []
    for r in runs or []:
        llm = r.get("llm") or {}
        res = r.get("result") or {}
        ledger = res.get("modelRequests") or []
        if ledger:
            for q in ledger:
                out.append({"runId": r.get("id"), "pass": q.get("pass"), "provider": q.get("provider") or llm.get("provider") or "anthropic",
                            "model": q.get("model") or llm.get("model"), "at": q.get("startedAt") or r.get("created_at"), "status": q.get("status"),
                            "attempts": q.get("attempts") or 1, "usage": q.get("usage")})
            continue
        passes = res.get("passes") or []
        usage = r.get("usage") or res.get("usage") or {}
        asked = bool(passes) or any(int((usage or {}).get(k) or 0) for k in TOKEN_KEYS) or bool(res.get("visionRequested"))
        if not asked:
            continue
        if passes:
            for p in passes:
                out.append({"runId": r.get("id"), "pass": p.get("name"), "provider": llm.get("provider") or "anthropic", "model": llm.get("model"),
                            "at": r.get("created_at"), "status": "completed", "attempts": 1, "usage": p.get("usage")})
        else:
            done = str(r.get("status")) == "done" and any(int((usage or {}).get(k) or 0) for k in TOKEN_KEYS)
            out.append({"runId": r.get("id"), "pass": None, "provider": llm.get("provider") or "anthropic", "model": llm.get("model"), "at": r.get("created_at"),
                        "status": ("completed" if done else "interrupted"), "attempts": 1, "usage": (usage if done else None)})
    return out
