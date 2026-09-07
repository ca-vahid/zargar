const when = (value: unknown) => typeof value === 'number' && Number.isFinite(value) && value >= 0
  ? new Date(value).toISOString() : 'Unknown';

function SourceLink({value, label}: {value:unknown; label:string}) {
  if (typeof value !== 'string') return null;
  try {
    const url = new URL(value);
    if (url.protocol === 'https:' && url.hostname === 'www.tradingview.com') {
      return <a href={url.href} target="_blank" rel="noreferrer">{label}</a>;
    }
  } catch { /* Non-URL evidence remains plain text. */ }
  return <span>{value}</span>;
}

export function CartelEvidenceResult({mode, result}: {mode:'fundamentals'|'membership'; result:any}) {
  return <section aria-label="Saved stock evidence">
    <h3>{mode === 'fundamentals' ? 'Capitalization evidence' : 'Verified industry membership'}</h3>
    <p>Symbol: {result.symbol}{result.exchange ? ` · ${result.exchange}` : ''}</p>
    <p>Observed at: {when(result.observedAt)}</p>
    {mode === 'fundamentals' ? <>
      <p>Captured USD capitalization: {typeof result.marketCapUsd === 'number'
        ? result.marketCapUsd.toLocaleString(undefined, {style:'currency', currency:'USD', maximumFractionDigits:0}) : 'Unavailable'}</p>
      <p>Provider price timestamp: {when(result.providerPriceAt)} · Reported currency: {result.currency || 'Unknown'}</p>
      <p>Provider industry suggestion: {result.providerIndustry || 'Unavailable'} · Sector: {result.providerSector || 'Unavailable'}</p>
      <p>The provider’s industry suggestion does not verify membership in a TradingView industry. Screening checks the capture’s availability and data age at its decision time.</p>
    </> : <>
      <p>Industry: {result.industry} · Member row: {result.memberRowKey}</p>
      <p>{result.verification}</p>
      <p><SourceLink value={result.source} label="Stock classification source"/> · <SourceLink value={result.industryUrl} label="Industry membership source"/></p>
      <p>{result.warning}</p>
      <p>Membership does not establish weekly or monthly leadership; performance evidence is checked separately.</p>
    </>}
    <p>To use this evidence, select the matching symbol and saved capture in the desk’s evidence controls. Opening a history record does not change the selected scan evidence.</p>
  </section>;
}
