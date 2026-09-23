import { useCallback, useEffect, useState } from "react";
import { api } from "../../lib/api";
import { Spinner } from "../ui";

/** EM integrated review (2026-09-18): what the author said vs what we planned and why (source → plan → gate), the
 * order-free source candidates, first-sale R at the final quantity, realized / displayed / executable profit and the
 * effective policy + collection knobs. READ-ONLY: nothing here arms, orders or calls a model. Collapsed until opened. */
type Tab = "source" | "candidates" | "firstsale" | "profit" | "policy";
const TABS: [Tab, string][] = [["source", "Source → plan"], ["candidates", "Candidates"], ["firstsale", "First sale"], ["profit", "Profit capture"], ["policy", "Policy"]];

const etToday = () => new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York" }).format(new Date());
const hhmm = (v: any) => {
  if (!v) return "—";
  const d = typeof v === "number" ? new Date(v) : new Date(String(v).replace(" ", "T"));
  return isNaN(d.getTime()) ? "—" : new Intl.DateTimeFormat("en-GB", { timeZone: "America/New_York", hour: "2-digit", minute: "2-digit", hour12: false }).format(d);
};
const num = (v: any, d = 2) => (v === null || v === undefined || Number.isNaN(Number(v)) ? "unknown" : Number(v).toFixed(d));
const pillFor = (s: string) => (["aligned", "triggered", "eligible", "pass", "requalification_eligible"].includes(s) ? "ok"
  : ["refused", "fail", "invalidated", "opposite_direction", "conflict"].includes(s) ? "bad" : ["waiting", "expired"].includes(s) ? "dim" : "wait");
const words = (s: any) => String(s ?? "—").replace(/_/g, " ");

export function EmReviewPanel() {
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState<Tab>("source");
  const [date, setDate] = useState(etToday());
  const [data, setData] = useState<Record<string, any>>({});
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    setBusy(true); setErr(null);
    try {
      const d = tab === "source" ? await api.emSourceTable(date) : tab === "candidates" ? await api.emCandidates(date)
        : tab === "firstsale" ? await api.emFirstSale(date) : tab === "profit" ? { ...(await api.emProfitCapture(date)), modelCost: await api.emModelCost(date).catch(() => null) } : await api.emManifest();
      setData((prev) => ({ ...prev, [tab]: d }));
    } catch (e: any) { setErr(e.message ?? String(e)); } finally { setBusy(false); }
  }, [tab, date]);
  useEffect(() => { if (open) load(); }, [open, load]);

  const d = data[tab];
  return (
    <div className="panel mb tq-em-review">
      <div className="panel-head tq-form-head" role="button" tabIndex={0} onClick={() => setOpen((v) => !v)}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") setOpen((v) => !v); }}>
        <span className="tq-picker-caret">{open ? "▾" : "▸"}</span> Source, policy and profit review
        <span className="sub">what the author said vs what we planned and why · order-free candidates · first-sale R · realized / displayed / executable — read-only</span>
      </div>
      {open && <div className="panel-body">
        <div className="tabs" role="tablist" style={{ marginBottom: 8 }}>
          {TABS.map(([k, label]) => <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "active" : ""} onClick={() => setTab(k)}>{label}</button>)}
          {tab !== "policy" && <input type="date" value={date} onChange={(e) => setDate(e.target.value)} aria-label="Session date" style={{ marginLeft: "auto" }} />}
          <button className="ghost-btn" onClick={load} disabled={busy}>{busy ? <Spinner /> : "Refresh"}</button>
        </div>
        {err && <div className="sub" style={{ color: "var(--bad)" }}>{err}</div>}
        {!d && !err && <div className="sub">{busy ? "Loading…" : "Nothing loaded."}</div>}
        {d && tab === "source" && <SourceTable d={d} />}
        {d && tab === "candidates" && <Candidates d={d} />}
        {d && tab === "firstsale" && <FirstSale d={d} />}
        {d && tab === "profit" && <Profit d={d} />}
        {d && tab === "policy" && <Policy d={d} />}
      </div>}
    </div>
  );
}

function SourceTable({ d }: { d: any }) {
  const [openRow, setOpenRow] = useState<string | null>(null);
  if (!d.rows?.length) return <div className="sub">No source note with an extraction for {d.date}.</div>;
  return (<>
    <div className="sub" style={{ marginBottom: 6 }}>Author result: {d.authorResult}. Preparation policy: <b>{d.policy?.preparationPolicy}</b> ({d.policy?.preparationPolicyVersion}).</div>
    <div className="tq-table-wrap"><table className="tq-table tq-wf">
      <thead><tr><th>Author</th><th>Usable</th><th>Said</th><th>Symbol</th><th>Side</th><th>Level</th><th>Targets</th><th>Source</th><th>Our plan</th><th>Policy</th><th>Gate</th></tr></thead>
      <tbody>{d.rows.map((r: any) => {
        const sc = r.scenario, sup = sc.authorSupplied, app = sc.appDerived, id = sc.scenarioId;
        const best = (r.plans ?? []).find((p: any) => p.alignedTrigger) ?? (r.plans ?? [])[r.plans.length - 1];
        const lastGate = best?.gateEvents?.filter((e: any) => e.type !== "Armed").slice(-1)[0];
        return [
          <tr key={id} onClick={() => setOpenRow(openRow === id ? null : id)} style={{ cursor: "pointer" }}>
            <td>{r.author}{sc.stance === "preferred" ? " ★" : ""}</td><td>{hhmm(r.usableAt)}</td>
            <td title={sup.note ?? ""}>{sup.condition ?? "—"}</td>
            <td>{sc.symbol.resolved ?? <span title={sc.flags?.join("; ")}>{sup.symbolAsExtracted}?</span>}</td>
            <td>{sup.direction}{sc.pairId ? " ⑂" : ""}</td><td>{app.level ?? "unknown"}</td>
            <td title={sup.optionMentions?.map((o: any) => o.raw).join(", ")}>{app.underlyingTargets?.length ? app.underlyingTargets.join(" / ") : "unknown"}</td>
            <td><span className={`status-pill ${sc.disposition === "candidate_source" ? "ok" : "wait"}`} title={(sc.heldReasons ?? sc.flags ?? []).join("; ")}>{sc.disposition === "candidate_source" ? sc.symbol.status : words(sc.symbol.status !== "resolved" ? sc.symbol.status : "held")}</span></td>
            <td>{best ? <span className={`status-pill ${pillFor(best.overall)}`}>{words(best.overall)}</span> : <span className="sub">no plan</span>}</td>
            <td>{best ? `${words(best.prepDecision.disposition)} (${best.prepDecision.modelReview})` : "—"}</td>
            <td>{lastGate ? `${lastGate.trigger ?? ""} ${words(lastGate.reason ?? lastGate.type)} ${hhmm(lastGate.ts)}` : "—"}</td>
          </tr>,
          openRow === id && <tr key={id + "-x"}><td colSpan={11}>
            <div className="sub">Evidence: {(sc.evidence ?? []).map((e: any) => `${e.offsetSeconds != null ? `[${Math.floor(e.offsetSeconds / 60)}:${String(e.offsetSeconds % 60).padStart(2, "0")}] ` : ""}${e.quote}`).join(" · ") || "not located"}</div>
            {(sc.flags ?? []).length > 0 && <div className="sub">Flags: {sc.flags.join("; ")}</div>}
            {(r.plans ?? []).map((p: any) => <div key={p.runId} className="sub">Plan {p.runId.slice(0, 8)} ({p.origin}{p.causal === false ? ", built BEFORE the source was usable" : ""}): {p.triggers.map((t: any) =>
              `${t.trigger} ${t.kind} @ ${t.level}${t.valid ? "" : " ✕"} → ${words(t.verdict)}`).join(" · ")}</div>)}
          </td></tr>,
        ];
      })}</tbody>
    </table></div>
    {d.avoid?.length > 0 && <div className="sub" style={{ marginTop: 6 }}>Author passed on: {d.avoid.map((a: any) => `${a.symbol} (${words(a.status)})`).join(", ")}</div>}
  </>);
}

function Candidates({ d }: { d: any }) {
  if (!d.rows?.length) return <div className="sub">No source candidates for {d.date}.</div>;
  return (<>
    <div className="sub" style={{ marginBottom: 6 }}>Order-free research: a candidate never arms or orders. Source: {words(d.source)}.</div>
    <div className="tq-table-wrap"><table className="tq-table tq-wf">
      <thead><tr><th>Author</th><th>Variant</th><th>Symbol</th><th>Side</th><th>Condition</th><th>Entry</th><th>Stop</th><th>Targets</th><th>Disposition</th><th>Why</th><th>Underlying proxy</th><th>Executable pricing</th><th>Baseline</th></tr></thead>
      <tbody>{d.rows.map((c: any) => <tr key={c.candidateId}>
        <td>{c.author ?? "—"}</td><td>{words(c.variant)}</td><td>{c.symbol ?? "unresolved"}</td><td>{c.direction}</td><td>{c.condition ?? "—"}</td>
        <td>{c.entry ?? "unknown"}</td><td>{c.stop ?? "unknown"}</td><td>{c.targets?.length ? c.targets.join(" / ") : "unknown"}</td>
        <td><span className={`status-pill ${pillFor(c.disposition)}`}>{words(c.disposition)}</span>{c.firedTs ? ` ${hhmm(c.firedTs)}` : ""}</td>
        <td title={c.reason ?? ""}>{(c.reason ?? "").slice(0, 70)}</td>
        <td>{c.outcomeProxy ? `${c.outcomeProxy} ${num(c.rProxy)}R (proxy)` : "—"}</td>
        <td title={c.pricing ? Object.entries(c.pricing.gates ?? {}).map(([k, v]) => `${k}: ${v}`).join(" · ") : ""}>{c.pricing ? <><span className={`status-pill ${c.pricing.overall === "feasible" && c.pricing.completeness === "complete" ? "ok" : c.pricing.overall === "infeasible" ? "bad" : "wait"}`}>{c.pricing.overall === "unknown" && c.pricing.completeness === "partial" ? "partial" : c.pricing.overall}</span>{(c.pricing.missing ?? []).length > 0 && <span className="sub"> unknown: {c.pricing.missing.join(", ")}</span>}</> : "—"}</td>
        <td>{(c.baseline ?? []).map((b: any) => `${b.trigger} ${words(b.status)}`).join(", ") || "—"}</td>
      </tr>)}</tbody>
    </table></div>
  </>);
}

function FirstSale({ d }: { d: any }) {
  return (<>
    <div className="sub" style={{ marginBottom: 6 }}>R2 to the gate target of the FINAL quantity, from the worse of our entry and the validated live underlying bound (unrounded). Mode: <b>{d.mode}</b>. Off records nothing; observe records and never refuses; enforce refuses below the minimum and defers when evidence is missing.</div>
    {!d.rows?.length ? <div className="sub">No first-sale record for {d.date} (the record is off by default).</div> :
      <div className="tq-table-wrap"><table className="tq-table tq-wf">
        <thead><tr><th>Time</th><th>Stage</th><th>Symbol</th><th>Trigger</th><th>Vehicle</th><th>Qty</th><th>Gate target</th><th>First production sale</th><th>Admission price</th><th>R at admission</th><th>R at our entry</th><th>Min</th><th>Verdict</th><th>Disposition</th><th>Plan time measured</th></tr></thead>
        <tbody>{d.rows.map((r: any, i: number) => <tr key={i}>
          <td>{hhmm(r.ts)}</td><td>{r.stage ?? "order"}</td><td>{r.symbol}</td><td>{r.trigger}</td><td>{r.instrument}</td><td>{r.quantity ?? "unknown"}</td><td>{r.rung}</td><td>{r.firstProductionSale ?? "—"}</td>
          <td title={(r.missingEvidence ?? []).join("; ")}>{r.admissionEntry != null ? `${r.admissionEntry} (${r.boundBasis ?? "entry"})` : "unknown"}</td>
          <td>{num(r.rAdmission, 3)}</td><td>{num(r.rRunnerEntry, 3)}</td><td>{r.min}</td>
          <td><span className={`status-pill ${pillFor(r.verdict)}`}>{r.verdict}</span></td><td>{words(r.disposition)}</td>
          <td>{r.planTime ? `TP${(r.planTime.targetIndex ?? 0) + 1}: ${r.planTime.rr}R${r.differsFromPlanTime ? " (different rung)" : ""}` : "—"}</td>
        </tr>)}</tbody>
      </table></div>}
  </>);
}

function Profit({ d }: { d: any }) {
  const c = d.capture ?? {}, e = d.execution ?? {};
  return (<>
    <div className="sub" style={{ marginBottom: 6 }}>{d.note} Recorder: <b>{d.recorderOn ? "on" : "off"}</b>.</div>
    <div className="tq-table-wrap"><table className="tq-table tq-wf tq-stat"><tbody>
      {c.status === "error_mixed_scope" && <tr><td colSpan={3} style={{ color: "var(--bad)" }}>Snapshots of more than one book or session were found — nothing is reduced.</td></tr>}
      <tr><td>Realized (execution ledger, after commissions)</td><td>{e.complete === false ? "unknown" : num(e.net, 4)}</td><td>{e.fills ?? 0} fills · fees {e.complete === false ? "unknown" : num(e.fees)}{e.openAtCutoff?.length ? ` · open: ${e.openAtCutoff.join(", ")}` : ""}{e.unknownInstrument?.length ? ` · instrument identity unknown: ${e.unknownInstrument.length}` : ""}</td></tr>
      <tr><td>Peak displayed net (marks)</td><td>{c.peakDisplayedNet ? num(c.peakDisplayedNet.value) : "unknown"}</td><td>{c.peakDisplayedNet ? `${hhmm(c.peakDisplayedNet.at)} · a mark, not a price anyone paid` : "no capture"}</td></tr>
      <tr><td>Peak executable net (covered, scorable only)</td><td>{c.peakExecutableNet ? num(c.peakExecutableNet.value) : "unknown"}</td><td>{c.peakExecutableNet ? `${hhmm(c.peakExecutableNet.at)} · hypothetical liquidation estimate — no sale occurred` : "no scorable snapshot"}</td></tr>
      <tr><td>Giveback vs the executable peak</td><td>{c.givebackVsExecutablePeak != null ? num(c.givebackVsExecutablePeak) : "unknown"}</td><td>hypothetical estimate, not a fill</td></tr>
      <tr><td>Coverage</td><td>{c.coverage ? `${c.coverage.scorable}/${c.snapshots}` : "0"}</td><td>{c.coverage ? `recorder starts ${c.coverage.recorderInstances ?? 1} · drops ${c.coverage.recorderDrops} · gaps ${c.coverage.gaps.length} · revised by late fills ${(c.coverage.revisedByLateExecutions ?? []).length} · ${Object.entries(c.coverage.unscorableReasons ?? {}).map(([k, v]) => `${words(k)} ${v}`).join(", ") || "all scorable"}` : words(c.status)}</td></tr>
      <tr><td>Reconciliation to fills</td><td><span className={`status-pill ${c.reconciliation?.status === "ok" ? "ok" : String(c.reconciliation?.status ?? "").startsWith("error") ? "bad" : "wait"}`}>{words(c.reconciliation?.status ?? "not reconciled")}</span></td><td>{c.reconciliation?.difference != null ? `difference ${num(c.reconciliation.difference, 4)}` : ""}{(c.reconciliation?.comparisonsUnavailable ?? []).length ? ` · not compared: ${c.reconciliation.comparisonsUnavailable.join(", ")}` : ""}</td></tr>
    </tbody></table></div>
    {(c.attributionAtExecutablePeak ?? []).length > 0 && <div className="tq-table-wrap" style={{ marginTop: 8 }}><table className="tq-table tq-wf">
      <thead><tr><th>Trade</th><th>Net at the executable peak</th><th>Final net</th><th>Giveback</th><th>Fees after the peak</th></tr></thead>
      <tbody>{c.attributionAtExecutablePeak.map((a: any) => <tr key={a.tradeInstance}><td title={`entry order ${a.tradeInstance}`}>{a.symbol}{a.trigger ? ` · ${a.trigger}` : ""}</td><td>{num(a.netAtPeak)}</td><td>{num(a.finalNet)}</td><td>{num(a.giveback)}</td><td>{num(a.feesAfterPeak)}</td></tr>)}</tbody>
    </table></div>}
    {d.modelCost && <div className="tq-table-wrap" style={{ marginTop: 8 }}><table className="tq-table tq-wf tq-stat"><tbody>
      <tr><td>Model cost of preparing this session — invoice-verified</td><td>{num(d.modelCost.cost?.invoiceVerified?.usd)}</td><td>no invoice is recorded by the app</td></tr>
      <tr><td>Estimated at the current price card</td><td>{num(d.modelCost.cost?.estimated?.usd)}</td><td>{d.modelCost.cost?.estimated?.requests ?? 0} requests · an estimate, not an invoice · never subtracted from trading results</td></tr>
      <tr><td>Unknown cost</td><td>{d.modelCost.cost?.unknown?.requests ?? 0} requests</td><td>{Object.entries(d.modelCost.cost?.unknown?.why ?? {}).map(([k, v]) => `${words(k)} ${v}`).join(", ") || "none"}</td></tr>
      <tr><td>Subscription allocation</td><td>{num(d.modelCost.cost?.subscriptionAllocation?.usd)}</td><td>none declared</td></tr>
    </tbody></table></div>}
  </>);
}

function Policy({ d }: { d: any }) {
  return (<>
    <div className="sub" style={{ marginBottom: 6 }}>Preparation: <b>{d.policy?.preparationPolicy}</b> ({d.policy?.preparationPolicyVersion}) · conditional-review fix: <b>{d.policy?.conditionalReviewFix}</b> · grade floor {d.policy?.gradeFloor} · audit quota {d.policy?.auditQuotaPct}%. Changing any of these is a separate decision in Settings.</div>
    <div className="tq-table-wrap"><table className="tq-table tq-wf"><thead><tr><th>Setting</th><th>Default</th><th>Effective</th></tr></thead>
      <tbody>{(d.knobs ?? []).map((k: any) => <tr key={k.key}><td>{k.key}</td><td>{String(k.default)}</td><td>{String(k.effective) !== String(k.default) ? <b>{String(k.effective)}</b> : String(k.effective)}</td></tr>)}</tbody>
    </table></div>
    {d.observer && <div className="sub" style={{ marginTop: 6 }}>Book snapshot recorder: captured {d.observer.captured}, written {d.observer.written}, dropped (queue full) {d.observer.droppedQueueFull}, dropped (write failed) {d.observer.droppedWriteFailed}.</div>}
  </>);
}
