import { useState } from "react";

export function CartelScanControls({ busy, profile, direction, onScan, onCapture, captureErrors = {}, capturedSymbols = [] }: {
  capturedSymbols?: string[];
  captureErrors?: Record<string, string>;
  onCapture: (symbols: string[]) => Promise<void>;
  busy: boolean; profile: string; direction: string; onScan: (symbols: string[]) => Promise<void>;
}) {
  const [symbols, setSymbols] = useState("");
  const [error, setError] = useState('');
  const run = async (action: (symbols: string[]) => Promise<void>) => {
    setError('');
    const selected = symbols.split(/[\s,]+/).filter(Boolean).map(s => s.toUpperCase());
    if (!selected.length || selected.length > 20 || new Set(selected).size !== selected.length ||
      selected.some(s => !/^[A-Z][A-Z0-9.\-]{0,11}$/.test(s))) {
      setError('Enter 1 to 20 unique US equity symbols.'); return;
    }
    try { await action(selected); } catch (e) { setError(String(e)); }
  };
  return <form className="panel cartel-card" onSubmit={e => {
    e.preventDefault(); void run(onScan);
  }}><h2>Scan a focus list</h2>
    <p>Uses {profile.replaceAll("_", " ")} · {direction === "long" ? "bullish" : "bearish"}. Change these settings in Review a candidate below. Evidence entered there applies only to that symbol; other symbols need their own evidence. Scans do not arm plans.</p>
    <label>Symbols (up to 20)<textarea required value={symbols} onChange={e => setSymbols(e.target.value)} placeholder="MU, HOOD, CRCL"/></label>
    {error && <p role="alert" className="cartel-error">{error}</p>}
    <p>Capitalization captures selected this visit: {capturedSymbols.join(', ') || 'none'}. Only matching symbols use these captures; source timestamps are checked during analysis.</p>
    <button className="ghost-btn" type="button" disabled={busy || !symbols.trim()} onClick={() => void run(onCapture)}>Capture list capitalization</button>
    <p>Captures each listed symbol before scanning. Industry membership and performance evidence remain separate. Failed refreshes clear that symbol’s selected capitalization capture.</p>
    {Object.entries(captureErrors).map(([symbol, message]) => <p className="cartel-error" key={symbol}>{symbol}: {message}</p>)}
    <button className="ghost-btn" disabled={busy || !symbols.trim()}>Scan focus list</button>
  </form>;
}

export function CartelScanResult({ result, busy, onOpen }: { result: any; busy: boolean; onOpen: (id: string) => void }) {
  return <section aria-label="Focus-list scan results"><h3>Focus-list results</h3>
    <p>{result.summary.completed ?? result.rows.length} of {result.summary.requested} completed · {result.summary.qualified} with qualifying setups · {result.summary.dataErrors} data failures</p>
    {result.startupRecovery && <p>Recovered saved progress after interruption. No new market data was fetched; {result.startupRecovery.pending} symbols remain unresolved.</p>}
    <ul>{result.rows.map((row: any) => <li key={row.symbol}>
      <strong>{row.symbol}</strong> · {row.status.replaceAll("_", " ")}
      {row.reused && <span> · retained from earlier scan</span>}
      {row.error && <p>{row.error}</p>}
      {row.warnings?.map((warning: string) => <p key={warning}>{warning}</p>)}
      {row.runId && <button className="ghost-btn" disabled={busy} onClick={() => onOpen(row.runId)}>Review {row.symbol}</button>}
    </li>)}</ul>
  </section>;
}
