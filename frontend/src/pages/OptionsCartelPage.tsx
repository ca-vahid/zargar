import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import { useStore } from "../store";
import "./options-cartel.css";
import { CartelRiskCard } from "./CartelRiskCard";
import { CartelArmControls } from "./CartelArmControls";
import { CartelReplayControls, CartelReplayResult } from "./CartelReplayControls";
import { CartelPremiumReplayControls, CartelPremiumReplayResult } from "./CartelPremiumReplay";
import { CartelQuoteRecording } from "./CartelQuoteRecording";
import { CartelEvidenceResult } from "./CartelEvidenceResult";
import { CartelSweepControls, CartelSweepResult } from "./CartelSweepControls";
import { CartelScanControls, CartelScanResult } from "./CartelScanControls";
import { CartelScheduleControls } from "./CartelScheduleControls";
import { CartelPlanChart } from "./CartelPlanChart";
import { CartelMethodLibrary } from "./CartelMethodLibrary";
import { CartelIndustryControls, CartelIndustryResult } from "./CartelIndustryControls";
import { useWorkspace, workspaceOf } from "../lib/workspace";

type Gate = { label?: string; name?: string; status: string; value?: unknown };
type Candidate = { setup: string; trigger: number; invalidation: number; targets: number[]; contextPassed: boolean; reason: string };
type Run = { runId: string; symbol: string; mode: string; status: string; verdict: string; createdAt: string; asOfMs: number;
  chart?: {daily: any[]; asOfMs: number};
  parentRunId?: string; config?: any; result?: any; reviews?: { id: string; verdict: string; stage: string; notes: string }[] };
const ROOT = "/api/options-cartel";
const number = (v: number) => Number.isFinite(v) ? v.toLocaleString(undefined, { maximumFractionDigits: 2 }) : "—";
const label = (v: string) => v.replaceAll("_", " ");
const profiles = [["september_2026", "September 2026"], ["june_2026", "June 2026"], ["may_2026", "May 2026"], ["january_2026_volume", "January volume example"]];
const screenProfiles = [["september_2026", "September 2026"], ["june_2026", "June 2026 thread text"],
  ["september_2026_video", "September 2026 video: ADR 2%, relative volume >1"],
  ["june_2026_image", "June 2026 scanner image"], ["may_2026", "May 2026 text"], ["may_2026_image", "May 2026 scanner image"]];

function Checks({ rows }: { rows: Gate[] }) {
  return <ul className="cartel-checks">{rows.map((g, i) => <li key={i}>
    <span>{g.label || g.name}</span><strong className={`cartel-${g.status}`}>{g.status}</strong>
  </li>)}</ul>;
}

export function OptionsCartelPage() {
  const pageTab = useStore(s => s.pageTab);
  const setPageTab = useStore(s => s.setPageTab);
  const tab = ["desk", "plans", "history", "method"].includes(pageTab) ? pageTab : "desk";
  const [runs, setRuns] = useState<Run[]>([]);
  const [industrySnapshots, setIndustrySnapshots] = useState<Run[]>([]);
  const [industrySnapshotId, setIndustrySnapshotId] = useState('');
  const [fundamentalsCaptures, setFundamentalsCaptures] = useState<Record<string, Run>>({});
  const [savedFundamentals, setSavedFundamentals] = useState<Run[]>([]);
  const [captureErrors, setCaptureErrors] = useState<Record<string, string>>({});
  const [savedMemberships, setSavedMemberships] = useState<Run[]>([]);
  const [membershipCaptures, setMembershipCaptures] = useState<Record<string, Run>>({});
  const [membershipExchange, setMembershipExchange] = useState('NASDAQ');
  const [armed, setArmed] = useState<any[]>([]);
  const workspace = useWorkspace();
  const streamedArmed = useStore(s => s.techniqueArmed);
  useEffect(() => setArmed(streamedArmed.filter(a => a.technique === "options_cartel" && ["armed", "paused", "closing"].includes(a.status))), [streamedArmed]);
  const [selected, setSelected] = useState<Run | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [symbol, setSymbol] = useState("");
  const fundamentalsCapture = fundamentalsCaptures[symbol];
  const membershipCapture = membershipCaptures[symbol];
  const [profile, setProfile] = useState("september_2026");
  const [direction, setDirection] = useState("long");
  const [cap, setCap] = useState("");
  const [industry, setIndustry] = useState("");
  const [week, setWeek] = useState("");
  const [month, setMonth] = useState("");
  const [source, setSource] = useState("");
  const [observed, setObserved] = useState(() => new Date().toISOString().slice(0, 16));
  const [candidate, setCandidate] = useState<Candidate | null>(null);
  const [targets, setTargets] = useState("");
  const [note, setNote] = useState("");
  const [targetSource, setTargetSource] = useState("");
  const [horizon, setHorizon] = useState(5);
  const [entryTf, setEntryTf] = useState(15);
  const [stopMode, setStopMode] = useState("session_extreme");
  const [entryMode, setEntryMode] = useState("breakout");
  const [volumeMultiple, setVolumeMultiple] = useState(1.5);
  const [closeLocation, setCloseLocation] = useState(70);
  const [chaseR, setChaseR] = useState(.5);
  const [exitProfile, setExitProfile] = useState("september_2026");
  const [fractions, setFractions] = useState("");
  const [review, setReview] = useState("");
  const [verdict, setVerdict] = useState("unclear");
  const [reviewStage, setReviewStage] = useState("setup");
  const requestId = useRef(0);
  const refresh = useCallback(async () => {
    const [history, alerts, captures, fundamentals, memberships] = await Promise.all([api.get<Run[]>(`${ROOT}/runs?limit=100`), api.get<any[]>(`${ROOT}/armed`),
      api.get<Run[]>(`${ROOT}/runs?mode=industry&limit=200`), api.get<Run[]>(`${ROOT}/runs?mode=fundamentals&limit=200`),
      api.get<Run[]>(`${ROOT}/runs?mode=membership&limit=200`)]);
    setRuns(history); setArmed(alerts); setIndustrySnapshots(captures); setSavedFundamentals(fundamentals); setSavedMemberships(memberships);
  }, []);
  useEffect(() => { let alive = true; refresh().catch(e => { if (alive) setError(e.message); })
    .finally(() => { if (alive) setLoading(false); }); return () => { alive = false; requestId.current++; }; }, [refresh]);
  const open = async (id: string) => {
    const ticket = ++requestId.current;
    setBusy("Loading run"); setError(""); setCandidate(null);
    try { const r = await api.get<Run>(`${ROOT}/runs/${id}`); if (ticket === requestId.current) setSelected(r); }
    catch (e) { if (ticket === requestId.current) setError(String(e)); }
    finally { if (ticket === requestId.current) setBusy(""); }
  };
  useEffect(() => {
    if (selected?.mode !== "scan" || selected.status !== "running") return;
    const id = selected.runId;
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const next = await api.get<Run>(`${ROOT}/runs/${id}`);
        if (!alive) return;
        setSelected(previous => previous?.runId === id ? next : previous);
        if (next.status === "running") timer = setTimeout(poll, 2000);
        else await refresh();
      } catch (e) {
        if (alive) { setError(String(e)); timer = setTimeout(poll, 5000); }
      }
    };
    timer = setTimeout(poll, 1000);
    return () => { alive = false; clearTimeout(timer); };
  }, [selected?.runId, selected?.mode, selected?.status, refresh]);
  const collect = async (event: React.FormEvent) => {
    event.preventDefault(); setBusy("Collecting market history"); setError(""); setCandidate(null);
    try {
      const metadata = cap || industry || week || month;
      const facts = metadata ? { symbol: symbol.toUpperCase(), marketCap: cap ? Number(cap) : null,
        industry: industry || null, weekRank: week ? Number(week) : null, monthRank: month ? Number(month) : null,
        rankDirection: direction, source, observedAt: new Date(observed + "Z").getTime() } : null;
      const r = await api.post<Run>(`${ROOT}/collect`, { symbol, profile, direction, facts,
        membershipSnapshotId: membershipCapture?.runId || null,
        fundamentalsSnapshotId: fundamentalsCapture?.symbol === symbol ? fundamentalsCapture.runId : null,
        industrySnapshotId:industrySnapshotId || null });
      setSelected(r); await refresh();
    } catch (e) { setError(String(e)); } finally { setBusy(""); }
  };
  const prepare = async (event: React.FormEvent) => {
    event.preventDefault(); if (!selected || !candidate) return;
    setError("");
    try {
      const prices = targets.split(",").map(v => Number(v.trim()));
      if (!targets.trim() || prices.some(p => !Number.isFinite(p) || p <= 0)) throw Error("Enter positive target prices separated by commas.");
      let rungs: any[] = [];
      let refs: string[];
      let allocationNote: string;
      if (exitProfile === "september_2026") {
        const f = fractions.split(",").map(v => Number(v.trim()) / 100);
        if (f.length !== 5 || f.some(v => !Number.isFinite(v) || v <= 0) || Math.abs(f[0] - .25) > 1e-6 || Math.abs(f.reduce((a,b) => a+b,0)-1) > 1e-6)
          throw Error("September needs five positive percentages totaling 100%; the first must be 25%.");
        rungs = [{ id: "target1", kind: "target", fraction: f[0], target: prices[0] },
          { id: "extension", kind: "extension", fraction: f[1], ema_period: 8, atr_multiple: 3 },
          ...[8,21,50].map((p,i) => ({ id: `ema${p}`, kind: "ema", fraction: f[i+2], ema_period: p }))];
        refs = ["S01"]; allocationNote = "First trim and exit conditions from Sean; later fractions chosen in this review.";
      } else {
        if (exitProfile === "january_2026_volume" && prices.length < 3) throw Error("January's volume example needs three reviewed target prices.");
        if (exitProfile === "june_2026" && prices.length < 2) throw Error("June's exit schedule needs two target prices.");
        rungs = [{ id: "target1", kind: "target", fraction: .25, target: prices[0] }];
        if (exitProfile === "june_2026") rungs.push({ id: "target2", kind: "target", fraction: .25, target: prices[1] });
        if (exitProfile === "january_2026_volume") rungs.push(...prices.slice(1,3).map((target,i) => ({id:`target${i+2}`,kind:"target",fraction:.25,target})));
        rungs.push(...(exitProfile === "june_2026" ? [8,21] : exitProfile === "january_2026_volume" ? [8] : [8,21,50]).map(p => ({ id: `ema${p}`, kind: "ema", fraction: .25, ema_period: p })));
        refs = [exitProfile === "june_2026" ? "S02" : exitProfile === "january_2026_volume" ? "S05" : "S04"]; allocationNote = "Source's quarter-position schedule.";
      }
      setBusy("Saving reviewed plan");
      const r = await api.post<Run>(`${ROOT}/runs/${selected.runId}/plan`, { setup: candidate.setup, horizonSessions: horizon,
        reviewedTargets: prices, reviewNote: note, targetSource, entryPolicy: { timeframe_minutes: entryTf, stop_mode: stopMode,
          mode: entryMode, volume_multiple: volumeMultiple, min_close_location: closeLocation/100, max_chase_r: chaseR },
        exitCampaign: { profile: exitProfile, source_refs: refs, allocation_note: allocationNote, rungs } });
      setSelected(r); setCandidate(null); setPageTab("plans"); await refresh();
    } catch (e) { setError(String(e)); } finally { setBusy(""); }
  };
  const saveReview = async (event: React.FormEvent) => {
    event.preventDefault(); if (!selected) return; setBusy("Saving review"); setError("");
    try { await api.post(`${ROOT}/runs/${selected.runId}/reviews`, { verdict, stage: reviewStage, notes: review });
      setSelected(await api.get<Run>(`${ROOT}/runs/${selected.runId}`)); setReview("");
    } catch (e) { setError(String(e)); } finally { setBusy(""); }
  };
  const alertAction = async (id:string, action:string) => {
    setBusy("Updating alert"); setError("");
    try { await api.post(`${ROOT}/armed/${id}/${action}`); await refresh(); }
    catch(e) { setError(String(e)); } finally { setBusy(""); }
  };
  const analysis = selected?.result?.analysis;
  const visibleArmed = armed.filter(a => workspaceOf(a.portfolio?.kind) === workspace);
  const p = selected?.result?.plan?.plan;
  const filtered = tab === "plans" ? runs.filter(r => r.mode === "plan") : runs;
  return <section className="cartel-page">
    <header className="cartel-header"><div><p className="cartel-eyebrow">SEAN TRADES · MOMENTUM SWINGS</p>
      <h1>The Options Cartel</h1><p>Leading stocks. Planned entries. Room for the trend to develop.</p></div>
      <span className="cartel-stage">Research & execution review</span></header>
    <nav className="cartel-tabs" aria-label="Options Cartel sections">{["desk", "plans", "history", "method"].map(t =>
      <button key={t} disabled={!!busy} aria-current={tab === t ? "page" : undefined} onClick={() => {
        setPageTab(t); setCandidate(null); if (t === "plans" && selected?.mode !== "plan") setSelected(null);
      }}>{label(t)}</button>)}</nav>
    {error && <div className="cartel-error" role="alert">{error}</div>}
    {tab === "history" && <CartelSweepControls runs={runs.filter(r => r.mode === "replay")} busy={!!busy} onRun={async body => {
      setBusy("Comparing entry rules"); setError("");
      try { setSelected(await api.post<Run>(`${ROOT}/sweeps`, body)); await refresh(); }
      catch (e) { setError(String(e)); } finally { setBusy(""); }
    }}/>}
    {busy && <p role="status">{busy}…</p>}
    {tab === "method" ? <div className="cartel-card cartel-method">
      <h2>The method</h2><p>Start with market direction, then strong themes and sector leaders. Review weekly bases and daily contraction, with quieter consolidation volume and renewed volume at the breakout.</p>
      <h3>Plan before entry</h3><p>Mark the trigger, invalidation and targets. Confirm the breakout on a closed intraday candle. Bullish ideas can use calls or shares; bearish ideas use puts. Contract selection is separate from the chart setup.</p>
      <h3>Manage the swing</h3><p>Take the first 25% at a meaningful target and move the stop to entry after that trim fills. The September thread adds an extension trim at 3× ATR from the 8 EMA and partial exits on daily closes below the 8, 21 and 50 EMAs. Later trim allocations require an explicit choice.</p>
      <h3>Keep source versions distinct</h3><p>May uses a 2% ADR screen and target/8/21/50 EMA quarters. June uses 3% ADR and two target quarters followed by 8/21 EMA quarters. September emphasizes weekly/monthly industry leadership and adds the ATR extension. Numerical pattern measurements are engineering definitions awaiting further example validation.</p>
      <p>The June scanner image differs from its thread text: it shows ADR above 2% and 10-day average volume above 500,000. Choose the scanner-image profile to use those values. The older thread-text profile keeps its previous completed-day volume interpretation. Exit schedules remain a separate reviewed choice.</p>
      <p><a href="https://x.com/SRxTrades/status/2096632160639734027" target="_blank" rel="noreferrer">September method thread ↗</a> · <a href="https://x.com/TheOptionCartel" target="_blank" rel="noreferrer">The Options Cartel ↗</a></p>
      <p>Saved plans support alert, proposal and automatic execution modes. Each entry is checked again at submission; confirmed fills use durable position management. Research coverage, calibration and broker rollout verification remain in progress.</p>
      <CartelMethodLibrary />
    </div> : <>
      {tab === "desk" && <CartelRiskCard />}
      {tab === "desk" && <CartelScheduleControls />}
      {tab === "desk" && <CartelQuoteRecording/>}
      {tab === "desk" && <CartelIndustryControls snapshots={industrySnapshots} selectedId={industrySnapshotId}
        onSelect={setIndustrySnapshotId} onImported={async run => {setSelected(run); await refresh();}}/>}
      {tab === "desk" && <CartelScanControls busy={!!busy} profile={profile} direction={direction}
        capturedSymbols={Object.keys(fundamentalsCaptures)} captureErrors={captureErrors} onCapture={async symbols => {
          setError(''); setCaptureErrors({}); setBusy('Capturing list capitalization');
          setFundamentalsCaptures(previous => {
            const next = {...previous}; symbols.forEach(s => delete next[s]); return next;
          });
          try {
            for (const [index, requested] of symbols.entries()) {
              setBusy(`Capturing ${requested} (${index+1}/${symbols.length})`);
              try {
                const capture = await api.post<Run>(`${ROOT}/fundamentals/${encodeURIComponent(requested)}`, {});
                setFundamentalsCaptures(previous => ({...previous, [requested]: capture}));
              } catch (e) {
                setCaptureErrors(previous => ({...previous, [requested]: String(e)}));
              }
            }
            await refresh();
          } finally { setBusy(''); }
        }} onScan={async symbols => {
        setBusy("Scanning focus list"); setError("");
        try {
          const facts = symbols.includes(symbol.toUpperCase()) && (cap || industry || week || month) ? {
            [symbol.toUpperCase()]: {symbol: symbol.toUpperCase(), marketCap: cap ? Number(cap) : null,
              industry: industry || null, weekRank: week ? Number(week) : null, monthRank: month ? Number(month) : null,
              rankDirection: direction, source, observedAt: new Date(observed + "Z").getTime()}
          } : {};
          const fundamentalsSnapshotIds = Object.fromEntries(symbols.filter(s => fundamentalsCaptures[s])
            .map(s => [s, fundamentalsCaptures[s].runId]));
          const membershipSnapshotIds = Object.fromEntries(symbols.filter(s => membershipCaptures[s])
            .map(s => [s, membershipCaptures[s].runId]));
          setSelected(await api.post<Run>(`${ROOT}/scans`, {symbols, profile, direction, facts, fundamentalsSnapshotIds, membershipSnapshotIds,
            industrySnapshotId:industrySnapshotId || null})); await refresh();
        } catch (e) { setError(String(e)); } finally { setBusy(""); }
      }}/>}
      {tab === "desk" && <form className="cartel-card" onSubmit={collect}><h2>Review a candidate</h2>
        <div className="cartel-fields"><label>Symbol<input required value={symbol} onChange={e => { setSymbol(e.target.value.toUpperCase()); setCap(''); setIndustry(''); setWeek(''); setMonth(''); setSource(''); }} placeholder="e.g. MU" maxLength={12}/></label>
          <label>Direction<select value={direction} onChange={e => setDirection(e.target.value)}><option value="long">Bullish</option><option value="short">Bearish puts</option></select></label>
          <label>Source profile<select value={profile} onChange={e => setProfile(e.target.value)}>{screenProfiles.map(([v,l]) => <option key={v} value={v}>{l}</option>)}</select></label></div>
        <details><summary>Fundamental and industry evidence</summary><p>Supply current, sourced values when available. Missing evidence stays unknown and prevents a qualifying plan.</p>
          <label>Saved capitalization capture<select disabled={!!busy || !symbol} value={fundamentalsCapture?.runId || ''}
            onChange={async e => {
              const id = e.target.value, requested = symbol;
              if (!id) {
                setFundamentalsCaptures(previous => { const next = {...previous}; delete next[requested]; return next; });
                return;
              }
              setBusy('Loading capitalization evidence'); setError('');
              try {
                const capture = await api.get<Run>(`${ROOT}/runs/${id}`);
                if (capture.mode !== 'fundamentals' || capture.symbol !== requested) throw Error('Capture does not match this symbol.');
                setFundamentalsCaptures(previous => ({...previous, [requested]: capture})); setCap('');
              } catch (e) { setError(String(e)); } finally { setBusy(''); }
            }}>
            <option value="">Manual capitalization / no capture</option>
            {savedFundamentals.filter(r => r.symbol === symbol).map(r => <option key={r.runId} value={r.runId}>
              {new Date(r.asOfMs).toISOString()} · {label(r.verdict)}
            </option>)}
          </select></label>
          <p>Choose a capture explicitly from the 200 most recent saved captures. Its original timestamps still govern eligibility.</p>
          <button type="button" disabled={!!busy || !symbol} onClick={async () => {
            const requested = symbol;
            setBusy('Capturing fundamentals'); setError('');
            try {
              const capture = await api.post<Run>(`${ROOT}/fundamentals/${encodeURIComponent(requested)}`, {});
              setFundamentalsCaptures(previous => ({...previous, [requested]: capture})); setCap(''); await refresh();
            } catch (e) { setError(String(e)); } finally { setBusy(''); }
          }}>Capture current capitalization</button>
          {fundamentalsCapture?.symbol === symbol && <div className="cartel-notice">
            <p>Yahoo capitalization: {fundamentalsCapture.result?.marketCapUsd == null ? 'unavailable' : `$${number(fundamentalsCapture.result.marketCapUsd)}`}.
              Captured {new Date(fundamentalsCapture.asOfMs).toISOString()}.
              Provider price time: {fundamentalsCapture.result?.providerPriceAt ? new Date(fundamentalsCapture.result.providerPriceAt).toISOString() : 'unknown'}.</p>
            <p>This capture supplies capitalization for this candidate and focus-list scans containing this symbol. Industry membership and ranks require separate evidence.</p>
            {fundamentalsCapture.result?.warnings?.map((w: string) => <p key={w}>{w}</p>)}
            <button type="button" onClick={() => setFundamentalsCaptures(previous => {
              const next = {...previous}; delete next[symbol]; return next;
            })}>Use manual capitalization</button>
          </div>}
          <p>Use the <a href="https://www.tradingview.com/markets/stocks-usa/sectorandindustry-industry/" target="_blank" rel="noreferrer">industry Performance view</a>: sort 1W and 1M separately and record both ranks. Overview order is not performance rank. Today’s rankings cannot establish historical leadership.</p>
          <label>Saved industry membership<select disabled={!!busy || !symbol} value={membershipCapture?.runId || ''}
            onChange={async e => {
              const id = e.target.value, requested = symbol;
              if (!id) {
                setMembershipCaptures(previous => { const next = {...previous}; delete next[requested]; return next; });
                return;
              }
              setBusy('Loading industry membership'); setError('');
              try {
                const capture = await api.get<Run>(`${ROOT}/runs/${id}`);
                if (capture.mode !== 'membership' || capture.symbol !== requested || capture.verdict !== 'verified') {
                  throw Error('Membership capture does not match this symbol or is unverified.');
                }
                setMembershipCaptures(previous => ({...previous, [requested]: capture})); setIndustry('');
              } catch (e) { setError(String(e)); } finally { setBusy(''); }
            }}>
            <option value="">Manual industry mapping / no capture</option>
            {savedMemberships.filter(r => r.symbol === symbol && r.verdict === 'verified').map(r => <option key={r.runId} value={r.runId}>
              {new Date(r.asOfMs).toISOString()} · verified
            </option>)}
          </select></label>
          <p>Choose explicitly from the 200 most recent membership captures. The original observation time still applies.</p>
          <label>Listing exchange<select value={membershipExchange} onChange={e => setMembershipExchange(e.target.value)}>
            <option>NASDAQ</option><option>NYSE</option><option>AMEX</option>
          </select></label>
          <button type="button" disabled={!!busy || !symbol} onClick={async () => {
            const requested = symbol;
            setBusy('Verifying industry membership'); setError('');
            try {
              const capture = await api.post<Run>(`${ROOT}/membership/${membershipExchange}/${encodeURIComponent(requested)}`, {});
              setMembershipCaptures(previous => ({...previous, [requested]: capture})); setIndustry(''); await refresh();
            } catch (e) { setError(String(e)); } finally { setBusy(''); }
          }}>Verify industry membership</button>
          {membershipCapture && <div className="cartel-notice">
            <p>{membershipCapture.result.exchange}:{membershipCapture.symbol} belongs to {membershipCapture.result.industry} on TradingView.
              Observed {new Date(membershipCapture.asOfMs).toISOString()}. Applies to this candidate and matching scan symbols.</p>
            <p>Verified stock-page link and industry-table member row. This establishes current membership; performance ranks still require separate evidence.</p>
            <button type="button" onClick={() => setMembershipCaptures(previous => {
              const next = {...previous}; delete next[symbol]; return next;
            })}>Use manual industry mapping</button>
          </div>}
          <div className="cartel-fields"><label>Market cap (USD)<input disabled={fundamentalsCapture?.symbol === symbol} type="number" min="1" value={cap} onChange={e => setCap(e.target.value)}/></label>
            <label>Industry<input disabled={!!membershipCapture} value={industry} onChange={e => setIndustry(e.target.value)}/></label>
            <label>Weekly rank<input disabled={!!industrySnapshotId} type="number" min="1" value={week} onChange={e => setWeek(e.target.value)}/></label>
            <label>Monthly rank<input disabled={!!industrySnapshotId} type="number" min="1" value={month} onChange={e => setMonth(e.target.value)}/></label>
            <label>Evidence source<input value={source} onChange={e => setSource(e.target.value)} required={!!(cap || industry || week || month)} placeholder="Source URL or description"/></label>
            <label>Observed at (UTC)<input type="datetime-local" required value={observed} onChange={e => setObserved(e.target.value)}/></label></div>
          <p>For bearish candidates, ranks must describe downside leadership.</p></details>
        <button className="cartel-primary" disabled={!!busy}>Collect history & analyze</button></form>}
      {armed.length > visibleArmed.length && <p className="cartel-notice">{armed.length-visibleArmed.length} Cartel plan(s) in the other workspace.</p>}
      {visibleArmed.length > 0 && <section className="cartel-card"><h2>Active plans</h2>{visibleArmed.map(a => <article key={a.runId} className="cartel-candidate">
        <div className="cartel-row"><strong>{a.symbol} · {a.config?.mode} · {label(a.status)}</strong><span>{a.portfolio?.name}</span></div>
        {a.execution?.report?.expression && <p>Latest preflight: {a.execution.report.expression.quantity} units of {a.execution.report.expression.symbol} · ask {a.execution.report.expression.ask} · rechecked at submission.</p>}
        <p>{a.summary}</p><div className="cartel-row"><button disabled={!!busy} onClick={() => open(a.runId)}>View plan</button>
          <button disabled={!!busy || a.status === "closing"} onClick={() => alertAction(a.runId, a.status === "paused" ? "resume" : "pause")}>{a.status === "paused" ? "Resume" : "Pause"}</button>
          <button disabled={!!busy} onClick={() => alertAction(a.runId,"disarm")}>Disarm</button>
          {a.awaitingApproval && <button disabled={!!busy || a.execution?.report?.passed === false} onClick={async () => {
            setBusy("Approving signal"); setError("");
            try { await api.post(`${ROOT}/armed/${a.runId}/approve`, {signalId:a.signal.id}); await refresh(); }
            catch(e) {setError(String(e));} finally {setBusy("");}
          }}>Approve signal</button>}
          {a.openPositions > 0 && <button disabled={!!busy} onClick={() => alertAction(a.runId,"flatten")}>Close positions</button>}</div>
        {a.trades?.map((trade: any) => <p key={trade.triggerId}>{trade.orderSymbol} · filled {trade.filledQty} · remaining {trade.remaining} · {trade.status}</p>)}
      </article>)}</section>}
      <div className="cartel-columns"><aside className="cartel-card"><div className="cartel-row"><h2>{tab === "plans" ? "Saved plans" : "Research history"}</h2>
        <button disabled={!!busy} onClick={() => refresh().catch(e => setError(e.message))}>Refresh</button></div>
        {loading ? <p>Loading history…</p> : !filtered.length ? <p>No {tab === "plans" ? "plans" : "analyses"} yet. Start with a candidate on the Desk tab.</p> :
          <ul className="cartel-runs">{filtered.map(r => <li key={r.runId}><button disabled={!!busy} onClick={() => open(r.runId)} aria-pressed={r.runId === selected?.runId}>
            <strong>{r.symbol}</strong><span>{label(r.mode)} · {label(r.verdict || "done")}</span><small>{new Date(r.createdAt).toLocaleString()}</small></button></li>)}</ul>}
      </aside><div className="cartel-card">
        {!selected ? <><h2>Plan with context</h2><p>Select an analysis to inspect market conditions, setup measurements and the evidence behind its levels.</p></> : <>
          <div className="cartel-row"><h2>{selected.symbol} · {label(selected.mode)}</h2><span>{label(selected.verdict || "done")}</span></div>
          <p>{['industry', 'fundamentals', 'membership'].includes(selected.mode) ? "Captured at" : "Market data as of"} {new Date(selected.asOfMs).toLocaleString()}</p>
          {selected.config?.dataSource && <p>Source: {selected.config.dataSource}</p>}
          {selected.mode === "industry" && <CartelIndustryResult key={selected.runId} result={selected.result}/>}
          {(selected.mode === 'fundamentals' || selected.mode === 'membership') && <CartelEvidenceResult mode={selected.mode} result={selected.result}/>}
          {selected.mode === 'premium_replay' && <CartelPremiumReplayResult result={selected.result}/>}
          {selected.mode === 'replay' && <CartelPremiumReplayControls key={selected.runId} busy={!!busy} onValue={async (request, stored = false) => {
            setBusy('Valuing recorded option quotes'); setError('');
            try { setSelected(await api.post<Run>(`${ROOT}/runs/${selected.runId}/${stored ? 'premium-replay-stored' : 'premium-replay'}`, request)); await refresh(); }
            catch (e) { setError(String(e)); } finally { setBusy(''); }
          }}/>}
          {selected.chart && <CartelPlanChart key={selected.runId} daily={selected.chart.daily} plan={p || selected.config?.planSnapshot?.plan}/>}
          {selected.result?.collection?.warnings?.map((w: string) => <p className="cartel-notice" key={w}>{w}</p>)}
          {selected.result?.warnings?.map((w: string) => <p className="cartel-notice" key={w}>{w}</p>)}
          {selected.mode === "sweep" && selected.result?.summaries && <CartelSweepResult result={selected.result}/>}
          {selected.mode === "scan" && selected.result?.rows && <>
            <CartelScanResult result={selected.result} busy={!!busy} onOpen={open}/>
            {selected.status !== "running" && selected.result.rows.some((row: any) => ["pending", "data_error"].includes(row.status)) && <>
              <p>Retry keeps the original cutoff and evidence and reuses completed analyses. It saves a new linked scan.</p>
              <button disabled={!!busy} onClick={async () => {
                setBusy("Retrying unresolved symbols"); setError("");
                try { setSelected(await api.post<Run>(`${ROOT}/scans/${selected.runId}/retry`)); await refresh(); }
                catch (e) { setError(String(e)); } finally { setBusy(""); }
              }}>Retry unresolved symbols</button>
            </>}
          </>}
          {selected.result?.screen && <><h3>Market & universe</h3><Checks rows={selected.result.screen.gates}/></>}
          {analysis && <><h3>Weekly & daily context</h3><Checks rows={analysis.checks}/><h3>Measured candidates</h3>
            {(analysis.candidates as Candidate[]).map((c,i) => <article className="cartel-candidate" key={i}><h4>{label(c.setup)}</h4>
              <p>Trigger {number(c.trigger)} · Invalidation {number(c.invalidation)} · Targets {c.targets.length ? c.targets.map(number).join(", ") : "need reviewed levels"}</p>
              <p>{c.reason}</p>{selected.mode === "analysis" && <button disabled={!!busy || !c.contextPassed} onClick={() => {
                setCandidate(c); setTargets(c.targets.join(", ")); setNote(""); setTargetSource("");
                const selectedProfile = selected.config?.thresholds?.profile || profile;
                setExitProfile(selectedProfile === "june_2026_image" ? "june_2026" : selectedProfile === "may_2026_image" ? "may_2026" : selectedProfile === "september_2026_video" ? "september_2026" : selectedProfile);
              }}>Review & prepare plan</button>}</article>)}</>}
          {candidate && <form className="cartel-plan-form" onSubmit={prepare}><h3>Prepare {label(candidate.setup)}</h3>
            {selected.config?.thresholds?.profile === "september_2026_video" && <p className="cartel-notice">The video gives the screen, entry and initial stop. Choose an exit profile from the written method below; the video does not specify exit allocations.</p>}
            <div className="cartel-fields"><label>Target prices<input required value={targets} onChange={e => setTargets(e.target.value)} placeholder="e.g. 120, 135"/></label>
              <label>Target source / rationale<input required value={targetSource} onChange={e => setTargetSource(e.target.value)}/></label>
              <label>Wait horizon (sessions)<input type="number" min="1" max="60" required value={horizon} onChange={e => setHorizon(Number(e.target.value))}/></label>
              <label>Confirmation<select value={entryTf} onChange={e => setEntryTf(Number(e.target.value))}>{[5,15,30].map(v => <option key={v} value={v}>{v} minute close</option>)}</select></label>
              <label>Initial stop<select value={stopMode} onChange={e => setStopMode(e.target.value)}><option value="session_extreme">Session low/high at entry</option><option value="breakout_bar">Confirmation candle extreme</option><option value="preplanned">Reviewed invalidation</option></select></label>
              <label>Entry pattern<select value={entryMode} onChange={e => setEntryMode(e.target.value)}><option value="breakout">Breakout confirmation</option><option value="retest">Confirmed break, then retest</option></select></label>
              <label>Volume / same-time baseline<input required type="number" min="0.1" step="0.1" value={volumeMultiple} onChange={e => setVolumeMultiple(Number(e.target.value))}/></label>
              <label>Close within directional range (%)<input required type="number" min="0" max="100" value={closeLocation} onChange={e => setCloseLocation(Number(e.target.value))}/></label>
              <label>Maximum chase (planned R)<input required type="number" min="0" max="10" step="0.1" value={chaseR} onChange={e => setChaseR(Number(e.target.value))}/></label>
              <label>Exit schedule<select value={exitProfile} onChange={e => setExitProfile(e.target.value)}>{profiles.map(([v,l]) => <option key={v} value={v}>{l}</option>)}</select></label></div>
            {exitProfile === "september_2026" && <label>Five allocation percentages: target, extension, 8 / 21 / 50 EMA<input required value={fractions} onChange={e => setFractions(e.target.value)} placeholder="First is 25; total must be 100"/></label>}
            <label>Review note<textarea required value={note} onChange={e => setNote(e.target.value)}/></label>
            <p>Volume, candle-close quality and chase limits are adjustable implementation choices, not exact thresholds stated by Sean.</p>
            <p>Saving records a plan and its selected rules. It does not arm a position or submit an order.</p>
            <button className="cartel-primary" disabled={!!busy}>Save reviewed plan</button></form>}
          {p && <><h3>Reviewed plan</h3><p>{label(p.direction)} · {label(p.setup)} · {p.first_session} through {p.last_session}</p>
            <p>Trigger {number(p.trigger)} · Invalidation {number(p.invalidation)} · Targets {p.targets.map(number).join(", ")}</p>
            <p>{p.rationale}</p><h3>Exit schedule</h3><ul>{selected.result.exitCampaign?.rungs.map((r: any) => <li key={r.id}>{label(r.id)}: {number(r.fraction*100)}%{r.target ? ` at ${number(r.target)}` : ""}</li>)}</ul>
            <CartelArmControls key={selected.runId} runId={selected.runId} active={armed.find(a => a.runId === selected.runId)} onChanged={refresh}/></>}
          {selected.mode === "plan" && <CartelReplayControls key={selected.runId} busy={!!busy} onReplay={async request => {
            setBusy("Replaying campaign"); setError("");
            try {
              const run = await api.post<Run>(`${ROOT}/runs/${selected.runId}/replay-campaign`, request);
              setSelected(run); setPageTab("history"); await refresh();
            } catch (e) { setError(String(e)); } finally { setBusy(""); }
          }}/>}
          {selected.result?.fills && selected.mode === "replay" ? <CartelReplayResult result={selected.result}/> :
            selected.result?.entryRead && <><h3>Entry replay</h3><p>{label(selected.result.entryRead.status)} · simulation, no orders</p></>}
          <details><summary>Review this record</summary><form onSubmit={saveReview} className="cartel-plan-form"><div className="cartel-fields">
            <label>Verdict<select value={verdict} onChange={e => setVerdict(e.target.value)}>{["correct","wrong_levels","wrong_plan","data_issue","unclear"].map(v => <option key={v} value={v}>{label(v)}</option>)}</select></label>
            <label>Area<select value={reviewStage} onChange={e => setReviewStage(e.target.value)}>{["data","setup","entry","exit","expression","execution","other"].map(v => <option key={v}>{v}</option>)}</select></label></div>
            <label>Notes<textarea required value={review} onChange={e => setReview(e.target.value)}/></label><button disabled={!!busy}>Save review</button></form></details>
          {selected.reviews?.map(r => <blockquote key={r.id}><strong>{label(r.verdict)} · {r.stage}</strong><p>{r.notes}</p></blockquote>)}
        </>}
      </div></div>
    </>}
  </section>;
}
