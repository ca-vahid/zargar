import { useCartelPortfolios } from "./cartelAccounts";
import { useEffect, useState } from "react";
import { api } from "../lib/api";


type RiskReport = { portfolioId: string; day: string; asOfMs: number; available: boolean;
  pnl: number | null; baseCurrency: string; issues: string[]; limitPct: number; halted: boolean;
  assets: {symbol: string; openingQty: number; priorClose: number | null}[] };

export function CartelRiskCard() {
  const books = useCartelPortfolios();
  const [chosen, setChosen] = useState("");
  const selected = books.some(b => b.id === chosen) ? chosen : books[0]?.id || "";
  const [report, setReport] = useState<RiskReport | null>(null);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const [recovering, setRecovering] = useState(false);
  const [recovery, setRecovery] = useState<{portfolioId: string; message: string; issues: string[]} | null>(null);
  const recover = async () => {
    const account = selected;
    setRecovering(true);
    try {
      const result = await api.post<{session: string; recovered: string[]; unavailable: {symbol: string; reason: string}[]}>(
        `/api/options-cartel/risk/${encodeURIComponent(account)}/recover-marks`);
      setRecovery({portfolioId: account, message: `Recovered ${result.recovered.length} prior close(s) for ${result.session}.`,
        issues: result.unavailable.map(item => `${item.symbol}: ${item.reason}`)});
      setRevision(r => r + 1);
    } catch (e) { setRecovery({portfolioId: account, message: "Prior-close recovery failed.", issues: [String(e)]}); }
    finally { setRecovering(false); }
  };
  useEffect(() => {
    let alive = true;
    setReport(null); setError("");
    if (selected) api.get<RiskReport>(`/api/options-cartel/risk/${encodeURIComponent(selected)}`)
      .then(r => { if (alive) setReport(r); }).catch(e => { if (alive) setError(String(e)); });
    return () => { alive = false; };
  }, [selected, revision]);
  return <section className="panel cartel-card" aria-label="Cartel daily trading P&L">
    <div className="cartel-row"><h2>Daily trading P&amp;L</h2>
      <button className="ghost-btn" type="button" disabled={!selected} onClick={() => setRevision(r => r + 1)}>Refresh risk report</button></div>
    {!books.length ? <p>No accounts in this workspace.</p> : <>
      <div className="cartel-fields"><label>Risk account<select value={selected} onChange={e => setChosen(e.target.value)}>
        {books.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}</select></label></div>
      {error ? <p className="cartel-error" role="alert">{error}</p> : !report || report.portfolioId !== selected ? <p role="status">Loading risk report…</p> : <>
        <p><strong>{report.available && report.pnl !== null ? `${report.baseCurrency} ${report.pnl.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}` : "Accounting data incomplete"}</strong>
          {" · "}{report.day} · as of {new Date(report.asOfMs).toLocaleTimeString(undefined, {timeZone: "America/New_York", timeZoneName: "short"})}</p>
        <p>Cartel price gains and losses after recorded fees, measured from the prior session close. Currency conversion uses current FX; FX translation is excluded.</p>
        <p>{report.limitPct > 0 ? `Daily technique limit: ${report.limitPct}% of book equity.` : "Daily technique limit is off; the book-wide loss guard is separate."}</p>
        {report.halted && <p className="cartel-notice" role="status">Cartel loss halt is active for this session day.</p>}
        {!report.available && <details><summary>Review missing accounting data</summary><ul>
          {report.issues.map((issue, i) => <li key={i}>{issue}</li>)}</ul></details>}
        {report.assets.some(asset => asset.openingQty > 0 && asset.priorClose === null) &&
          <button className="ghost-btn" type="button" disabled={recovering} onClick={recover}>{recovering ? "Recovering prior closes…" : "Recover prior closes"}</button>}
        {recovery?.portfolioId === selected && <div role="status"><p>{recovery.message}</p>
          {recovery.issues.length > 0 && <ul>{recovery.issues.map((issue, i) => <li key={i}>{issue}</li>)}</ul>}</div>}
      </>}
    </>}
  </section>;
}
