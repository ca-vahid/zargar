import { useMemo, useState } from "react";
import { api } from "../../lib/api";
import { fmtDateTime } from "../../lib/format";
import { useStore } from "../../store";
import type { GroundingCheck, TechniqueContract, TechniqueRun } from "../../types";
import { IconCheck, IconX } from "../icons";
import { Collapse } from "../Collapse";
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
export function RunResult({ run, rules }: { run: TechniqueRun; rules: Record<string, string> }) {
  const openChat = useStore((s) => s.openTechniqueChat);
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
        <div className="panel-head"><VerdictBadge run={run} /> <span className="sub">{run.symbol} · {run.primaryTf}</span></div>
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
        <span className="sub" style={{ marginLeft: "auto" }}>
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
                  <b>{options.symbol}</b> {options.optionType} {options.strike} exp {options.expiry}{options.is0dte ? " (0DTE)" : ""} ·
                  bid/ask {options.bid}/{options.ask} · spread {options.spreadPct}% · Δ {options.delta ?? "—"} · IV {options.iv ?? "—"} · OI {options.openInterest}
                  {options.warnings?.length > 0 && <ul className="tq-reasons">{options.warnings.map((w: string, i: number) => <li key={i}>{w}</li>)}</ul>}
                </div>
              ) : (
                <div className="muted">{options.error ?? "no contract"} · guidance: {a.optionsExpression?.strikeGuidance}; {a.optionsExpression?.expiryGuidance}</div>
              )}
            </div>
          )}
          <div className="tq-section"><div className="tq-label">Rationale</div><Markdown text={a.rationale} /></div>
          <div className="tq-section"><div className="tq-label">Rules fired</div><RuleChips ids={a.rulesFired} rules={rules} /></div>
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
          <div className="tq-side-actions">
            {run.threadId && <button className="primary-btn" onClick={() => openChat(run.threadId!)}>Discuss in chat</button>}

          </div>

        </div>
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
