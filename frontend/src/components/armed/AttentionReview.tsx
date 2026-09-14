import { useState } from 'react';
import type { ArmedPlan } from '../../types';
import { useWorkspace, workspaceOf } from '../../lib/workspace';
import { useTechniques } from '../../lib/techniques';
import { attentionSummary } from '../../lib/armedAttention';
import { ArmedCard } from '../technique/ArmedTab';
import { AttentionDetails } from './AttentionDetails';
import { SymIcon } from '../SymIcon';
import { Spinner } from '../ui';

export function AttentionReview({plans, refresh, error, loading}: {plans: ArmedPlan[]; refresh: () => void; error: string; loading: boolean}) {
  const workspace = useWorkspace(), registry = useTechniques();
  const [selected,setSelected] = useState<string | null>(null);
  const ordered = plans.slice().sort((a,b) => Number(attentionSummary(a).notice)-Number(attentionSummary(b).notice) || a.symbol.localeCompare(b.symbol) || a.runId.localeCompare(b.runId));
  return <section className="armed-review-list" aria-label="Plans needing review">
    <div className="panel panel-body"><h2>{plans.length} {plans.length === 1 ? 'plan' : 'plans'} to review</h2>
      <p>Only flagged plans are shown, across Practice and Live. Each card is one plan; it may contain several setup messages. Viewing this list does not change your trading workspace.</p>
      {error && <p role="alert">Could not refresh plans: {error}. Showing the last available data. <button className="link-btn" onClick={refresh}>Retry</button></p>}
      {loading && !plans.length ? <Spinner label="Loading flagged plans…"/> : !plans.length && <p>{error ? 'Current review status is unavailable.' : 'No flagged plans in the available data.'}</p>}
    </div>
    {ordered.map(a => {const known = ['live','paper','sim','shadow'].includes(a.portfolio?.kind || ''); const same = known && workspaceOf(a.portfolio?.kind) === workspace;return <article className="panel" key={a.runId} aria-label={`${a.symbol} attention plan`}>
      <div className="panel-head armed-review-identity"><h3><SymIcon sym={a.symbol} size={22}/>{a.symbol}</h3>
        <span>{registry.find(t=>t.id === (a.technique || 'enhanced_market'))?.label || (a.technique || 'EM').replaceAll('_',' ')}</span>
        <span>{a.portfolio?.name || 'Account unavailable'} · {known ? workspaceOf(a.portfolio?.kind) === 'live' ? 'Live' : 'Practice' : 'Workspace unavailable'}</span>
        <span className="muted">For {a.planFor}</span>
      </div>
      <div className="panel-body"><AttentionDetails plan={a}/>
        {same ? <><button className="ghost-btn" aria-expanded={selected === a.runId} onClick={()=>setSelected(selected === a.runId ? null : a.runId)}>{selected === a.runId ? 'Hide' : 'Review'} {a.symbol} plan and orders</button>
          {selected === a.runId && <ArmedCard a={a} onChanged={refresh}/>}</>
          : <p>{known ? `Switch to ${workspaceOf(a.portfolio?.kind) === 'live' ? 'Live' : 'Practice'} using the workspace selector to access this plan’s trading controls.` : 'Account details are unavailable. Refresh before accessing trading controls.'}</p>}
      </div>
    </article>;})}
  </section>;
}
