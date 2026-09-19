"""EM source-conditioned candidates (`source-continuation-v1`, 2026-09-18; integrated plan workstream C). ORDER-FREE.

Two separately identified research variants that consume workstream A's scenarios and workstream B's policy record:

  source_continuation   the author's OWN branch (symbol, direction, level, family), evaluated with app geometry taken
                        from the saved deterministic plan's trigger that the matcher calls `aligned`. No aligned trigger
                        = no app geometry = held (nothing is invented). An aligned trigger our gates rejected (AMD 2.97R)
                        stays a NAMED refusal with a cost/benefit diagnostic - the threshold is never lowered.
  requalification       `requalification-v1` (see requalification.py): fresh structure after an early invalidation.

Every candidate carries `origin = scenario:<id>`: `PlanRunner.arm` refuses that origin (the Delivery B order-free
boundary), so no API, ingestion, reuse or restore path can arm one. The evaluator owns its OWN `TriggerTracker`
instances - the baseline tracker state is never reset, reused or overwritten; baseline outcomes are reported in parallel.

State is a pure function of (candidate definition, closed bars so far): persistence stores the definition and the last
bar consumed; resume re-derives the state from the session's bars, so a restart can neither skip nor double-count.

UI dispositions: waiting | triggered | invalidated | requalification_eligible | held_for_missing_evidence | refused | expired.
"""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
from zoneinfo import ZoneInfo

from ..marketstructure.tracker import TriggerTracker, score_trigger
from . import requalification as rq
from .rulebook import DEFAULT_THRESHOLDS, Thresholds

VERSION = "source-continuation-v1"
DISPOSITIONS = ("waiting", "triggered", "invalidated", "requalification_eligible", "held_for_missing_evidence", "refused", "expired", "source_withdrawn")
TERMINAL_DISPOSITIONS = ("triggered", "invalidated", "refused", "expired", "source_withdrawn")     # never overwritten by a later interpretation
OUTCOME_KEYS = ("outcomeProxy",)                                                                   # what happened AFTERWARDS may still be scored
NY = ZoneInfo("America/New_York")
MORNING_EXPIRY_ET = (11, 30)          # `source-morning-expiry-v1`: a morning-rundown idea with no stated horizon ends at 11:30 ET


def _h(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def candidate_id(scenario_id: str, session: str) -> str:
    return "sc1-" + _h([VERSION, scenario_id, session])[:20]


def source_expiry_ts(session: str, horizon: str | None) -> tuple[int | None, str]:
    """When the SOURCE idea stops being actionable in-session (app convention, labelled). `swing` ideas are out of scope
    for the intraday evaluator; an unstated or `open` horizon ends at 11:30 ET; `0dte` lasts the session."""
    d = dt.date.fromisoformat(session)
    if horizon == "swing":
        return None, "swing: not evaluated intraday (separately declared horizon required)"
    from ..marketstructure.market_calendar import is_trading_day, session_close_minutes
    if not is_trading_day(d):
        return None, "not a trading session on the exchange calendar - held"
    close = int(session_close_minutes(d))                     # 16:00, or 13:00 on a shortened session
    hh, mm = divmod(close, 60) if horizon == "0dte" else MORNING_EXPIRY_ET
    if hh * 60 + mm > close:
        hh, mm = divmod(close, 60)
    return int(dt.datetime(d.year, d.month, d.day, hh, mm, tzinfo=NY).timestamp() * 1000), ("source-session-expiry-v1" if horizon == "0dte" else "source-morning-expiry-v1")


def branch_key(scenario: dict, payload: dict) -> str:
    """The author's BRANCH, independent of the message revision: note + symbol + direction + position on the board. An edit
    makes new scenario ids; it does not make a second branch (and so not a second requalified child)."""
    return "br1-" + _h([(payload.get("note") or {}).get("id"), (scenario.get("symbol") or {}).get("resolved") or scenario["authorSupplied"].get("symbolAsExtracted"),
                        scenario["authorSupplied"].get("direction"), scenario.get("index")])[:20]


def birth_plan(plans: list, usable_ms: int | None, upto_ts: int | None) -> tuple[dict | None, str]:
    """The saved plan a source idea is judged with is the one AVAILABLE AT ITS BIRTH - never the latest plan of the symbol:
    the newest plan built at or before the source became usable; when none existed yet, the FIRST plan built afterwards.
    A later same-session re-plan never reinterprets an earlier idea. Plans built after `upto_ts` do not exist yet."""
    seen = [p for p in plans or [] if upto_ts is None or (_ms(p.get("createdAt")) or 0) <= int(upto_ts)]
    seen.sort(key=lambda p: _ms(p.get("createdAt")) or 0)
    if not seen:
        return None, "no saved plan existed yet"
    if usable_ms is None:
        return seen[0], "source usable time unknown: the first saved plan"
    before = [p for p in seen if (_ms(p.get("createdAt")) or 0) <= int(usable_ms)]
    return (before[-1], "the newest plan at the source's usable time") if before else (seen[0], "the first plan built after the source became usable")


def build_candidate(*, scenario: dict, payload: dict, match: dict | None, plan: dict | None, policy_record: dict | None, session: str) -> dict:
    """ONE source-continuation candidate for ONE scenario branch. Pure; chooses nothing from later outcomes."""
    sid = scenario["scenarioId"]
    sup, app, sym = scenario["authorSupplied"], scenario["appDerived"], (scenario.get("symbol") or {})
    expires, exp_der = source_expiry_ts(session, app.get("horizon"))
    base = {"version": VERSION, "variant": "source_continuation", "candidateId": candidate_id(sid, session), "scenarioId": sid, "pairId": scenario.get("pairId"),
            "branchKey": branch_key(scenario, payload), "revisionId": (payload.get("revision") or {}).get("id"),
            "origin": f"scenario:{sid}", "orderFree": True, "session": session, "symbol": sym.get("resolved"), "direction": sup.get("direction"),
            "author": (payload.get("author") or {}).get("displayName"), "noteId": (payload.get("note") or {}).get("id"),
            "source": {"condition": sup.get("condition"), "level": app.get("level"), "family": app.get("family"), "targets": app.get("underlyingTargets"),
                       "stop": None, "usableAt": (scenario.get("correction") or {}).get("usableAt") or (payload.get("times") or {}).get("usableAt"),
                       "stance": scenario.get("stance")},
            "expiresTs": expires, "expiryDerivation": exp_der,
            "policy": ({"mode": policy_record.get("mode"), "version": policy_record.get("version"), "disposition": policy_record.get("disposition"),
                        "eligibleTriggers": policy_record.get("eligibleTriggers")} if policy_record else None)}
    if scenario.get("disposition") != "candidate_source" or not sym.get("resolved"):
        return {**base, "disposition": "held_for_missing_evidence", "reason": "source held for resolution: " + "; ".join(scenario.get("heldReasons") or [sym.get("status") or "unresolved"])}
    if expires is None:
        return {**base, "disposition": "held_for_missing_evidence", "reason": exp_der}
    aligned = [r for r in (match or {}).get("triggers") or [] if r.get("verdict") == "aligned"]
    if not aligned:
        why = "no app geometry: the saved plan has no trigger on the author's side at his level" + ("" if app.get("level") else " (the author gave no numeric level)")
        return {**base, "disposition": "held_for_missing_evidence", "reason": why, "matchOverall": (match or {}).get("overall")}
    pick = next((r for r in aligned if r.get("valid")), aligned[0])
    trig = next((copy.deepcopy(t) for t in (plan or {}).get("triggers") or [] if t.get("id") == pick["trigger"]), None)
    if trig is None:
        return {**base, "disposition": "held_for_missing_evidence", "reason": "aligned trigger not found in the saved plan"}
    geometry = {"planTrigger": pick["trigger"], "entry": (trig.get("entry") or {}).get("price"), "stop": (trig.get("stop") or {}).get("price"),
                "targets": [x.get("price") if isinstance(x, dict) else x for x in trig.get("targets") or []], "riskReward": trig.get("riskReward"),
                "provenance": "app-derived: the saved deterministic plan's trigger at the author's level (the author gave no stop)"}
    if not trig.get("valid"):
        return {**base, "disposition": "refused", "geometry": geometry, "namedBaselineOutcome": True,
                "reason": "our gates rejected the aligned trigger: " + "; ".join((trig.get("noTradeReasons") or ["not tradeable"])[:2])[:240], "trigger": trig}
    if policy_record and pick["trigger"] not in (policy_record.get("eligibleTriggers") or []) and policy_record.get("mode") == "deterministic":
        return {**base, "disposition": "refused", "geometry": geometry, "reason": "the preparation policy does not make this trigger eligible", "trigger": trig}
    trig["origin"] = f"scenario:{sid}"
    return {**base, "disposition": "waiting", "geometry": geometry, "trigger": trig, "reason": None}


def evaluate(candidate: dict, bars: list, *, thresholds: Thresholds | None = None, profile=None, prev_close: float | None = None,
             upto_ts: int | None = None, pricing_evidence=None, pricing_rules: dict | None = None) -> dict:
    """Causal evaluation with the candidate's OWN tracker. Only bars CLOSED by `upto_ts` (default: all given) and
    before the source expiry are fed. The proxy outcome (what the underlying did afterwards) is reported apart and
    never feeds back into the disposition."""
    out = {**candidate}
    trig = candidate.get("trigger")
    if candidate.get("disposition") not in ("waiting", "requalification_eligible") or not trig:
        return out
    t = thresholds or DEFAULT_THRESHOLDS
    usable = (_ms(candidate.get("bornAt")) or _ms(candidate.get("source", {}).get("usableAt"))) if candidate.get("variant") == "source_continuation" else candidate.get("eligibleFromTs")
    exp = candidate.get("expiresTs")
    tracker = TriggerTracker(copy.deepcopy(trig), t, profile, True, True, prev_close)
    born = int(candidate.get("eligibleFromTs") or 0) if candidate.get("variant") == "requalification" else 0
    if born:
        out["gapRule"] = "not applicable: the structure was born after the open (the tracker runs gap_unchecked, as production does for a late start); the parent's gap verdict stands"
    if born:
        bars = [b for b in bars if int(b.ts) >= born]       # `born` = the confirming bar's CLOSE: the confirming candle itself is never fed to the child;
    fed = 0                                                 # the tracker indexes its OWN bar list, so the slice is what it and the scorer get
    for i, b in enumerate(bars):
        closed = int(b.ts) + 60_000
        if upto_ts is not None and closed > int(upto_ts):
            break
        if exp is not None and int(b.ts) >= int(exp):
            break
        tracker.on_bar(b, i)
        fed += 1
        if tracker.status == "fired":
            if usable is not None and closed <= int(usable):
                # the condition completed BEFORE the source was usable to the app: not a source-informed entry
                out.update({"disposition": "expired", "reason": "the condition completed before the source became usable to the app", "firedTs": tracker.fired_ts})
                return out
            break
        if tracker.status in TriggerTracker.TERMINAL:
            break
    out["barsConsumed"] = fed
    out["lastBarTs"] = int(bars[fed - 1].ts) if fed else None
    out["trackerEvents"] = list(tracker.events[-8:]); out["skipped"] = list(tracker.skipped[-6:])
    if tracker.status == "fired":
        out.update({"disposition": "triggered", "firedTs": tracker.fired_ts, "firedWindow": tracker.fired_window, "fillProxy": tracker.fill_price})
        # the evidence must be CONTEMPORANEOUS with the trigger (captured within 3 minutes of the confirming bar's close);
        # anything later is not what an entry would have seen - it stays unknown
        ev = pricing_evidence(out) if callable(pricing_evidence) else pricing_evidence
        at = (ev or {}).get("atMs")
        fresh = at is not None and 0 <= int(at) - (int(tracker.fired_ts) + 60_000) <= 180_000
        out["pricingGates"] = pricing_gates(out, ((ev or {}).get("evidence") if fresh else None), now_ms=(at if fresh else None), rules=pricing_rules)
        if ev and not fresh:
            out["pricingGates"]["why"] = "evidence was not captured within 3 minutes of the trigger - not contemporaneous"
        scored = score_trigger(tracker, bars, thresholds=t)
        out["outcomeProxy"] = {**(scored.get("sim") or {}), "evidenceClass": "underlying_walkforward_proxy",
                               "note": "what the UNDERLYING did afterwards - not an option fill, not dollars; never feeds the disposition"}
    elif tracker.status in TriggerTracker.TERMINAL:
        out.update({"disposition": "invalidated", "reason": f"tracker: {tracker.status}", "invalidatedStatus": tracker.status,
                    "invalidatedTs": (tracker.events[-1].get("ts") if tracker.events else out["lastBarTs"])})
    elif exp is not None and bars and (upto_ts is None or int(upto_ts) >= int(exp)) and int(bars[-1].ts) + 60_000 >= int(exp):
        out.update({"disposition": "expired", "reason": "source expiry reached without the condition"})
    return out


PRICING_VERSION = "candidate-pricing-v2"
CHASE_VERSION = "candidate-chase-v1"
PRICING_GATES = ("contract", "quote", "spread", "sizing", "budget", "chase", "firstSaleR", "portfolio")
PRICING_DEFAULTS = {"riskPct": 2.0, "premiumStopPct": 50.0, "maxSpreadPct": 10.0, "maxPremiumNotional": 1000.0, "maxPremiumPct": 5.0,
                    "maxContracts": 10, "minRiskReward": 3.0, "singleExit": "tp2", "feePerContract": 1.04, "maxQuoteAgeMs": 10_000,
                    "fridayMult": 1.0, "chaseCapR": 0.25, "avoid0dteAfterMin": 630, "maxConstraintAgeMs": 10_000}
DIFFERENCES = ("chase: production EM has NO general underlying chase cap - its never-chase controls are the limit at the ask, the entry-window cancel (T4.1) and "
               "`entry_limit_cap` (none for EM). `candidate-chase-v1` is a separately versioned RESEARCH bound (the 0.25R the 429 re-pick uses), evaluated apart from R.",
               "portfolio: the production RiskGate verdict is taken as evidence (same function, dry, no order row); it is never re-implemented here.")


def size_contracts(*, equity: float, ask: float, rules: dict) -> dict:
    """The production risk-budget sizer as a pure bound: equity x risk% x Friday multiplier / (ask x 100 x premium-stop share)."""
    r = {**PRICING_DEFAULTS, **(rules or {})}
    stop_share = float(r["premiumStopPct"]) / 100.0 if 0 < float(r["premiumStopPct"]) < 100 else 1.0
    risk_per = float(ask) * 100.0 * stop_share
    budget = float(equity) * float(r["riskPct"]) / 100.0 * float(r["fridayMult"])
    n = min(int(budget / max(risk_per, 1e-9)), int(r["maxContracts"]))
    return {"contracts": n, "riskPerContract": round(risk_per, 2), "riskBudget": round(budget, 2)}


def contract_identity(candidate: dict, contract: dict | None, *, now_ms: int, rules: dict) -> dict:
    """Bind the supplied contract to THIS candidate by its OCC identity (`options.occ.parse`, the production parser): the
    underlying, the right and the expiry come from the symbol; explicit metadata that CONFLICTS with it fails; a symbol
    that does not parse, or no symbol, is UNKNOWN. A matching quote symbol alone binds nothing."""
    from ..options import occ as _occ
    if not contract or not contract.get("symbol"):
        return {"status": "unknown", "why": "no contract evidence (the research chain capture is off or returned nothing)"}
    sym = str(contract["symbol"])
    o = _occ.parse(sym)
    if o is None:
        return {"status": "unknown", "why": "the contract symbol is not a standard OCC identity - right, expiry and multiplier unknown", "symbol": sym}
    want = "put" if candidate.get("direction") == "short" else "call"
    today = dt.datetime.fromtimestamp(int(now_ms) / 1000.0, NY)
    fails = []
    if o.underlying.upper() != str(candidate.get("symbol") or "").upper():
        fails.append(f"wrong underlying: the contract is on {o.underlying}, the candidate is {candidate.get('symbol')}")
    if o.option_type != want:
        fails.append(f"wrong right: the contract is a {o.option_type}, the candidate needs a {want}")
    meta_type = str(contract.get("optionType") or "").strip().lower()
    if meta_type and meta_type[:1] != o.option_type[:1]:
        fails.append(f"conflicting metadata: optionType {meta_type} vs the symbol's {o.option_type}")
    if contract.get("expiry") and str(contract["expiry"])[:10] != o.expiry.isoformat():
        fails.append(f"conflicting metadata: expiry {str(contract['expiry'])[:10]} vs the symbol's {o.expiry.isoformat()}")
    if contract.get("strike") is not None and abs(float(contract["strike"]) - float(o.strike)) > 1e-6:
        fails.append(f"conflicting metadata: strike {contract['strike']} vs the symbol's {o.strike:g}")
    if contract.get("underlying") and str(contract["underlying"]).upper() != o.underlying.upper():
        fails.append(f"conflicting metadata: underlying {contract['underlying']} vs the symbol's {o.underlying}")
    if o.is_expired(today.date()):
        fails.append(f"expired contract: {o.expiry.isoformat()} is before the session {today.date().isoformat()}")
    elif o.dte(today.date()) == 0 and today.hour * 60 + today.minute >= int(rules["avoid0dteAfterMin"]):
        fails.append("0DTE after the production cut-off (technique.arm.avoid_0dte_after)")
    base = {"symbol": sym, "underlying": o.underlying, "optionType": o.option_type, "expiry": o.expiry.isoformat(), "strike": o.strike,
            "dte": o.dte(today.date()), "multiplier": 100.0, "delta": contract.get("delta"), "identityBasis": "OCC symbol (production parser)"}
    return {**base, "status": ("fail" if fails else "pass"), "why": ("; ".join(fails) or None)}


def pricing_gates(candidate: dict, evidence: dict | None, *, now_ms: int | None = None, rules: dict | None = None) -> dict:
    """The EXECUTABLE-PRICING stage of a triggered candidate (`candidate-pricing-v2`; IR-05, R2-02). ORDER-FREE: it evaluates
    frozen rules on SUPPLIED contemporaneous evidence and never fetches, arms or orders anything. `evidence` = {underlier,
    contract, contractQuote, equity, cash, constraints}. Every gate is `pass` | `fail` | `unknown`; missing evidence is
    UNKNOWN. `overall` is `feasible` ONLY when EVERY gate passes, `infeasible` when any fails, otherwise `unknown` with
    `completeness: partial` and the missing gates listed - a partial result is never production-equivalent.
      contract    OCC identity bound to the candidate: underlying, right, expiry (not expired, 0DTE cut-off), metadata conflicts
      quote       the contract's quote is validated venue evidence (identity, source, venue time, session, finite two-sided, size + unit)
      spread      (ask - bid) / mid within the production limit (T5.4, 10%)
      sizing      the production risk-budget sizer as a bound (0 contracts = fail)
      budget      premium within the RiskGate premium caps and the cash on hand NET of existing entry reservations
      chase       `candidate-chase-v1`: the validated executable underlying bound is at most `chaseCapR` x risk beyond the entry
                  in the trade's direction. Separate from R: adequate R never substitutes for a chase pass
      firstSaleR  the first-sale admission (R at the final quantity from the worse executable bound; first-sale-v2)
      portfolio   the production RiskGate's own verdict on the sized order (kill switch, book halt / pause, daily-loss limit,
                  exposure and position caps, cash), trading-halt state and the symbol's open-position slot - all snapshotted
                  at the evaluation; absent = unknown"""
    from . import first_sale as _fs
    from .profit_capture import quote_problems
    r = {**PRICING_DEFAULTS, **(rules or {})}
    ev = evidence or {}
    trig, geo = candidate.get("trigger") or {}, candidate.get("geometry") or {}
    out = {"version": PRICING_VERSION, "chaseVersion": CHASE_VERSION, "stage": "executable_pricing", "evaluatedAt": now_ms, "orderFree": True, "gates": {}, "rules": r,
           "productionEquivalent": False, "deliberateDifferences": list(DIFFERENCES),
           "note": "a triggered candidate is NOT an executable entry; nothing here arms or orders"}
    g = out["gates"]
    if not ev or now_ms is None:
        for k in PRICING_GATES:
            g[k] = {"status": "unknown", "why": "no contemporaneous evidence was supplied"}
        out.update({"overall": "unknown", "completeness": "none", "missing": list(PRICING_GATES)})
        return out
    contract, cq = ev.get("contract") or None, ev.get("contractQuote") or None
    g["contract"] = contract_identity(candidate, contract, now_ms=int(now_ms), rules=r)
    ask = bid = None
    if g["contract"]["status"] != "pass" or not cq:
        for k in ("quote", "spread", "sizing", "budget"):
            g[k] = {"status": "unknown", "why": ("no valid contract" if g["contract"]["status"] != "pass" else "no contract quote evidence")}
    else:
        probs = quote_problems(cq, symbol=str(contract["symbol"]), is_option=True, now_ms=int(now_ms), max_age_ms=int(r["maxQuoteAgeMs"]), side="ask")
        g["quote"] = {"status": ("pass" if not probs else "fail"), "problems": probs, "source": cq.get("source"), "ageMs": (int(now_ms) - int(cq.get("quoteTs") or 0) if cq.get("quoteTs") else None)}
        bid, ask = _fs._f(cq.get("bid")), _fs._f(cq.get("ask"))
        if probs or not bid or not ask:
            for k in ("spread", "sizing", "budget"):
                g[k] = {"status": "unknown", "why": "the contract quote is not valid evidence"}
        else:
            spread = (ask - bid) / ((ask + bid) / 2.0) * 100.0
            g["spread"] = {"status": ("pass" if spread <= float(r["maxSpreadPct"]) else "fail"), "spreadPct": round(spread, 2), "max": float(r["maxSpreadPct"])}
            equity = _fs._f(ev.get("equity"))
            if equity is None:
                g["sizing"] = {"status": "unknown", "why": "book equity unknown"}
                g["budget"] = {"status": "unknown", "why": "book equity unknown"}
            else:
                sz = size_contracts(equity=equity, ask=ask, rules=r)
                n = sz["contracts"]
                g["sizing"] = {"status": ("pass" if n >= 1 else "fail"), **sz,
                               "why": (None if n >= 1 else "one contract risks more than the trade budget at its premium stop (the budget is a bound)")}
                if n >= 1:
                    prem = n * ask * 100.0
                    cash, reserved = _fs._f(ev.get("cash")), _fs._f((ev.get("constraints") or {}).get("reservedPremium"))
                    free = (cash - reserved) if (cash is not None and reserved is not None) else None
                    fails = [w for ok, w in ((prem <= float(r["maxPremiumNotional"]), "premium notional cap"), (prem <= equity * float(r["maxPremiumPct"]) / 100.0, "premium % of equity cap"),
                                             (free is None or prem <= free, "cash on hand net of existing entry reservations")) if not ok]
                    unknown_cash = free is None and not fails
                    g["budget"] = {"status": ("unknown" if unknown_cash else ("pass" if not fails else "fail")), "premium": round(prem, 2), "failed": fails,
                                   "cash": cash, "reservedPremium": reserved, "freeCash": free,
                                   "why": ("cash or existing reservations unknown" if unknown_cash else None)}
                else:
                    g["budget"] = {"status": "unknown", "why": "no size to budget"}
    qty = (g.get("sizing") or {}).get("contracts") if (g.get("sizing") or {}).get("status") == "pass" else None
    direction = "short" if candidate.get("direction") == "short" else "long"
    runner_entry = candidate.get("fillProxy") if candidate.get("fillProxy") is not None else geo.get("entry")
    # --- chase: a genuine executable-price bound, judged apart from R
    und = _fs.validate_underlier(ev.get("underlier"), symbol=str(candidate.get("symbol") or ""), direction=direction, now_ms=int(now_ms), max_age_ms=int(r["maxQuoteAgeMs"]))
    e0, s0 = _fs._f(runner_entry), _fs._f(geo.get("stop"))
    if und.get("status") != "valid":
        g["chase"] = {"status": "unknown", "why": "no validated executable underlying evidence", "missing": und.get("problems")}
    elif und.get("basis") == "last":
        g["chase"] = {"status": "unknown", "why": "only a venue PRINT is available - a print is not an executable quote, so the chase bound stays unknown", "print": und.get("price")}
    elif e0 is None or s0 is None or abs(e0 - s0) <= 0:
        g["chase"] = {"status": "unknown", "why": "entry or stop unknown"}
    else:
        risk = abs(e0 - s0)
        ran = (e0 - float(und["price"])) if direction == "short" else (float(und["price"]) - e0)
        g["chase"] = {"status": ("pass" if ran <= float(r["chaseCapR"]) * risk + 1e-12 else "fail"), "version": CHASE_VERSION, "bound": und["price"], "boundBasis": und.get("basis"),
                      "entry": e0, "ranR": round(ran / risk, 4), "capR": float(r["chaseCapR"]),
                      "why": (None if ran <= float(r["chaseCapR"]) * risk + 1e-12 else f"the executable underlying is {ran / risk:.2f}R beyond the entry (cap {float(r['chaseCapR']):g}R) - not chased")}
    rec = _fs.build_record(stage="candidate", symbol=str(candidate.get("symbol") or ""), run_id=str(candidate.get("planRunId") or ""), trigger_id=str(trig.get("id") or ""),
                           family=str(trig.get("kind") or ""), direction=direction, session=candidate.get("session"),
                           plan_entry=geo.get("entry"), runner_entry=runner_entry,
                           stop=geo.get("stop"), targets=geo.get("targets") or [], underlier_evidence=ev.get("underlier"), instrument="options", qty=qty, multiplier=100.0,
                           limit_price=ask, single_exit=str(r["singleExit"]), pinned_gate_target="auto", pin_source="run_config", min_rr=float(r["minRiskReward"]),
                           contract=contract, option_quote=cq, fee_per_contract=float(r["feePerContract"]), stock_commission=0.0, affordable_qty=qty, plan_gate=None,
                           mode="observe", now_ms=int(now_ms), max_underlier_age_ms=int(r["maxQuoteAgeMs"]))
    gate = rec["gate"]
    g["firstSaleR"] = {"status": gate["verdict"], "rAdmission": gate["rAdmission"], "admissionEntry": gate["admissionEntry"], "rung": gate["rung"],
                       "firstProductionSale": (rec.get("firstSale") or {}).get("rung"),
                       "boundBasis": (gate["admissionBasis"] or {}).get("boundBasis"), "why": gate["reason"], "missing": gate["missingEvidence"]}
    # --- portfolio: the production verdict and book state, snapshotted causally
    c = ev.get("constraints") or None
    if not c:
        g["portfolio"] = {"status": "unknown", "why": "no portfolio constraint snapshot was supplied",
                          "missing": ["riskVerdict", "tradingHalted", "symbolOpenOrWorking", "reservedPremium"]}
    else:
        missing = [k for k in ("riskVerdict", "tradingHalted", "symbolOpenOrWorking", "maxOpenTrades", "reservedPremium") if c.get(k) is None]
        stale = c.get("atMs") is None or abs(int(now_ms) - int(c["atMs"])) > int(r["maxConstraintAgeMs"])
        fails = []
        if c.get("tradingHalted"):
            fails.append(f"trading is halted: {c.get('tradingHalted')}")
        rv = c.get("riskVerdict") or {}
        if rv and not rv.get("passed"):
            fails += [f"RiskGate {x.get('name')}: {x.get('detail') or 'failed'}" for x in rv.get("checks") or [] if not x.get("passed")] or ["RiskGate refused"]
        if rv and qty is not None and rv.get("qty") is not None and float(rv["qty"]) != float(qty):
            missing.append("riskVerdict(for the sized quantity)")
        if c.get("symbolOpenOrWorking") is not None and c.get("maxOpenTrades") is not None and int(c["symbolOpenOrWorking"]) >= max(1, int(c["maxOpenTrades"])):
            fails.append(f"no open-position slot: the symbol already holds {int(c['symbolOpenOrWorking'])} (max {int(c['maxOpenTrades'])})")
        status = "fail" if fails else ("unknown" if (missing or stale) else "pass")
        g["portfolio"] = {"status": status, "failed": fails, "missing": missing + (["fresh snapshot"] if stale else []), "snapshotAt": c.get("atMs"),
                          "riskChecks": [x.get("name") for x in rv.get("checks") or []],
                          "why": ("; ".join(fails) or ("constraints missing or not contemporaneous" if status == "unknown" else None))}
    states = {k: g[k]["status"] for k in PRICING_GATES}
    missing_gates = [k for k, v in states.items() if v == "unknown"]
    out["overall"] = "infeasible" if "fail" in states.values() else ("unknown" if missing_gates else "feasible")
    out["completeness"] = "complete" if not missing_gates else "partial"
    out["missing"] = missing_gates
    return out


def requalify(*, scenario: dict, payload: dict, baseline_trigger_state: dict, bars: list, session: str, thresholds: Thresholds | None = None,
              existing_children=None, upto_ts: int | None = None) -> dict:
    """Variant 2. `baseline_trigger_state` = {status, ts, entry} of the PARENT's invalidated baseline trigger (read-only)."""
    app = scenario["appDerived"]
    expires, exp_der = source_expiry_ts(session, app.get("horizon"))
    seen = rq.bars_upto(bars, upto_ts) if upto_ts is not None else list(bars)
    parent = {"scenarioId": scenario["scenarioId"], "branchKey": branch_key(scenario, payload), "symbol": (scenario.get("symbol") or {}).get("resolved"), "direction": scenario["authorSupplied"].get("direction"),
              "session": session, "invalidatedTs": baseline_trigger_state.get("ts"), "invalidatedStatus": baseline_trigger_state.get("status"),
              "sourceTargets": app.get("underlyingTargets"), "expiresTs": expires, "oldEntry": baseline_trigger_state.get("entry")}
    child = rq.build_child(parent=parent, bars=seen, thresholds=thresholds, existing_children=existing_children)
    return {**child, "variant": "requalification", "expiryDerivation": exp_der, "candidateId": child["childId"],
            "author": (payload.get("author") or {}).get("displayName"), "noteId": (payload.get("note") or {}).get("id")}


def exclusion_diagnostic(name: str, trigger: dict, bars: list, *, thresholds: Thresholds | None = None, profile=None, prev_close: float | None = None,
                         relax: str | None = None) -> dict:
    """Cost AND benefit of a named baseline exclusion (MU volume skip, AMD 2.97R), hindsight-labelled. `relax` =
    `volume` replays the same trigger with the volume floor off; None replays the rejected geometry as-is. Diagnostic
    only: it never changes a threshold and is never a selection feature."""
    import dataclasses
    t = thresholds or DEFAULT_THRESHOLDS
    if relax == "volume":
        over = {k: 0.0 for k in ("volume_spike_mult", "volume_floor_mult") if hasattr(t, k)}
        t = dataclasses.replace(t, **over) if over else t
    tr = TriggerTracker({**copy.deepcopy(trigger), "valid": True}, t, profile, True, True, prev_close)
    for i, b in enumerate(bars):
        tr.on_bar(b, i)
        if tr.status in TriggerTracker.TERMINAL:
            break
    sc = score_trigger(tr, bars, thresholds=t)
    sim = sc.get("sim") or {}
    return {"exclusion": name, "relaxed": relax, "status": sc.get("status"), "firedTs": sc.get("firedTs"), "outcome": sim.get("outcome"), "rMultiple": sim.get("rMultiple"),
            "stillSkippedBy": [x.get("reason") for x in (sc.get("skipped") or [])[-3:]],
            "benefitOfExclusion": (abs(sim["rMultiple"]) if (sim.get("rMultiple") or 0) < 0 else 0.0) if sim else None,
            "costOfExclusion": (sim["rMultiple"] if (sim.get("rMultiple") or 0) > 0 else 0.0) if sim else None,
            "label": "HINDSIGHT diagnostic on the underlying; a single path; never grounds for loosening the production gate"}


def _ms(v) -> int | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return int(v)
    try:
        d = dt.datetime.fromisoformat(str(v).replace("Z", "+00:00").replace(" ", "T", 1))
        return int((d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)).timestamp() * 1000)
    except ValueError:
        return None


def table_row(c: dict, baseline: dict | None = None) -> dict:
    """The source -> candidate -> gate row the report and the UI show."""
    g = c.get("geometry") or {}
    return {"candidateId": c.get("candidateId"), "variant": c.get("variant"), "author": c.get("author"), "symbol": c.get("symbol"), "direction": c.get("direction"),
            "condition": (c.get("source") or {}).get("condition"), "sourceLevel": (c.get("source") or {}).get("level"), "entry": g.get("entry"), "stop": g.get("stop"),
            "targets": g.get("targets"), "disposition": c.get("disposition"), "reason": c.get("reason"), "firedTs": c.get("firedTs"),
            "outcomeProxy": (c.get("outcomeProxy") or {}).get("outcome"), "rProxy": (c.get("outcomeProxy") or {}).get("rMultiple"),
            "pricing": ({"overall": (c.get("pricingGates") or {}).get("overall"), "completeness": (c.get("pricingGates") or {}).get("completeness"),
                         "missing": (c.get("pricingGates") or {}).get("missing"), "version": (c.get("pricingGates") or {}).get("version"),
                         "gates": {k: v.get("status") for k, v in ((c.get("pricingGates") or {}).get("gates") or {}).items()}} if c.get("pricingGates") else None),
            "baseline": baseline, "orderFree": True, "origin": c.get("origin")}


def definition_of(c: dict) -> dict:
    """The IMMUTABLE part of a born candidate: identity, source, plan, geometry, trigger, structure and times. Frozen at the
    first persist; a later tick, restart or re-plan evaluates THIS, never a newly favourable interpretation."""
    keep = ("version", "variant", "candidateId", "childId", "scenarioId", "parentScenarioId", "pairId", "branchKey", "revisionId", "origin", "orderFree", "session",
            "symbol", "direction", "author", "noteId", "source", "expiresTs", "expiryDerivation", "policy", "geometry", "trigger", "structure", "differsFromParent",
            "confirmation", "eligibleFromTs", "gate", "parentState", "planRunId", "planChoice", "bornAt", "matchOverall", "contextRunId")
    d = {k: copy.deepcopy(c[k]) for k in keep if k in c}
    d["definitionHash"] = _h(d)
    return d


def _resume(stored: dict, bars: list, *, ctx: tuple, upto_ts, pricing_evidence, pricing_rules) -> dict:
    """Continue a BORN candidate from its frozen definition. A terminal one keeps its disposition, trigger time, fill proxy
    and pricing for ever; only the after-the-fact outcome proxy is re-scored (and a disagreement is recorded, not applied)."""
    d = copy.deepcopy(stored.get("definition") or {})
    th, prof, pc = ctx
    start = "requalification_eligible" if d.get("variant") == "requalification" else "waiting"
    if stored.get("disposition") in TERMINAL_DISPOSITIONS:
        out = {k: v for k, v in stored.items() if k != "history"}
        if stored.get("disposition") == "triggered" and bars:
            again = evaluate({**d, "disposition": start, "source": d.get("source") or {}}, bars, thresholds=th, profile=prof,
                             prev_close=(None if d.get("variant") == "requalification" else pc), upto_ts=upto_ts)
            if again.get("firedTs") == stored.get("firedTs"):
                for k in OUTCOME_KEYS:
                    if k in again:
                        out[k] = again[k]
            else:
                out["replayDisagreement"] = {"storedFiredTs": stored.get("firedTs"), "replayFiredTs": again.get("firedTs"),
                                             "note": "the bars now replay differently; the FIRST observation stands"}
        out["frozen"] = "terminal"
        return out
    ev = evaluate({**d, "disposition": start, "source": d.get("source") or {}}, bars, thresholds=th, profile=prof,
                  prev_close=(None if d.get("variant") == "requalification" else pc), upto_ts=upto_ts, pricing_evidence=pricing_evidence, pricing_rules=pricing_rules) if bars else {**d, "disposition": start}
    return {**ev, "definition": stored["definition"], "frozen": "definition"}


def evaluate_session(*, payloads: list, plans_by_symbol: dict, bars_by_symbol: dict, baseline_by_symbol: dict | None, session: str,
                     upto_ts: int | None = None, thresholds_by_symbol: dict | None = None, profiles_by_symbol: dict | None = None,
                     policy_by_run: dict | None = None, prev_close_by_symbol: dict | None = None, pricing_evidence=None,
                     pricing_rules: dict | None = None, context_by_run: dict | None = None, frozen: dict | None = None) -> list:
    """The ONE evaluator the forward loop and the replay tool share. Pure: scenarios (A) + saved plans + the policy records
    (B) + closed bars -> candidates of both variants with their dispositions.
      `payloads`              the AUTHORITATIVE scenario payloads as of the evaluation (the caller selects revisions)
      `plans_by_symbol[sym]`  [{runId, createdAt, trigger(origin), plan}]; the plan used is the one available at the idea's
                              BIRTH (`birth_plan`), with THAT run's thresholds / profile / previous close (`context_by_run`)
      `frozen`                {candidateId: stored payload}: a born candidate is continued from its stored `definition`;
                              a terminal one is never re-decided; one child per BRANCH per session
      `baseline_by_symbol`    read-only states of the BASELINE trackers (never reset, reused or overwritten)
    Missing or irregular bars = held / waiting with the reason - never guessed."""
    from . import source_scenarios as _ss
    frozen = frozen or {}
    out = []
    child_branches = {str(v.get("branchKey")): k for k, v in frozen.items() if v.get("variant") == "requalification" and v.get("branchKey")}

    def ctx_for(run_id, sym):
        if context_by_run and run_id in context_by_run:
            return context_by_run[run_id]
        return ((thresholds_by_symbol or {}).get(sym), (profiles_by_symbol or {}).get(sym), (prev_close_by_symbol or {}).get(sym))
    for payload in payloads or []:
        for sc in payload.get("scenarios") or []:
            sym = (sc.get("symbol") or {}).get("resolved")
            all_bars = (bars_by_symbol or {}).get(sym) or []
            bars = rq.bars_upto(all_bars, upto_ts) if upto_ts is not None else list(all_bars)
            integ = rq.bars_integrity(bars)
            base = [b for b in ((baseline_by_symbol or {}).get(sym) or []) if b.get("direction") == sc["authorSupplied"].get("direction")]
            cid = candidate_id(sc["scenarioId"], session)
            stored = frozen.get(cid)
            if stored and stored.get("definition"):
                cand = _resume(stored, bars if integ["ok"] else [], ctx=ctx_for((stored.get("definition") or {}).get("contextRunId"), sym), upto_ts=upto_ts,
                               pricing_evidence=pricing_evidence, pricing_rules=pricing_rules)
            else:
                usable = _ms((sc.get("correction") or {}).get("usableAt") or (payload.get("times") or {}).get("usableAt"))
                plan, why = birth_plan((plans_by_symbol or {}).get(sym) or [], usable, upto_ts)
                match = _ss.match_plan(sc, payload, plan.get("plan") or {}, plan_built_at=plan.get("createdAt"), plan_origin=plan.get("trigger")) if plan else None
                pol = (policy_by_run or {}).get((plan or {}).get("runId"))
                cand = build_candidate(scenario=sc, payload=payload, match=match, plan=(plan or {}).get("plan"), policy_record=pol, session=session)
                cand.update({"planRunId": (plan or {}).get("runId"), "contextRunId": (plan or {}).get("runId"), "matchOverall": (match or {}).get("overall"),
                             "planChoice": {"rule": why, "runId": (plan or {}).get("runId"), "builtAt": (plan or {}).get("createdAt"),
                                            "plansSeen": len([p for p in (plans_by_symbol or {}).get(sym) or [] if upto_ts is None or (_ms(p.get("createdAt")) or 0) <= int(upto_ts)])}})
                if plan is not None:
                    cand["bornAt"] = max([x for x in (usable, _ms(plan.get("createdAt"))) if x is not None], default=None)
                if cand["disposition"] == "waiting":
                    cand["definition"] = definition_of(cand)
                    th, prof, pc = ctx_for(cand["contextRunId"], sym)
                    if not bars:
                        cand["barsCoverage"] = "none"
                    elif not integ["ok"]:
                        cand.update({"disposition": "held_for_missing_evidence", "reason": "bars are not a clean minute series - the condition cannot be judged", "definition": None})
                    else:
                        d = cand["definition"]
                        cand = {**evaluate(cand, bars, thresholds=th, profile=prof, prev_close=pc, upto_ts=upto_ts, pricing_evidence=pricing_evidence, pricing_rules=pricing_rules),
                                "definition": d}
                elif cand["disposition"] == "refused" and cand.get("geometry"):
                    cand["definition"] = definition_of(cand)
            cand["baseline"] = base
            cand["barsIntegrity"] = {k: integ[k] for k in ("ok", "bars", "duplicates", "outOfOrder", "misaligned", "missingMinutes")}
            out.append(cand)
            # ---- variant 2: one requalified child per BRANCH per session
            bkey = branch_key(sc, payload)
            chid = rq.child_id(sc["scenarioId"], session)
            ch_stored = frozen.get(chid)
            if ch_stored and ch_stored.get("definition"):
                child = _resume(ch_stored, bars if integ["ok"] else [], ctx=ctx_for((ch_stored.get("definition") or {}).get("contextRunId"), sym), upto_ts=upto_ts,
                                pricing_evidence=pricing_evidence, pricing_rules=pricing_rules)
                child["baseline"] = base
                out.append(child)
                continue
            dead = next((b for b in sorted(base, key=lambda b: int(b.get("ts") or 0)) if b.get("status") in rq.TERMINAL_UNFIRED), None)
            if sym and dead is not None and sc.get("disposition") == "candidate_source":
                other = child_branches.get(bkey)
                if other and other != chid:
                    child = {"version": rq.VERSION, "variant": "requalification", "candidateId": chid, "parentScenarioId": sc["scenarioId"], "branchKey": bkey,
                             "origin": f"scenario:{sc['scenarioId']}", "orderFree": True, "symbol": sym, "direction": sc["authorSupplied"].get("direction"),
                             "disposition": "refused", "reason": "one_requalified_candidate_per_branch_per_session", "existingChild": other}
                elif bars:
                    th, prof, _pc = ctx_for(cand.get("contextRunId"), sym)
                    child = requalify(scenario=sc, payload=payload, baseline_trigger_state=dead, bars=bars, session=session, thresholds=th, upto_ts=None)
                    child["contextRunId"] = cand.get("contextRunId")
                    if child.get("disposition") == "requalification_eligible":
                        d = definition_of(child)
                        ev = evaluate({**child, "source": {}}, bars, thresholds=th, profile=prof, prev_close=None, upto_ts=upto_ts, pricing_evidence=pricing_evidence, pricing_rules=pricing_rules)
                        child = {**child, **{k: ev[k] for k in ("disposition", "firedTs", "fillProxy", "outcomeProxy", "pricingGates", "reason", "barsConsumed", "gapRule") if k in ev},
                                 "definition": d}
                else:
                    child = {"version": rq.VERSION, "variant": "requalification", "candidateId": chid, "parentScenarioId": sc["scenarioId"], "branchKey": bkey,
                             "origin": f"scenario:{sc['scenarioId']}", "orderFree": True, "symbol": sym, "direction": sc["authorSupplied"].get("direction"),
                             "disposition": "waiting", "barsCoverage": "none", "reason": "no session bars - unknown, not assumed"}
                child["baseline"] = base
                out.append(child)
    return out
