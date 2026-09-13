import {useEffect,useState} from "react";
import {api} from "../lib/api";
import {SymIcon} from "../components/SymIcon";

export function CartelIgnition() {
  const [data,setData]=useState<any>(null),[error,setError]=useState("");
  const refresh=()=>api.get<any>("/api/options-cartel/ignition").then(setData).catch(e=>setError(String(e.message||e)));
  useEffect(()=>{void refresh();const t=setInterval(refresh,30000);return ()=>clearInterval(t);},[]);
  return <section className="panel" aria-label="Ignition watchlist">
    <div className="panel-head"><strong>Ignition watchlist · Research</strong><button className="btn" onClick={()=>void refresh()}>Refresh watchlist</button></div>
    <div className="cartel-inset"><p>Strong ignition move → quiet consolidation → prospective breakout. These theses persist across sessions. They do not place orders or automatically change your execution profile.</p>
    {error && <p role="alert">{error}</p>}
    {!data?.rows?.length ? <p>No ignition theses recorded yet. Preparation discovers and updates them from completed daily history.</p> : <div className="scroll-x"><table className="tbl"><thead><tr><th>Symbol</th><th>Event</th><th>Stage</th><th>Volume</th><th>Sessions</th><th>Prospective trigger</th><th>Evidence</th></tr></thead><tbody>
      {data.rows.map((r:any)=><tr key={r.id}><td><SymIcon sym={r.symbol}/>{r.symbol}</td><td>{r.eventSession}</td><td>{r.stage.replaceAll("_"," ")}</td><td>{r.eventVolumeRatio.toFixed(2)}×</td><td>{r.consolidationSessions}</td><td>{r.trigger?.toFixed(2)||"Developing"}</td><td>{r.reasons?.join("; ")||"Research checks passed; executable plan requires fresh review"}<br/><small>As of {new Date(r.asOf).toLocaleString()} · Catalyst unverified</small></td></tr>)}
    </tbody></table></div>}</div>
  </section>;
}
