import { useEffect, useState } from 'react';
import { api } from '../lib/api';

type Status = {enabled:boolean; running:boolean; lastAttemptAt:number|null; captured:number; errors:Record<string,string>};
export function CartelQuoteRecording() {
  const [status, setStatus] = useState<Status|null>(null);
  const [enabled, setEnabled] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const refresh = async () => {
    const next = await api.get<Status>('/api/options-cartel/quote-recording');
    setStatus(next); setEnabled(next.enabled);
  };
  useEffect(() => { void refresh().catch(e=>setError(String(e))); }, []);
  return <details className="cartel-card"><summary>Option quote recording</summary>
    <p>Record cached quotes for active Cartel option plans, including paused plans and positions being closed. This does not subscribe to additional feeds or place orders.</p>
    <p>Samples are taken roughly every five seconds while enabled. Sampling may miss price changes; delayed quotes and missing provider timestamps stay labeled.</p>
    {error && <p role="alert" className="cartel-error">{error}</p>}
    <form className="cartel-form" onSubmit={async e=>{
      e.preventDefault(); setBusy(true); setError('');
      try { setStatus(await api.post<Status>('/api/options-cartel/quote-recording', {enabled})); }
      catch(e) { setError(String(e)); } finally { setBusy(false); }
    }}>
      <label><input type="checkbox" checked={enabled} onChange={e=>setEnabled(e.target.checked)}/>Enable Cartel option quote recording</label>
      <button disabled={busy || !status}>Save recording setting</button>
    </form>
    <button disabled={busy} onClick={()=>{setError(''); void refresh().catch(e=>setError(String(e)));}}>Refresh recording status</button>
    {status && <>
      <p>Saved setting: {status.enabled ? 'on' : 'off'} · {status.running ? 'recording' : 'idle'}.
        Last batch: {status.lastAttemptAt ? new Date(status.lastAttemptAt).toISOString() : 'none'} · {status.captured} observations captured.</p>
      {Object.entries(status.errors).map(([id,message])=><p className="cartel-error" key={id}>Plan {id}: {message}</p>)}
    </>}
  </details>;
}
