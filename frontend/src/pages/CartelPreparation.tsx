import { useCallback, useEffect, useRef, useState } from "react";
import { EmptyState, ErrorState, Spinner } from "../components/ui";
import { SymIcon } from "../components/SymIcon";
import { api } from "../lib/api";
import { useWorkspace, useWorkspacePortfolios } from "../lib/workspace";
import { useStore } from "../store";

const ROOT = "/api/options-cartel/preparation";
const label = (value: string) => value.replaceAll("_", " ");
export function CartelPreparation({onOpen, onSettings, onChanged, view}: {
  onOpen: (id: string) => void; onSettings: () => void; onChanged: () => Promise<void>; view: "plans" | "settings";
}) {
  const workspace = useWorkspace();
  const live = workspace === "live";
  const workspaceLabel = live ? "Live" : "Practice";
  const portfolios = useWorkspacePortfolios();
  const endpoint = (suffix = "") => `${ROOT}${suffix}?workspace=${workspace}`;
  const toast = useStore(s => s.toast);
  const books = portfolios.filter(p => live ? p.kind === "live" || p.kind === "paper" : p.kind === "sim");
  const refreshKey = useRef("");
  const [evidenceLimit, setEvidenceLimit] = useState(100);
  const [status, setStatus] = useState<any>(null);
  const [config, setConfig] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const reload = useCallback(() => setRevision(v => v + 1), []);
  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      let running = false;
      try {
        const next = await api.get<any>(endpoint());
        if (alive) { setStatus(next); setConfig((old: any) => old ?? next.configuration); setError(""); }
        running = next.latest?.status === "running";
        const key = `${next.latest?.runId}:${next.latest?.status}:${next.latest?.result?.shortlist?.length || 0}:${next.latest?.result?.armed || 0}`;
        if (alive && next.latest && key !== refreshKey.current) { await onChanged(); refreshKey.current = key; }
      } catch (e) { if (alive) setError(String(e)); }
      if (alive) timer = setTimeout(poll, running ? 3000 : 30000);
    };
    void poll();
    return () => { alive = false; clearTimeout(timer); };
  }, [revision, workspace, onChanged]);
  const act = async (save: boolean, resume = false) => {
    setBusy(true); setError("");
    try {
      if (save) {
        const next = await api.post<any>(endpoint("/config"), {...config, workspace, portfolioId: config.portfolioId || (!live && books.length === 1 ? books[0].id : null)});
        setStatus(next); setConfig(next.configuration); toast("info", "Cartel preparation settings saved");
      } else {
        await api.post(endpoint("/run")+(resume ? `&resumeRunId=${encodeURIComponent(status.latest.runId)}` : ""), {});
        toast("info", resume ? "Resuming saved Cartel preparation" : "Cartel preparation started"); setEvidenceLimit(100); reload();
      }
    } catch (e) { setError(String(e)); } finally { setBusy(false); }
  };
  const result = status?.latest?.result;
  const account = books.find(p => p.id === status?.configuration?.portfolioId) || (!live && books.length === 1 ? books[0] : null);
  const running = status?.latest?.status === "running";
  const progress = result?.discoveryProgress;
  const elapsedEnd = running ? status?.serverNow || Date.now() : result?.finishedAt || result?.updatedAt;
  const elapsed = result?.startedAt && elapsedEnd ? Math.max(0, Math.floor((elapsedEnd-result.startedAt)/1000)) : null;
  const sinceUpdate = result?.updatedAt ? Math.max(0, Math.floor(((status?.serverNow || Date.now())-result.updatedAt)/1000)) : null;
  const permissionBlocked = live && status?.configuration?.enabled && !status?.liveAutoAllowed;
  return <section className="panel mb" aria-label={view === "settings" ? "Daily preparation settings" : "Daily preparation"}>
    <div className="panel-head">{view === "settings" ? "Daily preparation settings" : "Daily preparation"}
      <span className={`status-pill ${permissionBlocked ? "wait" : status?.configuration?.enabled ? "ok" : "dim"}`}>{permissionBlocked ? "Permission required" : status?.configuration?.enabled ? "Scheduled" : "Off"}</span>
      {view === "plans" && <button className="primary-btn cartel-push" disabled={busy || running || !status?.configuration?.enabled || (live && !status?.liveAutoAllowed)}
        onClick={() => void act(false)}>{busy || running ? "Preparing…" : "Prepare now"}</button>}
      {view === "plans" && status?.canResume && <button className="ghost-btn" disabled={busy || running || !status?.configuration?.enabled || permissionBlocked}
        onClick={() => void act(false, true)}>Resume saved scan</button>}
    </div>
    {error && <ErrorState message={error} onRetry={reload}/>}
    {!status && !error && <Spinner label="Loading preparation…"/>}
    {status && <div className="cartel-inset muted">Automatic {workspaceLabel} · {account?.name || `Choose a ${workspaceLabel} account`} · 08:45 / 20:20 ET
      {view === "plans" && <button className="link-btn" onClick={onSettings}>Settings</button>}
    </div>}
    {view === "settings" && config && <form className="panel-body cartel-form" onSubmit={e => { e.preventDefault(); void act(true); }}>
      <label className="cartel-check"><input type="checkbox" checked={config.enabled} onChange={e => setConfig({...config, enabled:e.target.checked})}/>Enable scheduled preparation and automatic {workspaceLabel} arming</label>
      {live && <>
        <label className="cartel-check"><input type="checkbox" checked={config.allowLive} onChange={e => setConfig({...config, allowLive:e.target.checked})}/>Allow this preparation to arm automatic trades on the selected Live account</label>
        <label className="cartel-check"><input type="checkbox" checked={config.overnightAck} onChange={e => setConfig({...config, overnightAck:e.target.checked})}/>I acknowledge that overnight options use app-managed protection</label>
        <p>Live settings are separate from Practice. The selected broker must be connected and all execution checks must pass.</p>
        <p>Cartel live-auto permission: <strong>{status?.liveAutoAllowed ? "enabled" : "disabled"}</strong>.</p>
        <button className="ghost-btn" type="button" disabled={busy} onClick={async () => {
          setBusy(true); setError("");
          try { await api.patchSettings({"techniques.options_cartel.allow_live_auto": !status?.liveAutoAllowed}); reload(); }
          catch (e) { setError(String(e)); } finally { setBusy(false); }
        }}>{status?.liveAutoAllowed ? "Disable Cartel live-auto permission" : "Enable Cartel live-auto permission"}</button>
      </>}
      <div className="cartel-fields">
        <label>{workspaceLabel} account<select required value={config.portfolioId || (!live && books.length === 1 ? books[0].id : "")} onChange={e => setConfig({...config, portfolioId:e.target.value || null})}>
          <option value="" disabled>Choose an account</option>{books.map(p => <option key={p.id} value={p.id}>{p.name}{p.kind === "paper" ? " (broker paper)" : ""}</option>)}
        </select></label>
        <label>Shortlist size<input required type="number" min={1} max={20} value={config.focusCount} onChange={e => setConfig({...config, focusCount:Number(e.target.value)})}/></label>
        <label className="cartel-check"><input type="checkbox" checked={config.scanAll ?? true} onChange={e => setConfig({...config, scanAll:e.target.checked})}/>Evaluate all eligible stocks</label>
        {config.scanAll === false && <label>Optional symbol cap<input required type="number" min={1} max={10000} value={config.historyLimit} onChange={e => setConfig({...config, historyLimit:Number(e.target.value)})}/></label>}
        <label>Premium limit (account currency)<input required type="number" min={1} max={100000} value={config.budget} onChange={e => setConfig({...config, budget:Number(e.target.value)})}/></label>
        <label>Equity at risk (%)<input required type="number" min={0.01} max={5} step={0.01} value={config.riskPct} onChange={e => setConfig({...config, riskPct:Number(e.target.value)})}/></label>
      </div>
      <p>All eligible listings are checked by default. Stocks that clearly fail the required industry gate are ruled out before requesting history. The shortlist size limits final selection, not coverage. History requests are paced and cached. Full option premium counts toward risk.</p>
      <details><summary>Plan policy and exit allocations</summary>
        <p>Screen: {label(config.profile)}. Exit profile: {label(config.exitProfile)}. Entry window: {config.horizonSessions} session(s); held positions may continue longer.</p>
        <p>September allocations: {config.septemberFractions.map((v: number) => `${v * 100}%`).join(" / ")}. Automatic Fibonacci targets: {config.allowFibonacciTargets ? "enabled when historical pivots are unavailable" : "disabled"}.</p>
        <p>Allocations and automatic target anchors are engineering choices recorded in each plan.</p>
      </details>
      <button className="primary-btn" disabled={busy}>{busy ? "Saving…" : "Save preparation settings"}</button>
      <p className="muted">Runs outside regular hours. Disabling stops future preparation; existing armed plans and positions remain managed.</p>
    </form>}
    {view === "plans" && status && <>
      {!status.configuration.enabled && <div className="cartel-inset">Enable {workspaceLabel} preparation in Settings to build and arm your daily shortlist.</div>}
      {live && !status.liveAutoAllowed && <div className="cartel-inset">Cartel live-auto permission is off. Enable it in Settings before preparing Live plans.</div>}
      {result ? <>
        <div className="cartel-inset" role="status" aria-live="polite">
          <strong>{result.message || (running ? `Working: ${label(result.phase || "starting")}` : "Preparation finished")}</strong>
          {running && <>
            {result.phase === "discovering" ? <><p>{progress?.received || 0}{progress?.total != null ? ` / ${progress.total}` : ""} listings received</p>
              <progress aria-label="Discovery progress" max={progress?.total || 1} {...(progress?.total ? {value:progress.received} : {})}/></> :
              result.phase === "evaluating" ? <><p>{result.processed || 0} / {result.evaluationTotal || 0} stocks processed{result.currentSymbol ? ` · ${result.currentSymbol}` : ""}</p>
                <progress aria-label="Stock evaluation progress" max={result.evaluationTotal || 1} value={result.processed || 0}/></> : <progress aria-label="Preparation activity"/>}
          </>}
          <p className="muted">{elapsed != null ? `Elapsed ${Math.floor(elapsed/60)}m ${elapsed%60}s` : ""}{sinceUpdate != null ? ` · Last update ${sinceUpdate}s ago` : ""}
            {result.cacheHits != null ? ` · ${result.cacheHits} history cache hits` : ""}{result.resumedAnalyses ? ` · ${result.resumedAnalyses} saved analyses reused` : ""}</p>
          {running && sinceUpdate != null && sinceUpdate > 30 && <p className="cartel-notice">No recent progress update. The provider or worker may be delayed; this does not confirm progress.</p>}
          {!running && result.coverageComplete === false && <p className="cartel-notice">Coverage incomplete: {result.notEvaluated || 0} not processed · {result.dataErrors || 0} data errors.</p>}
          {result.planErrors > 0 && <p className="cartel-notice">{result.planErrors} plan(s) blocked during preparation. Review evidence and exclusions for the reasons.</p>}
          {status.canResume && <p>Resume reuses the original snapshot and successful analyses. Prepare now refreshes market evidence.</p>}
        </div>
        <div className="cartel-inset cartel-row"><strong>{result.session} · {label(result.phase || "pending")}</strong>
          <span className="muted">{result.discovered} discovered · {result.prefiltered || 0} ruled out by industry · {result.evaluated} histories evaluated · {result.dataErrors || 0} data errors · {result.qualifying} qualifying · {result.armed} armed</span></div>
        {status.latest.error && <ErrorState message={status.latest.error}/>}
        {result.shortlist?.length ? <div className="scroll-x"><table className="tbl cartel-table"><thead><tr><th>Symbol</th><th>Setup</th><th className="num">Trigger</th><th className="num">Invalidation</th><th>Status</th><th>Plan</th></tr></thead><tbody>
          {result.shortlist.map((r: any, i: number) => <tr key={r.planId || i}>
            <td><SymIcon sym={r.symbol} size={18}/> <b>{r.symbol}</b></td><td>{label(r.setup || "existing plan")}</td>
            <td className="num">{r.trigger?.toFixed(2) || "—"}</td><td className="num">{r.invalidation?.toFixed(2) || "—"}</td>
            <td className="cartel-wrap"><span className={`status-pill ${r.status === "armed" ? "ok" : r.status === "awaiting_contract" ? "wait" : "dim"}`}>{label(r.status)}</span>
              {r.status === "awaiting_contract" && <p className="small">{r.selection?.pendingReason || "Waiting for a contract within the selection limits."}</p>}
              {r.selection?.audit && <details><summary>Contract selection details</summary>
                <p>Maximum ask ${r.selection.audit.effectiveMaxAsk.toFixed(2)} · maximum debit ${r.selection.audit.maxDebitUsd.toFixed(2)} per contract before fees.</p>
                <p>{r.selection.audit.expiriesChecked} / {r.selection.audit.expiriesInRange} allowed expiry dates checked · {r.selection.audit.rowsExamined} contracts inspected.</p>
                {r.selection.audit.lowestOtherwiseEligibleAsk != null && <p>Lowest ask passing the other filters: ${r.selection.audit.lowestOtherwiseEligibleAsk.toFixed(2)}.</p>}
                <p>First failing filter: {Object.entries(r.selection.audit.rejections).filter(([,count]) => Number(count)>0).map(([reason,count]) => `${label(reason)} ${count}`).join(" · ") || "none"}.</p>
              </details>}
              {r.selection?.errors?.map((e: string, j: number) => <p key={j}>{e}</p>)}
              {status.activation?.plans?.[r.planId] && <p>{status.activation.plans[r.planId]}</p>}
            </td><td>{r.planId && <button className="link-btn" onClick={() => onOpen(r.planId)}>Open {r.symbol}</button>}</td>
          </tr>)}
        </tbody></table></div> : <EmptyState art={false} title={running ? label(result.phase || "Starting preparation") : "No qualifying shortlist"} hint={running ? "Progress and provider activity are shown above." : "Missing evidence or a market without alignment can produce no setups."}/>}
        <details className="cartel-inset"><summary>Evidence and exclusions · {result.rows?.length || 0} records</summary>
          {result.warnings?.map((w: string, i: number) => <p key={i}>{w}</p>)}
          <div className="scroll-x"><table className="tbl cartel-table"><thead><tr><th>Symbol</th><th>Result</th><th>Reason</th><th>Evidence</th></tr></thead><tbody>
            {result.rows?.slice(0, evidenceLimit).map((r: any, i: number) => <tr key={i}><td>{r.symbol}</td><td>{label(r.status)}</td>
              <td className="cartel-wrap">{r.reason || r.reasons?.join("; ") || "Checks passed"}</td>
              <td>{r.analysisId && <button className="link-btn" onClick={() => onOpen(r.analysisId)}>Open evidence</button>}</td>
            </tr>)}
          </tbody></table></div>
          {result.rows?.length > evidenceLimit && <button className="ghost-btn" onClick={() => setEvidenceLimit(n => n+100)}>Show 100 more ({evidenceLimit} of {result.rows.length} shown)</button>}
        </details>
        {status.activation?.error && <ErrorState message={status.activation.error}/>}
        {Object.entries(status.quoteRefresh?.errors || {}).map(([symbol, reason]) => <ErrorState key={symbol} message={`${symbol}: ${reason}`}/>)}
      </> : <EmptyState art={false} title="No preparation yet" hint={`Enable automatic ${workspaceLabel} preparation in Settings, then prepare the next session outside regular market hours.`} action={<button className="ghost-btn" onClick={onSettings}>Set up preparation</button>}/>}
    </>}
  </section>;
}
