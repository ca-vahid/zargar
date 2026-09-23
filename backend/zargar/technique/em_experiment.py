"""EM Experimental (`em-experiment-v1`, 2026-09-19; user direction `2026-09-19-ACTIVE-EXPERIMENTAL-PRACTICE-ROLLOUT.md`).

ONE dedicated sim-only Practice book runs the INTEGRATED bundle actively while the existing EM Practice book stays the
unchanged baseline. Everything here is BOOK-SCOPED: a policy is resolved for the plan's book, never flipped technique-wide.

  setting   `techniques.enhanced_market.experiment` = {enabled, portfolioId, label, version, startedAt, startingEquity,
            comparisonTs, owner, overrides: {preparation_policy, conditional_review_fix, prep_grade_floor,
            first_sale_rr_gate, book_snapshot_observe, source_candidates_execute, runner_protection}}
  policy    `book_policy(get, pid, key, default)`: the override for THE experimental book, else the technique-wide setting.
            The baseline book and every other desk therefore read exactly what they read before.
  identity  every experimental plan run is MINTED with tags `experiment:<version>` + `xbook:<pid>` (runs are never
            edited). The arm guard makes the boundary two-way: a tagged run arms ONLY in the experimental book, and the
            experimental book accepts ONLY tagged runs. Orders carry the same tags.
  prepare   `prepare(svc, plan_for)`: the next session's sheet rows -> the deterministic eligibility owner (zero model
            calls) -> one deterministic plan run per eligible row -> `prep_arm` (one arm per candidate per BOOK, database
            lock) into the experimental book. Idempotent and restart-safe: a second call mints and arms nothing new.
  promote   `promote_candidates`: the order-free research objects stay order-free (`scenario:*` never arms anywhere).
            A born, still-live, unexpired candidate of TODAY's session is copied into a separately identified executable
            plan (`origin = experiment:<candidateId>`, deterministic run id, frozen single trigger, `eligibleFromTs` = now,
            `expiresTs` = the source horizon) and armed in the experimental book. It then trades through the production
            runner: live tracker, sizing, first-sale enforcement, final guard, RiskGate, production exits. Historical or
            expired candidates are never promoted; missing geometry is never fabricated.
The bundle's performance difference against the baseline cannot by itself say WHICH change caused it."""
from __future__ import annotations

import contextlib
import copy
import datetime as dt
import hashlib
import json
import logging
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .. import events as ev
from ..models import TechniqueArmed, TechniqueRun, TechniqueSourceCandidate, TechniqueSweep, TechniqueWalkforward
from . import preparation_policy as pp

log = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")
KEY = "techniques.enhanced_market.experiment"
VERSION = "em-experiment-v1"
TAG = "experiment:"
BOOK_TAG = "xbook:"
ORIGIN = "experiment:"
OVERRIDES = {"preparation_policy": ("baseline", "deterministic"), "conditional_review_fix": ("report", "apply"), "prep_grade_floor": ("A", "B", "C"),
             "first_sale_rr_gate": ("off", "observe", "enforce"), "book_snapshot_observe": (True, False),
             "source_candidates_execute": (True, False), "runner_protection": ("off", "execute")}
BUNDLE = {"preparation_policy": "deterministic", "conditional_review_fix": "apply", "prep_grade_floor": "B", "first_sale_rr_gate": "enforce",
          "book_snapshot_observe": True, "source_candidates_execute": True, "runner_protection": "execute"}
LIVE = ("waiting", "requalification_eligible")


def _h(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def config(get) -> dict:
    """The validated experiment setting. Anything invalid = NOT enabled, with the errors listed - never a silent default."""
    raw = get(KEY, None)
    out = {"enabled": False, "portfolioId": "", "label": "", "version": VERSION, "overrides": {}, "errors": []}
    if not raw:
        return out
    if not isinstance(raw, dict):
        out["errors"].append("the experiment setting must be an object")
        return out
    ov = dict(raw.get("overrides") or {})
    for k, v in ov.items():
        if k not in OVERRIDES:
            out["errors"].append(f"unknown override {k!r}")
        elif v not in OVERRIDES[k]:
            out["errors"].append(f"override {k} = {v!r} is not one of {OVERRIDES[k]}")
    pid = str(raw.get("portfolioId") or "")
    if raw.get("enabled") and not pid:
        out["errors"].append("portfolioId is required while the experiment is enabled")
    out.update({k: raw.get(k) for k in ("label", "startedAt", "startingEquity", "comparisonTs", "owner", "baselinePortfolioId")})
    out.update({"portfolioId": pid, "version": str(raw.get("version") or VERSION), "overrides": ov,
                "enabled": bool(raw.get("enabled")) and bool(pid) and not out["errors"]})
    return out


def is_book(get, portfolio_id) -> bool:
    c = config(get)
    return bool(c["enabled"] and portfolio_id and str(portfolio_id) == c["portfolioId"])


def book_policy(get, portfolio_id, key: str, default):
    """The EM policy value in force FOR THIS BOOK: the experiment's override in the experimental book, otherwise the
    technique-wide setting - so the baseline book and every other caller read exactly what they read before."""
    if portfolio_id and key in OVERRIDES:
        c = config(get)
        if c["enabled"] and str(portfolio_id) == c["portfolioId"] and key in c["overrides"]:
            return c["overrides"][key]
    return get("techniques.enhanced_market." + key, default)


def prep_policy(get, portfolio_id) -> dict:
    """`preparation_policy.effective` for one book."""
    base = pp.effective(get)
    if not is_book(get, portfolio_id):
        return base
    ov = config(get)["overrides"]
    return {**base, "preparationPolicy": ov.get("preparation_policy", base["preparationPolicy"]), "conditionalReviewFix": ov.get("conditional_review_fix", base["conditionalReviewFix"]),
            "gradeFloor": ov.get("prep_grade_floor", base["gradeFloor"]), "experiment": stamp(get)}


def stamp(get) -> dict | None:
    c = config(get)
    if not c["enabled"]:
        return None
    return {"version": c["version"], "label": c.get("label"), "portfolioId": c["portfolioId"], "overrides": dict(c["overrides"]),
            "policyVersions": {"preparation": pp.VERSION, "conditionalReview": pp.REVIEW_VERSION, "firstSale": "first-sale-v2", "bookSnapshot": "book-snapshot-v3",
                               "candidates": "source-continuation-v1", "requalification": "requalification-v1", "runnerProtection": "tp1-reclaim-runner-exit-v1"},
            "bundleHash": _h([c["version"], c["overrides"]])[:16]}


def run_tags(get) -> list:
    c = config(get)
    return [TAG + c["version"], BOOK_TAG + c["portfolioId"]] if c["enabled"] else []


def run_book(run: dict | None) -> str | None:
    """The experimental book a run was minted for (from its immutable tags), or None for an ordinary run."""
    tags = [str(t) for t in ((run or {}).get("tags") or [])]
    if not any(t.startswith(TAG) for t in tags):
        return None
    return next((t[len(BOOK_TAG):] for t in tags if t.startswith(BOOK_TAG)), "")


def arm_refusal(get, run: dict, portfolio_id: str, portfolio: dict | None) -> str | None:
    """The two-way boundary. An experimental run arms ONLY in its own enabled sim book; the experimental book accepts
    ONLY experimental runs. Everything else is untouched."""
    book = run_book(run)
    c = config(get)
    if book is not None:
        if not c["enabled"]:
            return "experimental plan: the experiment is not enabled"
        if str(portfolio_id) != c["portfolioId"] or book != c["portfolioId"]:
            return "experimental plan: it may arm only in the experimental Practice book"
        if str((portfolio or {}).get("kind") or "") != "sim":
            return "experimental plan: the experimental book must be a sim (Practice) book"
        return None
    if c["enabled"] and str(portfolio_id) == c["portfolioId"]:
        return "the experimental Practice book accepts only plans minted for the experiment"
    return None


# ------------------------------------------------------------------------------------------------------- preparation
def _arm_config(pid: str) -> dict:
    return {"portfolioId": pid, "mode": "auto"}                # every other field = the SAME runtime defaults the baseline arms with (risk limits preserved)


async def _sheet(svc, plan_for: str):
    async with svc.engine.sf() as s:
        sweeps = (await s.execute(select(TechniqueSweep).where(TechniqueSweep.status == "done").order_by(TechniqueSweep.created_at.desc()).limit(12))).scalars().all()
        sw = next((x for x in sweeps if (x.params or {}).get("kind") == "next" and str((x.params or {}).get("planFor") or "")[:10] == plan_for), None)
        if sw is None:
            return None, []
        rows = (await s.execute(select(TechniqueWalkforward).where(TechniqueWalkforward.sweep_id == sw.id).order_by(TechniqueWalkforward.symbol))).scalars().all()
    return sw, rows


async def _existing_run(svc, symbol: str, plan_for: str, tags: list) -> dict | None:
    async with svc.engine.sf() as s:
        runs = (await s.execute(select(TechniqueRun).where(TechniqueRun.symbol == symbol, TechniqueRun.trigger == "experiment", TechniqueRun.status == "done",
                                                           TechniqueRun.technique == "enhanced_market").order_by(TechniqueRun.created_at.desc()).limit(8))).scalars().all()
    for r in runs:
        plan = (r.result or {}).get("plan") or {}
        if str(plan.get("planFor") or "")[:10] == plan_for and set(tags) <= set(r.tags or []) and not str((r.config or {}).get("origin") or "").startswith(ORIGIN):
            return {"id": r.id}
    return None


async def prepare(svc, plan_for: str, *, limit: int | None = None) -> dict:
    """Deterministic preparation of ONE session for the experimental book. Zero model calls. Idempotent."""
    from .prep_service import prep_arm
    from ..marketstructure.sessions import session_bounds
    get = svc.engine.settings.get
    c = config(get)
    out = {"planFor": plan_for, "experiment": stamp(get), "sheet": None, "rows": 0, "eligible": 0, "minted": 0, "reusedRuns": 0, "armed": 0, "alreadyArmed": 0,
           "skipped": {}, "errors": [], "armedRuns": [], "modelCalls": 0}
    if not c["enabled"]:
        out["errors"].append("experiment not enabled: " + ("; ".join(c["errors"]) or "no configuration"))
        return out
    pid = c["portfolioId"]
    book = svc.engine.positions.portfolio(pid)
    if not book or str(book.get("kind")) != "sim":
        out["errors"].append("the experimental book is missing or is not a sim book")
        return out
    sw, rows = await _sheet(svc, plan_for)
    if sw is None:
        out["errors"].append(f"no finished plan sheet for {plan_for}")
        return out
    out["sheet"], out["rows"] = sw.id, len(rows)
    params = sw.params or {}
    policy = prep_policy(get, pid)
    tags = run_tags(get)
    thresholds = {**dict(params.get("thresholds") or {}), **dict(params.get("overrides") or {})} or None

    def skip(why):
        out["skipped"][why] = out["skipped"].get(why, 0) + 1
    for row in rows[: (limit or len(rows))]:
        plan = dict(row.plan or {})
        try:
            d = pp.decide(symbol=row.symbol, plan=plan, analysis=None, policy=policy, origin="experiment")
            if d.get("disposition") != "eligible":
                skip(str(d.get("disposition") or "not_eligible"))
                continue
            out["eligible"] += 1
            run = await _existing_run(svc, row.symbol, plan_for, tags)
            if run is None:
                _, close_ms = session_bounds(row.session)
                run = await svc.analyze(row.symbol, as_of_ms=close_ms + 1, primary_tf=params.get("triggerTf"), trigger="experiment", plan=True, with_vision=False,
                                        wait=True, thresholds_override=thresholds, tags=tags)
                out["minted"] += 1
            else:
                out["reusedRuns"] += 1
            rid = run["id"]
            res = await prep_arm(svc, rid, origin="experiment", policy=policy, portfolio_id=pid,
                                 arm=lambda _rid=rid: svc.arm_plan(_rid, _arm_config(pid), _prep_checked=True))
            if res["armed"]:
                out["armed"] += 1
                out["armedRuns"].append({"runId": rid, "symbol": row.symbol, "triggers": (res["decision"] or {}).get("eligibleTriggers")})
            elif res["why"] in ("already_armed", "duplicate_of_armed_candidate"):
                out["alreadyArmed"] += 1
            else:
                skip("after_mint:" + str(res["why"]))
        except Exception as exc:                           # noqa: BLE001 - one symbol never stops the batch
            out["errors"].append(f"{row.symbol}: {type(exc).__name__}: {exc}"[:200])
    return out


async def arm_ingest_run(svc, run: dict, *, source_hold: list | None, source_ids: list | None, authorized=None) -> dict:
    """The ingestion path's board plan, for the experimental book. The baseline run id belongs to the baseline arm (an armed
    plan's identity IS its run id), so the experiment gets its own immutable COPY of the run, tagged at mint, and that copy
    passes the same eligibility owner under the experimental book's policy. Idempotent (deterministic copy id)."""
    from .prep_service import prep_arm
    get = svc.engine.settings.get
    c = config(get)
    if not c["enabled"]:
        return {"armed": False, "why": "experiment not enabled"}
    pid = c["portfolioId"]
    rid = "xi" + _h([VERSION, run.get("id"), pid])[:30]
    async with svc.engine.sf() as s:
        src = await s.get(TechniqueRun, str(run.get("id") or ""))
        if src is None:
            return {"armed": False, "why": "source run not found"}
        if await s.get(TechniqueRun, rid) is None:
            s.add(TechniqueRun(id=rid, symbol=src.symbol, technique="enhanced_market", tags=[*list(src.tags or []), *run_tags(get)], as_of=src.as_of,
                               primary_tf=src.primary_tf, mode=src.mode, trigger="experiment", status="done", verdict=src.verdict, facts=dict(src.facts or {}),
                               result=copy.deepcopy(dict(src.result or {})), config={**dict(src.config or {}), "experiment": stamp(get), "copiedFromRun": src.id},
                               llm=dict(src.llm or {}), parent_run_id=src.id))
            try:
                await s.commit()
            except IntegrityError:
                await s.rollback()

    async def _arm():
        if authorized is not None and not await authorized():
            from .ingest import StaleWorker
            raise StaleWorker("lease or source no longer authorize this attempt (superseded)")
        return await svc.arm_plan(rid, _arm_config(pid), _prep_checked=True)
    out = await prep_arm(svc, rid, origin="ingest", source_hold=source_hold, source_ids=source_ids, policy=prep_policy(get, pid), portfolio_id=pid, arm=_arm)
    return {"armed": bool(out["armed"]), "why": out.get("why"), "runId": rid, "disposition": (out.get("decision") or {}).get("disposition")}


# ------------------------------------------------------------------------------------------- the promotion boundary
def promoted_run_id(candidate_id: str, pid: str) -> str:
    return "xp" + _h([VERSION, candidate_id, pid])[:30]


def executable_plan(cand: dict, birth_plan: dict | None, *, now_ms: int, stamp_: dict) -> tuple[dict | None, str | None]:
    """The frozen single-trigger plan of ONE candidate, or (None, why). Pure. Nothing is fabricated: a candidate without
    a complete app geometry, outside its horizon, not of today's session or no longer live yields no plan."""
    d = cand.get("definition") or {}
    trig = copy.deepcopy(d.get("trigger") or {})
    if cand.get("disposition") not in LIVE or not trig:
        return None, f"not live ({cand.get('disposition')})"
    entry, stop = (trig.get("entry") or {}).get("price"), ((trig.get("stop") or {}).get("price") if isinstance(trig.get("stop"), dict) else trig.get("stop"))
    targets = [x.get("price") if isinstance(x, dict) else x for x in trig.get("targets") or []]
    if entry is None or stop is None or not targets:
        return None, "geometry incomplete (entry, stop or targets missing) - unresolved, never fabricated"
    exp = d.get("expiresTs")
    if exp is None or int(exp) <= int(now_ms):
        return None, "outside the source horizon"
    born = max(int(d.get("eligibleFromTs") or 0), int(_ms(d.get("bornAt")) or 0))
    if born and born > int(now_ms):
        return None, "not yet eligible"
    session = str(d.get("session") or "")
    if session != dt.datetime.fromtimestamp(now_ms / 1000.0, ET).date().isoformat():
        return None, "not of today's session - historical candidates are never replayed into orders"
    trig.pop("origin", None)
    trig.update({"valid": True, "promotedFrom": cand.get("candidateId") or d.get("candidateId")})
    bp = birth_plan or {}
    minute = int(now_ms) // 60_000 * 60_000
    plan = {"symbol": d.get("symbol"), "planFor": session, "triggerTf": bp.get("triggerTf") or "1m", "referencePrice": bp.get("referencePrice"),
            "lastClose": bp.get("lastClose"), "builtFromMs": bp.get("builtFromMs"), "triggers": [trig], "eligibleFromTs": minute, "expiresTs": int(exp),
            "experiment": stamp_, "promotion": {"candidateId": d.get("candidateId") or d.get("childId"), "variant": d.get("variant"), "definitionHash": d.get("definitionHash"),
                                                "scenarioId": d.get("scenarioId") or d.get("parentScenarioId"), "revisionId": d.get("revisionId"), "noteId": d.get("noteId"),
                                                "author": d.get("author"), "branchKey": d.get("branchKey"), "promotedAtMs": int(now_ms),
                                                "eligibilityBasis": ("requalification-v1 frozen gates (R2, stop cap, author targets)" if d.get("variant") == "requalification"
                                                                     else "deterministic preparation policy on the aligned saved trigger")}}
    return plan, None


def _ms(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return int(v)
    try:
        x = dt.datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return int((x if x.tzinfo else x.replace(tzinfo=dt.timezone.utc)).timestamp() * 1000)
    except ValueError:
        return None


async def promote_candidates(svc, now_ms: int) -> dict:
    """Promote today's live candidates into executable experimental plans, each ONCE (deterministic run id = the claim)."""
    get = svc.engine.settings.get
    c = config(get)
    out = {"promoted": [], "covered": [], "skipped": {}, "errors": []}
    if not (c["enabled"] and c["overrides"].get("source_candidates_execute")):
        return out
    pid = c["portfolioId"]
    session = dt.datetime.fromtimestamp(now_ms / 1000.0, ET).date().isoformat()
    async with svc.engine.sf() as s:
        rows = (await s.execute(select(TechniqueSourceCandidate).where(TechniqueSourceCandidate.session == session,
                                                                       TechniqueSourceCandidate.disposition.in_(LIVE)))).scalars().all()
    armed = [a for a in _book_plans(svc, pid) if a.status in ("armed", "paused")]
    policy = prep_policy(get, pid)
    for row in rows:
        cand = dict(row.payload or {})
        cid = str(cand.get("candidateId") or row.id)
        try:
            rid = promoted_run_id(cid, pid)
            async with svc.engine.sf() as s:
                if await s.get(TechniqueRun, rid) is not None:
                    continue                                  # promoted before (this tick, an earlier tick or before a restart): never twice
                parent = await s.get(TechniqueRun, str((cand.get("definition") or {}).get("planRunId") or (cand.get("definition") or {}).get("contextRunId") or "")) \
                    if (cand.get("definition") or {}) else None
            birth_plan = ((parent.result or {}).get("plan") if parent is not None else None) or {}
            plan, why = executable_plan(cand, birth_plan, now_ms=now_ms, stamp_=stamp(get))
            if plan is None:
                out["skipped"][why] = out["skipped"].get(why, 0) + 1
                continue
            trig = plan["triggers"][0]
            if (cand.get("definition") or {}).get("variant") != "requalification":
                d = pp.decide(symbol=str(plan["symbol"]), plan=plan, analysis=None, policy=policy, origin="experiment")
                if d.get("disposition") != "eligible":
                    out["skipped"]["policy:" + str(d.get("disposition"))] = out["skipped"].get("policy:" + str(d.get("disposition")), 0) + 1
                    continue
                same = next((a for a in armed if a.symbol == plan["symbol"] and any(
                    t.get("valid") and t.get("kind") == trig.get("kind") and abs(float((t.get("entry") or {}).get("price") or 0) - float(trig["entry"]["price"])) < 1e-6
                    for t in ((a.plan or {}).get("triggers") or []))), None)
                if same is not None:                          # the prepared plan already trades this exact trigger in this book: one position, not two
                    out["covered"].append({"candidateId": cid, "byRunId": same.run_id})
                    continue
            cfg = {**dict((parent.config if parent is not None else {}) or {}), "origin": ORIGIN + cid, "experiment": plan["experiment"], "promotion": plan["promotion"]}
            run = TechniqueRun(id=rid, symbol=str(plan["symbol"]), technique="enhanced_market", tags=[*run_tags(get), "promoted:" + str(plan["promotion"]["variant"])],
                               as_of=int(now_ms), primary_tf=str(plan["triggerTf"]), mode="plan", trigger="experiment", status="done", verdict="plan",
                               result={"plan": plan, "analysis": None}, config=cfg, parent_run_id=(parent.id if parent is not None else None))
            try:
                async with svc.engine.sf() as s:
                    s.add(run)
                    await s.commit()
            except IntegrityError:
                continue                                      # another worker claimed this candidate first
            await svc.arm_plan(rid, _arm_config(pid), _prep_checked=True)
            out["promoted"].append({"candidateId": cid, "runId": rid, "symbol": plan["symbol"], "variant": plan["promotion"]["variant"]})
        except Exception as exc:                              # noqa: BLE001
            out["errors"].append(f"{cid}: {type(exc).__name__}: {exc}"[:200])
    return out


async def expire_promoted(svc, now_ms: int) -> int:
    """A promoted plan never outlives its source horizon or its source: past `expiresTs`, or once the candidate is withdrawn,
    it is disarmed - only when it holds no open or working trade (an open position keeps being managed to its exit)."""
    get = svc.engine.settings.get
    c = config(get)
    if not c["enabled"]:
        return 0
    n = 0
    for a in _book_plans(svc, c["portfolioId"]):
        plan = a.plan or {}
        promo = plan.get("promotion")
        if not promo or a.status not in ("armed", "paused"):
            continue
        if any(str(getattr(t, "status", "")) in ("open", "working", "submitting") for t in a.trades.values()):
            continue
        why = None
        if plan.get("expiresTs") and int(plan["expiresTs"]) <= int(now_ms):
            why = "source horizon expired"
        else:
            async with svc.engine.sf() as s:
                row = await s.get(TechniqueSourceCandidate, str(promo.get("candidateId") or ""))
            if row is not None and row.disposition == "source_withdrawn":
                why = "source withdrawn"
        if why:
            try:
                await svc.disarm_plan(a.run_id, flatten=False, reason="experiment: " + why)
                n += 1
            except Exception:                                 # noqa: BLE001
                log.exception("experiment: disarm of %s failed", a.run_id)
    return n


def _book_plans(svc, pid: str) -> list:
    """The EM armer's in-memory plans of ONE book (objects: `.plan`, `.trades`, `.status`, `.run_id`, `.symbol`)."""
    return [a for a in list(getattr(svc.armer, "_armed", {}).values()) if str(a.config.portfolio_id) == str(pid)]


_PREPARED: set = set()            # (book, planFor) this process has already prepared or found prepared
_PREPARING: dict = {}             # single flight


async def _already_prepared(svc, pid: str, plan_for: str) -> bool:
    async with svc.engine.sf() as s:
        runs = (await s.execute(select(TechniqueRun.tags, TechniqueRun.result, TechniqueRun.config).where(
            TechniqueRun.trigger == "experiment", TechniqueRun.technique == "enhanced_market").order_by(TechniqueRun.created_at.desc()).limit(400))).all()
    return any(BOOK_TAG + pid in (tags or []) and str(((res or {}).get("plan") or {}).get("planFor") or "")[:10] == plan_for
               and not str((cfg or {}).get("origin") or "").startswith(ORIGIN) and not (cfg or {}).get("copiedFromRun") for tags, res, cfg in runs)


async def auto_prepare(svc, now_ms: int) -> str | None:
    """The restart-safe daily preparation: once the NEXT session's sheet exists and this book has no prepared plan for it,
    run `prepare` ONCE in the background (single flight; `prepare` itself is idempotent, so a crash mid-way is finished
    by the next pass). Returns the session it started for, or None."""
    import asyncio
    from ..marketstructure import sessions as _sessions
    c = config(svc.engine.settings.get)
    if not c["enabled"]:
        return None
    pid, plan_for = c["portfolioId"], _sessions.next_session_date(int(now_ms))
    key = (pid, plan_for)
    if key in _PREPARED or key in _PREPARING:
        return None
    sw, _rows = await _sheet(svc, plan_for)
    if sw is None:
        return None
    if await _already_prepared(svc, pid, plan_for):
        _PREPARED.add(key)
        return None

    async def _run():
        try:
            out = await prepare(svc, plan_for)
            log.info("experiment: prepared %s - eligible %s, minted %s, armed %s, errors %s", plan_for, out["eligible"], out["minted"], out["armed"], len(out["errors"]))
            with contextlib.suppress(Exception):
                await svc.engine.journal.append(ev.TECHNIQUE_EXPERIMENT_PREPARED, {k: out.get(k) for k in ("planFor", "sheet", "rows", "eligible", "minted", "reusedRuns", "armed",
                                                                                                         "alreadyArmed", "skipped", "modelCalls", "experiment")} | {"errors": out["errors"][:10]},
                                                 aggregate_type="portfolio", aggregate_id=pid, portfolio_id=pid)
            if not out["errors"] or out["armed"] or out["alreadyArmed"]:
                _PREPARED.add(key)
        except Exception:                                     # noqa: BLE001
            log.exception("experiment: preparation of %s failed", plan_for)
        finally:
            _PREPARING.pop(key, None)
    _PREPARING[key] = asyncio.create_task(_run(), name="em-experiment-prepare")
    return plan_for


async def tick(svc, now_ms: int) -> dict:
    """One pass of the experiment's own loop (once a minute, never on a trading path)."""
    if not config(svc.engine.settings.get)["enabled"]:
        return {"enabled": False}
    started = await auto_prepare(svc, now_ms)
    promoted = await promote_candidates(svc, now_ms)
    return {"enabled": True, "preparing": started, "promoted": len(promoted["promoted"]), "covered": len(promoted["covered"]),
            "expired": await expire_promoted(svc, now_ms), "errors": promoted["errors"][:5]}


async def status(svc) -> dict:
    get = svc.engine.settings.get
    c = config(get)
    out = {"config": c, "stamp": stamp(get), "book": None, "baseline": None, "armed": [], "bundle": BUNDLE}
    if c["portfolioId"]:
        out["book"] = svc.engine.positions.portfolio(c["portfolioId"])
    base = str(get("techniques.enhanced_market.default_portfolio", "") or "")
    if base:
        out["baseline"] = svc.engine.positions.portfolio(base)
    for a in (_book_plans(svc, c["portfolioId"]) if c["portfolioId"] else []):
        out["armed"].append({"runId": a.run_id, "symbol": a.symbol, "planFor": a.plan_for, "status": a.status,
                             "promotion": ((a.plan or {}).get("promotion") or {}).get("variant")})
    async with svc.engine.sf() as s:
        out["armedRows"] = len((await s.execute(select(TechniqueArmed.run_id).where(TechniqueArmed.portfolio_id == c["portfolioId"],
                                                                                   TechniqueArmed.status.in_(("armed", "paused"))))).all()) if c["portfolioId"] else 0
    return out
