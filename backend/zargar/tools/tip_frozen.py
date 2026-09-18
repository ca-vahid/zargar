"""Frozen knowledge comparison CLI (KFIN-09) - standalone, reads the DB
directly, never touches the running app, never places anything.

    python -m zargar.tools.tip_frozen capture --signal <id> | --run <id>
    python -m zargar.tools.tip_frozen show    --bundle fb-...
    python -m zargar.tools.tip_frozen replay  --bundle fb-... [--variants current,core_only] [--repeats 1] [--dry-run]
    python -m zargar.tools.tip_frozen report  --bundle fb-...   [--json out.json]

`capture` builds the immutable bundle from what the DB already holds (the
analyst run's trace = the tool outputs it saw, the rule snapshot, the notes it
was handed, the message, the settings) and persists it under its content hash.
`replay` runs the analyst prompt against that bundle only, per variant, with
the LLM (paid call) - every tool call is served from the bundle or refused,
`save_note` is captured on the report and never written. `--dry-run` swaps
the model for a stub that answers "review" so the plumbing can be exercised
for free. `report` prints the side-by-side of every stored replay of the
bundle: decision changes, grounding, protections, no-verdict rate, latency,
tokens - and no verdict on which variant is better.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys


class _StubBlock:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class _StubClient:
    """No-cost stand-in: answers a 'review' opinion without a provider. Its usage is SYNTHETIC
    (prompt chars / 4, output 40 tokens; with a cache-marked system the prefix is reported as a
    cache write on the first call and a cache read afterwards) so the dry run exercises the
    per-attempt accounting and the budget guard for free - the numbers are not measurements."""

    def __init__(self):
        self.messages = self
        self.calls = 0

    async def create(self, **kw):
        self.calls += 1
        sys_p, tools_p = kw.get("system"), kw.get("tools") or []
        cached = isinstance(sys_p, list) and any(isinstance(b, dict) and b.get("cache_control") for b in sys_p)
        prefix = len(json.dumps(sys_p, default=str)) // 4 + len(json.dumps(tools_p, default=str)) // 4
        header = len(json.dumps(kw.get("messages"), default=str)) // 4
        text = json.dumps({"verdict": "review", "rationale": "dry run - stub model, no provider call",
                           "confidence": 0.0, "invalidation": "n/a"})
        if cached:
            usage = _StubBlock(input_tokens=header, output_tokens=40,
                               cache_creation_input_tokens=prefix if self.calls == 1 else 0,
                               cache_read_input_tokens=0 if self.calls == 1 else prefix)
        else:
            usage = _StubBlock(input_tokens=prefix + header, output_tokens=40,
                               cache_creation_input_tokens=0, cache_read_input_tokens=0)
        return _StubBlock(content=[_StubBlock(type="text", text=text)], stop_reason="end_turn", usage=usage)


async def _open():
    from ..bus import Bus
    from ..config import get_config
    from ..db import make_engine, make_session_factory
    from ..events import Journal
    from ..settings_service import SettingsService
    cfg = get_config()
    eng = make_engine(cfg.database_url)
    sf = make_session_factory(eng)
    bus = Bus()
    journal = Journal(sf, bus)
    settings = SettingsService(sf, bus, journal)
    await settings.load()
    return cfg, eng, sf, settings, journal


def _print_report(cmp: dict) -> None:
    print(f"bundle {cmp.get('bundleId')} - baseline verdict: {(cmp.get('baseline') or {}).get('verdict')} "
          f"(run {str((cmp.get('baseline') or {}).get('runId') or '')[:8]})")
    print(f"evidence: {cmp.get('evidence')} · decision differs across variants: {cmp.get('decisionDiffers')}")
    for v, d in (cmp.get("variants") or {}).items():
        nv = d.get("noVerdictRate")
        print(f"  {v:<13} runs={d['runs']} verdicts={d['verdicts']} changed_vs_baseline={d['decisionChangedVsBaseline']} "
              f"no_verdict_rate={nv if nv is None else round(nv, 2)} tools served/missing="
              f"{d['toolCalls']['served']}/{d['toolCalls']['missing']} proposed_notes={d['proposedNotes']} "
              f"latency_ms={d['latencyMs']} tokens={[{k: t.get(k) for k in ('in', 'out', 'calls')} if t else None for t in d['tokens']]}")
        if d.get("skipped"):
            print(f"               skipped: {d['skipped']}")
    print(f"\n{cmp.get('disclaimer')}")


async def run(a) -> int:
    from ..techniques.tip import frozen
    from ..models import TipFrozenReplay
    from sqlalchemy import select

    cfg, eng, sf, settings, journal = await _open()
    try:
        if a.cmd == "capture":
            b = await frozen.capture_bundle(sf, run_id=a.run, signal_id=a.signal,
                                            settings=settings, journal=journal)
            print(f"bundle {b['id']} ({'existing' if b['existing'] else 'new'}) - signal {b['signal']['id']} "
                  f"{b['signal']['ticker']} · run {(b.get('run') or {}).get('id')} · "
                  f"{len(b['toolOutputs'])} tool output(s) · {len(b['knowledge']['rules'])} rule(s) · "
                  f"{len(b['knowledge']['notes'])} note(s) · manifest "
                  f"{'exact' if (b.get('manifest') or {}).get('exact') else 'RECONSTRUCTED'}")
            for g in b["gaps"]:
                print(f"  gap: {g}")
            return 0
        bundle = await frozen.load_bundle(sf, a.bundle)
        if a.cmd == "show":
            print(json.dumps({k: v for k, v in bundle.items() if k != "manifest"}, indent=2, default=str)[:20000])
            man = bundle.get("manifest") or {}
            print(f"manifest: exact={man.get('exact')} headerSha={man.get('headerSha')} systemSha={man.get('systemSha')}")
            return 0
        if a.cmd == "replay":
            variants = [v.strip() for v in (a.variants or str(settings.get("techniques.tip.frozen_variants")
                                                                 or "current,core_only")).split(",") if v.strip()]
            # CACHE-P1/P2: explicit cache switch + an enforced dollar ceiling shared by every attempt
            # of every replay in this invocation (retries and unknown-billed attempts included)
            prompt_cache = (a.cache == "on")
            model_for_budget = a.model or (bundle.get("run") or {}).get("model") or str(settings.get("techniques.tip.analyst_model") or "") \
                or str(settings.get("llm.model") or "")
            budget = None
            if a.budget_usd is not None:
                rates = settings.get("llm.rates") or {}
                rates = rates.get("v", rates) if isinstance(rates, dict) and "v" in rates else rates
                card = (rates or {}).get(model_for_budget) if isinstance(rates, dict) else None
                try:
                    budget = frozen.ReplayBudget(float(a.budget_usd), card, model=model_for_budget)
                except ValueError as exc:
                    sys.exit(f"cannot budget this replay: {exc}")
            elif not a.dry_run:
                sys.exit("a paid replay needs --budget-usd <cap> (an enforced ceiling incl. retries); --dry-run needs none")
            # the client is built only after the ceiling is in place - a paid replay never starts uncapped
            if a.dry_run:
                client = _StubClient()
            else:
                if not cfg.anthropic_api_key:
                    sys.exit("no ZARGAR_ANTHROPIC_API_KEY - use --dry-run to exercise the plumbing")
                import anthropic
                client = anthropic.AsyncAnthropic(api_key=cfg.anthropic_api_key)
            reports = []
            for v in variants:
                for _ in range(max(1, a.repeats)):
                    # a dry run is labelled as such on the persisted row: the stub's synthetic usage is
                    # priced at the intended model's card but never attributed to that model
                    rep = await frozen.replay(bundle, variant=v, client=client,
                                              model=(f"dry-run-stub({model_for_budget})" if a.dry_run else a.model),
                                              prompt_cache=prompt_cache, budget=budget)
                    rep["dryRun"] = bool(a.dry_run)
                    rid = await frozen.persist_replay(sf, rep, journal=journal)
                    reports.append(rep)
                    tk = rep.get("tokens") or {}
                    print(f"  {v:<13} replay {rid[:8]} cache={'on' if rep.get('promptCache') else 'off'} verdict={rep.get('verdict')} "
                          f"noVerdict={rep.get('noVerdict')} changed={rep.get('decisionChanged')} "
                          f"served/missing={rep['toolCalls']['served']}/{rep['toolCalls']['missing']} "
                          f"in/out={tk.get('in')}/{tk.get('out')} cacheWrite/Read={tk.get('cacheCreation')}/{tk.get('cacheRead')} "
                          f"prefix~{rep.get('prefixTokensEst')}tok header~{rep.get('headerTokensEst')}tok "
                          f"attempts={len(tk.get('attempts') or [])} unknownBilled={tk.get('unknownBilled')} "
                          f"{('error=' + str(rep.get('error'))[:80]) if rep.get('error') else ''} hash={rep.get('reportHash', '')[:12]}")
                    for at in (tk.get("attempts") or []):
                        print(f"      attempt {at.get('attempt')}: in={at.get('inputTokens')} out={at.get('outputTokens')} "
                              f"cacheWrite={at.get('cacheWriteTokens')} cacheRead={at.get('cacheReadTokens')} "
                              f"est=${at.get('estimateUsd', 0) or 0:.4f} usd=${at.get('usd', 0) or 0:.4f} {at.get('billing', '')} "
                              f"{('error=' + str(at.get('error'))[:60]) if at.get('error') else ''}")
                    if rep.get("error") and str(rep["error"]).startswith("budget:"):
                        print("  budget ceiling reached - no further replays in this invocation")
                        break
                else:
                    continue
                break
            if budget is not None:
                bs = budget.summary()
                print(f"budget: spent ${bs['spentUsd']:.4f} of ${bs['capUsd']:.2f} over {bs['attempts']} attempt(s), "
                      f"{bs['unknownBilled']} unknown-billed (charged at estimate), {len(bs['refused'])} refused; model {bs['model']}")
            _print_report(frozen.compare(reports))
            return 0
        if a.cmd == "assemble":
            # PAR178: offline treatment assembly - hashes, sizes, budgets; no model, no writes
            asm = frozen.assemble_treatments(bundle)
            print(json.dumps(asm, indent=2, default=str))
            return 0
        if a.cmd == "report":
            async with sf() as session:
                rows = (await session.execute(select(TipFrozenReplay).where(
                    TipFrozenReplay.bundle_id == a.bundle).order_by(TipFrozenReplay.created_at.asc()))).scalars().all()
            reports = [r.report for r in rows]
            if not reports:
                print("no replays stored for this bundle yet")
                return 1
            cmp = frozen.compare(reports)
            _print_report(cmp)
            if a.json:
                with open(a.json, "w", encoding="utf-8") as f:
                    json.dump({"bundle": {k: v for k, v in bundle.items() if k != "manifest"},
                               "manifest": {k: v for k, v in (bundle.get("manifest") or {}).items()
                                            if k not in ("header", "system")},
                               "replays": reports, "comparison": cmp}, f, indent=2, default=str)
                print(f"written: {a.json}")
            return 0
    finally:
        await eng.dispose()
    return 0


def main() -> None:
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", choices=["capture", "show", "replay", "report", "assemble"])
    ap.add_argument("--signal")
    ap.add_argument("--run")
    ap.add_argument("--bundle")
    ap.add_argument("--variants", default="")
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--model", default=None)
    ap.add_argument("--dry-run", action="store_true", help="replay with a stub model (no provider call; synthetic usage)")
    ap.add_argument("--cache", choices=["off", "on"], default="off", help="CACHE-P1: mark the stable prefix cacheable (off by default)")
    ap.add_argument("--budget-usd", type=float, default=None, help="CACHE-P2: enforced dollar ceiling for every attempt of this invocation")
    ap.add_argument("--json", default="", help="report: also write the full JSON report here")
    a = ap.parse_args()
    if a.cmd == "capture" and not (a.signal or a.run):
        ap.error("capture needs --signal or --run")
    if a.cmd != "capture" and not a.bundle:
        ap.error(f"{a.cmd} needs --bundle")
    sys.exit(asyncio.run(run(a)))


if __name__ == "__main__":
    main()
