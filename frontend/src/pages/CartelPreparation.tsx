import { useCallback, useEffect, useState } from "react";
import { EmptyState, ErrorState, Spinner } from "../components/ui";
import { SymIcon } from "../components/SymIcon";
import { api } from "../lib/api";
import { useStore } from "../store";

const ROOT = "/api/options-cartel/preparation";
const label = (value: string) => value.replaceAll("_", " ");
export function CartelPreparation({onOpen, onSettings, view}: {
  onOpen: (id: string) => void; onSettings: () => void; view: "plans" | "settings";
}) {
  const portfolios = useStore(s => s.portfolios);
  const toast = useStore(s => s.toast);
  const books = portfolios.filter(p => p.kind === "sim");
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
        const next = await api.get<any>(ROOT);
        if (alive) { setStatus(next); setConfig((old: any) => old ?? next.configuration); setError(""); }
        running = next.latest?.status === "running";
      } catch (e) { if (alive) setError(String(e)); }
      if (alive) timer = setTimeout(poll, running ? 3000 : 30000);
    };
    void poll();
    return () => { alive = false; clearTimeout(timer); };
  }, [revision]);
  const act = async (save: boolean) => {
    setBusy(true); setError("");
    try {
      if (save) {
        const next = await api.post<any>(`${ROOT}/config`, config);
        setStatus(next); setConfig(next.configuration); toast("info", "Cartel preparation settings saved");
      } else {
        await api.post(`${ROOT}/run`, {});
        toast("info", "Cartel preparation started"); reload();
      }
    } catch (e) { setError(String(e)); } finally { setBusy(false); }
  };
  const result = status?.latest?.result;
  const account = books.find(p => p.id === status?.configuration?.portfolioId) || (books.length === 1 ? books[0] : null);
  const running = status?.latest?.status === "running";
  return <section className="panel mb" aria-label={view === "settings" ? "Daily preparation settings" : "Daily preparation"}>
    <div className="panel-head">{view === "settings" ? "Daily preparation settings" : "Daily preparation"}
      <span className={`status-pill ${status?.configuration?.enabled ? "ok" : "dim"}`}>{status?.configuration?.enabled ? "Scheduled" : "Off"}</span>
      {view === "plans" && <button className="primary-btn cartel-push" disabled={busy || running || !status?.configuration?.enabled}
        onClick={() => void act(false)}>{busy || running ? "Preparing…" : "Prepare now"}</button>}
    </div>
    {error && <ErrorState message={error} onRetry={reload}/>}
    {!status && !error && <Spinner label="Loading preparation…"/>}
    {status && <div className="cartel-inset muted">Automatic Practice · {account?.name || "Choose a Practice account"} · 08:45 / 20:20 ET
      {view === "plans" && <button className="link-btn" onClick={onSettings}>Settings</button>}
    </div>}
    {view === "settings" && config && <form className="panel-body cartel-form" onSubmit={e => { e.preventDefault(); void act(true); }}>
      <label className="cartel-check"><input type="checkbox" checked={config.enabled} onChange={e => setConfig({...config, enabled:e.target.checked})}/>Enable scheduled preparation and automatic Practice arming</label>
      <div className="cartel-fields">
        <label>Practice account<select value={config.portfolioId || ""} onChange={e => setConfig({...config, portfolioId:e.target.value || null})}>
          <option value="">Use the sole Practice account</option>{books.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select></label>
        <label>Shortlist size<input required type="number" min={1} max={20} value={config.focusCount} onChange={e => setConfig({...config, focusCount:Number(e.target.value)})}/></label>
        <label>Symbols to evaluate<input required type="number" min={1} max={2000} value={config.historyLimit} onChange={e => setConfig({...config, historyLimit:Number(e.target.value)})}/></label>
        <label>Premium limit (account currency)<input required type="number" min={1} max={100000} value={config.budget} onChange={e => setConfig({...config, budget:Number(e.target.value)})}/></label>
        <label>Equity at risk (%)<input required type="number" min={0.01} max={5} step={0.01} value={config.riskPct} onChange={e => setConfig({...config, riskPct:Number(e.target.value)})}/></label>
      </div>
      <p>Discovery covers the available market. Detailed analysis starts with the most active listings, up to the symbol limit. Full option premium counts toward risk.</p>
      <details><summary>Plan policy and exit allocations</summary>
        <p>Screen: {label(config.profile)}. Exit profile: {label(config.exitProfile)}. Entry window: {config.horizonSessions} session(s); held positions may continue longer.</p>
        <p>September allocations: {config.septemberFractions.map((v: number) => `${v * 100}%`).join(" / ")}. Automatic Fibonacci targets: {config.allowFibonacciTargets ? "enabled when historical pivots are unavailable" : "disabled"}.</p>
        <p>Allocations and automatic target anchors are engineering choices recorded in each plan.</p>
      </details>
      <button className="primary-btn" disabled={busy}>{busy ? "Saving…" : "Save preparation settings"}</button>
      <p className="muted">Runs outside regular hours. Disabling stops future preparation; existing armed plans and positions remain managed.</p>
    </form>}
    {view === "plans" && status && <>
      {!status.configuration.enabled && <div className="cartel-inset">Enable preparation in Settings to build and arm your daily shortlist.</div>}
      {result ? <>
        <div className="cartel-inset cartel-row" role="status"><strong>{result.session} · {label(result.phase || "pending")}</strong>
          <span className="muted">{result.discovered} discovered · {result.evaluated} evaluated · {result.qualifying} qualifying · {result.armed} armed</span></div>
        {status.latest.error && <ErrorState message={status.latest.error}/>}
        {result.shortlist?.length ? <div className="scroll-x"><table className="tbl cartel-table"><thead><tr><th>Symbol</th><th>Setup</th><th className="num">Trigger</th><th className="num">Invalidation</th><th>Status</th><th>Plan</th></tr></thead><tbody>
          {result.shortlist.map((r: any, i: number) => <tr key={r.planId || i}>
            <td><SymIcon sym={r.symbol} size={18}/> <b>{r.symbol}</b></td><td>{label(r.setup || "existing plan")}</td>
            <td className="num">{r.trigger?.toFixed(2) || "—"}</td><td className="num">{r.invalidation?.toFixed(2) || "—"}</td>
            <td className="cartel-wrap"><span className={`status-pill ${r.status === "armed" ? "ok" : r.status === "awaiting_contract" ? "wait" : "dim"}`}>{label(r.status)}</span>
              {r.status === "awaiting_contract" && <p className="small">{r.selection?.pendingReason || "Waiting for a contract within the selection limits."}</p>}
              {r.selection?.errors?.map((e: string, j: number) => <p key={j}>{e}</p>)}
              {status.activation?.plans?.[r.planId] && <p>{status.activation.plans[r.planId]}</p>}
            </td><td>{r.planId && <button className="link-btn" onClick={() => onOpen(r.planId)}>Open {r.symbol}</button>}</td>
          </tr>)}
        </tbody></table></div> : <EmptyState art={false} title={running ? "Evaluating candidates" : "No qualifying shortlist"} hint="Missing evidence or a market without alignment can produce no setups."/>}
        <details className="cartel-inset"><summary>Evidence and exclusions · {result.rows?.length || 0} records</summary>
          {result.warnings?.map((w: string, i: number) => <p key={i}>{w}</p>)}
          <div className="scroll-x"><table className="tbl cartel-table"><thead><tr><th>Symbol</th><th>Result</th><th>Reason</th><th>Evidence</th></tr></thead><tbody>
            {result.rows?.map((r: any, i: number) => <tr key={i}><td>{r.symbol}</td><td>{label(r.status)}</td>
              <td className="cartel-wrap">{r.reason || r.reasons?.join("; ") || "Checks passed"}</td>
              <td>{r.analysisId && <button className="link-btn" onClick={() => onOpen(r.analysisId)}>Open evidence</button>}</td>
            </tr>)}
          </tbody></table></div>
        </details>
        {status.activation?.error && <ErrorState message={status.activation.error}/>}
        {Object.entries(status.quoteRefresh?.errors || {}).map(([symbol, reason]) => <ErrorState key={symbol} message={`${symbol}: ${reason}`}/>)}
      </> : <EmptyState art={false} title="No preparation yet" hint="Enable automatic Practice preparation in Settings, then prepare the next session outside regular market hours." action={<button className="ghost-btn" onClick={onSettings}>Set up preparation</button>}/>}
    </>}
  </section>;
}
