import { useState } from "react";
import { api } from "../lib/api";

function percent(raw: string): number | null {
  const value = raw.trim().replace('−', '-').replace(/%$/, '');
  if (!value || /^(?:—|-|n\/a)$/i.test(value)) return null;
  if (!/^[+-]?(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+)$/.test(value)) throw Error(`Invalid percentage: ${raw}`);
  return Number(value.replaceAll(',', ''));
}

export function CartelIndustryControls({ snapshots, selectedId, onSelect, onImported }: {
  snapshots: {runId: string; asOfMs: number; createdAt: string}[];
  selectedId: string; onSelect: (id: string) => void; onImported: (run: any) => Promise<void>;
}) {
  const [source, setSource] = useState('');
  const [observed, setObserved] = useState(() => new Date().toISOString().slice(0,16));
  const [dataAt, setDataAt] = useState('');
  const [count, setCount] = useState('');
  const [week, setWeek] = useState('Provider 1W performance');
  const [month, setMonth] = useState('Provider 1M performance');
  const [table, setTable] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  return <section className="cartel-card" aria-label="Industry evidence">
    <h2>Industry evidence</h2>
    <label>Recent industry snapshot<select value={selectedId} onChange={e => onSelect(e.target.value)}>
      <option value="">Use manually entered ranks</option>
      {snapshots.map(s => <option key={s.runId} value={s.runId}>{new Date(s.asOfMs).toLocaleString()} · {s.runId.slice(-6)}</option>)}
    </select></label>
    <p>A selected snapshot supplies ranks for the industry entered below. Stock capitalization and industry mapping still need their own sourced evidence. Up to 200 recent captures are listed.</p>
    <details><summary>Import an industry capture</summary>
      <p>Paste three tab-separated columns: industry name, 1W percentage, 1M percentage. One industry per line, without a header. Leave unavailable values blank; include every industry shown by the source.</p>
      {error && <p role="alert" className="cartel-error">{error}</p>}
      <form className="cartel-plan-form" onSubmit={async event => {
        event.preventDefault(); setError(''); setBusy(true);
        try {
          const rows = table.split(/\r?\n/).filter(line => line.trim()).map((line, index) => {
            const cells = line.split('\t');
            if (cells.length !== 3) throw Error(`Row ${index+1} must have exactly three tab-separated cells.`);
            return {industry:cells[0].trim(), weekPct:percent(cells[1]), monthPct:percent(cells[2])};
          });
          if (rows.length !== Number(count)) throw Error(`Expected ${count} industries; found ${rows.length}.`);
          const saved = await api.post('/api/options-cartel/industry-snapshots', {source,
            observedAt:Date.parse(observed+'Z'), dataAsOfMs:dataAt ? Date.parse(dataAt+'Z') : null, expectedCount:Number(count),
            weekDefinition:week, monthDefinition:month, rows});
          await onImported(saved);
        } catch (e) { setError(String(e)); } finally { setBusy(false); }
      }}>
        <label>Capture source<input required value={source} onChange={e => setSource(e.target.value)} placeholder="Source URL and capture description"/></label>
        <label>Observed at (UTC)<input required type="datetime-local" value={observed} onChange={e => setObserved(e.target.value)}/></label>
        <label>Source data as of (UTC; blank if unknown)<input type="datetime-local" value={dataAt} onChange={e => setDataAt(e.target.value)}/></label>
        <p>Without a source-data timestamp, freshness remains unknown and the capture cannot qualify a stock.</p>
        <label>Expected industry count<input required type="number" min={1} max={500} value={count} onChange={e => setCount(e.target.value)}/></label>
        <label>Weekly period definition<input required value={week} onChange={e => setWeek(e.target.value)}/></label>
        <label>Monthly period definition<input required value={month} onChange={e => setMonth(e.target.value)}/></label>
        <label>Industry performance rows<textarea required rows={7} value={table} onChange={e => setTable(e.target.value)} placeholder={'Semiconductors\t5.2%\t10.1%'}/></label>
        <button disabled={busy}>{busy ? 'Importing…' : 'Import capture for review'}</button>
      </form>
    </details>
  </section>;
}

export function CartelIndustryResult({ result }: { result: any }) {
  const [direction, setDirection] = useState('bullish');
  const [period, setPeriod] = useState('weekPct');
  const ordered = [...result.rows].sort((a:any,b:any) => {
    const tie = a.industry.localeCompare(b.industry);
    if (a[period] == null) return b[period] == null ? tie : 1;
    if (b[period] == null) return -1;
    return (direction === 'bullish' ? -1 : 1)*(a[period]-b[period]) || tie;
  });
  const rank = (value: any) => value ? value.best === value.worst ? String(value.best) : `${value.best}–${value.worst}` : 'Unknown';
  return <section aria-label="Industry capture results"><h3>{result.count} captured industries</h3>
    <p>Source data time: {result.rows[0]?.bullish?.dataAsOfMs == null ?
      result.rows[0]?.bullish?.freshnessBasis === 'publisher_observation'
        ? 'Constituent time unknown. This publisher snapshot uses its receipt time for context freshness, for at most 24 hours.'
        : 'Unknown; freshness cannot be established.' : new Date(result.rows[0].bullish.dataAsOfMs).toLocaleString()}</p>
    <p>Captured ranks describe only these saved values, including ties and missing-value uncertainty. They do not establish freshness. Trade eligibility is checked separately at the analysis cutoff.</p>
    <label>Rank direction<select value={direction} onChange={e => setDirection(e.target.value)}><option value="bullish">Bullish</option><option value="bearish">Bearish</option></select></label>
    <label>Sort captured values<select value={period} onChange={e=>setPeriod(e.target.value)}><option value="weekPct">Weekly performance</option><option value="monthPct">Monthly performance</option></select></label>
    <div className="md-table-wrap"><table className="md-table"><thead><tr><th>Industry</th><th>1W %</th><th>1M %</th><th>Captured 1W rank</th><th>Captured 1M rank</th><th>Eligible top ten</th></tr></thead>
      <tbody>{ordered.map((row: any) => <tr key={row.industry}><td>{row.industry}</td><td>{row.weekPct ?? 'Unknown'}</td><td>{row.monthPct ?? 'Unknown'}</td>
        <td>{rank(row.capturedRanks?.[direction]?.weekRank ?? row[direction]?.weekRank)}</td><td>{rank(row.capturedRanks?.[direction]?.monthRank ?? row[direction]?.monthRank)}</td><td>{row[direction]?.status ?? 'unknown'}</td></tr>)}</tbody>
    </table></div>
  </section>;
}
