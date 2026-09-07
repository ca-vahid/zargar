import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { useStore } from "../store";

const ROOT = "/api/options-cartel/preparation";
export function CartelPreparation({onOpen}: {onOpen: (id: string) => void}) {
  const portfolios = useStore(s => s.portfolios);
  const books = portfolios.filter(p => p.kind === "sim");
  const [status, setStatus] = useState<any>(null);
  const [config, setConfig] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const next = await api.get<any>(ROOT);
        if (alive) { setStatus(next); setConfig((old: any) => old ?? next.configuration); }
      } catch (e) { if (alive) setError(String(e)); }
      if (alive) timer = setTimeout(poll, 3000);
    };
    void poll();
    return () => { alive = false; clearTimeout(timer); };
  }, []);
  const save = async (run: boolean) => {
    setBusy(true); setError("");
    try {
      const next = await api.post<any>(`${ROOT}/config`, config);
      setStatus(next); setConfig(next.configuration);
      if (run) { await api.post(`${ROOT}/run`, {}); setStatus(await api.get(ROOT)); }
    } catch (e) { setError(String(e)); } finally { setBusy(false); }
  };
  const result = status?.latest?.result;
  return <section className="cartel-card"><h2>Daily preparation · Automatic Practice</h2>
    <p>Discover the market, evaluate completed sessions, and arm a daily options shortlist. The engine enters qualifying setups automatically in Practice and manages their exits.</p>
    {error && <p role="alert">{error}</p>}
    {config && <form className="cartel-form" onSubmit={e => { e.preventDefault(); void save(false); }}>
      <label className="cartel-check"><input type="checkbox" checked={config.enabled} onChange={e => setConfig({...config, enabled:e.target.checked})}/>Prepare automatically at 20:20 and 08:45 ET</label>
      <label>Practice account<select value={config.portfolioId || ""} onChange={e => setConfig({...config, portfolioId:e.target.value || null})}>
        <option value="">Use the sole Practice account</option>
        {books.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
      </select></label>
      <label>Daily shortlist size<input type="number" min={1} max={20} value={config.focusCount} onChange={e => setConfig({...config, focusCount:Number(e.target.value)})}/></label>
      <label>Detailed history budget (symbols)<input type="number" min={1} max={2000} value={config.historyLimit} onChange={e => setConfig({...config, historyLimit:Number(e.target.value)})}/></label>
      <label>Maximum premium per setup (account currency)<input type="number" min={1} max={100000} value={config.budget} onChange={e => setConfig({...config, budget:Number(e.target.value)})}/></label>
      <label>Maximum equity at risk (%)<input type="number" min={0.01} max={5} step={0.01} value={config.riskPct} onChange={e => setConfig({...config, riskPct:Number(e.target.value)})}/></label>
      <p>Full premium counts toward risk. Discovery covers the available universe; detailed analysis starts with the most active listings, up to the history budget. Entries still require fresh execution data and all risk checks.</p>
      <details><summary>Plan policy</summary>
        <p>Screen: {config.profile.replaceAll("_", " ")}. Exit profile: {config.exitProfile.replaceAll("_", " ")}.
          Entry window: {config.horizonSessions} session(s). Held positions can continue beyond that window.</p>
        <p>September exit allocations: {config.septemberFractions.map((v: number) => `${v * 100}%`).join(" / ")}.
          Automatic Fibonacci targets: {config.allowFibonacciTargets ? "enabled when historical pivot targets are unavailable" : "disabled"}.</p>
        <p>These allocations and automatic anchor selection are engineering choices, recorded in each plan.</p>
      </details>
      <button disabled={busy}>Save preparation settings</button>
      <button type="button" disabled={busy || !config.enabled || status?.latest?.status === "running"} onClick={() => void save(true)}>Save and prepare next session now</button>
      <p>Preparation runs outside regular market hours. Disabling stops future preparation; existing armed plans and positions remain managed.</p>
    </form>}
    {result && <div aria-live="polite"><h3>{result.session} · {result.phase?.replaceAll("_", " ")}</h3>
      <p>{result.discovered} discovered · {result.evaluated} evaluated · {result.qualifying} qualifying · {result.armed} armed</p>
      {result.warnings?.map((w: string, i: number) => <p key={i}>{w}</p>)}
      {status.latest.error && <p role="alert">{status.latest.error}</p>}
      <ul>{result.shortlist?.map((r: any, i: number) => <li key={r.planId || i}>
        <strong>{r.symbol}</strong> · {r.status.replaceAll("_", " ")}
        {r.planId && <button onClick={() => onOpen(r.planId)}>View plan</button>}
        {r.selection?.errors?.map((e: string, j: number) => <p key={j}>{e}</p>)}
        {r.status === "awaiting_contract" && <p>{r.selection?.pendingReason || "Waiting for an option contract that meets the configured selection limits."}</p>}
        {status.activation?.plans?.[r.planId] && <p>{status.activation.plans[r.planId]}</p>}
      </li>)}</ul>
      {!result.shortlist?.length && <p>No shortlist yet. Missing evidence or a market without alignment can produce no setups.</p>}
      {status.activation?.error && <p role="alert">{status.activation.error}</p>}
      {Object.entries(status.quoteRefresh?.errors || {}).map(([symbol, reason]) => <p key={symbol}>{symbol}: {String(reason)}</p>)}
      <details><summary>Candidate evidence and exclusions</summary><ul>
        {result.rows?.map((r: any, i: number) => <li key={i}>{r.symbol} · {r.status.replaceAll("_", " ")}
          {r.reason && <p>{r.reason}</p>}{r.reasons?.length > 0 && <p>{r.reasons.join("; ")}</p>}
          {r.analysisId && <button onClick={() => onOpen(r.analysisId)}>View evidence</button>}
        </li>)}
      </ul></details>
    </div>}
  </section>;
}
