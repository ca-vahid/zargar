import { useCartelPortfolios } from "./cartelAccounts";
import { useCallback, useEffect, useRef, useState } from "react";
import { EmptyState, ErrorState, Spinner } from "../components/ui";
import { SymIcon } from "../components/SymIcon";
import { CartelRunLink } from "./CartelRunLink";
import { api } from "../lib/api";
import { useWorkspace } from "../lib/workspace";
import { useStore } from "../store";

const ROOT = "/api/options-cartel/preparation";
const label = (value: string) => value.replaceAll("_", " ");
export function CartelPreparation({onOpen, onSettings, onChanged, view}: {
  onOpen: (id: string) => void; onSettings: () => void; onChanged: () => Promise<void>; view: "plans" | "settings";
}) {
  const workspace = useWorkspace();
  const live = workspace === "live";
  const workspaceLabel = live ? "Live" : "Practice";
  const portfolios = useCartelPortfolios();
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
        <label className="cartel-check"><input type="checkbox" checked={config.scanAll ?? true} onChange={e => setConfig({...config, scanAll:e.target.checked})}/>Evaluate all eligible stocks and reviewed ETFs</label>
        {config.scanAll === false && <label>Optional symbol cap<input required type="number" min={1} max={10000} value={config.historyLimit} onChange={e => setConfig({...config, historyLimit:Number(e.target.value)})}/></label>}
        <label>History batch size<input required type="number" min={1} max={50} value={config.historyBatchSize ?? 25} onChange={e => setConfig({...config, historyBatchSize:Number(e.target.value)})}/></label>
        <label>Parallel history fetches<input required type="number" min={1} max={12} value={config.historyConcurrency ?? 6} onChange={e => setConfig({...config, historyConcurrency:Number(e.target.value)})}/></label>
        <label>Premium limit (account currency)<input required type="number" min={1} max={100000} value={config.budget} onChange={e => setConfig({...config, budget:Number(e.target.value)})}/></label>
        <label>Equity at risk (%)<input required type="number" min={0.01} max={10} step={0.01} value={config.riskPct} onChange={e => setConfig({...config, riskPct:Number(e.target.value)})}/></label>
      </div>
      <p>All eligible listings are checked by default. Industry context mode records ranks without excluding a stock solely on its industry. Strict mode requires weekly/monthly top-list agreement. The shortlist size limits final selection, not coverage. History is prefetched in bounded batches; requests overlap but remain paced and cached. A batch of 25 does not send 25 requests at once. Full option premium counts toward risk. The risk percentage uses this account’s equity, not the combined Practice total.</p>
      <p>Allowed range: above 0% through 10% per setup. The lower of this equity allowance and the premium limit controls spending; a $500 premium limit still caps purchases at $500. Practice and Live values are saved independently. Existing saved values are preserved.</p>
      {live && <p className="cartel-notice">10% permits up to one-tenth of this account’s equity in option premium per setup. Increasing the limit does not enable Live execution or bypass its permissions.</p>}
      <details open><summary>Market coverage and method choices</summary>
        <p>Sean describes theme leadership, volume-supported breakouts, 5m/15m confirmation and retests. Exact volume, candle-quality and ranking thresholds below are our measurable interpretations, not prescribed author numbers. Saved plans keep their original settings.</p>
        <div className="cartel-fields">
          <label>Market alignment<select aria-label="Market alignment" value={config.marketAlignment || "strict"} disabled={live} onChange={e => setConfig({...config, marketAlignment:e.target.value})}>
            <option value="strict">Strict — both indices aligned</option>{!live && <option value="moderate">Moderate — Practice experiment</option>}
          </select></label>
          <p>{live ? "Live requires strict alignment." : "Moderate allows bullish preparation when one index closes above its 8/21/50 EMAs and both close above their 50 EMA. This is a Practice experiment, not an author-verified rule. Save and prepare again; existing research records are not promoted."}</p>
          <label>Volume baseline readiness<select aria-label="Volume baseline readiness" value={config.baselineReadiness || (live ? "full_session" : "covered_periods")} onChange={e => setConfig({...config, baselineReadiness:e.target.value})}><option value="covered_periods">Watch only periods with supported history</option><option value="full_session">Require every period (legacy strict)</option></select></label>
          <label>Shortlist ranking<select aria-label="Shortlist ranking" value={config.shortlistRanking || "quality"} onChange={e => setConfig({...config, shortlistRanking:e.target.value})}><option value="quality">Target room, relative strength, then volume</option><option value="volume">Discovery volume order</option></select></label>
          <label>Minimum first-target distance (%)<input type="number" min={0} max={10} step="any" value={config.minTargetDistancePct ?? .5} onChange={e => setConfig({...config, minTargetDistancePct:Number(e.target.value)})}/></label>
          <label>Minimum first-target reward/risk at entry<input type="number" min={0} max={10} step="any" value={config.minEntryTargetR ?? .25} onChange={e => setConfig({...config, minEntryTargetR:Number(e.target.value)})}/></label>
          <p>These are engineering target-room checks, not Sean's published numbers. Nearby resistance is never skipped to invent a better reward/risk ratio. The entry ratio uses the actual initial stop and is rechecked at execution.</p>
          <label>Industry policy<select value={config.industryPolicy || "context"} onChange={e => setConfig({...config, industryPolicy:e.target.value})}>
            <option value="context">Context — evaluate strong stocks across industries</option><option value="strict">Strict — require both top-ten industry ranks</option>
          </select></label>
          <label>Research direction when market is blocked<select value={config.researchDirection || "long"} onChange={e => setConfig({...config, researchDirection:e.target.value})}><option value="long">Bullish research</option><option value="short">Bearish research</option></select></label>
          <label>Reviewed ETF symbols<input defaultValue={(config.reviewedEtfs || []).join(", ")} onBlur={e => setConfig({...config, reviewedEtfs:e.target.value.toUpperCase().split(/[ ,]+/).filter(Boolean)})}/></label>
          <label>Confirmation timeframe<select value={config.entry.timeframe_minutes} onChange={e => setConfig({...config, entry:{...config.entry, timeframe_minutes:Number(e.target.value)}})}>
            <option value={5}>5 minutes</option><option value={15}>15 minutes</option><option value={30}>30 minutes (research variant)</option>
          </select></label>
          <label>Entry approach<select value={config.entry.mode} onChange={e => setConfig({...config, entry:{...config.entry, mode:e.target.value}})}><option value="breakout">Breakout confirmation</option><option value="retest">Confirmed retest</option></select></label>
          {config.entry.mode === "retest" && <label className="cartel-check"><input type="checkbox" checked={!!config.entry.allow_gap_retest} onChange={e => setConfig({...config, entry:{...config.entry, allow_gap_retest:e.target.checked}})}/>Allow a completed retest after an opening gap</label>}
          <label>Required volume multiple<input type="number" min={0.01} max={100} step="any" value={config.entry.volume_multiple} onChange={e => setConfig({...config, entry:{...config.entry, volume_multiple:Number(e.target.value)}})}/></label>
          <label>Minimum close location (0–1)<input type="number" min={0} max={1} step="any" value={config.entry.min_close_location} onChange={e => setConfig({...config, entry:{...config.entry, min_close_location:Number(e.target.value)}})}/></label>
        </div>
        <p>Reviewed ETFs must be classified as ETFs by the provider. They use the same price, liquidity, trend and setup checks; stock market capitalization and stock-industry membership do not apply. Add only funds whose structure you have reviewed; leveraged or inverse funds need a separate method review.</p>
        <p>Each usable confirmation period still requires five complete historical samples. Unsupported periods cannot trigger an entry. Strict baseline mode requires every period; covered-period mode needs at least one usable period before the closing bell. Pending plans also need complete opening history, current data, and an unreached first target before automatic arming.</p>
        <label>Comparison watchlist (optional)<input defaultValue={(config.comparisonSymbols || []).join(", ")} onBlur={e => setConfig({...config, comparisonSymbols:e.target.value.toUpperCase().split(/[ ,]+/).filter(Boolean)})}/></label>
        <label>Dated watchlist source or rationale<input maxLength={2000} value={config.comparisonSource || ""} onChange={e => setConfig({...config, comparisonSource:e.target.value})}/></label>
        <p>This comparison explains inclusion and exclusion; it does not bypass entry checks or copy another trader’s orders.</p>
      </details>
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
        {result.market && <section className="cartel-inset" aria-label="Market alignment">
          <strong>{result.armingBlocked || result.phase === "no_market_alignment" ? "Automatic arming blocked — research does not grant trading permission" : "Market alignment permits plan evaluation"}</strong>
          <p>Alignment mode: <b>{label(result.market.alignmentMode || "strict")}</b>. {result.market.reason}</p>
          {Object.entries(result.market.indices || {}).map(([symbol, value]) => { const read = value as any; return <p key={symbol}>
            <b>{symbol}</b> · {read.session || "session unavailable"} · {label(read.direction)} · close {read.close?.toFixed(2) ?? "not recorded"}
            {Object.entries(read.emas || {}).map(([period, value]) => <span key={period}> · EMA {period}: {typeof value === "number" ? value.toFixed(2) : "unavailable"}{read.aboveEmas?.[period] != null ? (read.aboveEmas[period] ? " (price above)" : " (price at/below)") : ""}</span>)}
          </p>; })}
          {result.breadthContext && <details><summary>Market breadth context (advisory)</summary>
            <p>{result.breadthContext.interpretation}</p>
            {Object.entries(result.breadthContext.indices || {}).map(([sym,raw]) => {const r=raw as any;return <p key={sym}><b>{sym}</b>: {r.available ? `${r.session} · ${r.changePct.toFixed(2)}% · ${r.aboveEma21 ? "above" : "at/below"} EMA21` : "unavailable"}</p>;})}
            <p>NYMO: {result.breadthContext.nymo?.reason || "unavailable"}</p>
          </details>}
          {result.armingBlocked && <p>{label(result.researchDirection || "long")} candidates are research only. Run fresh preparation after market alignment changes; these records cannot auto-arm.</p>}
        </section>}
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
          {running && result.historyConcurrency != null && <p>History pipeline: {result.activeHistoryRequests || 0} active fetches · up to {result.historyConcurrency} parallel · batch window {result.historyBatchSize} · {result.prefetchedHistories || 0} histories ready so far.</p>}
          {running && sinceUpdate != null && sinceUpdate > 30 && <p className="cartel-notice">No recent progress update. The provider or worker may be delayed; this does not confirm progress.</p>}
          {!running && result.coverageComplete === false && result.phase !== "no_market_alignment" && <p className="cartel-notice">Coverage incomplete: {result.notEvaluated || 0} not processed · {result.dataErrors || 0} data errors.</p>}
          {result.planErrors > 0 && <p className="cartel-notice">{result.planErrors} plan(s) blocked during preparation. Review evidence and exclusions for the reasons.</p>}
          {status.canResume && <p>Resume reuses the original snapshot and successful analyses. Prepare now refreshes market evidence.</p>}
        </div>
        <div className="cartel-inset cartel-row"><strong>{result.session} · {label(result.phase || "pending")}</strong>
          <span className="muted">{result.discovered} discovered · {result.prefiltered || 0} ruled out by industry · {result.evaluated} histories evaluated · {result.dataErrors || 0} data errors · {result.qualifying} qualifying · {result.researchCandidates || 0} research-only candidates · {result.armed} armed</span></div>
        {status.latest.error && <ErrorState message={status.latest.error}/>}
        {result.shortlist?.length ? <div className="scroll-x"><table className="tbl cartel-table"><thead><tr><th>Symbol</th><th>Setup</th><th className="num">Trigger</th><th className="num">Invalidation</th><th>Status</th><th>Plan</th></tr></thead><tbody>
          {result.shortlist.map((r: any, i: number) => <tr key={r.planId || i}>
            <td><SymIcon sym={r.symbol} size={18}/> <b>{r.symbol}</b></td><td>{label(r.setup || "existing plan")}</td>
            <td className="num">{r.trigger?.toFixed(2) || "—"}</td><td className="num">{r.invalidation?.toFixed(2) || "—"}</td>
            <td className="cartel-wrap"><span className={`status-pill ${r.status === "armed" ? "ok" : r.status === "awaiting_contract" ? "wait" : "dim"}`}>{label(r.status)}</span>
              {r.volumeCoverage && <details><summary>Volume coverage: {r.volumeCoverage.available}/{r.volumeCoverage.expected} periods{r.volumeCoverage.limited ? " — limited entry windows" : ""}</summary>
                <p>{r.volumeCoverage.historicalSessions} historical sessions · minimum {r.volumeCoverage.minSamples} complete samples per period. Missing minutes are not filled with zeros.</p>
                <p>Supported confirmation windows (ET): {r.volumeCoverage.entryWindows?.map((w:any)=>`${w.startET}–${w.confirmationET}`).join(", ") || "none"}. The trigger, live data and all execution checks must still pass.</p>
              </details>}
              {r.ranking && <p className="small">Target room {r.ranking.firstTargetPct.toFixed(2)}% · structural target {r.ranking.structuralTargetR.toFixed(2)}R · relative strength {r.ranking.directionalRelativeStrength.toFixed(2)} percentage points. Ranking: {result.shortlistRanking || "volume"}.</p>}
              {r.reason && <p className="small">{r.reason}</p>}
              {r.status === "awaiting_contract" && <p className="small">{r.selection?.pendingReason || "Waiting for a contract within the selection limits."}</p>}
              {r.selection?.audit && <details><summary>Contract selection details</summary>
                <p>Maximum ask ${r.selection.audit.effectiveMaxAsk.toFixed(2)} · maximum debit ${r.selection.audit.maxDebitUsd.toFixed(2)} per contract before fees.</p>
                <p>{r.selection.audit.expiriesChecked} / {r.selection.audit.expiriesInRange} allowed expiry dates checked · {r.selection.audit.rowsExamined} contracts inspected.</p>
                {r.selection.audit.lowestOtherwiseEligibleAsk != null && <p>Lowest ask passing the other filters: ${r.selection.audit.lowestOtherwiseEligibleAsk.toFixed(2)}.</p>}
                <p>First failing filter: {Object.entries(r.selection.audit.rejections).filter(([,count]) => Number(count)>0).map(([reason,count]) => `${label(reason)} ${count}`).join(" · ") || "none"}.</p>
              </details>}
              {r.selection?.errors?.map((e: string, j: number) => <p key={j}>{e}</p>)}
              {status.activation?.plans?.[r.planId] && <p>{status.activation.plans[r.planId]}</p>}
            </td><td>{(r.planId || r.analysisId) && <CartelRunLink id={r.planId || r.analysisId} onOpen={onOpen}>Open {r.symbol}</CartelRunLink>}</td>
          </tr>)}
        </tbody></table></div> : <EmptyState art={false} title={running ? label(result.phase || "Starting preparation") : "No qualifying shortlist"} hint={running ? "Progress and provider activity are shown above." : "Missing evidence or a market without alignment can produce no setups."}/>}
        {!!result.watchlistComparison?.rows?.length && <details className="cartel-inset" open><summary>Watchlist coverage comparison</summary>
          <p>{result.watchlistComparison.source}</p>
          {result.watchlistComparison.rows.map((r:any) => <p key={r.symbol}><b>{r.symbol}</b> · {label(r.status)} · {r.reason || r.reasons?.join("; ") || "Passed setup checks; selection and execution checks remain"}</p>)}
        </details>}
        <details className="cartel-inset"><summary>Evidence and exclusions · {result.rows?.length || 0} records</summary>
          {result.warnings?.map((w: string, i: number) => <p key={i}>{w}</p>)}
          <div className="scroll-x"><table className="tbl cartel-table"><thead><tr><th>Symbol</th><th>Result</th><th>Reason</th><th>Evidence</th></tr></thead><tbody>
            {result.rows?.slice(0, evidenceLimit).map((r: any, i: number) => <tr key={i}><td>{r.symbol}</td><td>{label(r.status)}</td>
              <td className="cartel-wrap">{r.reason || r.reasons?.join("; ") || "Checks passed"}
                {r.industryContext && <details><summary>Industry context ({r.industryPolicy || "strict"})</summary><p>{r.industryContext.industry || "Unclassified"} · weekly rank {r.industryContext.weekRank?.best ?? "unknown"}–{r.industryContext.weekRank?.worst ?? "unknown"} · monthly rank {r.industryContext.monthRank?.best ?? "unknown"}–{r.industryContext.monthRank?.worst ?? "unknown"}</p><p>{r.industryContext.reason}</p></details>}</td>
              <td>{r.analysisId && <CartelRunLink id={r.analysisId} onOpen={onOpen}>Open evidence</CartelRunLink>}</td>
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
