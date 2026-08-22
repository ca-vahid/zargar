import { useState } from "react";
import { api } from "../../lib/api";
import { fmtDateTime } from "../../lib/format";
import { useStore } from "../../store";
import { absoluteUrl } from "../../lib/routing";
import type { PlanTrigger, SessionPlan, TechniqueRun } from "../../types";
import { CopyChip } from "../CopyChip";
import { OutcomeSection, Provenance, ReplayControls, ReviewSection, TracePanel, WindowBadge } from "./RunResult";

function fmt(n: number | null | undefined, d = 2) {
  return n === null || n === undefined || Number.isNaN(n) ? "—" : n.toFixed(d);
}

const KIND_LABEL: Record<string, string> = { bounce: "Support bounce", breakout: "Breakout", wedge_break: "Wedge break" };

function TriggerRow({ t, outcome }: { t: PlanTrigger; outcome?: any }) {
  const [open, setOpen] = useState(false);
  const fired = outcome && outcome.planSource && outcome.outcome && outcome.outcome !== "not_triggered";
  return (
    <div className={`tq-trigger ${t.valid ? "valid" : "invalid"}`}>
      <button type="button" className="tq-trigger-head" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        <span className="tq-chip">{t.id}</span>
        <b>{KIND_LABEL[t.kind] ?? t.kind}</b>
        <span>WATCH <b>{fmt(t.levelPrice)}</b></span>
        <span className="muted">· IF {t.conditions.map((c) => c.kind).join(" + ")} · THEN long {fmt(t.entry.price)} / stop {fmt(t.stop.price)} · R:R {fmt(t.riskReward)}</span>
        {!t.valid && <span className="tq-badge failed">not tradeable</span>}
        {outcome && (
          <span className={`tq-badge ${fired && (outcome.rMultiple ?? 0) > 0 ? "setup" : fired && (outcome.rMultiple ?? 0) < 0 ? "failed" : "nosetup"}`}
            title={outcome.note ?? ""}>
            {outcome.outcome ? String(outcome.outcome).replace(/_/g, " ") : outcome.status}
            {outcome.rMultiple !== null && outcome.rMultiple !== undefined && fired ? ` ${outcome.rMultiple > 0 ? "+" : ""}${outcome.rMultiple.toFixed(2)}R` : ""}
          </span>
        )}
      </button>
      {open && (
        <div className="tq-trigger-body">
          <div className="tq-trigger-grid">
            <div><small>IF</small>
              <ul>{t.conditions.map((c, i) => <li key={i}><span className="tq-chip">{c.rule}</span> {c.text}</li>)}</ul></div>
            <div><small>THEN</small>
              <div>long <b>{fmt(t.entry.price)}</b> ({t.entry.basis.replace(/_/g, " ")}) · stop <b className="neg">{fmt(t.stop.price)}</b> ({t.stop.reference.replace(/_/g, " ")})</div>
              <div>targets {t.targets.map((x) => `${fmt(x.price)} (${x.trimPct}%)`).join(" · ")} · R:R <b className={t.riskReward >= 3 ? "pos" : "neg"}>{fmt(t.riskReward)}</b> · risk {fmt(t.risk)}</div>
            </div>
            <div><small>VOID IF</small><ul>{t.voidIf.map((v, i) => <li key={i}>{v}</li>)}</ul></div>
            <div><small>Why</small>
              <div>{t.confluences.length ? t.confluences.join("; ") : "no extra confluence"} · confidence {fmt(t.confidence)}</div>
              {t.noTradeReasons.length > 0 && <ul className="tq-reasons small">{t.noTradeReasons.map((r, i) => <li key={i}>{r}</li>)}</ul>}
              <div className="muted">{t.notes}</div>
              <div className="tq-chips">{t.rules.map((r) => <span key={r} className="tq-chip">{r}</span>)}</div>
            </div>
          </div>
          {outcome?.plan?.counterfactual && (
            <div className="muted small">
              counterfactual — without the R6 gate: {outcome.plan.counterfactual.noWindowGate?.status}
              {outcome.plan.counterfactual.noWindowGate?.sim ? ` (${outcome.plan.counterfactual.noWindowGate.sim.outcome}, ${outcome.plan.counterfactual.noWindowGate.sim.rMultiple}R)` : ""}
              · without gap rules: {outcome.plan.counterfactual.noGapRules?.status}
              {outcome.plan.observedMidday ? ` · mid-day touches observed: ${outcome.plan.observedMidday}` : ""}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/** A session plan run: the map + conditional triggers (never a fill), what the
 *  next session did to them, arm/disarm, review. */
export function PlanCard({ run, onRefresh }: { run: TechniqueRun; onRefresh?: () => void }) {
  const plan: SessionPlan | undefined = run.result?.plan;
  const toast = useStore((s) => s.toast);
  const openChat = useStore((s) => s.openTechniqueChat);
  const armed = useStore((s) => s.techniqueArmed);
  const [showTrace, setShowTrace] = useState(false);
  const [busy, setBusy] = useState(false);
  const isArmed = armed.some((a) => a.runId === run.id);
  const trace = run.result?.trace ?? [];
  const outs = run.outcomes ?? [];
  const byTrigger = Object.fromEntries(outs.filter((o) => o.planSource.startsWith("trigger:")).map((o) => [o.planSource.slice(8), o]));
  const levelsRow = outs.find((o) => o.planSource === "levels");
  const respect: any[] = levelsRow?.plan?.levels ?? [];
  const respectBy = Object.fromEntries(respect.map((r: any) => [String(r.price), r]));
  if (!plan) return null;
  const arm = async () => {
    setBusy(true);
    try {
      if (isArmed) { await api.techniqueDisarm(run.id); toast("info", "Plan disarmed"); }
      else { await api.techniqueArm(run.id); toast("success", `Armed ${plan.symbol} plan for ${plan.planFor}`); }
      onRefresh?.();
    } catch (e: any) { toast("error", e.message); } finally { setBusy(false); }
  };
  return (
    <div className="panel tq-result tq-plan-card">
      <div className="panel-head">
        <span className="tq-badge plan">PLAN · {plan.validTriggers} trigger{plan.validTriggers === 1 ? "" : "s"}</span>
        <span className="tq-sym">{plan.symbol}</span>
        <span className="sub">for <b>{plan.planFor}</b> · built from the {plan.builtFromSession} close {fmt(plan.lastClose)} · structure {plan.structureTfs.join("/")} · triggers on {plan.triggerTf}</span>
        {isArmed && <span className="tq-badge setup">ARMED</span>}
        <span className="sub tq-head-right">
          <CopyChip value={run.id} link={absoluteUrl({ page: "technique", techniqueTab: "analyse", runId: run.id })} />
          {run.finishedAt ? fmtDateTime(run.finishedAt) : ""} · {run.seconds ?? run.result?.seconds ?? "?"}s
        </span>
      </div>
      <div className="panel-body tq-result-body">
        <div className="tq-result-main">
          <div className="tq-nosetup">
            <div className="tq-nosetup-head">Tomorrow's map, not a trade</div>
            <div className="tq-nosetup-body">
              The market was closed at the as-of instant (R6.4), so this is the book's pre-session routine (pp. 116–117, 120):
              the levels that matter and <i>conditional</i> triggers — WATCH a level, IF price reaches it inside a prime window on
              adequate volume, THEN the plan, VOID IF the open gaps past it. Levels are redrawn every session; prior-day HOD/LOD carry.
              {plan.notes.length > 0 && <div className="tq-nosetup-cand">{plan.notes.join(" ")}</div>}
            </div>
          </div>
          <div className="tq-section">
            <div className="tq-label">Levels <span className="muted">— provenance, touches, age{levelsRow ? " · what the session did" : ""}</span></div>
            <table className="tq-table tq-plan-levels">
              <thead><tr><th>Price</th><th>Kind</th><th>Touches</th><th>Source</th><th>TFs</th><th>Dist</th><th>Age</th>{levelsRow && <th>Session</th>}</tr></thead>
              <tbody>
                {plan.levels.map((l, i) => {
                  const r = respectBy[String(l.price)];
                  return (
                    <tr key={i} className={l.priorDayExtreme ? "pd" : ""}>
                      <td><b>{fmt(l.price)}</b></td>
                      <td><span className={`tq-level ${l.effectiveKind}`}>{l.effectiveKind}</span></td>
                      <td>×{l.touches}</td>
                      <td className="muted">{l.sources.join(",")}{l.priorDayExtreme ? " · prior-day" : ""}{l.carried ? " (carried)" : ""}</td>
                      <td className="muted">{l.timeframes.join(",")}</td>
                      <td>{l.distancePct !== null && l.distancePct !== undefined ? `${l.distancePct > 0 ? "+" : ""}${l.distancePct.toFixed(2)}%` : "—"}</td>
                      <td className="muted">{l.ageSessions ?? "—"}</td>
                      {levelsRow && <td><span className={`tq-badge ${r?.status === "respected" ? "setup" : r?.status === "broken" ? "failed" : "nosetup"}`}>{r?.status ?? "—"}</span></td>}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="tq-section">
            <div className="tq-label">Triggers <span className="muted">— conditional, never a fill (T4.1); click to expand</span></div>
            {plan.triggers.length === 0 && <div className="muted">No level within reach — a plan with nothing to do (p. 117).</div>}
            {plan.triggers.map((t) => <TriggerRow key={t.id} t={t} outcome={byTrigger[t.id]} />)}
          </div>
          <div className="tq-section">
            <div className="tq-label">Void if</div>
            <ul className="tq-reasons">{plan.invalidations.map((i, k) => <li key={k}><span className="tq-chip">{i.rule}</span> {i.text}</li>)}</ul>
            <div className="muted small">Gap handling is our extrapolation — the book is silent on overnight gaps (spec Q11–Q13); the walk-forward reports it with and without.</div>
          </div>
          {levelsRow && (
            <div className="tq-section">
              <div className="tq-label">What the session did <span className="muted">— {levelsRow.note}</span></div>
              <div className="tq-plan">
                {levelsRow.path && levelsRow.path["+30"] && (
                  <div className="tq-plan-cell"><small>+30 bars</small><b>{levelsRow.path["+30"].closePct > 0 ? "+" : ""}{levelsRow.path["+30"].closePct}%</b><span>hi {fmt(levelsRow.path["+30"].high)} · lo {fmt(levelsRow.path["+30"].low)}</span></div>
                )}
                {levelsRow.plan?.summary && (
                  <>
                    <div className="tq-plan-cell"><small>Gap at open</small><b>{levelsRow.plan.summary.gapPct > 0 ? "+" : ""}{levelsRow.plan.summary.gapPct}%</b><span>open {fmt(levelsRow.plan.summary.open)} · close {fmt(levelsRow.plan.summary.close)}</span></div>
                    <div className="tq-plan-cell"><small>Triggers fired</small><b>{levelsRow.plan.summary.fired} / {levelsRow.plan.summary.triggers}</b><span>{levelsRow.plan.summary.wins} win · ΣR {levelsRow.plan.summary.sumR}</span></div>
                    <div className="tq-plan-cell"><small>Levels</small><b>{levelsRow.plan.summary.levelsRespected} respected</b><span>{levelsRow.plan.summary.levelsBroken} broken · {levelsRow.plan.summary.levelsUntested} untested</span></div>
                  </>
                )}
              </div>
            </div>
          )}
          {!levelsRow && <OutcomeSection run={run} onRefresh={onRefresh} />}
          <ReviewSection run={run} onRefresh={onRefresh} />
        </div>
        <div className="tq-result-side">
          <div className="tq-label">Context</div>
          <div className="muted small">
            {Object.entries(plan.context?.trend ?? {}).map(([tf, tr]: any) => <div key={tf}>trend {tf}: {tr.direction}</div>)}
            {plan.context?.prevSession && <div>prev {plan.context.prevSession.date}: HOD {fmt(plan.context.prevSession.hod)} · LOD {fmt(plan.context.prevSession.lod)}</div>}
            {plan.context?.lastSession && <div>last: open {fmt(plan.context.lastSession.open)} · HOD {fmt(plan.context.lastSession.hod)} · LOD {fmt(plan.context.lastSession.lod)} · close {fmt(plan.context.lastSession.close)}</div>}
            <WindowBadge window={run.result?.sessionWindow} />
          </div>
          {run.result?.passes && run.result.passes.length > 0 && (
            <><div className="tq-label" style={{ marginTop: 10 }}>Vision passes</div>
              <table className="tq-passes"><tbody>{run.result.passes.map((p, i) => <tr key={i}><td>{p.name}</td><td>{p.seconds}s</td></tr>)}</tbody></table></>
          )}
          <Provenance run={run} />
          <div className="tq-label" style={{ marginTop: 10 }}>Trace {trace.length ? `${trace.length} steps` : ""}
            {trace.length > 0 && <button className="link-btn" onClick={() => setShowTrace((v) => !v)}>{showTrace ? "hide" : "show"}</button>}</div>
          <div className="tq-side-actions">
            <button className={isArmed ? "ghost-btn" : "primary-btn"} disabled={busy || run.status !== "done"} onClick={arm}
              title="Arm: watch the triggers on live 1m bars inside the prime windows; a fire becomes a setup (and a practice proposal if enabled)">
              {busy ? "…" : isArmed ? "Disarm" : "Arm for live triggers"}
            </button>
            {run.threadId && <button className="ghost-btn" onClick={() => openChat(run.threadId!)}>Discuss in chat</button>}
            <ReplayControls run={run} />
            <a className="ghost-btn tq-dl" href={api.techniqueBundleUrl(run.id)}>Download bundle</a>
          </div>
        </div>
        {showTrace && trace.length > 0 && <TracePanel trace={trace} />}
      </div>
    </div>
  );
}
