export function CartelLeaderContext({context, protocol}: {context: any; protocol: any}) {
  if (!context && !protocol) return null;
  return <details className="cartel-inset"><summary>Leadership and prospective evidence</summary>
    {protocol && <>
      <p>Research cohort: <code>{protocol.cohortId}</code>. {protocol.promotion}</p>
      <p>{protocol.valuation}</p>
    </>}
    {context && <>
      <p>{context.basis}</p>
      <p>{context.evaluated} of {context.discovered} listings have dated leader observations. Execution still follows the selected preparation rules.</p>
      <div className="scroll-x"><table className="tbl"><thead><tr><th>Industry</th><th>Coverage</th><th>Trend passes</th><th>Positive relative strength</th><th>Median strength</th><th>Observed leaders</th></tr></thead><tbody>
        {context.groups?.slice(0, 20).map((r: any) => <tr key={r.industry}>
          <td>{r.industry}</td><td>{r.evaluated} / {r.discovered}</td><td>{r.trendPassed} / {r.evaluated}</td>
          <td>{r.positiveRelativeStrength} / {r.strengthKnown}</td><td>{r.medianRelativeStrength == null ? 'Unknown' : `${r.medianRelativeStrength.toFixed(2)} pp`}{r.strengthKnown < 3 ? ' · unranked' : ''}</td>
          <td>{r.leaders?.join(', ') || 'No observations'}</td>
        </tr>)}
      </tbody></table></div>
      <p className="muted">Showing up to 20 groups. This is context for research, not a recommended trade list.</p>
    </>}
  </details>;
}
