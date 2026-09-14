import { useState } from 'react';
import { api } from '../lib/api';
import { ErrorState } from '../components/ui';
import { useWorkspace } from '../lib/workspace';

export function CartelExecutionLimitReview({runId, active}: {runId: string; active: any}) {
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const workspace = useWorkspace();
  const spec = active?.executionSettings;
  if (!active?.preparation?.runId || active.preparation.workspace !== 'practice' || !spec ||
    active.config?.mode !== 'auto' || active.portfolio?.kind !== 'sim' || workspace !== 'practice') return null;
  if (spec.contractPolicy) return <p className="muted">Entry contract limits are saved and checked again before submission, including the bid/ask spread.</p>;
  const review = async () => {
    setBusy(true); setError('');
    try { await api.post(`/api/options-cartel/armed/${encodeURIComponent(runId)}/review-limits`, {}); setDone(true); }
    catch (e) { setError(String(e)); } finally { setBusy(false); }
  };
  return <div className="cartel-notice">
    <p>{done ? 'Execution limits reviewed. Refresh the record to see the saved policy.' : 'This older automatic arm needs its contract limits reviewed before it can enter. Its contract, chart targets and exit policy stay saved as reviewed.'}</p>
    {!done && <button className="ghost-btn" disabled={busy || active.status !== 'armed' || active.phase !== 'waiting' || active.submissionReserved || !!active.trades?.length} onClick={review}>{busy ? 'Reviewing…' : 'Review entry contract limits'}</button>}
    {error && <ErrorState message={error}/>}
  </div>;
}
