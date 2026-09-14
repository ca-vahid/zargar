import type { ArmedPlan } from '../../types';
import { attentionSummary } from '../../lib/armedAttention';

export function AttentionDetails({plan}: {plan: ArmedPlan}) {
  const info = attentionSummary(plan);
  return <section className={`armed-attention-detail ${info.notice ? 'notice' : 'action'}`} aria-label={`${plan.symbol} review details`}>
    <h3>{info.title}</h3>
    <p>{info.next}</p>
    <ul>{info.items.map((item,i) => <li key={i}><strong>{item.setup}</strong><p>{item.reason}</p></li>)}</ul>
    <details><summary>Technical details</summary><p>Setup references identify entry conditions within this plan, not separate stocks.</p>
      <ul>{info.items.map((item,i) => <li key={i}>{item.raw}</li>)}</ul>
      <p>Plan reference: {plan.runId}</p>
    </details>
  </section>;
}
