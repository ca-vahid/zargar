import {useEffect,useState} from 'react';
import {api} from '../lib/api';
import {useWorkspace} from '../lib/workspace';
export function CartelIntradayResearch({settings=false}:{settings?:boolean}) {
 const [revision,setRevision]=useState(0);
 const workspace=useWorkspace();const [data,setData]=useState<any>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false);
 useEffect(()=>{let active=true;setData(null);setError('');const refresh=()=>api.get<any>(`/api/options-cartel/intraday-research?workspace=${workspace}`).then(r=>{if(active)setData(r);}).catch(e=>{if(active)setError(`Could not load research observations. ${e.message && e.message !== 'Error' ? e.message : 'The app may be restarting; try Refresh shortly.'}`);});void refresh();const timer=setInterval(()=>void refresh(),30000);return()=>{active=false;clearInterval(timer);};},[workspace,revision]);
 const latest=data?.rows?.[0];
 return <section className="panel cartel-card" aria-label="Intraday market research"><div className="panel-head"><strong>Intraday market research</strong><span className="badge">Research only</span><button className="ghost-btn" onClick={()=>setRevision(n=>n+1)}>Refresh research</button></div><div className="cartel-inset">
  <p>Observes completed 15-minute candles against saved <strong>daily</strong> EMA levels. It cannot arm plans, place orders or change the market gate.</p>
  {workspace==='live'?<p>Available in Practice only. Live permissions are unchanged.</p>:<>
   {settings&&<label className="cartel-check"><input type="checkbox" checked={!!data?.enabled} disabled={!data||busy} onChange={async e=>{const enabled=e.target.checked;setBusy(true);try{await api.patchSettings({'techniques.options_cartel.intraday_research':enabled});setData((d:any)=>({...d,enabled}));setError('');}catch(e:any){setError(e.message||'Could not save research setting');}finally{setBusy(false);}}}/>Enable non-executing intraday research</label>}
   {error&&<p role="alert">{error}</p>}
   {!data?<p>Loading research status…</p>:!data.enabled?<p>Research monitoring is off.</p>:!latest?<p>Waiting for a blocked Practice shortlist and completed market candles. Preparation and automatic entry permission remain unchanged.</p>:<>
    <p><strong>{latest.market.status.replaceAll('_',' ')}</strong> · observed {new Date(latest.at).toLocaleString()}</p>
    <p>{latest.market.sustained?'Two consecutive observations meet the research alignment rule. This is not permission to trade.':'Sustained research alignment has not been established.'}</p>
    {Object.entries(latest.market.indices).map(([symbol,r]:[string,any])=><p key={symbol}><strong>{symbol}</strong> · {r.status==='observed'?`15-minute close ${r.close.toFixed(2)} · daily EMA references: 8 ${r.dailyEmas['8'].toFixed(2)}, 21 ${r.dailyEmas['21'].toFixed(2)}, 50 ${r.dailyEmas['50'].toFixed(2)}`:r.reason}</p>)}
    <div className="scroll-x"><table className="tbl"><thead><tr><th>Stock</th><th>Research observation</th></tr></thead><tbody>{latest.candidates.map((c:any)=><tr key={c.symbol}><td>{c.symbol}</td><td>{c.status.replaceAll('_',' ')}{c.reason&&<p>{c.reason}</p>}{c.signal&&<p>Underlying confirmation at {new Date(c.signal.at).toLocaleTimeString()}. Option eligibility and profit are not established.</p>}</td></tr>)}</tbody></table></div>
    <details><summary>Earlier observations · {data.rows.length}</summary>{data.rows.slice(1).map((r:any)=><p key={r.id}>{new Date(r.at).toLocaleTimeString()} · {r.market.status.replaceAll('_',' ')}</p>)}</details>
   </>}
   {data?.reason&&<p className="cartel-notice">{data.reason}</p>}
  </>}
  <p className="muted">Engineering experiment, not a verified Sean rule. No retrospective entries, automatic unlocking or simulated profits.</p>
 </div></section>;
}
