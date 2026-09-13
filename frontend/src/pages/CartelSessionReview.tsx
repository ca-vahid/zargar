import {useState} from "react";
import {api} from "../lib/api";
import {useWorkspace} from "../lib/workspace";
export function CartelSessionReview(){
 const workspace=useWorkspace(); const [day,setDay]=useState(new Intl.DateTimeFormat('en-CA',{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date()));
 const [data,setData]=useState<any>(null),[error,setError]=useState('');
 return <details className="cartel-inset"><summary>Session review · as-observed evidence</summary><label>Session<input aria-label="Review session" type="date" value={day} onChange={e=>{setDay(e.target.value);setData(null);}}/></label>
 <button className="ghost-btn" onClick={()=>void api.get<any>(`/api/options-cartel/session-review?day=${encodeURIComponent(day)}&workspace=${workspace}`).then(r=>{setData(r);setError('');}).catch(e=>setError(String(e.message||e)))}>Load session review</button>
 {error&&<p role="alert">{error}</p>}{data&&<><p>{data.orderCount} orders · {data.filledOrders} orders with fills. {data.note}</p><div className="scroll-x"><table className="tbl"><thead><tr><th>Symbol</th><th>Status</th><th>Outcome</th><th>Data sources</th></tr></thead><tbody>{data.rows.map((r:any)=><tr key={r.planId}><td>{r.symbol}</td><td>{r.status}</td><td>{r.category.replaceAll('_',' ')}<details><summary>Decisions</summary>{r.decisions.map((d:any,i:number)=><p key={i}>{new Date(d.at).toLocaleTimeString()} · {d.reason}</p>)}</details></td><td>{Object.entries(r.dataEvidence.sourceCounts).map(([k,v])=>`${k}: ${v}`).join(' · ')||'not recorded'}</td></tr>)}</tbody></table></div></>}
 </details>;
}
