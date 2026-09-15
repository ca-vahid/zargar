import {useEffect, useRef, useState} from 'react';
import {EmptyState, ErrorState, Spinner} from '../components/ui';
import {api} from '../lib/api';
import {useWorkspace} from '../lib/workspace';
import {CartelPremiumReplayResult} from './CartelPremiumReplay';

type Evidence = Record<string, unknown>;
type Candidate = {
  id:string; symbol:string; direction:string; cohort:'primary'|'bearish';
  baselineRank:number|null; leaderRank:number|null; status:string; reasons:string[];
  entry:Evidence|null; experiments:Evidence|null; gaps:string[];
  optionObservation?:Evidence|null;
  optionQuote?:Evidence|null;
  targetRoomProbe?:Evidence|null;
  entryComparison?:Evidence|null;
  campaignExperiments?:Evidence|null;
  sharesComparison?:Evidence|null;
};
type Research = {
  day:string; workspace:'practice'; researchOnly:true; placesOrders:false; enabled:boolean;
  status:string; asOfMs:number|null; contextId?:string|null; preparationId?:string|null;
  denominator:{discovered:number; evaluated:number; eligible:number; observed:number; boundedLimit:number;
    omitted:number; primaryEligible:number; bearishEligible:number; baselineReady:number};
  rankings:Record<string, Evidence>;
  candidates:Candidate[];
  bearish:{status:string; eligible:number; observed:number; rows:Candidate[]};
  experiments:Evidence[];
  gaps:{kind:string; count:number; reason:string}[];
  protocol?:Evidence;
};

const SETTING = 'techniques.options_cartel.profitability_research';
const human = (value:string) => value.replaceAll('_', ' ');
const number = (value:unknown, digits=2) => typeof value === 'number' && Number.isFinite(value)
  ? value.toLocaleString(undefined, {maximumFractionDigits:digits}) : 'Unavailable';
const time = (value:unknown) => typeof value === 'number' && Number.isFinite(value)
  ? `${new Date(value).toLocaleTimeString(undefined, {timeZone:'America/New_York', hour:'2-digit', minute:'2-digit'})} ET` : 'Not recorded';
const dateTime = (value:number) => `${new Date(value).toLocaleString(undefined, {timeZone:'America/New_York', year:'numeric', month:'short', day:'numeric', hour:'2-digit', minute:'2-digit'})} ET`;
const sessionToday = () => new Intl.DateTimeFormat('en-CA', {timeZone:'America/New_York', year:'numeric', month:'2-digit', day:'2-digit'}).format(new Date());
const record = (value:unknown):Evidence => value && typeof value === 'object' && !Array.isArray(value) ? value as Evidence : {};
const records = (value:unknown):Evidence[] => Array.isArray(value) ? value.map(record) : [];
const strings = (value:unknown):string[] => Array.isArray(value) ? value.filter((item):item is string => typeof item === 'string') : [];
const price = (value:unknown) => typeof value === 'number' && Number.isFinite(value) ? `$${number(value)}` : 'Unavailable';

function CandidateEvidence({candidate}:{candidate:Candidate}) {
  const entry = candidate.entry;
  const probe = record(candidate.targetRoomProbe);
  const probeSignal = Object.keys(record(probe.signal)).length ? record(probe.signal) : probe;
  return <details className="cartel-research-evidence"><summary>Study evidence for {candidate.symbol}</summary>
    {candidate.reasons?.map((reason, index) => <p key={index}>{reason}</p>)}
    {entry ? <div className="cartel-research-facts">
      <p><strong>Stock confirmation</strong> · {time(entry.at)}</p>
      <p>Reference {price(entry.referencePrice ?? entry.price)} · stop {price(entry.stop)}{typeof entry.risk === 'number' ? ` · risk distance ${number(entry.risk)}` : ''}</p>
      <p className="muted">A stock confirmation is a research observation. It is not an option fill or account profit.</p>
    </div> : <p>No qualifying stock confirmation recorded.</p>}
    {!entry && Object.keys(probe).length > 0 && <p><strong>Target-room diagnostic:</strong> {time(probeSignal.at)} · reference {price(probeSignal.referencePrice)}. This probe retains the target veto; it is not an eligible baseline entry.</p>}
    {!!candidate.gaps?.length && <ul className="cartel-research-gaps">{candidate.gaps.map((gap, index) => <li key={index}>{human(gap)}</li>)}</ul>}
    {candidate.entryComparison && <EntryComparison evidence={candidate.entryComparison}/>}
    {candidate.optionObservation && <QuoteEvidence observation={candidate.optionObservation} latest={candidate.optionQuote}/>}
    {candidate.experiments && <ExperimentEvidence evidence={candidate.experiments}/>}
    {candidate.campaignExperiments && <details><summary>Campaign-target challenger outcomes</summary>
      <p>Separate research entry policy. The original target levels and execution permission remain unchanged.</p>
      <ExperimentEvidence evidence={candidate.campaignExperiments}/>
    </details>}
    {candidate.sharesComparison && <SharesComparison evidence={candidate.sharesComparison}/>}
  </details>;
}

function EntryComparison({evidence}:{evidence:Evidence}) {
  const baseline = record(evidence.baseline), challenger = record(evidence.campaignAware);
  const levels = Array.isArray(evidence.originalTargets) ? evidence.originalTargets.map(price).join(', ') : 'Unavailable';
  return <div className="cartel-research-facts"><p><strong>Entry target comparison</strong></p>
    <p>Original targets retained: {levels}</p>
    <p>Baseline: {typeof baseline.status === 'string' ? human(baseline.status) : 'Not evaluated'}{record(baseline.signal).at ? ` at ${time(record(baseline.signal).at)}` : ''}.</p>
    <p>Campaign-target challenger: {typeof challenger.status === 'string' ? human(challenger.status) : 'Not evaluated'} · comparison target {price(challenger.comparisonTarget)}.</p>
    {typeof challenger.reason === 'string' && <p>{challenger.reason}</p>}
    <p className="muted">A target-only probe or challenger signal does not become a baseline trade.</p>
  </div>;
}

function QuoteEvidence({observation,latest}:{observation:Evidence; latest?:Evidence|null}) {
  const selected = record(observation.selected), funding = record(observation.funding);
  const quote = record(latest ?? observation.quote);
  return <div className="cartel-research-facts"><p><strong>Contract evidence:</strong> {typeof observation.status === 'string' ? human(observation.status) : 'Pending'}{typeof observation.reason === 'string' ? ` · ${observation.reason}` : ''}</p>
    {typeof selected.symbol === 'string' && <p>{selected.symbol} · observed {time(observation.observedAt)}{observation.timely === false ? ' · outside the confirmation window' : ''}</p>}
    {!!Object.keys(funding).length && <p>Estimated whole contracts: {number(funding.quantity,0)} · cash cap {price(funding.cashCapUsd)} USD. This is a funding estimate, not reserved capital.</p>}
    {!!Object.keys(quote).length && <p>Recorded quote: {typeof quote.status === 'string' ? human(quote.status) : 'Unavailable'} · bid {price(quote.bid)} / ask {price(quote.ask)} · {typeof quote.source === 'string' ? quote.source : 'source unknown'} · source time {time(quote.sourceAt)}.{typeof quote.reason === 'string' ? ` ${quote.reason}` : ''}</p>}
    {strings(observation.selectionErrors).map((reason,index) => <p key={index}>{reason}</p>)}
    {observation.affordabilityOnly === true && <p>Only affordability prevented selection among the inspected contracts. This is not proof that the entire chain was exhausted.</p>}
  </div>;
}

function SharesComparison({evidence}:{evidence:Evidence}) {
  const shares = record(evidence.shares), skip = record(evidence.skip);
  return <details><summary>Ordinary shares versus cash</summary>
    <p>{typeof evidence.status === 'string' ? human(evidence.status) : 'Pending'}{typeof evidence.reason === 'string' ? ` · ${evidence.reason}` : ''}</p>
    <p>Cash comparator: {price(skip.netPnl)} scenario result · cash budget {price(skip.cashBudget)} USD.</p>
    {!!Object.keys(shares).length && <>
      <p>{number(shares.quantity,0)} unlevered shares · modeled debit {price(shares.investedCash)} · idle cash {price(shares.idleCash)} USD.</p>
      {Object.keys(record(shares.study)).length > 0 && <ExperimentEvidence evidence={record(shares.study)}/>}
    </>}
    <p className="muted">An affordability-only research comparison, not a substitute order or permission to buy shares.</p>
  </details>;
}

function ExperimentEvidence({evidence}:{evidence:Evidence}) {
  const entry = record(evidence.entry);
  const target = record(evidence.targetDiagnostic);
  const nearest = record(target.nearestTarget);
  const firstExit = record(target.firstExecutableExit);
  const campaignTarget = record(target.campaignTarget);
  const variants = records(evidence.variants);
  const quantityBasis = typeof entry.quantityBasis === 'string' ? human(entry.quantityBasis) : record(entry.quantityBasis).note;
  const targetVerdict = (value:unknown) => value === true ? 'passes' : value === false ? 'does not pass' : 'not established';
  const proxy = (value:unknown) => entry.instrument === 'shares' ? `${price(value)} share scenario` : `${number(value)} proxy units`;
  return <>
    {typeof evidence.note === 'string' && <p>{evidence.note}</p>}
    {typeof evidence.status === 'string' && <p>Study status: {human(evidence.status)}</p>}
    <p>Modeled quantity: {number(entry.quantity,0)}{typeof quantityBasis === 'string' ? ` · ${quantityBasis}` : ''}. {typeof entry.instrument === 'string' ? `Expression: ${human(entry.instrument)}.` : ''}</p>
    {!!Object.keys(target).length && <>
      <p><strong>Target study</strong> · Nearest target {price(nearest.price)} · {number(nearest.rewardR)}R · {targetVerdict(nearest.passes)}.</p>
      {!!Object.keys(firstExit).length && <p>First feasible exit: {typeof firstExit.kind === 'string' ? human(firstExit.kind) : 'Unavailable'} · {number(firstExit.quantity,0)} units{typeof firstExit.price === 'number' ? ` at ${price(firstExit.price)}` : ' · no fixed price target'}.</p>}
      {!!Object.keys(campaignTarget).length && <p>Campaign target {price(campaignTarget.price)} · {number(campaignTarget.rewardR)}R · {targetVerdict(campaignTarget.passes)}.{typeof campaignTarget.reason === 'string' ? ` ${campaignTarget.reason}` : ''}</p>}
    </>}
    {variants.length > 0 && <><p><strong>Same-entry policy comparisons</strong></p>
      <p className="muted">{entry.instrument === 'shares' ? 'Share scenarios below use the modeled unlevered share quantity.' : 'Proxy units are stock-price changes multiplied by the modeled exit quantity, without the option multiplier. They are not dollars of option profit.'} These comparisons are separate from the actual account.</p>
      <div className="scroll-x"><table className="tbl cartel-research-variants"><thead><tr><th scope="col">Policy</th><th scope="col">Observed path</th><th scope="col">Underlying proxy</th></tr></thead><tbody>
        {variants.map((variant,index) => {
          const exit = record(variant.firstExit);
          const option = record(variant.optionValuation);
          return <tr key={typeof variant.id === 'string' ? variant.id : index}>
            <td>{typeof variant.label === 'string' ? variant.label : typeof variant.id === 'string' ? human(variant.id) : 'Policy comparison'}</td>
            <td>{typeof variant.status === 'string' ? human(variant.status) : 'Pending'}{variant.dataComplete === false && <p>Incomplete data; comparison is provisional.</p>}
              {!!Object.keys(exit).length && <p>First exit {time(exit.at)} · {typeof exit.kind === 'string' ? human(exit.kind) : 'Recorded exit'} · {number(exit.qty,0)} units at {price(exit.price)}</p>}
              {strings(variant.warnings).map((warning,i) => <p key={i}>{warning}</p>)}
            </td>
            <td>Gross: {typeof variant.grossUnderlyingPnl === 'number' ? proxy(variant.grossUnderlyingPnl) : 'Not priced'}
              <p>Net: {typeof variant.netUnderlyingPnl === 'number' ? proxy(variant.netUnderlyingPnl) : 'Not priced; complete costs required'}</p>
              <p>Remaining: {number(variant.remainingQty,0)} units</p>
              {!!Object.keys(option).length ? <details><summary>Recorded-quote option valuation</summary><CartelPremiumReplayResult result={option}/></details> : <p>Option outcome not priced.</p>}
            </td>
          </tr>;
        })}
      </tbody></table></div>
    </>}
    {strings(evidence.warnings).map((warning,index) => <p className="cartel-notice" key={index}>{warning}</p>)}
    {!variants.length && <p className="muted">No funded policy comparison is available. An unknown quantity or missing price evidence is not a zero-profit trade.</p>}
  </>;
}

export function CartelProfitabilityResearch({settings=false, onSettings}:{settings?:boolean; onSettings?:()=>void}) {
  const workspace = useWorkspace();
  const [day, setDay] = useState(sessionToday);
  const [revision, setRevision] = useState(0);
  const [data, setData] = useState<Research|null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [saved, setSaved] = useState(false);
  const [enabled, setEnabled] = useState(false);
  const [cohort, setCohort] = useState<'all'|'primary'|'bearish'>('all');
  const [ranking, setRanking] = useState<'baselineRank'|'leaderRank'>('baselineRank');
  const [limit, setLimit] = useState(10);
  const scope = `${workspace}:${day}`;
  const currentScope = useRef(scope); currentScope.current = scope;
  useEffect(() => {
    let active = true;
    setData(null); setError(''); setSaved(false); setLimit(10);
    if (workspace !== 'practice') {setLoading(false); return;}
    if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) {setLoading(false); return;}
    setLoading(true);
    void api.get<Research>(`/api/options-cartel/profitability-research?workspace=practice&day=${encodeURIComponent(day)}`)
      .then(result => {
        if (!active) return;
        if (result.workspace !== 'practice' || result.day !== day || result.researchOnly !== true || result.placesOrders !== false) {
          throw new Error('Research response does not match the selected Practice session.');
        }
        setData(result); setEnabled(result.enabled);
      })
      .catch((failure:unknown) => {if (active) setError(failure instanceof Error ? failure.message : 'Could not load profitability research.');})
      .finally(() => {if (active) setLoading(false);});
    return () => {active = false;};
  }, [workspace, day, revision]);

  async function save() {
    if (workspace !== 'practice' || !data || saving) return;
    const selectedScope = scope;
    setSaving(true); setError(''); setSaved(false);
    try {
      await api.patchSettings({[SETTING]: enabled});
      if (currentScope.current === selectedScope) {
        setData(previous => previous && {...previous, enabled}); setSaved(true);
      }
    } catch (failure) {
      if (currentScope.current === selectedScope) setError(failure instanceof Error ? failure.message : 'Could not save research collection setting.');
    } finally {setSaving(false);}
  }

  const rows = [...(data?.candidates ?? [])].filter(candidate => cohort === 'all' || candidate.cohort === cohort)
    .sort((a,b) => (a[ranking] ?? Infinity)-(b[ranking] ?? Infinity) || a.symbol.localeCompare(b.symbol));
  const counts = data?.denominator;
  return <section className="panel cartel-card cartel-research" aria-label={settings ? 'Profitability research settings' : 'Profitability research'}>
    <div className="panel-head"><h2>Profitability research{settings ? ' settings' : ''}</h2><span className="badge">Research only</span>
      {data && <span className="status-pill dim">{data.enabled ? human(data.status) : 'Collection off'}</span>}
    </div>
    <p>Compare candidate selection and trading policies using recorded evidence. This study does not place trades.</p>
    {workspace !== 'practice' ? <p className="cartel-notice">Available in Practice only. Switch workspace to view this research; Live trading permissions are unchanged.</p> : <>
      {!settings && <div className="cartel-research-controls">
        <label>Research session (ET)<input aria-label="Profitability research session" type="date" value={day} onChange={event => setDay(event.target.value)}/></label>
        <button className="ghost-btn" disabled={loading || !day} onClick={() => setRevision(value => value+1)}>{loading ? 'Loading research…' : 'Refresh profitability research'}</button>
        {onSettings && <button className="link-btn" onClick={onSettings}>Collection settings</button>}
      </div>}
      {error && <ErrorState message={error} onRetry={() => setRevision(value => value+1)}/>}
      {loading && <Spinner label="Loading profitability research…"/>}
      {!settings && !day && <p>Choose a session date to load research.</p>}
      {settings && data && <form className="cartel-form" onSubmit={event => {event.preventDefault(); void save();}}>
        <label className="cartel-check"><input type="checkbox" checked={enabled} disabled={saving} onChange={event => {setEnabled(event.target.checked); setSaved(false);}}/>Collect profitability research in Practice</label>
        <p>Records the bounded candidate pool, ranking alternatives, bearish research and policy comparisons. Saved observations remain available when collection is off.</p>
        <button className="ghost-btn" disabled={saving || enabled === data.enabled}>{saving ? 'Saving…' : 'Save research collection'}</button>
        {saved && <p role="status">Research collection setting saved.</p>}
        <p className="muted">View dated observations under Validation → Profitability research. This setting does not change entry rules, budgets or existing positions.</p>
      </form>}
      {!settings && data && <>
        <p className="muted">{data.day} · {data.asOfMs ? `Latest snapshot ${dateTime(data.asOfMs)}` : 'No observation time recorded'} · Actual trades and account P&L are in Plans → Daily review.</p>
        {!data.enabled && <p className="cartel-notice">Collection is off. Any results below are previously saved observations.</p>}
        {counts && <dl className="cartel-research-metrics">
          <div><dt>Daily histories</dt><dd>{number(counts.evaluated,0)} / {number(counts.discovered,0)}</dd></div>
          <div><dt>Eligible research candidates</dt><dd>{number(counts.eligible,0)}</dd></div>
          <div><dt>Candidates in latest observation</dt><dd>{number(counts.observed,0)} / cap {number(counts.boundedLimit,0)}</dd></div>
          <div><dt>Outside observation cap</dt><dd>{number(counts.omitted,0)}</dd></div>
        </dl>}
        {counts && <p>{number(counts.primaryEligible,0)} primary candidates · {number(counts.bearishEligible,0)} bearish candidates · {number(counts.baselineReady,0)} with supported baselines. Observations include waiting and unavailable-data results; they are not trade counts.</p>}
        {!data.candidates.length ? <EmptyState art={false}
          title={data.status === 'awaiting_preparation' ? 'No preparation recorded for this session' : !data.enabled ? 'No saved observations for this session' : 'Waiting for candidate observations'}
          hint="Preparation and scheduled research collection supply the study. A date with no qualifying candidates is a valid result; missing evidence is not a zero-profit trade."/> : <>
          <h3>Candidate pool and ranking alternatives</h3>
          <p>Compare the current structural-target-R order with the leader-first research order within each cohort. Changing this view does not change the execution shortlist.</p>
          {Object.entries(data.rankings).some(([,value]) => strings(value.baselineIds).length > 0) && <details><summary>Compare the two ranked shortlists</summary>
            {Object.entries(data.rankings).map(([name,value]) => {
              const names = new Map(records(value.candidates).map(item => [item.id, item.symbol]));
              const namesFor = (ids:unknown) => strings(ids).map(id => names.get(id)).filter(item => typeof item === 'string').join(', ') || 'No ranked candidates';
              return <div key={name}><p><strong>{name === 'bearish' ? 'Bearish cohort' : 'Primary cohort'}</strong></p>
                <p>Current target-R list: {namesFor(value.baselineIds)}</p><p>Leader-first list: {namesFor(value.leaderIds)}</p>
                <p>{strings(value.overlapIds).length} shared candidates. Both lists retain the same entry and evidence checks.</p>
              </div>;
            })}
          </details>}
          <div className="cartel-research-controls">
            <label>Cohort<select aria-label="Research candidate cohort" value={cohort} onChange={event => {setCohort(event.target.value as typeof cohort); setLimit(10);}}>
              <option value="all">All candidates</option><option value="primary">Primary cohort</option><option value="bearish">Bearish cohort</option>
            </select></label>
            <label>Display order<select aria-label="Research ranking order" value={ranking} onChange={event => setRanking(event.target.value as typeof ranking)}>
              <option value="baselineRank">Current target-R ranking</option><option value="leaderRank">Leader-first research ranking</option>
            </select></label>
          </div>
          <div className="scroll-x"><table className="tbl cartel-table cartel-research-table"><thead><tr>
            <th scope="col">Stock / direction</th><th scope="col">Current rank</th><th scope="col">Leader rank</th><th scope="col">Research observation</th>
          </tr></thead><tbody>{rows.slice(0,limit).map(candidate => <tr key={candidate.id}>
            <td><strong>{candidate.symbol}</strong><span className="cartel-research-subline">{candidate.direction === 'short' ? 'Bearish / puts' : 'Bullish'} · {candidate.cohort === 'bearish' ? 'Bearish cohort' : 'Primary cohort'}</span></td>
            <td>{candidate.baselineRank == null ? 'Unranked' : number(candidate.baselineRank,0)}</td><td>{candidate.leaderRank == null ? 'Unranked' : number(candidate.leaderRank,0)}</td>
            <td className="cartel-wrap"><strong>{human(candidate.status)}</strong><CandidateEvidence candidate={candidate}/></td>
          </tr>)}</tbody></table></div>
          {!rows.length && <p>No candidates in this cohort for the selected session.</p>}
          <div className="cartel-row"><p>Showing {Math.min(limit,rows.length)} of {rows.length} saved candidates in this view.</p>
            {limit < rows.length && <button className="ghost-btn" onClick={() => setLimit(rows.length)}>Show all observed candidates</button>}
          </div>
        </>}
        <div className="cartel-research-note"><h3>Bearish research</h3><p>{human(data.bearish.status)} · {number(data.bearish.observed,0)} observed / {number(data.bearish.eligible,0)} eligible.</p>
          <p>Studies weak stocks after confirmed bearish market context. A weak or mixed market does not automatically authorize a put entry.</p></div>
        <details className="cartel-research-protocol"><summary>Policy comparisons and evidence limits</summary>
          <h3>Selection</h3><p>Compare target-R-first and leader-first rankings over the same candidate pool, with equal execution eligibility and capital limits. A large chart target is not a predicted option return.</p>
          <h3>Targets and funded quantity</h3><p>Retain nearby resistance and inspect target room against the actual stop and the first exit a whole-contract position can make. One contract cannot take a fractional trim.</p>
          <h3>Failed-break containment</h3><p>Compare a predefined completed-bar failure rule with the existing campaign on the same entry cohort. Include profitable trends cut short as well as losses reduced.</p>
          {data.experiments?.length > 0 && <><h3>Frozen comparison rules</h3><ul className="cartel-research-gaps">{data.experiments.map((definition,index) => <li key={typeof definition.id === 'string' ? definition.id : index}>
            <strong>{typeof definition.label === 'string' ? definition.label : 'Research policy'}</strong>{typeof definition.rule === 'string' && <p>{definition.rule}</p>}
          </li>)}</ul></>}
          <p className="muted">Missing quotes, costs or source-qualified bars leave outcomes unpriced. Research observations are not fills, realized returns or proof that a policy is profitable.</p>
          {typeof data.protocol?.version === 'string' && <p className="muted">Study version: {data.protocol.version}</p>}
        </details>
        <h3>Data, quote and cost gaps</h3>
        {data.gaps.length ? <ul className="cartel-research-gaps">{data.gaps.map((gap,index) => <li key={`${gap.kind}:${index}`}><strong>{human(gap.kind)} · {number(gap.count,0)}</strong><p>{gap.reason}</p></li>)}</ul>
          : <p>No additional gap summaries recorded. This does not certify executable option outcomes.</p>}
      </>}
    </>}
  </section>;
}
