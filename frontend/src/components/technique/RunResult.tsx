import { useEffect, useMemo, useState } from "react";
import { api } from "../../lib/api";
import { fmtDateTime } from "../../lib/format";
import { useStore } from "../../store";
import { absoluteUrl } from "../../lib/routing";
import type {
  GroundingCheck, TechniqueContract, TechniqueOutcome, TechniqueReview, TechniqueRun, TechniqueTaxonomy, TraceStep,
} from "../../types";
import { IconCheck, IconX } from "../icons";
import { Collapse } from "../Collapse";
import { CopyChip } from "../CopyChip";
import { Markdown } from "./Markdown";
import { FactsView } from "./StreamingOutput";

function fmt(n: number | null | undefined, d = 2) {
  return n === null || n === undefined || Number.isNaN(n) ? "—" : n.toFixed(d);
}

export function VerdictBadge({ run }: { run: Pick<TechniqueRun, "status" | "verdict" | "setupType" | "confidence" | "grounded"> }) {
  if (run.status === "running") return <span className="tq-badge running">running</span>;
  if (run.status === "failed") return <span className="tq-badge failed">failed</span>;
  if (run.verdict === "setup") {
    return <span className="tq-badge setup">SETUP · {run.setupType?.replace(/_/g, " ")}</span>;
  }
  return <span className="tq-badge nosetup">no setup</span>;
}

/** Outcome pill for lists: which plan, what happened, R. */
export function OutcomeBadge({ outcome }: { outcome: TechniqueOutcome | null }) {
  if (!outcome) return <span className="tq-badge nosetup" title="not scored yet">—</span>;
  const src = outcome.planSource === "analysis" ? "plan" : outcome.planSource === "candidate" ? "declined" : "market";
  if (outcome.status === "pending" || outcome.status === "unscorable") {
    return <span className="tq-badge nosetup" title={outcome.note ?? ""}>{src} · {outcome.status}</span>;
  }
  const r = outcome.rMultiple;
  const cls = outcome.outcome === "not_filled" || r === null ? "nosetup" : r > 0 ? "setup" : r < 0 ? "failed" : "nosetup";
  const txt = outcome.outcome ? outcome.outcome.replace(/_/g, " ") : "path";
  return (
    <span className={`tq-badge ${cls}`} title={`${src} plan · MFE ${outcome.mfeR ?? "—"}R / MAE ${outcome.maeR ?? "—"}R · ${outcome.barsHeld ?? 0} bars${outcome.status === "partial" ? " · partial" : ""}`}>
      {src} · {txt}{r !== null && outcome.outcome !== "not_filled" ? ` ${r > 0 ? "+" : ""}${r.toFixed(2)}R` : ""}{outcome.status === "partial" ? "*" : ""}
    </span>
  );
}

export function ReviewBadge({ last, count }: { last: TechniqueRun["lastReview"]; count: number }) {
  if (!last) return <span className="muted">—</span>;
  const cls = last.reviewVerdict === "correct" ? "setup" : last.reviewVerdict === "unclear" ? "nosetup" : "failed";
  return (
    <span className={`tq-badge ${cls}`} title={`${count} review(s) · last by ${last.reviewer}`}>
      {last.reviewVerdict.replace(/_/g, " ")}{last.rootCauseStage ? ` · ${last.rootCauseStage.replace(/_/g, " ")}` : ""}
    </span>
  );
}

export function RuleChips({ ids, rules }: { ids: string[]; rules: Record<string, string> }) {
  return (
    <div className="tq-chips">
      {ids.map((id) => (
        <span key={id} className="tq-chip" title={rules[id] ?? id}>{id}</span>
      ))}
    </div>
  );
}

/** The full result card for a finished run (analysis contract, grounding,
 *  annotated chart, options pick, pass usage). */
export function RunResult({ run, rules, onRefresh }: { run: TechniqueRun; rules: Record<string, string>; onRefresh?: () => void }) {
  const openChat = useStore((s) => s.openTechniqueChat);
  const [showTrace, setShowTrace] = useState(false);
  const trace: TraceStep[] = run.result?.trace ?? [];
  const a: TechniqueContract | null | undefined = run.result?.analysis ?? run.analysis;
  const grounding = run.result?.grounding;
  const options = run.result?.options ?? run.options;
  const passes = run.result?.passes ?? [];
  const [showChecks, setShowChecks] = useState(false);
  const [showFacts, setShowFacts] = useState(false);
  const annotated = run.images?.annotated;
  const failed = useMemo(() => (grounding?.checks ?? []).filter((c: GroundingCheck) => !c.passed), [grounding]);
  const usage = run.usage ?? {};
  // The deterministic candidate the analysis declined — shown so "no setup" is
  // explained by geometry rather than merely asserted.
  const rejectedLine = useMemo(() => {
    const c = (run.facts?.candidateSetups ?? [])[0];
    if (!c || a?.verdict === "setup") return null;
    return `Considered: ${String(c.setupType).replace(/_/g, " ")} — entry ${fmt(c.entry?.price)}, `
      + `stop ${fmt(c.stop?.price)}, first target ${fmt(c.targets?.[0]?.price)} → R:R ${fmt(c.riskReward)} `
      + `(needs ≥ 3.0).`;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run.facts, a?.verdict]);
  const cost = useMemo(() => {
    // Opus 5 list price: $5/M in, $25/M out; cache reads $0.50/M, writes $6.25/M
    const u: any = usage;
    const inTok = (u.input ?? 0) - (u.cacheRead ?? 0) - (u.cacheWrite ?? 0);
    return (Math.max(0, inTok) * 5 + (u.output ?? 0) * 25 + (u.cacheRead ?? 0) * 0.5 + (u.cacheWrite ?? 0) * 6.25) / 1e6;
  }, [usage]);

  if (run.status === "failed") {
    return (
      <div className="panel tq-result">
        <div className="panel-head"><VerdictBadge run={run} /> <span className="sub">{run.symbol} · {run.primaryTf}</span>
          <span className="tq-head-right"><CopyChip value={run.id}
            link={absoluteUrl({ page: "technique", techniqueTab: "analyse", runId: run.id })} /></span></div>
        <div className="panel-body"><div className="neg">{run.error}</div></div>
      </div>
    );
  }
  if (!a) return null;

  return (
    <div className="panel tq-result">
      <div className="panel-head">
        <VerdictBadge run={run} />
        <span className="tq-sym">{a.symbol}</span>
        <span className="sub">{run.primaryTf} · trend {a.trend} · confidence <b>{fmt(a.confidence)}</b>
          {run.mode === "image_only" ? " · image-only (approximate prices)" : ""}</span>
        <span className="tq-grounded" title="Every price re-verified against the bar data">
          {grounding?.passed ? <><IconCheck size={11} /> grounded</> : <><IconX size={11} /> not grounded</>}
        </span>
        <span className="sub tq-head-right">
          <CopyChip value={run.id} title={`Run ${run.id} — click to copy the id`}
            link={absoluteUrl({ page: "technique", techniqueTab: "analyse", runId: run.id })} />
          {run.finishedAt ? fmtDateTime(run.finishedAt) : ""} · {run.seconds ?? run.result?.seconds ?? "?"}s · ≈${cost.toFixed(2)}
        </span>
      </div>
      <div className="panel-body tq-result-body">
        <div className="tq-result-main">
          {a.verdict === "setup" && a.entry && a.stop && (
            <div className="tq-plan">
              <div className="tq-plan-cell"><small>Entry</small><b>{fmt(a.entry.price)}</b>
                <span>{a.entry.basis.replace(/_/g, " ")}{a.entry.requiresConfirmation ? " · confirm" : ""}</span></div>
              <div className="tq-plan-cell"><small>Stop</small><b className="neg">{fmt(a.stop.price)}</b>
                <span>{a.stop.kind} · {a.stop.reference.replace(/_/g, " ")}</span></div>
              {a.targets.map((t, i) => (
                <div className="tq-plan-cell" key={i}><small>TP{i + 1}</small><b className="pos">{fmt(t.price)}</b>
                  <span>{t.trimPct}% · {t.basis.replace(/_/g, " ")}</span></div>
              ))}
              <div className="tq-plan-cell"><small>R:R</small><b className={a.riskReward >= 3 ? "pos" : "neg"}>{fmt(a.riskReward)}</b>
                <span>runner {a.runnerPct}%</span></div>
            </div>
          )}
          {a.verdict === "no_setup" && (
            <div className="tq-nosetup">
              <div className="tq-nosetup-head">No tradeable setup right now</div>
              <div className="tq-nosetup-body">
                The numbers below describe what the market <i>is</i> doing — the levels, volume and
                structure the method reads. They are not a trade. The chart marks the candidate that
                was considered and declined (dashed, ✗), so you can see the geometry that failed.
                {rejectedLine && <div className="tq-nosetup-cand">{rejectedLine}</div>}
              </div>
            </div>
          )}
          {annotated && (
            <a href={api.assetUrl(annotated)} target="_blank" rel="noreferrer" className="tq-img-wrap">
              <img src={api.assetUrl(annotated)} alt="annotated chart" className="tq-img" />
              <span className="tq-img-cap">
                {a.verdict === "setup"
                  ? "solid = the plan · blue support / amber resistance · shaded = risk and reward"
                  : "dashed grey ✗ = candidate declined · blue support / amber resistance"}
              </span>
            </a>
          )}
          <div className="tq-section">
            <div className="tq-label">Levels that matter</div>
            <div className="tq-levels">
              {a.levels.map((lv, i) => (
                <span key={i} className={`tq-level ${lv.kind}`} title={lv.note}>
                  {lv.kind === "support" ? "S" : "R"} {fmt(lv.price)} <em>×{lv.touches}</em>
                </span>
              ))}
            </div>
          </div>
          <div className="tq-section"><div className="tq-label">Volume</div><div>{a.volumeVerdict}</div></div>
          {a.pattern?.present && (
            <div className="tq-section"><div className="tq-label">Pattern</div>
              <div>{a.pattern.kind.replace(/_/g, " ")}{a.pattern.widestHeight ? ` · height ${fmt(a.pattern.widestHeight)}` : ""}
                {a.pattern.volumeDeclining ? " · volume declining" : ""} — {a.pattern.notes}</div></div>
          )}
          {a.breakout?.observed && (
            <div className="tq-section"><div className="tq-label">Breakout test</div>
              <div className="tq-chips">
                <span className={`tq-chip ${a.breakout.verdict === "breakout" ? "ok" : "bad"}`}>{a.breakout.verdict}</span>
                <span className={`tq-chip ${a.breakout.volumeConfirmed ? "ok" : "bad"}`}>volume</span>
                <span className={`tq-chip ${a.breakout.decisiveCandle ? "ok" : "bad"}`}>decisive candle</span>
                <span className={`tq-chip ${a.breakout.followThrough ? "ok" : "bad"}`}>follow-through</span>
                <span className={`tq-chip ${a.breakout.holdsLevel ? "ok" : "bad"}`}>holds level</span>
                <span className={`tq-chip ${a.breakout.higherTfAgrees ? "ok" : "bad"}`}>higher TF</span>
              </div></div>
          )}
          {a.noTradeReasons.length > 0 && (
            <div className="tq-section"><div className="tq-label">{a.verdict === "setup" ? "Warnings" : "No-trade reasons"}</div>
              <ul className="tq-reasons">{a.noTradeReasons.map((r, i) => <li key={i}>{r}</li>)}</ul></div>
          )}
          {options && (
            <div className="tq-section"><div className="tq-label">Options expression (T5)</div>
              {options.available && options.symbol ? (
                <div>
                  <b>{options.display ?? options.symbol}</b> {options.optionType} {options.strike} exp {options.expiry}{options.is0dte ? " (0DTE)" : ""} ·
                  bid/ask {options.bid}/{options.ask} · spread {options.spreadPct}% · Δ {options.delta ?? "—"} · IV {options.iv ?? "—"} · OI {options.openInterest}
                  {" "}<button className="link-btn" onClick={() => useStore.getState().openOptions({ contract: options.symbol, side: "BUY", qty: 1 })}
                    title="Open the option ticket with this contract loaded (practice by default)">trade this contract →</button>
                  {options.warnings?.length > 0 && <ul className="tq-reasons">{options.warnings.map((w: string, i: number) => <li key={i}>{w}</li>)}</ul>}
                </div>
              ) : (
                <div className="muted">{options.error ?? "no contract"} · guidance: {a.optionsExpression?.strikeGuidance}; {a.optionsExpression?.expiryGuidance}</div>
              )}
            </div>
          )}
          <div className="tq-section"><div className="tq-label">Rationale</div><Markdown text={a.rationale} /></div>
          <div className="tq-section"><div className="tq-label">Rules fired</div><RuleChips ids={a.rulesFired} rules={rules} /></div>
          <OutcomeSection run={run} onRefresh={onRefresh} />
          <ReviewSection run={run} onRefresh={onRefresh} />
        </div>
        <div className="tq-result-side">
          <div className="tq-label">Grounding {grounding ? `${(grounding.checks ?? []).length - failed.length}/${(grounding.checks ?? []).length}` : ""}
            <button className="link-btn" onClick={() => setShowChecks((v) => !v)}>{showChecks ? "hide" : "show"}</button></div>
          {showChecks && (
            <div className="check-grid tq-checks">
              {(grounding?.checks ?? []).map((c: GroundingCheck) => (
                <span key={c.name} className={`check-item ${c.passed ? "ok" : "fail"}`} title={c.detail}>
                  {c.passed ? <IconCheck size={10} /> : <IconX size={10} />} {c.name.replace(/_/g, " ")}
                </span>
              ))}
            </div>
          )}
          {!showChecks && failed.length > 0 && (
            <ul className="tq-reasons small">{failed.map((c) => <li key={c.name}>{c.name.replace(/_/g, " ")} — {c.detail}</li>)}</ul>
          )}
          <div className="tq-label" style={{ marginTop: 10 }}>Passes</div>
          <table className="tq-passes">
            <tbody>
              {passes.map((p, i) => (
                <tr key={i}><td>{p.name}</td><td>{p.seconds}s</td>
                  <td className="muted">{p.usage?.input}↓ {p.usage?.output}↑{p.usage?.cacheRead ? ` · ${p.usage.cacheRead} cached` : ""}</td></tr>
              ))}
            </tbody>
          </table>
          <div className="muted" style={{ marginTop: 6 }}>
            {run.llm?.model} · effort {run.llm?.effort} · total {(usage as any).input ?? 0}↓ {(usage as any).output ?? 0}↑
          </div>
          <Provenance run={run} />
          <div className="tq-label" style={{ marginTop: 10 }}>Trace {trace.length ? `${trace.length} steps` : ""}
            {trace.length > 0 && <button className="link-btn" onClick={() => setShowTrace((v) => !v)}>{showTrace ? "hide" : "show"}</button>}</div>
          {!trace.length && <div className="muted">no trace recorded (run predates tracing)</div>}
          <div className="tq-side-actions">
            {run.threadId && <button className="primary-btn" onClick={() => openChat(run.threadId!)}>Discuss in chat</button>}
            <ReplayControls run={run} />
            <a className="ghost-btn tq-dl" href={api.techniqueBundleUrl(run.id)} title="Everything about this run as a zip: trace, transcript, facts, bars, images, outcome, reviews">
              Download bundle
            </a>
          </div>
        </div>
        {showTrace && trace.length > 0 && <TracePanel trace={trace} />}
        <div className="tq-facts-bar">
          <button className="tq-facts-toggle" onClick={() => setShowFacts((v) => !v)}
            aria-expanded={showFacts}>
            <span className={`disclosure-chev ${showFacts ? "open" : ""}`} aria-hidden="true">
              <svg width="10" height="10" viewBox="0 0 16 16" fill="none" stroke="currentColor"
                   strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M5 3l6 5-6 5" /></svg>
            </span>
            Deterministic facts
            <span className="muted">— every level, volume reading and candidate the detectors measured</span>
          </button>
          <Collapse open={showFacts}>
            <div className="tq-facts"><FactsView facts={run.facts} /></div>
          </Collapse>
        </div>
      </div>
    </div>
  );
}


// --- review loop: provenance, trace, outcome, review, replay ---------------------------------

function Provenance({ run }: { run: TechniqueRun }) {
  const c = run.config ?? {};
  if (!c.processVersion) return null;
  const ov = c.overrides ?? {};
  const ovText = Object.keys(ov.thresholds ?? {}).length
    ? Object.entries(ov.thresholds).map(([k, v]) => `${k}=${v}`).join(", ") : "";
  return (
    <div className="tq-prov muted" title={`prompt ${c.promptVersion} · rulebook ${c.rulebookVersion} · code ${c.codeVersion}`}>
      process <code>{c.processVersion}</code> · code <code>{c.codeVersion}</code>
      {run.parentRunId && (
        <> · replay of <button className="link-btn" onClick={() => useStore.getState().openTechniqueRun(run.parentRunId!)}>{run.parentRunId.slice(0, 8)}</button>
          {ovText ? <> with {ovText}</> : null}{ov.barsFromSnapshot ? " (same bars)" : ""}</>
      )}
    </div>
  );
}

const STAGE_ORDER = ["run", "data", "loop", "context", "pattern", "entry", "critic", "grounding", "options", "setup", "proposal"];

function TracePanel({ trace }: { trace: TraceStep[] }) {
  const [open, setOpen] = useState<number | null>(null);
  return (
    <div className="tq-trace">
      <div className="tq-label">Decision trace <span className="muted">— every step the pipeline took and why</span></div>
      <table className="tq-trace-table">
        <tbody>
          {trace.map((t) => (
            <tr key={t.seq} className={`stage-${STAGE_ORDER.includes(t.stage) ? t.stage : "other"} ${t.detail ? "clickable" : ""}`}
              onClick={() => t.detail && setOpen(open === t.seq ? null : t.seq)}>
              <td className="muted">{t.seq}</td>
              <td className="muted">{t.t !== null && t.t !== undefined ? `${t.t}s` : ""}</td>
              <td><span className="tq-chip">{t.stage}</span></td>
              <td className="tq-trace-step">{t.step}</td>
              <td className="tq-trace-reason">{t.reason}
                {open === t.seq && t.detail && <pre className="tq-trace-detail">{JSON.stringify(t.detail, null, 1)}</pre>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function OutcomeSection({ run, onRefresh }: { run: TechniqueRun; onRefresh?: () => void }) {
  const toast = useStore((s) => s.toast);
  const [busy, setBusy] = useState(false);
  const outs = run.outcomes ?? [];
  const score = async () => {
    setBusy(true);
    try { await api.techniqueScore(run.id); onRefresh?.(); }
    catch (e: any) { toast("error", e.message); }
    finally { setBusy(false); }
  };
  if (run.status !== "done" || run.mode === "image_only") return null;
  return (
    <div className="tq-section tq-outcome">
      <div className="tq-label">What happened next
        <span className="muted"> — scored like the backtester: fill at the entry, stop wins a straddling bar, 30/40/15 trims</span>
        <button className="link-btn" disabled={busy} onClick={score}>{busy ? "scoring…" : outs.length ? "re-score" : "score now"}</button>
      </div>
      {outs.length === 0 && <div className="muted">Not scored yet — the outcome loop picks finished runs up every 30 min once bars exist after the decision.</div>}
      {outs.length > 0 && (
        <div className="tq-plan">
          {outs.map((o) => {
            const src = o.planSource === "analysis" ? "The plan" : o.planSource === "candidate" ? "Declined candidate" : "Market path";
            const r = o.rMultiple;
            return (
              <div className="tq-plan-cell tq-outcome-cell" key={o.id} title={o.note ?? ""}>
                <small>{src}{o.status === "partial" ? " (partial)" : o.status === "pending" ? " (pending)" : o.status === "unscorable" ? " (unscorable)" : ""}</small>
                <b className={r === null ? "" : r > 0 ? "pos" : r < 0 ? "neg" : ""}>
                  {o.outcome ? o.outcome.replace(/_/g, " ") : o.status === "scored" || o.status === "partial" ? "path" : o.status}
                  {r !== null && o.outcome !== "not_filled" ? ` ${r > 0 ? "+" : ""}${r.toFixed(2)}R` : ""}
                </b>
                <span>
                  {o.mfeR !== null && o.outcome !== "not_filled" ? `MFE ${o.mfeR.toFixed(2)}R · MAE ${(o.maeR ?? 0).toFixed(2)}R · ${o.barsHeld ?? 0} bars` : (o.note ?? "")}
                  {o.path && o.path["+30"] ? ` · +30 bars: ${o.path["+30"].closePct > 0 ? "+" : ""}${o.path["+30"].closePct}%` : ""}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function ReviewSection({ run, onRefresh }: { run: TechniqueRun; onRefresh?: () => void }) {
  const toast = useStore((s) => s.toast);
  const reviews: TechniqueReview[] = run.reviews ?? [];
  const [tax, setTax] = useState<TechniqueTaxonomy | null>(null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [f, setF] = useState({ reviewVerdict: "", rootCauseStage: "", expectedVerdict: "", expectedSetupType: "",
    expectedEntry: "", expectedStop: "", expectationNote: "", notes: "", actions: "" });
  useEffect(() => { if (open && !tax) api.techniqueTaxonomy().then(setTax).catch(() => undefined); }, [open, tax]);
  const submit = async () => {
    if (!f.reviewVerdict) { toast("error", "Pick a review verdict"); return; }
    setBusy(true);
    try {
      const plan: any = {};
      if (f.expectedEntry) plan.entry = Number(f.expectedEntry);
      if (f.expectedStop) plan.stop = Number(f.expectedStop);
      await api.techniqueAddReview(run.id, {
        reviewVerdict: f.reviewVerdict, rootCauseStage: f.rootCauseStage || null,
        expectedVerdict: f.expectedVerdict || null, expectedSetupType: f.expectedSetupType || null,
        expectedPlan: plan, expectationNote: f.expectationNote, notes: f.notes,
        actions: f.actions.split("\n").map((x) => x.trim()).filter(Boolean), reviewer: "user",
      });
      toast("success", "Review saved");
      setOpen(false);
      setF({ reviewVerdict: "", rootCauseStage: "", expectedVerdict: "", expectedSetupType: "", expectedEntry: "",
        expectedStop: "", expectationNote: "", notes: "", actions: "" });
      onRefresh?.();
    } catch (e: any) { toast("error", e.message); } finally { setBusy(false); }
  };
  if (run.status !== "done") return null;
  return (
    <div className="tq-section tq-review">
      <div className="tq-label">Review
        <span className="muted"> — what you expected vs what it said; where the first wrong turn was</span>
        <button className="link-btn" onClick={() => setOpen((v) => !v)}>{open ? "cancel" : reviews.length ? "add review" : "review this run"}</button>
      </div>
      {reviews.length > 0 && (
        <ul className="tq-reviews">
          {reviews.map((r) => (
            <li key={r.id}>
              <ReviewBadge last={{ reviewVerdict: r.reviewVerdict, rootCauseStage: r.rootCauseStage, createdAt: r.createdAt, reviewer: r.reviewer }} count={1} />
              <span className="muted"> {r.reviewer} · {r.createdAt ? fmtDateTime(r.createdAt) : ""}{r.processVersion?.processVersion ? ` · process ${r.processVersion.processVersion}` : ""}</span>
              {r.expectedVerdict && <div>Expected <b>{r.expectedVerdict}</b>{r.expectedSetupType ? ` (${r.expectedSetupType.replace(/_/g, " ")})` : ""}
                {r.expectedPlan?.entry ? ` · entry ${r.expectedPlan.entry}` : ""}{r.expectedPlan?.stop ? ` · stop ${r.expectedPlan.stop}` : ""}
                {r.expectationNote ? ` — ${r.expectationNote}` : ""}</div>}
              {r.notes && <div className="tq-review-notes">{r.notes}</div>}
              {r.actions?.length > 0 && <ul className="tq-reasons small">{r.actions.map((a, i) => <li key={i}>{a.desc}{a.status && a.status !== "planned" ? ` (${a.status})` : ""}</li>)}</ul>}
            </li>
          ))}
        </ul>
      )}
      {open && (
        <div className="tq-review-form">
          <div className="tq-row">
            <label className="tq-ctl"><span className="tq-ctl-label">Verdict on the run</span>
              <select value={f.reviewVerdict} onChange={(e) => setF({ ...f, reviewVerdict: e.target.value })}>
                <option value="">—</option>
                {Object.entries(tax?.reviewVerdicts ?? {}).map(([k, v]) => <option key={k} value={k} title={v}>{k.replace(/_/g, " ")}</option>)}
              </select></label>
            <label className="tq-ctl"><span className="tq-ctl-label">Root-cause stage</span>
              <select value={f.rootCauseStage} onChange={(e) => setF({ ...f, rootCauseStage: e.target.value })}>
                <option value="">—</option>
                {Object.entries(tax?.rootCauseStages ?? {}).map(([k, v]) => <option key={k} value={k} title={v}>{k.replace(/_/g, " ")}</option>)}
              </select></label>
            <label className="tq-ctl"><span className="tq-ctl-label">I expected</span>
              <select value={f.expectedVerdict} onChange={(e) => setF({ ...f, expectedVerdict: e.target.value })}>
                <option value="">—</option><option value="setup">setup</option><option value="no_setup">no setup</option>
              </select></label>
            <label className="tq-ctl"><span className="tq-ctl-label">Type</span>
              <select value={f.expectedSetupType} onChange={(e) => setF({ ...f, expectedSetupType: e.target.value })}>
                <option value="">—</option><option value="support_bounce">support bounce</option>
                <option value="breakout">breakout</option><option value="falling_wedge">falling wedge</option>
              </select></label>
            <label className="tq-ctl"><span className="tq-ctl-label">Entry</span>
              <input type="number" step="0.01" value={f.expectedEntry} onChange={(e) => setF({ ...f, expectedEntry: e.target.value })} /></label>
            <label className="tq-ctl"><span className="tq-ctl-label">Stop</span>
              <input type="number" step="0.01" value={f.expectedStop} onChange={(e) => setF({ ...f, expectedStop: e.target.value })} /></label>
          </div>
          {tax && f.reviewVerdict && <small className="muted">{tax.reviewVerdicts[f.reviewVerdict]}</small>}
          {tax && f.rootCauseStage && <small className="muted"> · {tax.rootCauseStages[f.rootCauseStage]}</small>}
          <label className="field"><span className="tq-ctl-label">What I expected, in words</span>
            <input value={f.expectationNote} onChange={(e) => setF({ ...f, expectationNote: e.target.value })} placeholder="e.g. bounce at prior-day LOD with rising volume" /></label>
          <label className="field"><span className="tq-ctl-label">Notes / diagnosis</span>
            <textarea rows={3} value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} placeholder="where the first wrong turn was, and the evidence" /></label>
          <label className="field"><span className="tq-ctl-label">Planned actions (one per line)</span>
            <textarea rows={2} value={f.actions} onChange={(e) => setF({ ...f, actions: e.target.value })} placeholder="e.g. SYSTEM_PROMPT: bounce entries never need confirmation (T4.2)" /></label>
          <div className="tq-form-actions">
            <button className="primary-btn" disabled={busy} onClick={submit}>{busy ? "Saving…" : "Save review"}</button>
            <span className="muted">Tip: in Claude Code, <code>/technique-review {run.id.slice(0, 10)}</code> does the full audit.</span>
          </div>
        </div>
      )}
    </div>
  );
}

function ReplayControls({ run }: { run: TechniqueRun }) {
  const toast = useStore((s) => s.toast);
  const openRun = useStore((s) => s.openTechniqueRun);
  const [busy, setBusy] = useState(false);
  const [diff, setDiff] = useState<any | null>(null);
  if (run.status !== "done" || run.mode === "image_only") return null;
  const replay = async () => {
    setBusy(true);
    try {
      const child = await api.techniqueReplay(run.id, { useSnapshot: true, wait: false, note: "replay from UI" });
      toast("info", `Replaying ${run.symbol} as run ${child.id.slice(0, 8)}…`);
      openRun(child.id);
    } catch (e: any) { toast("error", e.message); } finally { setBusy(false); }
  };
  const compare = async (other: string) => {
    try { setDiff(await api.techniqueDiff(run.parentRunId ?? run.id, other)); }
    catch (e: any) { toast("error", e.message); }
  };
  const replays = run.replays ?? [];
  return (
    <>
      <button className="ghost-btn" disabled={busy} onClick={replay}
        title="Run the same moment again with the saved bars (new process version = same data, new verdict?)">
        {busy ? "Starting…" : "Replay (same bars)"}
      </button>
      {run.parentRunId && <button className="ghost-btn" onClick={() => compare(run.id)}>Compare with parent</button>}
      {replays.length > 0 && (
        <div className="tq-replays muted">
          replays: {replays.map((c) => (
            <span key={c.id}> <button className="link-btn" onClick={() => openRun(c.id)}>{c.id.slice(0, 8)}</button>
              ({c.verdict ?? c.status}) <button className="link-btn" onClick={() => compare(c.id)}>diff</button></span>
          ))}
        </div>
      )}
      {diff && (
        <div className="tq-diff">
          <div className="tq-label">Diff {diff.a.id.slice(0, 8)} → {diff.b.id.slice(0, 8)}
            <button className="link-btn" onClick={() => setDiff(null)}>close</button></div>
          {["versions", "thresholds", "settings", "analysis"].map((sec) => (
            <div key={sec}>
              <small className="muted">{sec}: {Object.keys(diff[sec] ?? {}).length === 0 ? "identical" : ""}</small>
              {Object.entries(diff[sec] ?? {}).map(([k, v]: any) => (
                <div key={k} className="tq-diff-row"><code>{k}</code> {JSON.stringify(v.a)} → {JSON.stringify(v.b)}</div>
              ))}
            </div>
          ))}
        </div>
      )}
    </>
  );
}
