import {useEffect,useState} from "react";
import {api} from "../lib/api";
import {SymIcon} from "../components/SymIcon";

export function CartelIgnition() {
  const [retired,setRetired]=useState(false),[limit,setLimit]=useState(25);
  const [data,setData]=useState<any>(null),[error,setError]=useState("");
  const refresh=()=>api.get<any>(`/api/options-cartel/ignition?include_inactive=${retired}`).then(setData).catch(e=>setError(String(e.message||e)));
  useEffect(()=>{void refresh();const t=setInterval(refresh,30000);return ()=>clearInterval(t);},[retired]);
  return <section className="panel" aria-label="Ignition watchlist">
    <div className="panel-head"><strong>Ignition watchlist · Research</strong><button className="btn" onClick={()=>void refresh()}>Refresh watchlist</button></div>
    <details className="cartel-inset"><summary>{data?.rows?.length || 0} research theses · expand watchlist</summary><label><input type="checkbox" checked={retired} onChange={e=>{setRetired(e.target.checked);setLimit(25);}}/>Include expired and invalidated research</label><p>Strong ignition move → quiet consolidation → prospective breakout. These theses persist across sessions. They do not place orders or automatically change your execution profile.</p>
    {error && <p role="alert">{error}</p>}
    {!data?.rows?.length ? <p>No ignition theses recorded yet. Preparation discovers and updates them from completed daily history.</p> : <div className="scroll-x"><table className="tbl"><thead><tr><th>Symbol</th><th>Event</th><th>Stage</th><th>Volume</th><th>Sessions</th><th>Prospective trigger</th><th>Evidence</th></tr></thead><tbody>
      {data.rows.slice(0,limit).map((r:any)=><tr key={r.id}><td><SymIcon sym={r.symbol}/>{r.symbol}</td><td>{r.eventSession}</td><td>{r.stage.replaceAll("_"," ")}</td><td>{r.eventVolumeRatio.toFixed(2)}×</td><td>{r.consolidationSessions}</td><td>{r.trigger?.toFixed(2)||"Developing"}</td><td>{r.reasons?.join("; ")||(r.stage==="setup_ready"?"Research setup ready; executable plan requires fresh review":r.stage==="ignition_verified"?"Waiting for post-event consolidation":r.stage==="expired"?"Research window expired":r.stage==="invalidated"?"Research thesis invalidated":"Still developing")}<br/><small>As of {new Date(r.asOf).toLocaleString()} · Catalyst unverified</small></td></tr>)}
    </tbody></table></div>}{data?.rows?.length > limit && <button className="ghost-btn" onClick={()=>setLimit(n=>n+25)}>Show 25 more</button>}</details>
  </section>;
}
