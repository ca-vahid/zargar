"""KFIN-09 (2026-09-14): frozen knowledge comparison + entry-variant cohort.

Deterministic and offline (scripted analyst client, sim feed, no provider,
no network). Proves the packet's four "done when" conditions:
  * write isolation - a frozen replay and a cohort simulation touch no note,
    revision, order, proposal, book or analyst run;
  * denominator correctness - skips, declines, blocked cards and failures are
    cohort rows; a close and an experiment sample are not;
  * missing-data handling - a tool output not in the bundle is refused (never
    fetched), a reconstructed manifest says so, an idea without a quote or a
    stated premium is 'insufficient' per variant, a later sample is labeled
    delayed and never back-fills the decision quote;
  * reproducibility - same bundle + same scripted answers -> same report
    hash; recomputing the variant books yields identical results.
"""
import datetime as dt
import json

import pytest
from sqlalchemy import select

from zargar.domain import Quote, now_ms
from zargar.engine import Engine
from zargar.models import (Order, Portfolio, Proposal, Signal, TipAnalystRun, TipEntryCohortRow,
                           TipEntryVariantResult, TipFrozenBundle, TipFrozenReplay, TipNote,
                           TipNoteRevision, RawContent)
from zargar.domain import new_id
from zargar.signals.schemas import ExtractionResult, TradeSignal
from zargar.signals.service import attach_signal_layer
from zargar.techniques.tip import cohort, frozen

from .conftest import make_test_config, wait_for

SOURCE_TEXT = """ALERT: We are buying AAPL today. Entry at $231.50, stop loss $220, target $260.
Apple remains our top pick."""


class _Block:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class _Resp:
    def __init__(self, content, stop="end_turn", usage=(120, 40)):
        self.content = content
        self.stop_reason = stop
        self.usage = _Block(input_tokens=usage[0], output_tokens=usage[1])


class _Scripted:
    def __init__(self, responses):
        self._responses = list(responses)
        self.requests: list[dict] = []
        self.messages = self

    async def create(self, **kw):
        self.requests.append(kw)
        return self._responses.pop(0)


def _opinion(verdict="skip", **extra):
    base = {"verdict": verdict, "rationale": f"scripted {verdict}", "confidence": 0.6,
            "invalidation": "n/a"}
    base.update(extra)
    return json.dumps(base)


def _tool(name, args, tid="t1"):
    return _Resp([_Block(type="tool_use", id=tid, name=name, input=args)], stop="tool_use")


def _text(s):
    return _Resp([_Block(type="text", text=s)])


def canned(*, ticker="AAPL", action="open", actionable=True, entry=231.50, instrument="shares",
           strike=None, expiry=None, premium=None):
    return ExtractionResult(
        signals=[TradeSignal(
            ticker=ticker, direction="long", action=action, entry_price=entry,
            target_price=260.0, stop_price=220.0, entry_type="limit", timeframe="swing",
            instrument=instrument, strike=strike, expiry=expiry, premium=premium,
            thesis_summary="scripted",
            evidence_quotes=["We are buying AAPL today",
                             "Entry at $231.50, stop loss $220, target $260"],
            confidence="explicit_call", is_actionable=actionable)],
        source_type="trade_alert")


async def _run(eng, extraction, *, source="KfinSrc", experiment=None):
    row = RawContent(id=new_id(), source_type="manual", source_name=source, subject="alert",
                     body_text=SOURCE_TEXT, meta={"messageId": None})
    async with eng.sf() as session:
        session.add(row)
        await session.commit()
    return await eng.signals_service.handle_extraction(
        row, extraction, source_text=SOURCE_TEXT, experiment=experiment)


@pytest.fixture
async def rig(fresh_db):
    eng = Engine(make_test_config())
    await eng.start()
    await attach_signal_layer(eng)
    await eng.ensure_symbol("AAPL")
    await wait_for(lambda: eng.quotes.get("AAPL") is not None)
    await eng.settings.set("verification.max_price_deviation_pct", 10.0)

    async def _no_refresh(sym):            # never reach a chain provider from a test
        return eng.quotes.get(sym.upper())
    eng.options.refresh_now = _no_refresh
    yield eng
    await eng.stop()


async def _counts(eng) -> dict:
    async with eng.sf() as session:
        out = {}
        for name, model in (("notes", TipNote), ("revisions", TipNoteRevision), ("orders", Order),
                            ("proposals", Proposal), ("portfolios", Portfolio),
                            ("runs", TipAnalystRun), ("bundles", TipFrozenBundle),
                            ("replays", TipFrozenReplay), ("cohort", TipEntryCohortRow)):
            out[name] = len((await session.execute(select(model))).scalars().all())
        return out


# ------------------------------------------------------------ frozen bundles
async def _seed_knowledge(eng):
    svc = eng.signals_service
    core = await svc.add_tip_note("rule", "RULE (geometry): never chase past the stated premium")
    other = await svc.add_tip_note("rule", "RULE (sizing): one lotto per session")
    await svc.pin_tip_note(core["id"])
    await svc.add_tip_note("ticker:AAPL", "AAPL gaps fill fast in the first hour")
    return core["id"], other["id"]


async def _original_run(eng, *, source="KfinSrc"):
    """One live appraisal with a scripted client that reads a quote, then skips."""
    eng.signals_service._analyst_client = _Scripted([
        _tool("get_quote", {"symbol": "AAPL"}),
        _text(_opinion("skip")),
    ])
    out = await _run(eng, canned(), source=source)
    sig = out[0]["signal"]
    assert sig["status"] in ("verified", "proposed"), sig["verification"]
    return sig["id"]


async def test_frozen_bundle_captures_exact_context_and_replays_in_isolation(rig):
    eng = rig
    await eng.settings.set("techniques.tip.frozen_capture_context", True)
    core_id, other_id = await _seed_knowledge(eng)
    sig_id = await _original_run(eng)

    bundle = await frozen.capture_bundle(eng.sf, signal_id=sig_id, settings=eng.settings,
                                         journal=eng.journal)
    assert bundle["id"].startswith("fb-") and not bundle["existing"]
    man = bundle["manifest"]
    assert man["exact"] and man["header"] and man["system"]
    assert [t["tool"] for t in bundle["toolOutputs"]] == ["get_quote"]
    assert bundle["toolOutputs"][0]["args"] == {"symbol": "AAPL"}
    rules = {r["id"]: r for r in bundle["knowledge"]["rules"]}
    assert rules[core_id]["core"] is True and rules[other_id]["core"] is False
    assert all(r["revisionNo"] for r in rules.values())
    assert [n["scope"] for n in bundle["knowledge"]["notes"]] == ["ticker:AAPL"]
    assert bundle["run"]["opinion"]["verdict"] == "skip"
    assert bundle["settings"]["techniques.tip.analyst_max_tools"] == 8
    # re-capture of unchanged evidence -> the same immutable bundle
    again = await frozen.capture_bundle(eng.sf, signal_id=sig_id, settings=eng.settings)
    assert again["id"] == bundle["id"] and again["existing"]

    before = await _counts(eng)

    def replay_client():
        return _Scripted([
            _tool("get_quote", {"symbol": "AAPL"}, "t1"),            # served from the bundle
            _tool("get_bars", {"symbol": "AAPL", "tf": "5m"}, "t2"), # NOT in the bundle -> missing
            _tool("save_note", {"scope": "ticker", "text": "AAPL note from a replay"}, "t3"),
            _text(_opinion("take", contract="AAPL260918C00230000", limit_price=2.5, quantity=2,
                           exit_targets=[240.0], exit_fractions=[1.0], underlying_stop=225.0,
                           used_notes=["N1"])),
        ])

    client = replay_client()
    rep = await frozen.replay(bundle, variant="current", client=client)
    # the model saw the ORIGINAL header verbatim and the original system prompt
    assert client.requests[0]["messages"][0]["content"] == man["header"]
    assert client.requests[0]["system"] == man["system"]
    assert rep["headerMatchesOriginal"] is True and rep["manifestGaps"] == []
    assert rep["verdict"] == "take" and rep["decisionChanged"] is True
    assert rep["baseline"]["verdict"] == "skip"
    assert rep["toolCalls"]["served"] == 1 and rep["toolCalls"]["missing"] == 1
    assert rep["toolCalls"]["missingCalls"][0]["tool"] == "get_bars"
    # the refused call told the model the input stays missing
    results = {blk["tool_use_id"]: json.loads(blk["content"])
               for m in client.requests[-1]["messages"] if m["role"] == "user" and isinstance(m["content"], list)
               for blk in m["content"] if blk.get("type") == "tool_result"}
    assert results["t1"]["ask"] == bundle["toolOutputs"][0]["result"]["ask"]   # served verbatim
    refused = results["t2"]
    assert "not in the bundle" in refused["error"] and "never fetches" in refused["error"]
    assert rep["proposedNotes"] == [{"scope": "ticker", "text": "AAPL note from a replay"}]
    assert rep["protections"] == {"targets": True, "underlyingStop": True,
                                  "premiumStop": False, "holdCap": False}
    assert rep["usedNotes"] == ["N1"] and rep["noVerdict"] is False
    assert rep["tokens"]["calls"] == 4 and rep["tokens"]["in"] == 480
    assert rep["latencyMs"] >= 0
    assert rep["knowledge"]["rulesSupplied"] == 2 and rep["knowledge"]["notesSupplied"] == 1
    rid = await frozen.persist_replay(eng.sf, rep, journal=eng.journal)

    # WRITE ISOLATION: no note, revision, order, proposal, book or analyst run
    after = await _counts(eng)
    assert {k: after[k] for k in ("notes", "revisions", "orders", "proposals", "portfolios", "runs")} == \
           {k: before[k] for k in ("notes", "revisions", "orders", "proposals", "portfolios", "runs")}
    assert after["replays"] == before["replays"] + 1
    live = await eng.signals_service.tip_notes(["ticker:AAPL", "general", "rule"])
    assert not any("from a replay" in n["text"] for n in live)

    # REPRODUCIBILITY: same bundle, same answers -> same report hash
    rep2 = await frozen.replay(bundle, variant="current", client=replay_client())
    assert rep2["reportHash"] == rep["reportHash"]

    # compact variant: only the pinned (core) rule and no non-core note reach the model
    c2 = replay_client()
    rep_core = await frozen.replay(bundle, variant="core_only", client=c2)
    hdr = c2.requests[0]["messages"][0]["content"]
    assert "never chase past the stated premium" in hdr
    assert "one lotto per session" not in hdr
    assert "AAPL gaps fill fast" not in hdr
    assert rep_core["knowledge"] == {**rep_core["knowledge"], "rulesSupplied": 1,
                                     "notesSupplied": 0, "dropped": 2, "ruleIds": [core_id]}
    assert rep_core["headerMatchesOriginal"] is False
    # the rest of the header is untouched by the swap
    assert hdr.split("YOUR TRADING RULES")[0] == man["header"].split("YOUR TRADING RULES")[0]
    assert hdr.split("THIS SOURCE'S LAST")[1] == man["header"].split("THIS SOURCE'S LAST")[1]

    # control: no knowledge at all
    c3 = replay_client()
    rep_none = await frozen.replay(bundle, variant="no_knowledge", client=c3)
    assert rep_none["knowledge"]["rulesSupplied"] == 0 and rep_none["knowledge"]["starterRules"]
    from zargar.techniques.tip.analyst import STARTER_RULES
    assert STARTER_RULES in c3.requests[0]["messages"][0]["content"]

    cmp = frozen.compare([rep, rep_core, rep_none])
    assert set(cmp["variants"]) == {"current", "core_only", "no_knowledge"}
    assert cmp["evidence"] == "adequate" and cmp["baseline"]["verdict"] == "skip"
    assert cmp["variants"]["current"]["noVerdictRate"] == 0.0
    assert "No profitability" in cmp["disclaimer"]
    async with eng.sf() as session:
        row = await session.get(TipFrozenReplay, rid)
        assert row.variant == "current" and row.report_hash == rep["reportHash"]


async def test_frozen_missing_inputs_stay_missing(rig):
    """Knob OFF -> the manifest is reconstructed and says so; a call the
    original run never made is refused; a failed/unparseable reply is a
    measured no-verdict, never an exception; an unknown variant is skipped."""
    eng = rig
    await _seed_knowledge(eng)
    sig_id = await _original_run(eng)
    bundle = await frozen.capture_bundle(eng.sf, signal_id=sig_id, settings=eng.settings)
    man = bundle["manifest"]
    assert man["exact"] is False and man["header"] is None
    assert any("reconstructed" in g for g in bundle["gaps"])
    before = await _counts(eng)

    client = _Scripted([
        _tool("get_quote", {"symbol": "AAPL"}, "t1"),                     # served (same args)
        _tool("search_messages", {"source": "KfinSrc", "hours": 72}, "t2"),  # never captured
        _text("I cannot decide."),                                     # no JSON -> no verdict
    ])
    rep = await frozen.replay(bundle, variant="current", client=client)
    hdr = client.requests[0]["messages"][0]["content"]
    assert frozen.MISSING in hdr                       # the history block is explicitly missing
    assert "Per-tip budget: $1,000" in hdr             # what the bundle DID hold is used
    assert rep["headerMatchesOriginal"] is False
    assert any("reconstructed" in g for g in rep["manifestGaps"])
    assert any("system prompt not captured" in g for g in rep["manifestGaps"])
    assert rep["toolCalls"] == {**rep["toolCalls"], "served": 1, "missing": 1}
    assert rep["noVerdict"] is True and rep["verdict"] is None
    assert "no parseable opinion" in rep["error"]
    assert rep["decisionChanged"] is False

    bad = await frozen.replay(bundle, variant="consolidated", client=_Scripted([]))
    assert bad["skipped"] and bad["noVerdict"]
    cmp = frozen.compare([rep, bad])
    assert cmp["evidence"] == "insufficient"
    assert (await _counts(eng)) == before               # nothing written at all


async def test_frozen_bundle_without_core_flags_cannot_run_core_only():
    bundle = {"id": "fb-x", "knowledge": {"rules": [{"id": "r1", "text": "x", "core": None,
                                                     "disputed": False, "createdAt": "2026-09-01"}],
                                          "notes": []},
              "manifest": {"exact": False}, "run": {"model": "m", "opinion": {"verdict": "skip"}},
              "settings": {}, "toolOutputs": [], "gaps": []}
    kv = frozen.variant_knowledge(bundle, "core_only")
    assert kv["available"] is False and "core flags" in kv["reason"]
    rep = await frozen.replay(bundle, variant="core_only", client=_Scripted([]))
    assert rep["skipped"] and "core flags" in rep["reason"]


# ------------------------------------------------------------- entry cohort
async def _enable_cohort(eng, *, delay_minutes=60.0):
    await eng.settings.set("techniques.tip.entry_cohort_enabled", True)
    await eng.settings.set("techniques.tip.entry_cohort_delay_minutes", delay_minutes)


async def _cohort_rows(eng) -> list[TipEntryCohortRow]:
    async with eng.sf() as session:
        return (await session.execute(
            select(TipEntryCohortRow).order_by(TipEntryCohortRow.decided_at.asc()))).scalars().all()


async def test_cohort_counts_every_eligible_idea_not_only_proposals(rig):
    eng = rig
    await _enable_cohort(eng)
    svc = eng.signals_service

    # (1) proposal mode, analyst skip -> a card waits for the human: "proposed"
    svc._analyst_client = _Scripted([_text(_opinion("skip"))])
    a = await _run(eng, canned(), source="ProposalSrc")
    assert a[0]["proposal"] is not None

    # (2) explicit auto source, analyst skip -> declined on the record
    await eng.settings.set("techniques.tip.sources", {"AutoSrc": {"mode": "auto"}})
    svc._analyst_client = _Scripted([_text(_opinion("skip"))])
    b = await _run(eng, canned(), source="AutoSrc")
    assert b[0]["proposal"]["status"] == "rejected"

    # (3) platform-default auto (not explicit) + analyst take -> earned-auto gate BLOCKS the card
    await eng.settings.set("techniques.tip.mode", "auto")
    svc._analyst_client = _Scripted([_text(_opinion("take"))])
    c = await _run(eng, canned(), source="EarnedSrc")
    assert (c[0]["proposal"]["context"] or {}).get("autoGate"), c[0]["proposal"]["context"]
    await eng.settings.set("techniques.tip.mode", "proposal")

    # (4) a price far from the tape: verification fails/parks - still an idea
    svc._analyst_client = _Scripted([_text(_opinion("skip"))])
    d = await _run(eng, canned(entry=50.0), source="FarSrc")
    assert d[0]["signal"]["status"] in ("verification_failed", "parked")

    # NOT eligible: a close action, an experiment sample
    svc._analyst_client = _Scripted([_text(_opinion("skip"))])
    await _run(eng, canned(action="close"), source="CloseSrc")
    svc._analyst_client = _Scripted([_text(_opinion("skip"))])
    await _run(eng, canned(), source="ExpSrc", experiment="bx")

    rows = await _cohort_rows(eng)
    decisions = {r.source: r.decision for r in rows}
    assert decisions == {"ProposalSrc": "proposed", "AutoSrc": "declined",
                         "EarnedSrc": "blocked", "FarSrc": d[0]["signal"]["status"]}
    assert "auto not yet earned" in next(r.decision_reason for r in rows if r.source == "EarnedSrc")
    # every row keeps the three times apart and the exact instruments
    for r in rows:
        assert r.received_at is not None and r.decided_at >= r.received_at
        assert r.posted_at is None and "source post time unknown" in " ".join(r.gaps)
        assert r.source_instrument["instrument"] == "shares" and r.source_instrument["occ"] is None
        assert r.decision_kind == "intake"
    proposed = next(r for r in rows if r.source == "ProposalSrc")
    assert proposed.proposed_instrument["kind"] == "proposal"
    assert proposed.proposed_instrument["secType"] == "STK"
    assert proposed.quote_symbol == "AAPL" and proposed.quote_status == "fresh"
    assert proposed.quote_at_decision["sampleKind"] == "decision"
    assert proposed.quote_at_decision["source"] and proposed.quote_at_decision["ageSeconds"] is not None
    assert proposed.delayed_status == "pending" and proposed.delayed_sample is None

    rep = await cohort.cohort_report(eng, eng.settings)
    assert rep["denominator"]["ideas"] == 4
    assert rep["denominator"]["byDecision"] == {"proposed": 1, "declined": 1, "blocked": 1,
                                                d[0]["signal"]["status"]: 1}
    assert set(rep["variants"]) == {"immediate", "delay", "cap"}
    assert rep["variants"]["immediate"]["book"] == "variant:immediate"
    # shares ideas: immediate adequate + filled, delay pending, cap not applicable
    assert rep["variants"]["immediate"]["adequate"] == 4 and rep["variants"]["immediate"]["filled"] == 4
    assert rep["variants"]["delay"]["insufficientReasons"] == {"delayed sample pending": 4}
    assert rep["variants"]["cap"]["insufficientReasons"] == {"cap variant applies to option ideas only": 4}
    assert "No profitability" in rep["disclaimer"] or "no profitability" in rep["disclaimer"]
    assert "pnl" not in json.dumps(rep).lower()

    # the journal carries the decision, never the quote
    async with eng.sf() as session:
        from zargar.models import Event
        evs = (await session.execute(select(Event).where(Event.type == "TipEntryCohort"))).scalars().all()
    assert len(evs) == 4
    assert all("ask" not in json.dumps(e.payload) and "bid" not in json.dumps(e.payload) for e in evs)
    assert {e.payload["decision"] for e in evs} == {"proposed", "declined", "blocked", d[0]["signal"]["status"]}


async def test_cohort_option_idea_missing_data_and_delayed_sample(rig):
    """An option idea with a fully stated contract but no quote: the decision
    quote is MISSING and stays missing; the later sample is labeled delayed;
    each variant reports its own insufficiency; the cohort is inert when off."""
    eng = rig
    svc = eng.signals_service
    # OFF by default: nothing recorded
    svc._analyst_client = _Scripted([_text(_opinion("skip"))])
    await _run(eng, canned(), source="OffSrc")
    assert await _cohort_rows(eng) == []

    await _enable_cohort(eng)
    svc._analyst_client = _Scripted([_text(_opinion("skip"))])
    out = await _run(eng, canned(instrument="call", strike=230.0, expiry="2026-10-16"), source="OptSrc")
    # whatever verification says, the IDEA is in the cohort (the denominator is the idea)
    assert out[0]["signal"]["status"] in ("verified", "proposed", "parked", "shadow", "verification_failed")
    rows = await _cohort_rows(eng)
    assert len(rows) == 1
    r = rows[0]
    occ = "AAPL261016C00230000"
    assert r.source_instrument["occ"] == occ and r.quote_symbol == occ
    assert r.quote_at_decision is None and r.quote_status == "missing"
    assert r.source_premium is None
    assert "no source-stated premium" in r.gaps and "no quote at decision" in r.gaps
    assert r.delayed_status == "pending" and r.delayed_due_at is not None

    res = {x["variant"]: x for x in cohort.simulate_variants(cohort._row_dict(r), cohort.assumptions(eng.settings))}
    assert not res["immediate"]["adequate"] and res["immediate"]["reason"] == "no quote at decision"
    assert not res["delay"]["adequate"] and res["delay"]["reason"] == "delayed sample pending"
    assert not res["cap"]["adequate"] and res["cap"]["reason"] == "no source-stated premium"
    assert all(x["fill"] is None for x in res.values())

    # before due: nothing sampled
    assert (await cohort.sample_one(eng, r.id, now=r.delayed_due_at - dt.timedelta(seconds=1)))["delayedStatus"] == "pending"
    # a quote appears LATER; the due sample is taken and labeled delayed
    eng.quotes.on_quote(Quote(symbol=occ, bid=1.00, ask=1.20, last=1.10, source="opra",
                              source_ts=now_ms()))
    got = await cohort.sample_one(eng, r.id, now=r.delayed_due_at)
    assert got["delayedStatus"] == "sampled"
    assert got["delayedSample"]["sampleKind"] == "delayed" and got["delayedSample"]["ask"] == 1.20
    assert got["delayedSample"]["source"] == "opra" and got["delayedSample"]["quoteStatus"] == "fresh"
    assert "never alert-time" in got["delayedSample"]["note"]
    assert got["quoteAtDecision"] is None and got["quoteStatus"] == "missing"   # unknown at alert STAYS unknown
    # idempotent: a second call changes nothing
    assert (await cohort.sample_one(eng, r.id, now=r.delayed_due_at)) == got

    before = await _counts(eng)
    results = await cohort.compute_results(eng, eng.settings)
    by = {x["variant"]: x for x in results}
    assert by["delay"]["adequate"] and by["delay"]["sampleKind"] == "delayed"
    a = cohort.assumptions(eng.settings)
    assert a["optionBudget"] == 750.0
    assert by["delay"]["fill"] == {"filled": True, "price": 1.2, "qty": 6, "cost": 720.0,
                                   "fees": round(a["feePerContract"] * 6, 2)}
    assert not by["immediate"]["adequate"] and not by["cap"]["adequate"]
    # REPRODUCIBLE + separate books + write isolation
    again = await cohort.compute_results(eng, eng.settings)
    assert again == results
    async with eng.sf() as session:
        books = (await session.execute(select(TipEntryVariantResult))).scalars().all()
    assert {b.book for b in books} == {"variant:immediate", "variant:delay", "variant:cap"}
    assert {b.id for b in books} == {f"{r.id}:{v}" for v in ("immediate", "delay", "cap")}
    after = await _counts(eng)
    assert {k: after[k] for k in ("orders", "proposals", "portfolios", "notes", "revisions")} == \
           {k: before[k] for k in ("orders", "proposals", "portfolios", "notes", "revisions")}

    # a row whose due time passed long ago (process was down) is MISSED, never back-labeled
    svc._analyst_client = _Scripted([_text(_opinion("skip"))])
    await _run(eng, canned(instrument="put", strike=200.0, expiry="2026-10-16"), source="LateSrc")
    late = next(x for x in await _cohort_rows(eng) if x.source == "LateSrc")
    missed = await cohort.sample_one(eng, late.id, now=late.delayed_due_at + dt.timedelta(days=1))
    assert missed["delayedStatus"] == "missed" and missed["delayedSample"] is None
    assert any("missed" in g for g in missed["gaps"])


async def test_cap_variant_fills_only_under_the_stated_premium_cap(rig):
    eng = rig
    a = cohort.assumptions(eng.settings)
    base = {"id": "c1", "signalId": "s1", "ticker": "AAPL", "decision": "skipped",
            "quoteSymbol": "AAPL261016C00230000", "quoteStatus": "fresh",
            "quoteAtDecision": {"ask": 2.20, "bid": 2.00, "ageSeconds": 3.0, "source": "opra",
                                "sourceTs": now_ms() - 3000, "delayed": False},   # KF83-04: executable evidence needs provenance
            "delayedStatus": "pending", "delayedSample": None, "sourcePremium": 2.00}
    res = {x["variant"]: x for x in cohort.simulate_variants(base, a)}
    assert res["cap"]["adequate"] and res["cap"]["fill"]["filled"] is False
    assert "above cap 2.1" in res["cap"]["fill"]["reason"]
    assert res["immediate"]["fill"] == {"filled": True, "price": 2.2, "qty": 3, "cost": 660.0,
                                        "fees": round(a["feePerContract"] * 3, 2)}
    ok = {**base, "quoteAtDecision": {**base["quoteAtDecision"], "ask": 2.05}}
    res2 = {x["variant"]: x for x in cohort.simulate_variants(ok, a)}
    assert res2["cap"]["fill"]["filled"] and res2["cap"]["fill"]["capLimit"] == 2.1
    assert res2["cap"]["fill"]["qty"] == res2["immediate"]["fill"]["qty"]   # identical budget/fees
    stale = {**base, "quoteStatus": "stale", "quoteAtDecision": {**base["quoteAtDecision"], "ageSeconds": 900.0}}
    res3 = {x["variant"]: x for x in cohort.simulate_variants(stale, a)}
    assert not res3["immediate"]["adequate"] and "stale" in res3["immediate"]["reason"]
    assert not res3["cap"]["adequate"] and "stale" in res3["cap"]["reason"]
