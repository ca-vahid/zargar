import { useState } from "react";

export function CartelSweepControls({ runs, busy, onRun }: {
  runs: { runId: string; symbol: string; createdAt: string }[]; busy: boolean;
  onRun: (body: unknown) => Promise<void>;
}) {
  const [ids, setIds] = useState<string[]>([]);
  const [name, setName] = useState("Entry comparison");
  const [volume, setVolume] = useState(1.5);
  const [location, setLocation] = useState(.7);
  const [matrix, setMatrix] = useState(true);
  const [chase, setChase] = useState(.5);
  return <details><summary>Compare entry rules</summary>
    <p>Select campaign replays, one per original plan. Compare reviewed levels and exit schedules on identical saved history. This does not change or arm the plans.</p>
    <form className="cartel-form" onSubmit={e => { e.preventDefault(); void onRun({ replayIds: ids,
      variants: matrix ? [5,15].flatMap(tf => ["breakout","retest"].map(mode => ({name:`${tf}m ${mode}`, timeframeMinutes:tf, mode,
        volumeMultiple:volume, minCloseLocation:location, maxChaseR:chase}))) : [{ name, volumeMultiple: volume, minCloseLocation: location, maxChaseR: chase }] }); }}>
      {runs.length === 0 && <p>Run a campaign replay from a saved plan first.</p>}
      {runs.map(run => <label className="cartel-check" key={run.runId}>
        <input type="checkbox" checked={ids.includes(run.runId)} onChange={e => setIds(previous => e.target.checked ? [...previous, run.runId] : previous.filter(id => id !== run.runId))}/>
        {run.symbol} · {new Date(run.createdAt).toLocaleString()}
      </label>)}
      <label className="cartel-check"><input type="checkbox" checked={matrix} onChange={e=>setMatrix(e.target.checked)}/>Compare 5m / 15m breakout and retest variants</label>
      <p>Timeframe changes rebuild volume baselines from the plan's historical inputs. No variant is automatically promoted. Compare multiple sessions, including losses and missed trades.</p>
      <label>Variant name<input required maxLength={80} value={name} onChange={e => setName(e.target.value)}/></label>
      <label>Volume multiple<input type="number" required min={.01} max={100} step="any" value={volume} onChange={e => setVolume(Number(e.target.value))}/></label>
      <label>Minimum close location (0–1)<input type="number" required min={0} max={1} step="any" value={location} onChange={e => setLocation(Number(e.target.value))}/></label>
      <label>Maximum chase (R)<input type="number" required min={0} max={10} step="any" value={chase} onChange={e => setChase(Number(e.target.value))}/></label>
      <button className="ghost-btn" disabled={busy || ids.length === 0 || ids.length > 20}>Compare with original rules</button>
    </form>
  </details>;
}

export function CartelSweepResult({ result }: { result: any }) {
  return <section aria-label="Entry-rule comparison"><h3>Entry-rule comparison</h3>
    {result.summaries.map((s: any) => <p key={s.variant}><strong>{s.variant}</strong>: {s.cases} cases · {s.closedScored} closed and scored · {s.open} open · {s.incomplete} incomplete · mean closed R: {s.meanClosedR == null ? "Unavailable" : s.meanClosedR.toFixed(2)}</p>)}
    {result.summaries.filter((s: any) => s.variant !== "baseline").map((s: any) => <p key={`paired:${s.variant}`}>
      {s.variant} versus baseline: {s.pairedClosed ?? 0} cases closed and complete in both · mean difference: {s.pairedMeanDeltaR == null ? "Unavailable" : `${s.pairedMeanDeltaR.toFixed(2)} R`}
    </p>)}
    <p>The paired comparison excludes cases that did not close in both versions. It does not measure missed opportunities or portfolio returns.</p>
    <details><summary>Inspect each case</summary><ul>{result.rows.map((row: any) => <li key={`${row.replayId}:${row.variant}`}>
      {row.symbol} · {row.variant} · baseline coverage {row.baselineCoverage ? `${row.baselineCoverage.available}/${row.baselineCoverage.expected}` : "not recorded"} · {row.result.status.replaceAll("_", " ")} · realized R: {row.result.realizedR == null ? "Unavailable" : row.result.realizedR.toFixed(2)}
    </li>)}</ul></details>
  </section>;
}
