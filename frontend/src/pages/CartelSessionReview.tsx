import {useEffect, useRef, useState} from "react";
import {api} from "../lib/api";
import {useWorkspace} from "../lib/workspace";
import {CartelRunLink} from "./CartelRunLink";
import {useStore} from "../store";
export function CartelSessionReview() {
  const workspace = useWorkspace();
  const [day, setDay] = useState(new Intl.DateTimeFormat('en-CA', {timeZone:'America/New_York', year:'numeric', month:'2-digit', day:'2-digit'}).format(new Date()));
  const [account, setAccount] = useState('');
  const [accounts, setAccounts] = useState<{id:string;name:string}[]>([]);
  const [data, setData] = useState<any>(null), [coverage, setCoverage] = useState<any>(null);
  const [error, setError] = useState(''), [busy, setBusy] = useState(false);
  const request = useRef(0);
  const openRun = useStore(s => s.openCartelRun);
  const scope = `${workspace}:${account}:${day}`;
  const currentScope = useRef(scope); currentScope.current = scope;
  useEffect(() => {
    setAccount(''); setAccounts([]);
    let active = true;
    void api.get<{id:string;name:string}[]>(`/api/options-cartel/review-accounts?workspace=${workspace}`)
      .then(rows => {if (active) setAccounts(rows);}).catch(() => {});
    return () => {active = false;};
  }, [workspace]);
  useEffect(() => {request.current++; setData(null); setCoverage(null); setError(''); setBusy(false);}, [workspace, account, day]);
  useEffect(() => () => {request.current++;}, []);
  async function load() {
    const selectedScope = scope;
    const id = ++request.current; setBusy(true); setError('');
    const query = `day=${encodeURIComponent(day)}&workspace=${workspace}${account ? `&portfolioId=${encodeURIComponent(account)}` : ''}`;
    try {
      const [result, quotes] = await Promise.all([api.get<any>(`/api/options-cartel/session-review?${query}`), api.get<any>(`/api/options-cartel/quote-coverage?${query}`)]);
      if (id === request.current && selectedScope === currentScope.current) {setData({...result, reviewScope:selectedScope}); setCoverage(quotes);}
    } catch(e:any) {if (id === request.current && selectedScope === currentScope.current) setError(e.message || String(e));}
    finally {if (id === request.current && selectedScope === currentScope.current) setBusy(false);}
  }
  const money = (value:number|null|undefined) => value == null ? 'Unavailable' : new Intl.NumberFormat(undefined, {style:'currency', currency:data?.baseCurrency || 'USD'}).format(value);
  async function olderAttempts() {
    const selectedScope = scope, id = ++request.current; setBusy(true);
    try {
      const page = await api.get<any>(`/api/options-cartel/preparation-attempts?day=${day}&workspace=${workspace}&portfolioId=${encodeURIComponent(data.portfolioId)}&cursor=${encodeURIComponent(data.attemptCursor)}&asOfMs=${data.asOfMs}`);
      if (id === request.current && selectedScope === currentScope.current) setData((previous:any) => ({...previous, attempts:[...previous.attempts,...page.rows], attemptCursor:page.nextCursor, attemptCount:page.total}));
    } catch(e:any) {if (id === request.current && selectedScope === currentScope.current) setError(e.message || String(e));}
    finally {if (id === request.current && selectedScope === currentScope.current) setBusy(false);}
  }
  const exitLabel = (value:string) => value === 'cartel:stop' ? 'Protective stop' : value.replace(/^cartel:/, '').replaceAll('_', ' ');
  return <details className="cartel-inset"><summary>Daily review · trades, costs and missed opportunities</summary>
    <div className="cartel-row"><label>Session (ET)<input aria-label="Review session" type="date" value={day} onChange={e => setDay(e.target.value)}/></label>
      <label>Account<select value={account} onChange={e => setAccount(e.target.value)}><option value="">Current Cartel account</option>{accounts.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}</select></label>
      <button className="ghost-btn" disabled={busy} onClick={() => void load()}>{busy ? 'Loading review…' : 'Load daily review'}</button></div>
    {error && <p role="alert">{error}</p>}
    {data && data.reviewScope === scope && <><h3>{data.account} · {data.session}</h3>
      <div className="cartel-row"><strong>Net realized {money(data.totals?.netRealized)}</strong><span>Gross {money(data.totals?.grossRealized)} · allocated fees {money(data.totals?.realizedFees)}</span></div>
      <p>{data.closedCampaigns} closed campaigns · {data.openInstruments} open instruments · {data.entryOrders} filled entry orders · {data.exitOrders} filled exit orders</p>
      <p className="muted">{data.note} Allocated fees include entry fees for lots closed today. Future exit fees are not included in open marks.</p>
      {data.issues.map((issue:string, i:number) => <p key={i} className="cartel-notice">{issue}</p>)}
      <div className="scroll-x"><table className="tbl"><thead><tr><th>Stock / plan</th><th>Outcome</th><th>Net realized</th><th>Remaining</th></tr></thead><tbody>
        {data.rows.map((r:any) => <tr key={r.planId}><td><CartelRunLink id={r.planId} onOpen={openRun}>{r.symbol}</CartelRunLink></td>
          <td>{r.category.replaceAll('_',' ')}{r.exitReasons?.length > 0 && <p>{r.exitReasons.map(exitLabel).join(' · ')}</p>}<details><summary>Decision evidence</summary>{r.decisions.map((d:any,i:number) => <p key={i}>{new Date(d.at).toLocaleTimeString()} · {d.reason}</p>)}<p>{r.recoveries?.length || 0} session recovery records</p></details></td>
          <td>{money(data.totals ? r.assets?.reduce((sum:number,a:any) => sum+a.netRealized,0) : null)}</td><td>{r.assets?.reduce((sum:number,a:any) => sum+a.remainingQty,0) || 0}</td></tr>)}
      </tbody></table></div>
      {!data.rows.length && <p>No armed campaign activity recorded for this session.</p>}
      {!!data.openInstruments && <details><summary>Open holdings and recorded marks</summary>{data.assets.filter((a:any) => a.remainingQty > 0).map((a:any,i:number) => <p key={i}>{a.symbol} · {a.remainingQty} units · open result {money(data.totals ? a.unrealizedNet : null)}{a.mark ? ` · bid ${a.mark.bid} · source ${new Date(a.mark.sourceAt).toLocaleString()}` : ' · no eligible mark at this cutoff'}</p>)}</details>}
      <details><summary>Preparation exclusions and pending plans · {data.candidates.length}</summary>{data.candidates.map((c:any,i:number) => <p key={i}><strong>{c.symbol}</strong> · {c.status.replaceAll('_',' ')} · {c.reason || c.reasons?.join('; ')}{c.volumeCoverage && ` · ${c.volumeCoverage.available}/${c.volumeCoverage.expected} baseline buckets`}</p>)}</details>
      <details><summary>Selection and recovery attempts · {data.attempts.length} of {data.attemptCount ?? data.attempts.length}</summary>{data.attempts.map((a:any) => <p key={a.id}>{new Date(a.at).toLocaleString()} · {a.symbol} · {a.status} · {a.reason || a.selection?.diagnostics?.reason || ''}</p>)}{data.attemptCursor && <button className="ghost-btn" disabled={busy} onClick={() => void olderAttempts()}>Load older attempts</button>}</details>
      <p className="muted">{data.fillEvidence.length} fills with exact source evidence · {data.missingFillEvidence} legacy fills without it.</p>
      {!!data.fillWaits?.length && <details><summary>Simulated orders waiting for quotes · {data.fillWaits.length}</summary>{data.fillWaits.map((w:any,i:number) => <p key={i}>{new Date(w.at).toLocaleString()} · {w.reason} · {w.subsequentlyFilled ? 'Later filled' : 'No recorded fill by this cutoff'}</p>)}</details>}
      {coverage && <details><summary>Recorded option coverage</summary><p className="muted">{coverage.note}</p>{coverage.rows.map((r:any) => <p key={`${r.planId}:${r.contract}`}>{r.contract} · {r.eligible}/{r.observations} eligible observations · {r.gapCount} recording gaps over 15 seconds · largest {Math.round(r.maxGapMs/1000)}s</p>)}</details>}
    </>}
  </details>;
}
