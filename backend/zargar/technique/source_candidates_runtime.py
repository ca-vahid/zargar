"""EM source-candidate forward evaluator (integrated plan C, 2026-09-18). ORDER-FREE, default OFF
(`techniques.enhanced_market.source_candidates_observe`).

Once a minute during the regular session it re-derives every candidate of TODAY's scenario artifacts from closed bars
(`source_candidate_policy.evaluate_session` - the same pure evaluator the replay tool uses) and upserts one row per
candidate in `technique_source_candidates`. State is a pure function of (definition, closed bars), so a restart
resumes by re-deriving: nothing is skipped, nothing is counted twice, and no candidate is ever created by a path that
could arm it (origin `scenario:*` - the runner refuses it). Reads: scenario artifacts, today's saved ingest / batch
plans, the `bars` table, the armer's BASELINE tracker states (read-only). No chain fetch, no model, no order."""
from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import hashlib
import json
import logging
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from ..marketstructure.outcome import rows_to_bars
from ..models import TechniqueRun, TechniqueSourceArtifact, TechniqueSourceCandidate, TechniqueSourceRevision
from . import source_candidate_policy as scp

log = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")
KNOB = "techniques.enhanced_market.source_candidates_observe"
MAX_CANDIDATES = 40


def _h(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def baseline_states(armer) -> dict:
    """The BASELINE trackers' states per symbol - read-only views, never the tracker objects themselves."""
    out: dict = {}
    for ap in list(getattr(armer, "_armed", {}).values()):
        for tid, tr in (getattr(ap, "trackers", None) or {}).items():
            if not (tr.trigger or {}).get("valid", True):
                continue
            ev = tr.events[-1] if tr.events else {}
            out.setdefault(ap.symbol, []).append({"runId": ap.run_id, "trigger": tid, "direction": tr.direction, "status": tr.status,
                                                  "ts": ev.get("ts"), "entry": float(tr.entry)})
    return out


_CTX_CACHE: dict = {}          # run id -> (thresholds, profile, prev_close); a run is immutable, so is its context


async def plan_context(svc, run: dict) -> tuple:
    """(thresholds, volume profile, prev close) a saved plan was built with - from the run's own config and saved bars
    snapshot. Cached per run id (runs never change). Any failure = (None, None, None): volume stays unknown, never guessed."""
    rid = run.get("runId")
    if rid in _CTX_CACHE:
        return _CTX_CACHE[rid]
    out = (None, None, None)
    try:
        import dataclasses
        import gzip
        from ..models import ChatAsset
        from .rulebook import DEFAULT_THRESHOLDS
        from .walkforward import build_profile, plan_window
        cfg, plan = run.get("config") or {}, run.get("plan") or {}
        names = {f.name for f in dataclasses.fields(DEFAULT_THRESHOLDS)}
        th = dataclasses.replace(DEFAULT_THRESHOLDS, **{k: (tuple(v) if isinstance(v, list) else v) for k, v in (cfg.get("thresholds") or {}).items() if k in names})
        prof = None
        aid = cfg.get("barsAssetId")
        if aid:
            async with svc.engine.sf() as s:
                asset = await s.get(ChatAsset, aid)
            if asset is not None and asset.data:
                snap = json.loads(gzip.decompress(asset.data).decode("utf-8"))
                ttf = plan.get("triggerTf") or "1m"
                by_tf = {tf: rows_to_bars(run.get("symbol") or "", tf, rows) for tf, rows in (snap.get("bars") or {}).items()}
                built = int(plan.get("builtFromMs") or 0) or None
                prof = build_profile(((plan_window(by_tf, built) if built else by_tf).get(ttf)) or [])
        out = (th, prof, float(plan.get("referencePrice") or plan.get("lastClose") or 0) or None)
    except Exception:                                      # noqa: BLE001
        log.exception("source candidates: plan context failed for %s", rid)
    if len(_CTX_CACHE) > 400:
        _CTX_CACHE.clear()
    _CTX_CACHE[rid] = out
    return out


async def authoritative_payloads(session, *, since: dt.datetime, as_of: dt.datetime) -> tuple[list, dict]:
    """The scenario payloads that are AUTHORITATIVE as of `as_of`, one per source message:
      - the message's CURRENT revision = the highest revision RECEIVED by `as_of` (an edit, a correction or a delete that
        arrives later does not exist yet - so a replay after later revisions reproduces what was knowable then)
      - a deleted (tombstoned) message has NO actionable scenario
      - only artifacts OF that current revision count, the newest first (a reviewed correction supersedes its base); an older
        revision's artifact is never independently actionable, even when the new revision has no scenarios yet
    Returns (payloads, withdrawn) where withdrawn = {scenarioId: reason} for every scenario of a superseded or deleted
    revision - the caller closes their FUTURE research eligibility and touches nothing else."""
    arts = (await session.execute(select(TechniqueSourceArtifact).where(TechniqueSourceArtifact.kind == "scenarios", TechniqueSourceArtifact.completed_at >= since,
                                                                        TechniqueSourceArtifact.completed_at <= as_of)
                                  .order_by(TechniqueSourceArtifact.completed_at, TechniqueSourceArtifact.created_at))).scalars().all()
    by_note: dict = {}
    for art in arts:
        by_note.setdefault(art.note_id, []).append(art)
    payloads, withdrawn = [], {}
    for note_id, mine in by_note.items():
        cur = (await session.execute(select(TechniqueSourceRevision).where(TechniqueSourceRevision.note_id == note_id, TechniqueSourceRevision.received_at <= as_of)
                                     .order_by(TechniqueSourceRevision.revision.desc()).limit(1))).scalars().first()
        current = [x for x in mine if cur is not None and x.revision_id == cur.id and not cur.deleted]
        chosen = current[-1] if current else None
        why = ("source deleted" if (cur is not None and cur.deleted) else "superseded by a newer source revision" if cur is not None else "no revision on record")
        for art in mine:
            if art is chosen:
                continue
            for sc in (art.payload or {}).get("scenarios") or []:
                withdrawn[str(sc.get("scenarioId"))] = (why if art.revision_id != getattr(cur, "id", None) or (cur is not None and cur.deleted) else "superseded by a reviewed correction")
        if chosen is not None:
            payloads.append(dict(chosen.payload or {}))
            for sc in (chosen.payload or {}).get("scenarios") or []:
                withdrawn.pop(str(sc.get("scenarioId")), None)
    return payloads, withdrawn


async def load_inputs(svc, session_day: str, as_of_ms: int | None = None) -> dict:
    day0 = dt.datetime.fromisoformat(session_day).replace(tzinfo=ET)
    o_ms, c_ms = int(day0.replace(hour=9, minute=30).timestamp() * 1000), int(day0.replace(hour=16).timestamp() * 1000)
    as_of = dt.datetime.fromtimestamp(as_of_ms / 1000.0, dt.timezone.utc) if as_of_ms is not None else dt.datetime.now(dt.timezone.utc)
    async with svc.engine.sf() as s:
        payloads, withdrawn = await authoritative_payloads(s, since=day0.astimezone(dt.timezone.utc) - dt.timedelta(hours=6), as_of=as_of)
        symbols = sorted({(sc.get("symbol") or {}).get("resolved") for p in payloads for sc in p.get("scenarios") or []} - {None})
        plans, bars = {}, {}
        for sym in symbols:
            runs = (await s.execute(select(TechniqueRun).where(TechniqueRun.symbol == sym, TechniqueRun.technique == "enhanced_market", TechniqueRun.status == "done",
                                                               TechniqueRun.created_at >= day0.astimezone(dt.timezone.utc) - dt.timedelta(hours=20),
                                                               TechniqueRun.created_at <= as_of)
                                    .order_by(TechniqueRun.created_at))).scalars().all()
            plans[sym] = [{"runId": r.id, "symbol": sym, "createdAt": r.created_at.isoformat(), "trigger": r.trigger, "plan": (r.result or {}).get("plan") or {},
                           "config": r.config or {}}
                          for r in runs if str(((r.result or {}).get("plan") or {}).get("planFor") or "")[:10] == session_day]
            rows = (await s.execute(text("select ts, open, high, low, close, volume from bars where symbol=:s and tf='1m' and ts >= :a and ts < :b order by ts"),
                                    {"s": sym, "a": o_ms, "b": c_ms})).mappings().all()
            bars[sym] = rows_to_bars(sym, "1m", [[r["ts"], r["open"], r["high"], r["low"], r["close"], r["volume"]] for r in rows])
    ctx_run = {}
    for sym, pls in plans.items():
        for pl in pls:                                     # EVERY saved plan keeps its OWN thresholds / profile / previous close (cached per immutable run)
            ctx_run[pl["runId"]] = await plan_context(svc, pl)
    return {"payloads": payloads, "withdrawn": withdrawn, "plans": plans, "bars": bars, "contextByRun": ctx_run}


CHAIN_KNOB = "techniques.enhanced_market.source_candidates_chain_fetch"
EVIDENCE_WINDOW_MS = 180_000


def pricing_rules(svc, now_ms: int) -> dict:
    """The frozen production numbers the pricing stage evaluates (read once per pass from settings; never tuned here)."""
    g = svc.engine.settings.get
    friday = dt.datetime.fromtimestamp(now_ms / 1000.0, ET).weekday() == 4
    return {"riskPct": float(g("technique.arm.risk_pct", 2.0) or 2.0), "premiumStopPct": float(g("techniques.enhanced_market.premium_stop_pct", g("technique.arm.premium_stop_pct", 50.0)) or 50.0),
            "maxSpreadPct": 10.0, "maxPremiumNotional": float(g("risk.max_option_premium_notional", 1000.0) or 0.0), "maxPremiumPct": float(g("risk.max_option_premium_pct", 5.0) or 0.0),
            "maxContracts": int(g("risk.max_option_contracts", 10) or 10), "minRiskReward": float(g("technique.min_risk_reward", 3.0) or 3.0),
            "singleExit": str(g("technique.arm.single_contract_exit", "tp2") or "tp2"),
            "feePerContract": float(g("options.fee_per_contract", 0.99) or 0.0) + float(g("sim.reg_fee_per_contract", 0.05) or 0.0),
            "maxQuoteAgeMs": int(float(g("risk.stale_quote_seconds", 10) or 10) * 1000),
            "fridayMult": (float(g("technique.arm.friday_size_mult", 0.5) or 1.0) if friday else 1.0),
            "avoid0dteAfterMin": _hhmm(g("technique.arm.avoid_0dte_after", "10:30"), 630)}


def _hhmm(v, default: int) -> int:
    try:
        hh, mm = (int(x) for x in str(v).split(":"))
        return hh * 60 + mm
    except Exception:                                      # noqa: BLE001
        return default


async def portfolio_constraints(svc, cand: dict, contract: dict | None, contract_quote: dict | None, equity, rules: dict, now_ms: int) -> dict:
    """The book's CURRENT constraints for this candidate, snapshotted at the evaluation - never an order, never a row:
      riskVerdict          `RiskGate.evaluate` itself (the production function: kill switch, book halt / pause, daily-loss
                           limit, exposure and position caps, premium caps, cash) on a DRY intent for the sized quantity.
                           It reads caches only; `OrderManager.place` is never called, so no order, journal or budget entry exists
      tradingHalted        `engine.trading_halted(book)` (all four halt scopes)
      symbolOpenOrWorking  EM trades open or working on the candidate's underlying / maxOpenTrades (the per-plan slot rule)
      reservedPremium      premium of EM entry orders still working (cash the book has not yet given up)
    Anything that cannot be read is None: the pure stage reports it as unknown."""
    eng = svc.engine
    out = {"atMs": int(now_ms), "riskVerdict": None, "tradingHalted": None, "symbolOpenOrWorking": None, "maxOpenTrades": None, "reservedPremium": None}
    pid = str(eng.settings.get("techniques.enhanced_market.default_portfolio", "") or eng.settings.get("technique.arm.default_portfolio", "") or "")
    if not pid:
        return out
    with contextlib.suppress(Exception):
        out["tradingHalted"] = eng.trading_halted(pid) or False
    armer = getattr(svc, "armer", None)
    with contextlib.suppress(Exception):
        n, reserved = 0, 0.0
        for ap in list(getattr(armer, "_armed", {}).values()):
            if str(ap.config.portfolio_id) != pid:
                continue
            for tr in ap.trades.values():
                live = str(getattr(tr, "status", "")) in ("open", "working", "pending", "submitting")
                if live and ap.symbol == cand.get("symbol"):
                    n += 1
                if str(getattr(tr, "status", "")) in ("working", "pending", "submitting"):
                    reserved += float(getattr(tr, "qty", 0) or 0) * float(getattr(tr, "limit_price", 0) or getattr(tr, "last_price", 0) or 0) * float(getattr(tr, "multiplier", 1.0) or 1.0)
        out["symbolOpenOrWorking"], out["reservedPremium"] = n, round(reserved, 2)
        out["maxOpenTrades"] = int(armer.rt("max_open_trades", 1) or 1)
    ask = (contract_quote or {}).get("ask")
    if contract and contract.get("symbol") and ask and equity is not None:
        try:
            from types import SimpleNamespace
            from ..orders import OrderIntent
            n = scp.size_contracts(equity=float(equity), ask=float(ask), rules=rules)["contracts"]
            if n >= 1:
                book = eng.positions.portfolio(pid) or {}
                intent = OrderIntent(portfolio_id=pid, symbol=str(contract["symbol"]), sec_type="OPT", side="BUY", qty=float(n), order_type="LMT",
                                     limit_price=round(float(ask), 2), dry_run=True, source="technique", technique_id="enhanced_market")
                verdict = await asyncio.wait_for(eng.risk.evaluate(intent, SimpleNamespace(kind=book.get("kind"), cash=book.get("cash"))), timeout=2.0)
                out["riskVerdict"] = {"passed": bool(verdict.passed), "qty": float(n), "checks": [c.to_dict() for c in verdict.checks]}
        except Exception as exc:                           # noqa: BLE001 - unknown stays unknown
            out["riskError"] = f"{type(exc).__name__}: {exc}"[:160]
    return out


async def gather_evidence(svc, cand: dict, now_ms: int, rules: dict | None = None) -> dict:
    """CONTEMPORANEOUS evidence for one newly triggered candidate, on the candidates' own task (never an entry or exit
    path). Cached quotes only by default; a contract is looked up ONLY when `source_candidates_chain_fetch` is on - one
    BACKGROUND-priority chain read (it stands down during a provider cooldown and is never retried) plus one bounded NBBO
    reprice. No model. Whatever is missing stays missing: the pricing stage reports it as unknown."""
    from .research_recorder import feed_identity, quote_evidence
    eng = svc.engine
    sym = str(cand.get("symbol") or "")
    ev: dict = {"underlier": quote_evidence(eng.quotes.get(sym), symbol=sym, is_option=False, feed=feed_identity(eng)), "contract": None, "contractQuote": None,
                "equity": None, "cash": None, "chainFetch": bool(eng.settings.get(CHAIN_KNOB, False))}
    pid = str(eng.settings.get("techniques.enhanced_market.default_portfolio", "") or eng.settings.get("technique.arm.default_portfolio", "") or "")
    try:
        if pid:
            ev["equity"] = float(await asyncio.wait_for(eng.positions.equity(pid), timeout=2.0))
            ev["cash"] = float((eng.positions.portfolio(pid) or {}).get("cash"))
    except Exception:                                      # noqa: BLE001 - unknown stays unknown
        pass
    if ev["chainFetch"] and sym:
        try:
            from ..options.chain import cboe_priority
            spot = (ev["underlier"] or {}).get("last") or (cand.get("geometry") or {}).get("entry")
            tg = (cand.get("geometry") or {}).get("targets") or []
            cap = float(tg[1] if len(tg) >= 2 else tg[0]) if tg else None
            short = cand.get("direction") == "short"
            with cboe_priority("background"):
                pick = await asyncio.wait_for(svc.option_pick(sym, "short" if short else "long", spot=float(spot) if spot else None,
                                                              max_strike=(None if short else cap), min_strike=(cap if short else None)), timeout=6.0)
            if pick and pick.get("available") and pick.get("symbol"):
                contract = {k: pick.get(k) for k in ("symbol", "strike", "expiry", "optionType", "delta", "dte", "openInterest", "bid", "ask")}
                if getattr(eng, "options", None) is not None:
                    with contextlib.suppress(Exception):
                        await asyncio.wait_for(eng.options.reprice(contract), timeout=2.5)
                ev["contract"] = contract
                ev["contractQuote"] = quote_evidence(eng.quotes.get(contract["symbol"]), symbol=contract["symbol"], is_option=True, feed=None)
        except Exception as exc:                           # noqa: BLE001
            ev["chainError"] = f"{type(exc).__name__}: {exc}"[:160]
    ev["constraints"] = await portfolio_constraints(svc, cand, ev.get("contract"), ev.get("contractQuote"), ev.get("equity"), rules or pricing_rules(svc, now_ms), now_ms)
    ev["observedAtMs"] = int(now_ms)                       # evidence is evidence for ITS observation time - never for an earlier instant
    return ev


async def attach_pricing(svc, cands: list, stored: dict, now_ms: int) -> None:
    """Pricing gates are decided ONCE, at the trigger: a stored evaluation is carried forward untouched; a candidate that
    triggered within the evidence window and has none yet is evaluated now; an older trigger with no evaluation stays
    unknown (the evaluator was not watching at the time) - evidence is never back-filled."""
    rules = None
    for c in cands:
        if c.get("disposition") != "triggered" or not c.get("firedTs"):
            continue
        prior = ((stored.get(str(c.get("candidateId"))) or {}).get("pricingGates")) or None
        if prior and prior.get("evaluatedAt"):
            c["pricingGates"] = prior
            continue
        age = int(now_ms) - (int(c["firedTs"]) + 60_000)
        if 0 <= age <= EVIDENCE_WINDOW_MS:
            rules = rules or pricing_rules(svc, now_ms)
            c["pricingGates"] = scp.pricing_gates(c, await gather_evidence(svc, c, now_ms, rules), now_ms=now_ms, rules=rules)
            c["pricingGates"]["observedAfterTriggerMs"] = age      # how long after the confirming close this evidence was observed
        else:
            c["pricingGates"] = {**scp.pricing_gates(c, None), "why": "the trigger was not observed within the evidence window - nothing is back-filled"}


async def tick(svc, now_ms: int) -> dict:
    """One evaluation pass. Returns counts; never raises into the caller's loop."""
    if not bool(svc.engine.settings.get(KNOB, False)):
        return {"enabled": False}
    now = dt.datetime.fromtimestamp(now_ms / 1000.0, ET)
    if now.weekday() >= 5 or not ((9, 30) <= (now.hour, now.minute) < (16, 5)):
        return {"enabled": True, "rth": False}
    session_day = now.date().isoformat()
    inp = await load_inputs(svc, session_day, as_of_ms=now_ms)
    async with svc.engine.sf() as s:
        rows = (await s.execute(select(TechniqueSourceCandidate).where(TechniqueSourceCandidate.session == session_day))).scalars().all()
    stored = {r.id: dict(r.payload or {}) for r in rows}
    cands = scp.evaluate_session(payloads=inp["payloads"], plans_by_symbol=inp["plans"], bars_by_symbol=inp["bars"],
                                 baseline_by_symbol=baseline_states(svc.armer), session=session_day, upto_ts=now_ms,
                                 context_by_run=inp["contextByRun"], frozen=stored)[:MAX_CANDIDATES]
    await attach_pricing(svc, cands, stored, now_ms)
    changed = await persist(svc, session_day, cands, now_ms)
    closed = await withdraw(svc, session_day, inp["withdrawn"], now_ms)
    return {"enabled": True, "rth": True, "candidates": len(cands), "changed": changed, "withdrawn": closed}


async def withdraw(svc, session_day: str, withdrawn: dict, now_ms: int) -> int:
    """A source that was edited, corrected or deleted loses its FUTURE research eligibility: its candidates that are not yet
    terminal become `source_withdrawn`. A terminal candidate (it triggered, was refused, expired...) is HISTORY and is kept
    untouched. Nothing here reaches a production plan, position or order."""
    if not withdrawn:
        return 0
    n = 0
    now = dt.datetime.fromtimestamp(now_ms / 1000.0, dt.timezone.utc)
    async with svc.engine.sf() as s:
        rows = (await s.execute(select(TechniqueSourceCandidate).where(TechniqueSourceCandidate.session == session_day,
                                                                       TechniqueSourceCandidate.scenario_id.in_(list(withdrawn))).with_for_update())).scalars().all()
        for row in rows:
            if row.disposition in scp.TERMINAL_DISPOSITIONS:
                continue
            p = dict(row.payload or {})
            hist = list(p.get("history") or []) + [{"at": now_ms, "disposition": "source_withdrawn"}]
            p.update({"disposition": "source_withdrawn", "reason": withdrawn.get(row.scenario_id), "withdrawnAt": now_ms, "history": hist})
            row.payload, row.disposition, row.updated_at = p, "source_withdrawn", now
            row.state_hash = _h({"withdrawn": now_ms, "id": row.id})
            n += 1
        await s.commit()
    return n


async def persist(svc, session_day: str, cands: list, now_ms: int) -> int:
    """Upsert by candidate id; a row is rewritten only when its state changed, and every transition is kept in
    `payload.history` (at, disposition) - the record of WHEN the app knew what."""
    changed = 0
    now = dt.datetime.fromtimestamp(now_ms / 1000.0, dt.timezone.utc)
    async with svc.engine.sf() as s:
        for c in cands:
            cid = str(c.get("candidateId"))
            slim = {k: v for k, v in c.items() if k not in ("trackerEvents",)}
            sh = _h({**{k: slim.get(k) for k in ("disposition", "reason", "firedTs", "geometry", "structure")}, "pricing": (slim.get("pricingGates") or {}).get("overall"),
                     "pricedAt": (slim.get("pricingGates") or {}).get("evaluatedAt")})   # never the bar counter: a quiet minute rewrites nothing
            row = await s.get(TechniqueSourceCandidate, cid, with_for_update=True)
            if row is None:
                try:
                    async with s.begin_nested():           # two workers may create the same candidate: the second insert is the SAME observation
                        s.add(TechniqueSourceCandidate(id=cid, session=session_day, symbol=str(c.get("symbol") or ""), scenario_id=str(c.get("scenarioId") or c.get("parentScenarioId") or ""),
                                                       variant=str(c.get("variant") or ""), disposition=str(c.get("disposition") or ""), state_hash=sh,
                                                       payload={**slim, "history": [{"at": now_ms, "disposition": c.get("disposition")}]}, created_at=now, updated_at=now))
                        await s.flush()
                    changed += 1
                    continue
                except IntegrityError:
                    row = await s.get(TechniqueSourceCandidate, cid, with_for_update=True)
                    if row is None:
                        raise
            prior = dict(row.payload or {})
            if row.disposition in scp.TERMINAL_DISPOSITIONS:
                # a terminal candidate is never re-decided; only the after-the-fact outcome proxy may be re-scored
                upd = {k: slim[k] for k in scp.OUTCOME_KEYS + ("replayDisagreement",) if k in slim and slim.get(k) != prior.get(k)}
                if upd and slim.get("disposition") == row.disposition:
                    row.payload, row.updated_at = {**prior, **upd}, now
                    changed += 1
                continue
            if prior.get("definition") and (slim.get("definition") or {}).get("definitionHash") != (prior["definition"] or {}).get("definitionHash"):
                # the FIRST definition stands: a later tick / restart / re-plan cannot move the stop, the targets or the entry
                slim = {**slim, **{k: v for k, v in prior["definition"].items() if k != "definitionHash"}, "definition": prior["definition"],
                        "reinterpretationIgnored": {"at": now_ms, "offeredHash": (slim.get("definition") or {}).get("definitionHash")}}
                sh = _h({**{k: slim.get(k) for k in ("disposition", "reason", "firedTs", "geometry", "structure")}, "pricing": (slim.get("pricingGates") or {}).get("overall"),
                         "pricedAt": (slim.get("pricingGates") or {}).get("evaluatedAt")})
            offered = (slim.get("reinterpretationIgnored") or {}).get("offeredHash")
            if row.state_hash != sh or (offered and (prior.get("reinterpretationIgnored") or {}).get("offeredHash") != offered):
                hist = list((row.payload or {}).get("history") or [])
                if not hist or hist[-1].get("disposition") != c.get("disposition"):
                    hist.append({"at": now_ms, "disposition": c.get("disposition")})
                row.payload, row.disposition, row.state_hash, row.updated_at = {**slim, "history": hist}, str(c.get("disposition") or ""), sh, now
                changed += 1
        await s.commit()
    return changed


async def list_candidates(svc, session_day: str) -> list:
    async with svc.engine.sf() as s:
        rows = (await s.execute(select(TechniqueSourceCandidate).where(TechniqueSourceCandidate.session == session_day)
                                .order_by(TechniqueSourceCandidate.symbol, TechniqueSourceCandidate.variant))).scalars().all()
    return [{**scp.table_row(dict(r.payload or {}), baseline=(r.payload or {}).get("baseline")), "history": (r.payload or {}).get("history"),
             "updatedAt": r.updated_at.isoformat() if r.updated_at else None} for r in rows]
