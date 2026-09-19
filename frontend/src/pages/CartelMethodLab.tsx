import {useEffect, useRef, useState} from 'react';
import {api} from '../lib/api';
import {useWorkspace} from '../lib/workspace';
import {ErrorState, Spinner} from '../components/ui';

type Read = {status:string; signal?:{at:number; referencePrice:number; stop:number}; captureStatus?:string;
  quoteStatus?:string; quoteAttempts?:{at:number;attempt:number;status:string;reason?:string;selectionErrors?:string[];underlyingFailures?:string[]}[];
  trace?:{status?:string; decision?:string; blockers?:string[]}[]};
type Receipt = {status:string;netPnl:number|null;fees?:number;remainingQty:number|null;gaps:string[];contractSymbol?:string;
  fills?:{at:number;side:string;quantity:number;price:number;fee:number}[]};
type Row = {id:string; symbol:string; observed:boolean; baselineStatus:string; baselineReason?:string;
  labFeatures:{recent5RangeAdr:number|null; compressionSessions:number|null};
  definitions:Record<string,{support:number}>; models:Record<string,Read>};
type Lab = {workspace:string; session:string; enabled:boolean; status:string; researchOnly:boolean; placesOrders:boolean;
  rows:Row[]; signalCount:number; pricedSignals:number; freezeError?:string|null;
  denominator:{eligible?:number; observedLimit?:number; omitted?:number};
  trial?:{id?:string; protocol?:{control:string; challenger:string; min_sessions:number; min_closed_per_variant:number}}|null};
type Trial = {trialId:string; activationAllowed:false; review:{status:string;failures:string[];sessions:number;
  completePairs:number;incompletePairs:number;metrics:Record<string,{netPnl:number;closedTrades:number;stressNetPnl:number;conservativeDrawdownPct:number}>};
  sessions:{session:string;selectionComparisons?:Record<string,{selectedSymbols:string[];covered:number;selectedCount:number;closedTrades:number;netPnl:number|null}>;
    economics:{rows:{signalId:string;symbol:string;variant:string;status:string;gaps:string[];
    receiptEconomics?:Receipt;shareReceiptEconomics?:Receipt}[]}}[]};
const SETTING='techniques.options_cartel.method_lab';
const today=()=>new Intl.DateTimeFormat('en-CA',{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
const human=(s:string)=>s.replaceAll('_',' ');
const num=(n:number|null|undefined)=>n==null?'Unknown':n.toLocaleString(undefined,{maximumFractionDigits:2});
const label:Record<string,string>={breakout_5m_v1:'Breakout · 5m',breakout_15m_v1:'Breakout · 15m',
  undercut_reclaim_5m_v1:'Undercut and reclaim',pivot_30m_5m_v1:'30m pivot'};

function ModelFills({value}:{value:Receipt}) {
  return <details><summary>Modeled fills · {value.contractSymbol??'instrument unavailable'}</summary>
    {value.fills?.length?<table><thead><tr><th>Time (ET)</th><th>Side</th><th>Quantity</th><th>Price</th><th>Fee</th></tr></thead>
      <tbody>{value.fills.map((f,i)=><tr key={i}><td>{new Date(f.at).toLocaleString(undefined,{timeZone:'America/New_York'})}</td>
        <td>{f.side}</td><td>{f.quantity}</td><td>{num(f.price)}</td><td>{num(f.fee)}</td></tr>)}</tbody></table>:<p>No modeled fills supported by the evidence.</p>}
    <p>{value.gaps.join(' · ')}</p>
  </details>;
}

export function CartelMethodLab({settings=false}:{settings?:boolean}) {
  const workspace=useWorkspace();const [day,setDay]=useState(today);
  const [revision,setRevision]=useState(0);const [data,setData]=useState<Lab|null>(null);
  const [error,setError]=useState('');const [loading,setLoading]=useState(false);
  const [enabled,setEnabled]=useState(false);const [saving,setSaving]=useState(false);const [saved,setSaved]=useState(false);
  const [trial,setTrial]=useState<Trial|null>(null);const [reviewing,setReviewing]=useState(false);
  const scope=`${workspace}:${day}`;const current=useRef(scope);current.current=scope;
  useEffect(()=>{
    let active=true;setData(null);setTrial(null);setError('');setSaved(false);
    if(workspace!=='practice'||!/^\d{4}-\d{2}-\d{2}$/.test(day)){setLoading(false);return;}
    setLoading(true);
    void api.get<Lab>(`/api/options-cartel/method-lab?workspace=practice&day=${encodeURIComponent(day)}`)
      .then(result=>{if(!active)return;if(result.workspace!=='practice'||result.session!==day||!result.researchOnly||result.placesOrders)
        throw new Error('Method-lab response does not match this Practice session.');setData(result);setEnabled(result.enabled);})
      .catch(e=>{if(active)setError(e instanceof Error?e.message:'Could not load method lab.');})
      .finally(()=>{if(active)setLoading(false);});
    return()=>{active=false;};
  },[workspace,day,revision]);
  async function save(){
    if(workspace!=='practice'||!data||saving)return;
    const origin=scope;setSaving(true);setError('');setSaved(false);
    try{await api.patchSettings({[SETTING]:enabled});if(current.current===origin){setSaved(true);setData(old=>old?{...old,enabled}:old);}}
    catch(e){if(current.current===origin)setError(e instanceof Error?e.message:'Could not save method-lab setting.');}
    finally{setSaving(false);}
  }
  async function review(){
    const id=data?.trial?.id;if(!id||workspace!=='practice'||reviewing)return;
    const origin=scope;setReviewing(true);setError('');
    try{const result=await api.get<Trial>(`/api/options-cartel/method-lab/trials/${encodeURIComponent(id)}?workspace=practice`);
      if(current.current===origin){if(result.trialId!==id||result.activationAllowed!==false)throw new Error('Invalid trial response');setTrial(result);}}
    catch(e){if(current.current===origin)setError(e instanceof Error?e.message:'Could not review trial.');}
    finally{setReviewing(false);}
  }
  return <section className="panel cartel-card" aria-label="Cartel method lab">
    <div className="panel-head"><h2>Method lab{settings?' settings':''}</h2><span className="badge">Practice research</span></div>
    <p>Compare breakout, undercut-and-reclaim and 30-minute pivot entries using frozen plans and recorded observations. This lab does not place trades.</p>
    {workspace!=='practice'?<p>Switch to Practice to view the method lab.</p>:<>
      {!settings&&<div className="cartel-research-controls"><label>Session (ET)<input type="date" value={day} onChange={e=>setDay(e.target.value)}/></label>
        <button className="ghost-btn" disabled={loading||!day} onClick={()=>setRevision(n=>n+1)}>Refresh method lab</button></div>}
      {loading&&<Spinner label="Loading method lab…"/>}
      {error&&<ErrorState message={error} onRetry={()=>setRevision(n=>n+1)}/>}
      {settings&&data&&<form className="cartel-form" onSubmit={e=>{e.preventDefault();void save();}}>
        <label className="cartel-check"><input type="checkbox" checked={enabled} disabled={saving} onChange={e=>{setEnabled(e.target.checked);setSaved(false);}}/>Collect shadow entry and trade-economics evidence</label>
        <p>Enable before a fresh preparation run. New candidates and baselines must be frozen before the market opens. Turning this off stops collection and preserves prior records.</p>
        <button className="ghost-btn" disabled={saving||enabled===data.enabled}>{saving?'Saving…':'Save method-lab setting'}</button>
        {saved&&<p role="status">Saved. Run fresh preparation before the next session to include the method lab.</p>}
      </form>}
      {!settings&&data&&<>
        <p><strong>{data.enabled?human(data.status):'Collection off'}</strong> · {data.denominator.eligible??0} eligible candidates · {data.denominator.observedLimit??0} monitored · {data.denominator.omitted??0} outside the research limit</p>
        <p>{data.signalCount} recorded research confirmations · {data.pricedSignals} with timely option observations. A confirmation or quote is not a filled trade.</p>
        {data.freezeError&&<p className="cartel-notice">{data.freezeError}</p>}
        {data.trial?.protocol&&<p>Frozen comparison: {label[data.trial.protocol.control]} versus {label[data.trial.protocol.challenger]}. First review requires at least {data.trial.protocol.min_sessions} sessions and {data.trial.protocol.min_closed_per_variant} complete closed outcomes per variant, plus cost, coverage and risk checks. No automatic promotion.</p>}
        {data.trial?.id&&<button className="ghost-btn" disabled={reviewing} onClick={()=>void review()}>{reviewing?'Reviewing stored evidence…':'Review trial economics'}</button>}
        {trial&&<div className="cartel-inset"><h3>Modeled trial results</h3>
          <p>{human(trial.review.status)} · {trial.review.sessions} paired sessions · {trial.review.completePairs} complete pairs · {trial.review.incompletePairs} incomplete pairs</p>
          <p className="muted">Receipt-timed quote models, not actual account profit. Unknown outcomes are excluded from dollar totals and remain visible in the review gate.</p>
          <p className="muted">Exits are evaluated when recorded minute bars arrive, then priced from fresh quotes. These models do not recreate every intraminute move or real broker execution.</p>
          {Object.entries(trial.review.metrics).map(([key,m])=><p key={key}>{label[key]??human(key)}: {m.closedTrades} closed modeled trades · net USD {num(m.netPnl)} · stressed net USD {num(m.stressNetPnl)} · drawdown bound {num(m.conservativeDrawdownPct)}%</p>)}
          <p>{trial.review.status==='awaiting_sessions'?'The trial has not started. No observation windows are overdue.':trial.review.failures.map(human).join(' · ')||'Ready for review; this does not activate trading.'}</p>
          <details><summary>Selection comparisons · same breakout control</summary>{trial.sessions.map(s=><div key={s.session}><strong>{s.session}</strong>
            {Object.entries(s.selectionComparisons??{}).map(([ranker,r])=><p key={ranker}>{human(ranker)}: {r.selectedSymbols.join(', ')} · {r.covered}/{r.selectedCount} complete · {r.closedTrades} closed modeled trades · net USD {num(r.netPnl)}</p>)}
          </div>)}</details>
          <details><summary>Economic evidence and gaps</summary>{trial.sessions.flatMap(s=>s.economics.rows.map(r=><div key={r.signalId}>
            <strong>{s.session} · {r.symbol} · {label[r.variant]??human(r.variant)}</strong>
            <p>{r.receiptEconomics?`${human(r.receiptEconomics.status)} · modeled net USD ${num(r.receiptEconomics.netPnl)} · ${num(r.receiptEconomics.remainingQty)} contracts remain`:human(r.status)}</p>
            {r.receiptEconomics&&<ModelFills value={r.receiptEconomics}/>}
            {r.shareReceiptEconomics&&<p>Shares: {human(r.shareReceiptEconomics.status)} · modeled net USD {num(r.shareReceiptEconomics.netPnl)} · {num(r.shareReceiptEconomics.remainingQty)} shares remain. Passing on the trade uses no capital and returns zero.</p>}
            {r.shareReceiptEconomics&&<ModelFills value={r.shareReceiptEconomics}/>}
            <p>{r.gaps.join(' · ')}</p></div>))}</details>
        </div>}
        <p className="muted">Reclaim and pivot models are experimental closed-bar interpretations. Original source context is still being verified. Missing option prices or costs remain unknown.</p>
        {!data.rows.length?<p>No frozen method-lab candidates for this session. Enable collection and run preparation before the open.</p>:
          <div className="table-scroll"><table><thead><tr><th>Stock</th><th>Preparation</th><th>Compression</th><th>Entry observations</th></tr></thead><tbody>
            {data.rows.map(row=><tr key={row.id}><td><strong>{row.symbol}</strong>{!row.observed&&<p>Outside research limit</p>}</td>
              <td>{human(row.baselineStatus)}{row.baselineReason&&<p>{row.baselineReason}</p>}</td>
              <td>{num(row.labFeatures.recent5RangeAdr)} ADR · {num(row.labFeatures.compressionSessions)} measured sessions</td>
              <td>{Object.entries(row.models).map(([key,read])=><div key={key}><strong>{label[key]??human(key)}</strong>: {human(read.status)}
                {read.signal&&<span> · reference {num(read.signal.referencePrice)}, stop {num(read.signal.stop)}</span>}
                {read.captureStatus&&<span> · {human(read.captureStatus)}</span>}
                {read.quoteStatus&&<span> · option observation: {human(read.quoteStatus)}</span>}
                {!!read.quoteAttempts?.length&&<details><summary>Quote attempts</summary>{read.quoteAttempts.map((a,i)=><p key={i}>Attempt {a.attempt}: {human(a.status)} · {[a.reason,...(a.selectionErrors??[]),...(a.underlyingFailures??[])].filter(Boolean).join(' · ')}</p>)}</details>}
                {!!read.trace?.length&&<details><summary>Evidence</summary>{read.trace.map((t,i)=><p key={i}>{human(t.status??t.decision??'unknown')}{t.blockers?.length?`: ${t.blockers.map(human).join(', ')}`:''}</p>)}</details>}
              </div>)}{!Object.keys(row.models).length&&<span>Waiting for session observations</span>}</td>
            </tr>)}
          </tbody></table></div>}
      </>}
    </>}
  </section>;
}
