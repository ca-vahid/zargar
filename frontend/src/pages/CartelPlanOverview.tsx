import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { useStore } from "../store";
import { ErrorState, Spinner } from "../components/ui";
import { useWorkspace } from "../lib/workspace";

const price = (n: number) => Number.isFinite(n) ? n.toFixed(2) : "—";
const label = (s: string) => s.replaceAll("_", " ");

export function CartelPlanOverview({run, active}: {run: any; active?: any}) {
  const plan = run.result.plan.plan;
  const preparation = run.config?.preparation;
  const workspace = useWorkspace();
  const mismatch = preparation && (preparation.workspace || "practice") !== workspace;
  const [decision, setDecision] = useState<any>(null);
  const [loading, setLoading] = useState(!!preparation);
  const [error, setError] = useState("");
  const openArmedPlan = useStore(s => s.openArmedPlan);
  useEffect(() => {
    let alive = true;
    if (!preparation?.runId) { setLoading(false); return; }
    api.get<any>(`/api/options-cartel/runs/${encodeURIComponent(preparation.runId)}`).then(parent => {
      if (alive) setDecision(parent.result?.shortlist?.find((r: any) => r.planId === run.runId) || null);
    }).catch(e => { if (alive) setError(String(e)); }).finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [run.runId, preparation?.runId]);
  const risk = Math.abs(plan.trigger-plan.invalidation);
  const firstTarget = run.result.exitCampaign?.rungs.find((r: any) => r.kind === "target")?.target;
  const ratio = risk && firstTarget ? Math.abs(firstTarget-plan.trigger)/risk : null;
  const status = active ? label(active.status) : decision?.status === "awaiting_contract" ? "Awaiting contract (at preparation)" : "No active arm reported";
  return <section className="cartel-plan-overview" aria-label="Plan explanation">
    <div className="cartel-row"><h3>What this plan means</h3><span className={`status-pill ${active?.status === "armed" ? "ok" : "wait"}`}>{status}</span></div>
    {loading && <Spinner label="Loading preparation decision…"/>}
    {error && <ErrorState message={error}/>}
    {mismatch && <p className="cartel-notice">This record belongs to {preparation.workspace || "practice"}. Switch to that workspace to use its execution controls.</p>}
    {preparation && <p>Automatically prepared for {preparation.workspace === "live" ? "Live" : "Practice"}. You do not need to approve the green checks or arm an alert. Automatic arming still requires a suitable contract, valid plan window and execution permissions.</p>}
    {!active && decision?.selection?.pendingReason && <p className="cartel-notice">At preparation: {decision.selection.pendingReason}</p>}
    {!active && decision?.selection?.errors?.map((e: string, i: number) => <p key={i}>{e}</p>)}
    {active && <p>Execution mode: {active.config?.mode || active.mode}. {active.summary} {!mismatch && <button className="link-btn" onClick={() => openArmedPlan(run.runId)}>Open execution monitor</button>}</p>}
    {active?.volumeCoverage && <details open={active.volumeCoverage.limited}><summary>Supported entry windows</summary>
      <p>Volume baseline: {active.volumeCoverage.available}/{active.volumeCoverage.expected} periods. Policy: {label(active.volumeCoverage.policy)}.</p>
      <p>Confirmation windows (ET): {active.volumeCoverage.entryWindows?.map((w:any)=>`${w.startET}–${w.confirmationET}`).join(", ") || "none"}. Unsupported periods cannot trigger an entry; current session data and risk checks remain mandatory.</p>
    </details>}
    {active?.observationHealth && <section aria-label="Observation health"><h3>Observation health</h3>
      <p>{active.observationHealth.recordedMinutes}/{active.observationHealth.expectedMinutes} completed minutes · {active.observationHealth.overdueMissingMinutes} overdue gaps · {active.observationHealth.recoveries} recoveries during this session.</p>
      {active.observationHealth.lastRecovery && <p>Latest recovery: {new Date(active.observationHealth.lastRecovery.at).toLocaleString()} · {label(active.observationHealth.lastRecovery.reason)}</p>}
      <p>{active.observationHealth.note}</p>{active.observationHealth.repairError && <p className="cartel-notice">{active.observationHealth.repairError}</p>}
    </section>}
    {!!active?.decisionHistory?.length && <details open><summary>Entry decisions (preserved through recovery)</summary>
      {active.decisionHistory.map((d:any, i:number) => <div key={i}><p><b>{new Date(d.at).toLocaleString()}</b> · {label(d.decision)} · {d.reason}</p>
        {d.measurements && <p className="muted">Close {price(d.measurements.close)} · volume {d.measurements.volumeRatio?.toFixed(2) ?? "unknown"}× (required {d.measurements.requiredVolumeMultiple}×) · close location {(d.measurements.closeLocation*100).toFixed(1)}% (required {(d.measurements.requiredCloseLocation*100).toFixed(1)}%)</p>}
      </div>)}
    </details>}
    <div className="cartel-fields">
      <div><span className="muted">Selected setup</span><p><strong>{label(plan.direction)} · {label(plan.setup)}</strong></p></div>
      <div><span className="muted">Entry trigger</span><p><strong>{price(plan.trigger)}</strong></p></div>
      <div><span className="muted">Reviewed invalidation</span><p><strong>{price(plan.invalidation)}</strong></p></div>
      <div><span className="muted">First profit trim</span><p><strong>{firstTarget ? price(firstTarget) : "See exit schedule"}</strong></p></div>
    </div>
    <p>Entry window: <strong>{plan.first_session}</strong>{plan.last_session !== plan.first_session ? ` through ${plan.last_session}` : ""}. Crossing the trigger alone is not an entry: the engine checks the closed {plan.entry.timeframe_minutes}-minute candle, volume, chase limits and risk gates.</p>
    <p>{plan.entry.stop_mode === "session_extreme" ? "The actual initial stop uses the session low/high at entry. The invalidation shown above is the reviewed structure level." : `Initial stop rule: ${label(plan.entry.stop_mode)}.`}
      {ratio != null && ` First-target distance / structural risk: ${ratio.toFixed(2)}R. This uses the reviewed invalidation, not the eventual option loss or actual entry stop.`}</p>
    <p>“Pass” means the configured screen and setup checks matched the saved data. It does not mean buy now or guarantee a profitable trade. The alternative candidates below explain the measurements; only <strong>{label(plan.setup)}</strong> is selected for this plan.</p>
    <h3>Planned exits</h3>
    <div className="scroll-x"><table className="tbl"><thead><tr><th>Condition</th><th className="num">Allocation</th></tr></thead><tbody>
      {run.result.exitCampaign?.rungs.map((r: any) => <tr key={r.id}><td className="cartel-wrap">{
        r.kind === "target" ? `Target reached at ${price(r.target)}` : r.kind === "extension" ? `${r.atr_multiple}× ATR extension from EMA ${r.ema_period}` : `Daily close ${plan.direction === "long" ? "below" : "above"} EMA ${r.ema_period}`
      }</td><td className="num">{Math.round(r.fraction*100)}%</td></tr>)}
    </tbody></table></div>
    <p className="muted">Actual trims depend on filled quantity. Chart reference targets are not automatically separate sell orders; this exit schedule controls the campaign. Allocations and automatic geometry choices are recorded engineering settings.</p>
    {plan.rationale && <details><summary>Saved review rationale</summary><p>{plan.rationale}</p></details>}
  </section>;
}
