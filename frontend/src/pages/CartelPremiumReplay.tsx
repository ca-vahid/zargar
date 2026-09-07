import { useState } from 'react';

export function CartelPremiumReplayControls({busy, onValue}: {
  busy: boolean; onValue: (request: unknown, stored?: boolean) => Promise<void>;
}) {
  const [contract, setContract] = useState('');
  const [source, setSource] = useState('');
  const [rows, setRows] = useState('');
  const [fee, setFee] = useState(0);
  const [age, setAge] = useState(15);
  const [error, setError] = useState('');
  const utc = (raw: string) => {
    const text = raw.trim(), value = Date.parse(text);
    const canonical = text.includes('.') ? text : text.replace('Z', '.000Z');
    if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{3})?Z$/.test(text) ||
      !Number.isFinite(value) || new Date(value).toISOString() !== canonical) throw Error('Use valid UTC timestamps such as 2026-05-05T13:40:00Z.');
    return value;
  };
  return <details><summary>Value with recorded option quotes</summary>
    <p>Use the saved underlying fill schedule with recorded ask entries and bid exits. This saves a separate valuation and places no orders.</p>
    <p>Paste six tab-separated columns without a header: source UTC time, available UTC time, bid, ask, delayed, halted (both true or false). Availability means when the quote was available to the strategy, not when you downloaded its history.</p>
    <p>Quotes must match the selected contract. Use standard US contracts and USD quotes/fees. Missing evidence stays unscorable; order depth, expiry settlement and premium-triggered exits are not modeled.</p>
    {error && <p role="alert" className="cartel-error">{error}</p>}
    <form className="cartel-form" onSubmit={async e => {
      e.preventDefault(); setError('');
      try {
        const quotes = rows.split(/\r?\n/).filter(line => line.trim()).map((line, index) => {
          const cells = line.split('\t').map(s => s.trim());
          if (cells.length !== 6 || !/^(true|false)$/.test(cells[4]) || !/^(true|false)$/.test(cells[5]) ||
            !cells[2] || !cells[3] || !Number.isFinite(Number(cells[2])) || !Number.isFinite(Number(cells[3]))) {
            throw Error(`Row ${index+1}: expected two UTC times, bid, ask and true/false delayed and halted flags.`);
          }
          return {sourceAt:utc(cells[0]), availableAt:utc(cells[1]), bid:Number(cells[2]), ask:Number(cells[3]), delayed:cells[4] === 'true', halted:cells[5] === 'true'};
        });
        if (!quotes.length || quotes.length > 40000 || !source.trim()) throw Error('Supply a source and 1–40,000 quotes.');
        await onValue({contractSymbol:contract.trim().toUpperCase(), source:source.trim(), quotes, feePerContract:fee, maxQuoteAgeMs:age*1000});
      } catch (e) { setError(String(e)); }
    }}>
      <label>Option contract<input required value={contract} onChange={e=>setContract(e.target.value)} placeholder="HOOD260515C00050000" maxLength={32}/></label>
      <label>Quote evidence source<input required value={source} onChange={e=>setSource(e.target.value)} placeholder="Provider, dataset and timestamp convention"/></label>
      <label>Fee per contract per fill (USD)<input required type="number" min={0} max={100} step="any" value={fee} onChange={e=>setFee(Number(e.target.value))}/></label>
      <label>Maximum quote age (seconds)<input required type="number" min={0} max={60} step={1} value={age} onChange={e=>setAge(Number(e.target.value))}/></label>
      <button type="button" disabled={busy || !contract.trim()} onClick={async()=>{
        setError('');
        try { await onValue({contractSymbol:contract.trim().toUpperCase(), feePerContract:fee, maxQuoteAgeMs:age*1000}, true); }
        catch(e) { setError(String(e)); }
      }}>Use stored plan quotes</button>
      <p>Stored observations come only from this replay’s parent plan and contract. Missing observations produce an incomplete valuation; they are not borrowed from another plan.</p>
      <label>Recorded quote rows<textarea required rows={7} value={rows} onChange={e=>setRows(e.target.value)}/></label>
      <button disabled={busy}>Save option valuation</button>
    </form>
  </details>;
}

export function CartelPremiumReplayResult({result}: {result:any}) {
  const money = (v:unknown) => typeof v === 'number' && Number.isFinite(v) ? `$${v.toFixed(2)}` : 'Unavailable';
  return <section aria-label="Option replay valuation"><h3>Option valuation · {result.status}</h3>
    <p>{result.contractSymbol} · recorded-quote valuation of the saved underlying schedule</p>
    <p>Realized: {money(result.realizedPnl)} · Open: {money(result.openPnl)} · Total: {money(result.totalPnl)}</p>
    <p>Fees paid: {money(result.fees)} · Return on initial debit: {result.returnOnDebitPct == null ? 'Unavailable' : `${result.returnOnDebitPct.toFixed(2)}%`}</p>
    <p>These modeled values do not establish achievable brokerage fills. Incomplete evidence produces no total return.</p>
    <ol>{result.fills.map((f:any,i:number)=><li key={i}>{new Date(f.at).toISOString()} · {f.kind} · {f.qty} contracts at {money(f.premium)} · fee {money(f.fee)}</li>)}</ol>
  </section>;
}
