import { useCartelPortfolios } from "./cartelAccounts";
import { useState } from "react";
import { api } from "../lib/api";


export function CartelArmControls({runId, active, preferredPortfolioId, onChanged}: {runId: string; active?: any; preferredPortfolioId?: string; onChanged: () => Promise<void>}) {
  const books = useCartelPortfolios();
  const initial = active?.executionSettings || {};
  const [book, setBook] = useState(initial.portfolioId || preferredPortfolioId || "");
  const portfolioId = books.some(b => b.id === book) ? book : books.find(b => b.kind === "sim")?.id || books[0]?.id || "";
  const real = books.find(b => b.id === portfolioId)?.kind === "live" || books.find(b => b.id === portfolioId)?.kind === "paper";
  const [mode, setMode] = useState(active?.config?.mode || "alert");
  const [instrument, setInstrument] = useState(initial.instrument || "options");
  const [contract, setContract] = useState(initial.contractSymbol || "");
  const [budget, setBudget] = useState(initial.budget ? String(initial.budget) : "");
  const [riskPct, setRiskPct] = useState(initial.riskPct || 1);
  const [maxUnits, setMaxUnits] = useState(initial.maxUnits || 10);
  const [maxPremium, setMaxPremium] = useState(initial.maxPremium ? String(initial.maxPremium) : "");
  const [overnightAck, setOvernightAck] = useState(!!initial.overnightAck);
  const [allowLive, setAllowLive] = useState(!!initial.allowLive);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [report, setReport] = useState<any>(null);
  const [minDte, setMinDte] = useState(14);
  const [maxDte, setMaxDte] = useState(60);
  const [targetDte, setTargetDte] = useState(30);
  const [delta, setDelta] = useState(.5);
  const [selection, setSelection] = useState<any>(null);
  const payload = () => ({portfolioId, mode, instrument, contractSymbol: contract || null,
    budget: Number(budget), riskPct, maxUnits, maxPremium: maxPremium ? Number(maxPremium) : null,
    overnightAck, allowLive});
  const run = async (name: string, fn: () => Promise<void>) => {
    setBusy(name); setError("");
    try { await fn(); } catch(e) { setError(String(e)); } finally { setBusy(""); }
  };
  return <form className="cartel-plan-form" onSubmit={e => {
    e.preventDefault(); run("Arming", async () => {
      await api.post(`/api/options-cartel/runs/${runId}/${mode === "alert" ? "arm-alert" : "arm"}`,
        mode === "alert" ? {portfolioId} : payload()); await onChanged();
    });
  }}>
    <h3>Arm reviewed plan</h3>
    <div className="cartel-fields">
      <label>Trading account<select required value={portfolioId} onChange={e => {setBook(e.target.value);setAllowLive(false);}}>
        {!books.length && <option value="">No accounts in this workspace</option>}
        {books.map(b => <option key={b.id} value={b.id}>{b.name} ({b.kind})</option>)}</select></label>
      <label>Execution mode<select value={mode} onChange={e => {setMode(e.target.value);setReport(null);}}>
        <option value="alert">Alert only</option><option value="proposal">Proposal — approve each signal</option>
        <option value="auto">Auto — submit qualifying signals</option></select></label>
    </div>
    {active && <p>Current plan: {active.config?.mode} · {active.status}. {active.submissionReserved ? "An entry has been submitted; use the active-plan controls to manage it." : "Reviewed updates will wait for a fresh signal."}</p>}
    {mode !== "alert" && <>
      <div className="cartel-fields"><label>Vehicle<select value={instrument} onChange={e => setInstrument(e.target.value)}>
        <option value="options">Options</option><option value="shares">Shares (bullish only)</option></select></label>
        <label>Cash budget (account currency)<input required type="number" min="1" value={budget} onChange={e => setBudget(e.target.value)}/></label>
        <label>Risk budget (% equity)<input required type="number" min=".01" max="10" step=".01" value={riskPct} onChange={e => setRiskPct(Number(e.target.value))}/></label>
        <label>Maximum units<input required type="number" min="1" value={maxUnits} onChange={e => setMaxUnits(Number(e.target.value))}/></label>
      </div>
      {instrument === "options" && <>
        <div className="cartel-fields"><label>Reviewed option (OCC symbol)<input required value={contract} onChange={e => setContract(e.target.value.toUpperCase())} placeholder="Choose from search or enter OCC"/></label>
          <label>Maximum quoted option premium<input required type="number" min=".01" step=".01" value={maxPremium} onChange={e => setMaxPremium(e.target.value)}/></label></div>
        <p>Option premiums are quoted per share; one standard contract costs the premium × 100.</p>
        <details><summary>Find an eligible contract</summary><p>These expiry/delta preferences are review choices. Sean's routine minimum absolute delta is 0.25.</p>
          <div className="cartel-fields"><label>Minimum DTE<input type="number" min="2" value={minDte} onChange={e => setMinDte(Number(e.target.value))}/></label>
            <label>Maximum DTE<input type="number" min="2" value={maxDte} onChange={e => setMaxDte(Number(e.target.value))}/></label>
            <label>Target DTE<input type="number" min="2" value={targetDte} onChange={e => setTargetDte(Number(e.target.value))}/></label>
            <label>Target absolute delta<input type="number" min=".25" max="1" step=".05" value={delta} onChange={e => setDelta(Number(e.target.value))}/></label></div>
          <button className="ghost-btn" type="button" disabled={!!busy || !maxPremium} onClick={() => run("Searching contracts", async () => {
            const value = await api.post<any>(`/api/options-cartel/runs/${runId}/contracts`, {dteMin:minDte,dteMax:maxDte,targetDte,
              targetAbsDelta:delta,maxAsk:Number(maxPremium),maxSpreadPct:10,minOpenInterest:100}); setSelection(value);
          })}>Search contracts</button>
          {selection && <><p>{selection.selected ? "Eligible refreshed contracts:" : "No eligible refreshed contract found."}</p>
            {selection.candidates?.filter((c: any) => c.eligible).map((c: any) => <button className="ghost-btn" type="button" key={c.symbol} onClick={() => setContract(c.symbol)}>
              {c.symbol} · ask {c.ask} · delta {c.delta}</button>)}<p>{selection.note}</p></>}
        </details>
        <label className="cartel-check"><input type="checkbox" required checked={overnightAck} onChange={e => setOvernightAck(e.target.checked)}/>I acknowledge that overnight options use app-managed protection.</label>
      </>}
      {real && <label className="cartel-check"><input type="checkbox" required checked={allowLive} onChange={e => setAllowLive(e.target.checked)}/>Allow this reviewed plan to execute on the selected real/paper account.</label>}
      <p>{mode === "auto" ? "Auto submits when a fresh closed-bar signal passes the execution checks." : "A confirmed signal presents a proposal for your approval."} Orders use the reviewed budget and are sized again at submission.</p>
      <button className="ghost-btn" type="button" disabled={!!busy || !portfolioId || !budget} onClick={e => {
        if (!e.currentTarget.form?.reportValidity()) return;
        run("Checking execution", async () => setReport(await api.post(`/api/options-cartel/runs/${runId}/preflight`, payload())));
      }}>Check execution now</button>
      {report && <><p>{report.passed ? "Current checks passed" : "Current checks block entry"} · proposed units {report.expression?.quantity}</p>
        <ul>{report.checks?.filter((c: any) => !c.passed).map((c: any) => <li key={c.name}>{c.reason}</li>)}
          {report.risk?.checks?.filter((c: any) => !c.passed).map((c: any) => <li key={c.name}>{c.detail || c.name}</li>)}</ul></>}
    </>}
    {error && <p className="cartel-error" role="alert">{error}</p>}
    <button className="primary-btn" disabled={!!busy || !portfolioId || !!active?.submissionReserved}>{busy || (mode === "alert" ? "Arm alert only" : `Arm ${mode}`)}</button>
  </form>;
}
