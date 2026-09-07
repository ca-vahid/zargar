import { useState } from "react";

export function CartelReplayControls({ busy, onReplay }: {
  busy: boolean;
  onReplay: (request: { source: string; asOfMs: number; quantity: number; slippageBps: number }) => Promise<void>;
}) {
  const [source, setSource] = useState("stored");
  const [cutoff, setCutoff] = useState(() => new Date().toISOString().slice(0, 16));
  const [quantity, setQuantity] = useState(100);
  const [slippage, setSlippage] = useState(0);
  return <details><summary>Replay this campaign</summary>
    <p>Model the underlying price through partial exits and the remaining position. This creates a history record; it places no orders.</p>
    <p>Fills use the next minute’s open after a closed-bar decision. Option premiums, fees, expiry, resting limit fills and quote stops are not modeled.</p>
    <form className="cartel-form" onSubmit={event => {
      event.preventDefault();
      void onReplay({ source, asOfMs: Date.parse(cutoff + "Z"), quantity, slippageBps: slippage });
    }}>
      <label>History source<select value={source} onChange={e => setSource(e.target.value)}>
        <option value="stored">Stored bars (may be simulated)</option>
        <option value="provider">Historical provider</option>
      </select></label>
      <label>Replay through (UTC)<input type="datetime-local" required value={cutoff} onChange={e => setCutoff(e.target.value)}/></label>
      <label>Modeled units<input type="number" required min={1} max={1000000} step={1} value={quantity} onChange={e => setQuantity(Number(e.target.value))}/></label>
      <label>Slippage per fill (basis points)<input type="number" required min={0} max={100} step="any" value={slippage} onChange={e => setSlippage(Number(e.target.value))}/></label>
      <button className="ghost-btn" disabled={busy}>Run campaign replay</button>
    </form>
  </details>;
}

export function CartelReplayResult({ result }: { result: any }) {
  const r = (value: unknown) => typeof value === "number" && Number.isFinite(value) ? `${value.toFixed(2)} R` : "Unavailable";
  return <section aria-label="Campaign replay result">
    <h3>Campaign replay · {String(result.status).replaceAll("_", " ")}</h3>
    <p>Underlying-price simulation · {result.dataComplete ? "No detected tape gaps" : "Incomplete data — outcome is not fully scorable"}</p>
    <p>Realized: {r(result.realizedR)} · Remaining position: {r(result.openR)}</p>
    <p>R is measured against the modeled entry-to-stop risk of the original position. It is not an option-premium return. Fees, expiry, resting limit fills and quote stops are not modeled.</p>
    <ol>{result.fills.map((fill: any, index: number) => <li key={index}>
      {new Date(fill.at).toISOString()} · {String(fill.kind).replaceAll("_", " ")} · {fill.qty} units at {Number(fill.price).toFixed(4)}
    </li>)}</ol>
    {result.pending?.length > 0 && <p>{result.pending.length} exit decision(s) await a subsequent modeled fill.</p>}
  </section>;
}
