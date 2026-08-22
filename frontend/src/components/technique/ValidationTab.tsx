import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../../lib/api";
import { fmtDateTime } from "../../lib/format";
import { useStore } from "../../store";
import type { TechniqueSweep, WalkforwardRow } from "../../types";
import { Spinner } from "../ui";

function toDateInput(d: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}
function weekdayBack(n: number): Date {
  const d = new Date();
  let left = n;
  while (left > 0) { d.setDate(d.getDate() - 1); if (d.getDay() !== 0 && d.getDay() !== 6) left--; }
  return d;
}
function pct(v: number | null | undefined) { return v === null || v === undefined ? "—" : `${(v * 100).toFixed(0)}%`; }
function num(v: number | null | undefined, d = 2) { return v === null || v === undefined ? "—" : Number(v).toFixed(d); }

function LevelTable({ title, data }: { title: string; data: Record<string, any> }) {
  const rows = Object.entries(data ?? {});
  if (!rows.length) return null;
  return (
    <div className="tq-section">
      <div className="tq-label">{title}</div>
      <table className="tq-table tq-wf">
        <thead><tr><th></th><th>n</th><th>respected</th><th>broken</th><th>flipped</th><th>untested</th><th>respect (tested)</th></tr></thead>
        <tbody>{rows.map(([k, v]: any) => (
          <tr key={k}><td><b>{k}</b></td><td>{v.n}</td><td className="pos">{v.respected}</td><td className="neg">{v.broken}</td><td>{v.flipped}</td><td className="muted">{v.untested}</td>
            <td><b>{pct(v.testedRespectRate)}</b></td></tr>))}</tbody>
      </table>
    </div>
  );
}

function TriggerTable({ title, data, planned = true }: { title: string; data: Record<string, any>; planned?: boolean }) {
  const rows = Object.entries(data ?? {});
  if (!rows.length) return null;
  return (
    <div className="tq-section">
      <div className="tq-label">{title}</div>
      <table className="tq-table tq-wf">
        <thead><tr><th></th>{planned && <th>planned</th>}<th>fired</th><th>wins</th><th>win rate</th><th>avg R</th><th>ΣR</th>
          {planned && <><th>gapped past</th><th>gapped through</th><th>gap void</th><th>mid-day observed</th><th>not triggered</th></>}</tr></thead>
        <tbody>{rows.map(([k, v]: any) => (
          <tr key={k}><td><b>{k}</b></td>{planned && <td>{v.planned ?? "—"}</td>}<td>{v.fired}</td><td>{v.wins}</td><td>{pct(v.winRate)}</td>
            <td className={(v.avgR ?? 0) > 0 ? "pos" : (v.avgR ?? 0) < 0 ? "neg" : ""}><b>{num(v.avgR)}</b></td><td>{num(v.sumR)}</td>
            {planned && <><td>{v.gappedPast ?? "—"}</td><td>{v.gappedThrough ?? "—"}</td><td>{v.gapVoid ?? "—"}</td><td>{v.observedMidday ?? "—"}</td><td>{v.notTriggered ?? "—"}</td></>}</tr>))}</tbody>
      </table>
    </div>
  );
}

export function ValidationTab() {
  const toast = useStore((s) => s.toast);
  const settings = useStore((s) => s.settings);
  const openRun = useStore((s) => s.openTechniqueRun);
  const bump = useStore((s) => s.techniqueSweepBump);
  const defaultSymbols: string[] = (settings["technique.walkforward.symbols"] as string[]) ?? ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "AMD", "META", "AMZN"];
  const [symbols, setSymbols] = useState(defaultSymbols.join(","));
  const [start, setStart] = useState(toDateInput(weekdayBack(Number(settings["technique.walkforward.sessions"] ?? 40))));
  const [end, setEnd] = useState(toDateInput(weekdayBack(1)));
  const [structure, setStructure] = useState(((settings["technique.structure_tfs"] as string[]) ?? ["1h", "30m"]).join(","));
  const [trigger, setTrigger] = useState(String(settings["technique.trigger_tf"] ?? "1m"));
  const [includeInvalid, setIncludeInvalid] = useState(false);
  const [busy, setBusy] = useState(false);
  const [sweeps, setSweeps] = useState<TechniqueSweep[]>([]);
  const [sel, setSel] = useState<TechniqueSweep | null>(null);
  const [showRows, setShowRows] = useState(false);

  const refresh = useCallback(() => { api.techniqueSweeps().then(setSweeps).catch(() => undefined); }, []);
  useEffect(() => { refresh(); }, [refresh, bump]);
  useEffect(() => {
    if (!sel) return;
    api.techniqueSweep(sel.id).then(setSel).catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bump, sel?.id]);
  useEffect(() => { if (!sel && sweeps.length) api.techniqueSweep(sweeps[0].id).then(setSel).catch(() => undefined); }, [sweeps, sel]);

  const run = async () => {
    setBusy(true);
    try {
      const d = await api.techniqueStartSweep({
        symbols: symbols.split(",").map((s) => s.trim().toUpperCase()).filter(Boolean), start, end,
        structureTfs: structure.split(",").map((s) => s.trim()).filter(Boolean), triggerTf: trigger, includeInvalid,
      });
      toast("info", `Sweep started: ${d.symbols.length} symbol(s) ${d.start}..${d.end}`);
      refresh();
    } catch (e: any) { toast("error", e.message); } finally { setBusy(false); }
  };
  const promote = async (r: WalkforwardRow) => {
    if (!sel) return;
    try {
      const run = await api.techniquePromote(sel.id, { symbol: r.symbol, session: r.session });
      toast("success", `Promoted ${r.symbol} ${r.session} → run ${run.id.slice(0, 8)}`);
      openRun(run.id);
    } catch (e: any) { toast("error", e.message); }
  };
  const sm = sel?.summary ?? {};
  const rows = useMemo(() => sel?.rows ?? [], [sel]);

  return (
    <div>
      <div className="panel mb">
        <div className="panel-head">Walk-forward validation <span className="sub">build a plan at every close, score it on the next session — deterministic, free (≥100 fires before trusting it, p. 72)</span></div>
        <div className="panel-body">
          <div className="tq-row">
            <div className="tq-ctl tq-ctl--symbol"><span className="tq-ctl-label">Symbols</span>
              <input value={symbols} onChange={(e) => setSymbols(e.target.value)} style={{ minWidth: 260 }} /></div>
            <div className="tq-ctl"><span className="tq-ctl-label">From</span><input type="date" value={start} onChange={(e) => setStart(e.target.value)} /></div>
            <div className="tq-ctl"><span className="tq-ctl-label">To</span><input type="date" value={end} onChange={(e) => setEnd(e.target.value)} /></div>
            <div className="tq-ctl"><span className="tq-ctl-label">Structure TFs</span><input value={structure} onChange={(e) => setStructure(e.target.value)} style={{ width: 90 }} /></div>
            <div className="tq-ctl"><span className="tq-ctl-label">Trigger TF</span>
              <select value={trigger} onChange={(e) => setTrigger(e.target.value)}>{["1m", "5m", "15m"].map((t) => <option key={t}>{t}</option>)}</select></div>
            <label className="tq-chipbtn"><input type="checkbox" checked={includeInvalid} onChange={(e) => setIncludeInvalid(e.target.checked)} /> include invalid triggers</label>
            <button className="primary-btn tq-run" disabled={busy} onClick={run}>{busy ? "Starting…" : "Run sweep"}</button>
          </div>
          <small className="muted">Yahoo depth: 1m triggers reach ~20 days, 5m ~60; structure 30m/1h is where history is deep (p. 114 is testable per structure TF).</small>
        </div>
      </div>

      <div className="tq-grid">
        <div className="tq-main">
          {sel && (
            <div className="panel mb">
              <div className="panel-head">
                {sel.status === "running" && <Spinner />} {sel.label || sel.id.slice(0, 8)} <span className="sub">{sel.start}..{sel.end} · {sel.symbols.join(", ")} · {sel.status}{sel.progress?.done !== undefined ? ` ${sel.progress.done}/${sel.progress.total}` : ""}</span>
              </div>
              <div className="panel-body">
                {!sm.sessions && <div className="muted">{sel.status === "running" ? "Running…" : sel.error ?? "No summary yet."}</div>}
                {sm.sessions > 0 && (
                  <>
                    <div className="tq-plan">
                      <div className="tq-plan-cell"><small>Sessions</small><b>{sm.sessions}</b><span>{sm.symbols?.length} symbol(s)</span></div>
                      <div className="tq-plan-cell"><small>Fired</small><b>{sm.sample?.fired}</b><span>of the ≥{sm.sample?.target} the book asks for</span></div>
                      <div className="tq-plan-cell"><small>Win rate</small><b>{pct(sm.triggers?.counterfactual?.base?.winRate)}</b><span>avg R {num(sm.triggers?.counterfactual?.base?.avgR)}</span></div>
                      <div className="tq-plan-cell"><small>Prior-day levels</small><b>{pct(sm.levels?.priorDayVsOther?.priorDay?.testedRespectRate)}</b><span>respected vs other {pct(sm.levels?.priorDayVsOther?.other?.testedRespectRate)}</span></div>
                    </div>
                    <div className="tq-section">
                      <div className="tq-label">Claims — book vs data (§6.4)</div>
                      <table className="tq-table tq-wf tq-claims">
                        <thead><tr><th>Claim</th><th>Rule</th><th>Metric</th><th>Verdict</th><th>Detail</th></tr></thead>
                        <tbody>{(sm.claims ?? []).map((c: any, i: number) => (
                          <tr key={i}><td>{c.claim}</td><td><span className="tq-chip">{c.rule}</span></td><td className="muted">{c.metric}</td>
                            <td><span className={`tq-badge ${c.verdict === "pass" ? "setup" : c.verdict === "fail" ? "failed" : "nosetup"}`}>{c.verdict}</span></td>
                            <td className="muted small">{JSON.stringify(c.detail)}</td></tr>))}</tbody>
                      </table>
                    </div>
                    <LevelTable title="Level quality — prior-day extremes vs other (T1.3a)" data={sm.levels?.priorDayVsOther} />
                    <LevelTable title="Level quality — by source" data={sm.levels?.bySource} />
                    <LevelTable title="Level quality — by touches (T1.2)" data={sm.levels?.byTouches} />
                    <LevelTable title="Level quality — by structure timeframe (p. 114)" data={sm.levels?.byTimeframe} />
                    <TriggerTable title="Trigger quality — by kind" data={sm.triggers?.byKind} />
                    <TriggerTable title="Trigger quality — by window fired (R6)" data={sm.triggers?.byWindow} planned={false} />
                    <TriggerTable title="Counterfactuals — with vs without our gates" data={sm.triggers?.counterfactual} planned={false} />
                    {sm.triggers?.middayFiresWithoutGate && <div className="muted small">Mid-day fires without the R6 gate: {JSON.stringify(sm.triggers.middayFiresWithoutGate)}</div>}
                    <TriggerTable title="By R:R gate (R2)" data={sm.triggers?.byRrGate} planned={false} />
                    {sm.errors?.length > 0 && <div className="neg">errors: {JSON.stringify(sm.errors)}</div>}
                  </>
                )}
                <div className="tq-section">
                  <div className="tq-label">Sessions <button className="link-btn" onClick={() => setShowRows((v) => !v)}>{showRows ? "hide" : `show ${rows.length}`}</button></div>
                  {showRows && (
                    <table className="tq-table tq-wf">
                      <thead><tr><th>Symbol</th><th>Plan built</th><th>For</th><th>Triggers</th><th>Fired</th><th>ΣR</th><th>Levels R/B/U</th><th>Gap</th><th></th></tr></thead>
                      <tbody>{rows.map((r) => (
                        <tr key={r.id}><td><b>{r.symbol}</b></td><td>{r.session}</td><td>{r.planFor}</td><td>{r.summary?.triggers ?? "—"}</td><td>{r.summary?.fired ?? "—"}</td>
                          <td className={(r.summary?.sumR ?? 0) > 0 ? "pos" : (r.summary?.sumR ?? 0) < 0 ? "neg" : ""}>{num(r.summary?.sumR)}</td>
                          <td>{r.summary?.levelsRespected ?? "—"}/{r.summary?.levelsBroken ?? "—"}/{r.summary?.levelsUntested ?? "—"}</td>
                          <td>{r.summary?.gapPct !== undefined && r.summary?.gapPct !== null ? `${r.summary.gapPct}%` : "—"}</td>
                          <td>{r.promotedRunId ? <button className="link-btn" onClick={() => openRun(r.promotedRunId!)}>run {r.promotedRunId.slice(0, 8)}</button>
                            : <button className="link-btn" onClick={() => promote(r)}>promote</button>}</td></tr>))}</tbody>
                    </table>
                  )}
                </div>
              </div>
            </div>
          )}
        </div>
        <div className="tq-rail">
          <div className="panel">
            <div className="panel-head">Sweeps <span className="sub">{sweeps.length}</span></div>
            <div className="panel-body tq-setups">
              {sweeps.length === 0 && <div className="empty">none yet</div>}
              {sweeps.map((s) => (
                <button key={s.id} className={`tq-setup-row ${sel?.id === s.id ? "valid" : ""}`} onClick={() => api.techniqueSweep(s.id).then(setSel)}>
                  <b>{s.start}..{s.end}</b> <span>{s.symbols.join(",").slice(0, 24)}</span>
                  <span className="muted">{s.status}{s.summary?.sessions ? ` · ${s.summary.sessions} sessions · ${s.summary.sample?.fired} fired` : ""} · {s.createdAt ? fmtDateTime(s.createdAt) : ""}</span>
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
