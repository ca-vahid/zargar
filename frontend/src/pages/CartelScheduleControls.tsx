import { useEffect, useState } from "react";
import { api } from "../lib/api";

export function CartelScheduleControls() {
  const [configuration, setConfiguration] = useState<any>(null);
  const [symbols, setSymbols] = useState("");
  const [jobs, setJobs] = useState<any[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let alive = true;
    api.get<any>("/api/options-cartel/schedule").then(value => {
      if (alive) { setConfiguration(value.configuration); setSymbols(value.configuration.scanSymbols.join(", ")); setJobs(value.jobs); }
    }).catch(e => { if (alive) setError(String(e)); });
    return () => { alive = false; };
  }, []);
  return <details className="cartel-card"><summary>Scheduled scans and recovery</summary>
    {error && <p role="alert">{error}</p>}
    {!configuration ? <p>Schedule configuration unavailable or loading.</p> : <form className="cartel-form" onSubmit={async e => {
      e.preventDefault(); setBusy(true); setError("");
      try {
        const result = await api.post<any>("/api/options-cartel/schedule", {...configuration,
          scanSymbols: symbols.split(/[\s,]+/).filter(Boolean)});
        setConfiguration(result.configuration); setJobs(result.jobs); setSymbols(result.configuration.scanSymbols.join(", "));
      } catch (e) { setError(String(e)); } finally { setBusy(false); }
    }}>
      <label className="cartel-check"><input type="checkbox" checked={configuration.scanEnabled} onChange={e => setConfiguration({...configuration, scanEnabled:e.target.checked})}/>Nightly scan at 20:15 ET</label>
      <label>Scheduled symbols (up to 20)<textarea value={symbols} onChange={e => setSymbols(e.target.value)}/></label>
      <label>Scheduled screen<select value={configuration.scanProfile} onChange={e => setConfiguration({...configuration, scanProfile:e.target.value})}>
        {['september_2026', 'september_2026_video', 'june_2026', 'june_2026_image', 'may_2026', 'may_2026_image'].map(p => <option key={p} value={p}>{p.replaceAll('_', ' ')}</option>)}
      </select></label>
      <label>Scheduled direction<select value={configuration.scanDirection} onChange={e => setConfiguration({...configuration, scanDirection:e.target.value})}><option value="long">Bullish</option><option value="short">Bearish puts</option></select></label>
      <p>Scheduled scans save research only. Fundamental and industry snapshots are not collected automatically; missing evidence stays unknown.</p>
      <label className="cartel-check"><input type="checkbox" checked={configuration.recoveryEnabled} onChange={e => setConfiguration({...configuration, recoveryEnabled:e.target.checked})}/>Recover held Cartel positions at 09:05 and 20:10 ET</label>
      <p>Recovery may trigger managed exits at current prices after missed daily signals are validated. It applies to all held Cartel positions, across accounts.</p>
      <button disabled={busy}>Save schedule</button>
      <p>Saving does not run a job immediately. Jobs run once per weekday; a job already run or skipped today waits until the next scheduled day.</p>
    </form>}
    <ul>{jobs.map(job => <li key={job.name}>
      {job.name.replaceAll('_', ' ')} · {job.at} ET
      <p>Latest recorded outcome: {job.lastOutcome ? `${job.lastOutcome.day} · ${job.lastOutcome.status === 'failed' ? 'failed' : job.lastOutcome.result?.status || 'finished'}` : 'No recorded outcome'}</p>
      {job.lastOutcome?.error && <p className="cartel-error">{job.lastOutcome.error}</p>}
      {job.lastOutcome?.result?.dataErrors > 0 && <p>{job.lastOutcome.result.dataErrors} symbols had data failures.</p>}
      {job.lastOutcome?.result?.positions?.map((position: any) => <p key={position.positionId}>
        Position {position.positionId}: {position.status}{position.reason ? ` — ${position.reason}` : ''}{position.catchupStatus ? ` · catch-up ${position.catchupStatus}` : ''}
      </p>)}
    </li>)}</ul>
  </details>;
}
